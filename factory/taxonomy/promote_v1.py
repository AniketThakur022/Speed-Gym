#!/usr/bin/env python3
"""Promote taxonomy_v1_candidate -> taxonomy_v1, within the reviewed bounds.

Review: docs/rag/TAXONOMY_V1_REVIEW.md. Authority to promote: coordinator GO,
on the basis that this promotion has ZERO user-visible impact and is reversible.

The architecture that makes it safe: `skill_key` (an existing :Skill.name) is the
stable machine key that BKT mastery joins on; `display_label` is the human-facing
string. Promotion NEVER rewrites a skill_key, so:
  - no user_technique_states / bkt_state_snapshots migration,
  - no prerequisite_closure rebuild,
  - display names stay owner-changeable later at zero cost.

Bounds honoured here:
  1. Class A merges (corpus-only labels, verified to have no :Skill node) applied.
  2. Class C display aliases mapped onto existing skill_keys — NOT renames.
  3. Rejected merges recorded WITH reasons (negation mismatches, compounds, subtypes).
  4. `Basic Operations (+, -, ×, ÷)` 4-way cluster left GATED — it touches keys.
  5. Long-tail / compound splitting convention left OPEN.
  6. The three bare difficulty-band names excised by EXACT match only (a band-word
     regex would wrongly excise legitimate "Basic <subject>" skills).
Every decline is written to the output with a reason — never silently absent.
"""

import json
from pathlib import Path

CANDIDATE = Path("data/taxonomy/taxonomy_v1_candidate.json")
OUT = Path("data/taxonomy/taxonomy_v1.json")

# Class A: corpus-only merges. survivor -> absorbed labels.
CLASS_A_MERGES = {
    "Logical Reasoning": ["Logic Reasoning", "Logic and Reasoning", "Logic Reasoning Problems"],
    "Competitive Reasoning": ["Competition Reasoning", "Competitive Exam Reasoning"],
    "Direction and Distance Reasoning": ["Direction and Distance"],
    "Logic Puzzles": ["Logic Puzzle"],
    "Arithmetic Reasoning": ["Arithmetical Reasoning"],
}

# Class C: corpus/display label -> existing :Skill.name (display alias, NOT a rename).
CLASS_C_ALIASES = {
    "Vedic Mathematics": "VedicMath",
    "Number Theory": "NumberTheory",
    "numerical cognition": "Numerical cognition",
    "Spatial Reasoning": "Spatial reasoning",
}

REJECTED_MERGES = [
    {"pair": ["Verbal Reasoning", "Non-Verbal Reasoning"], "reason":
     "NEGATION MISMATCH — these are opposites. The 0.67 overlap is an artefact of the "
     "shared word 'Reasoning'; merging would collapse a real distinction."},
    {"pair": ["Verbal Reasoning", "Verbal and Non-Verbal Reasoning"], "reason":
     "compound, not a duplicate — belongs in the (still open) splitting convention"},
    {"pair": ["Logical Reasoning", "Verbal and Logical Reasoning"], "reason":
     "compound spanning two skills — must be split, not absorbed"},
    {"pair": ["Number Theory", "Number Theory / Arithmetic"], "reason": "compound"},
    {"pair": ["Logic Puzzles", "Logic Grid Puzzles"], "reason":
     "genuine SUBTYPE of Logic Puzzles, not a spelling of it"},
    {"pair": ["Logical Reasoning", "Logical Reasoning and Data Interpretation"], "reason":
     "LRDI is a legitimate CAT section name, distinct from Logical Reasoning as a skill; "
     "the LRDI spellings merge with each other only"},
]

# Excised by EXACT match. A band-word regex would hit 292 closure rows and 371
# Q-matrix rows of legitimate subjects (Basic Algebra, Basic Geometry, ...).
BAND_NAMES_EXCISED = ["Advance Level", "Basic Level", "Intermediate Level"]

GATED = {
    "cluster": ["Basic Operations (+, -, ×, ÷)", "Arithmetic: Basic Operations (+, -, ×, ÷)",
                "Arithmetic:Basic Operations", "Arithmetic:Basic Operations (+, -, ×, ÷)"],
    "survivor": "Basic Operations (+, -, ×, ÷)",
    "why_gated": "This merge DOES touch skill_keys that BKT mastery joins on. Footprint: "
                 "survivor holds 34 REQUIRES edges / 75 closure rows / 289 Q-matrix problems; "
                 "the variants add 3 edges / 43 closure rows / 16 problems. Requires its own "
                 "operation with backend: Q-matrix re-point + closure rebuild into the shadow "
                 "table + diff, with the mastery-key migration.",
}

ORPHAN_PROBLEMS_DECLINED = {
    "problems": ["Schaums_College_Math_sa_" + n for n in
                 "11 13 14 16 19 20 21 24 25 26 27 30 31".split()],
    "decline_reason": "No skill edge added. These 13 :Problem nodes carry an EMPTY technique "
                      "field and only a coarse topic ('General' x10, 'DI' x3). Since the "
                      "Q-matrix is now the BKT join spine, deriving a mastery edge from a label "
                      "that carries no instructional meaning would corrupt mastery signal — "
                      "worse than the current gap.",
    "consequence": "They remain invisible to BKT: a learner can answer them and no skill updates.",
    "fix_owner": "extraction — needs technique enrichment at source, then edges can be derived.",
}


def main() -> int:
    cand = json.loads(CANDIDATE.read_text())
    entries = cand["entries"]
    by_label = {e["label"]: e for e in entries}

    absorbed = {lost: surv for surv, losts in CLASS_A_MERGES.items() for lost in losts}
    mappings = list(cand.get("label_mappings") or [])
    existing_pairs = {(m.get("from"), m.get("to")) for m in mappings if isinstance(m, dict)}

    promoted, declined = [], []
    for e in entries:
        label = e["label"]
        if label in BAND_NAMES_EXCISED:
            declined.append({"label": label, "reason": "bare difficulty band, not a subject",
                             "method": "exact match"})
            continue
        if label in absorbed:
            declined.append({"label": label, "reason": f"merged into '{absorbed[label]}'",
                             "kind": "semantic_merge"})
            continue
        if e.get("status") == "excluded":
            declined.append({"label": label,
                             "reason": e.get("review_note") or "excluded by candidate"})
            continue
        out = dict(e)
        # skill_key is the stable machine key; never rewritten by a display decision.
        out["skill_key"] = CLASS_C_ALIASES.get(label, label)
        out["display_label"] = label
        if label in CLASS_C_ALIASES:
            out["mapping_kind"] = "display_alias"
            out["mapping_note"] = ("display label mapped onto an existing :Skill.name; "
                                   "the key is NOT renamed, so no mastery migration")
        if label in CLASS_A_MERGES:
            out["absorbed_labels"] = CLASS_A_MERGES[label]
        if label in GATED["cluster"]:
            out["gated"] = True
            out["gated_reason"] = GATED["why_gated"]
        if e.get("review_tier") in ("long_tail", "compound_needs_split"):
            out["promotion_status"] = "carried_unresolved"
            out["open_question"] = ("awaiting a splitting/long-tail convention — a taxonomy "
                                    "decision, not a merge call; deliberately not invented here")
        else:
            out.setdefault("promotion_status", "promoted")
        promoted.append(out)

    for lost, surv in absorbed.items():
        if (lost, surv) not in existing_pairs:
            mappings.append({"from": lost, "to": surv, "kind": "semantic_merge",
                             "added_by": "rag_review_v1"})
    for lost, surv in CLASS_C_ALIASES.items():
        if (lost, surv) not in existing_pairs:
            mappings.append({"from": lost, "to": surv, "kind": "display_alias",
                             "added_by": "rag_review_v1",
                             "note": "display label -> existing skill_key; not a rename"})

    doc = {
        "version": "taxonomy_v1",
        "promoted_from": f"{CANDIDATE.name} ({cand.get('version')}, generated {cand.get('generated')})",
        "promoted_by": "Speed Gym RAG — review at docs/rag/TAXONOMY_V1_REVIEW.md",
        "authority": ("AUTHORITATIVE for display labels and corpus->skill mapping. "
                      "NOT authoritative for :Skill.name — skill_key mirrors the live graph."),
        "key_architecture": {
            "skill_key": "existing :Skill.name — the stable key BKT mastery joins on; never "
                         "rewritten by a display decision",
            "display_label": "human-facing string; owner-changeable at any time with zero "
                             "migration and no closure rebuild",
        },
        "migration_impact": {
            "skill_names_renamed": 0,
            "mastery_key_migration_required": False,
            "prerequisite_closure_rebuild_required": False,
            "user_visible_change": "none — no served surface consumes these labels yet",
        },
        "counts": {"promoted": len(promoted), "declined": len(declined),
                   "carried_unresolved": sum(1 for p in promoted
                                             if p.get("promotion_status") == "carried_unresolved"),
                   "label_mappings": len(mappings)},
        "class_a_merges_applied": CLASS_A_MERGES,
        "class_c_display_aliases": CLASS_C_ALIASES,
        "rejected_merges": REJECTED_MERGES,
        "band_names_excised": BAND_NAMES_EXCISED,
        "gated_not_applied": GATED,
        "orphan_problems_declined": ORPHAN_PROBLEMS_DECLINED,
        "declined": declined,
        "label_mappings": mappings,
        "entries": promoted,
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(f"promoted {len(promoted)} | declined {len(declined)} "
          f"(all with reasons) | mappings {len(mappings)}")
    print(f"carried unresolved: {doc['counts']['carried_unresolved']} "
          f"| skill_keys renamed: 0 | gated cluster: {len(GATED['cluster'])} labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
