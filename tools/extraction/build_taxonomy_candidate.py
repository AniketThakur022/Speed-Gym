#!/usr/bin/env python3
"""Build taxonomy_v1_candidate — a REVIEWABLE candidate vocabulary, not an authority.

Authorized 2026-09-03 (coordinator, Option B). No canonical taxonomy exists:
only 12 of 107 corpus topics match any Neo4j :Skill name even after
normalization, and 374 of 467 :Skill nodes are is_stub placeholders. Rather
than invent a third vocabulary silently, this derives a candidate from the
normalized union of the three sources we actually have, records where every
label came from, and marks its own confidence.

CONTRACT: nothing downstream treats this as authoritative until reviewed.
RAG reviews against the graph + ontology (they own corpus->graph mapping);
backend holds BKT joins until the reviewed v1. Until then the flattened export
carries raw label + normalized key + taxonomy_status: unresolved.

Sources, in descending trust:
  1. Neo4j :Skill, non-stub only (93) — the one curated set: every entry has
     name + topic + sub_topic across 9 domains.  -> status "curated"
  2. ontology_registry.yaml (43: 16 sutras, 9 techniques, 7 traps, 5 skills,
     6 strategies) — hand-written with aliases.   -> status "curated"
  3. MASTER explainer.topic (108 labels) — extraction output, uneven.
                                                  -> status "derived"

Entry shape follows withmarbleapp/os-taxonomy (stable id, type, domain,
description) — the proven schema for exactly this job (see reference-links).

Book-structure labels are EXCLUDED EXPLICITLY with a reason, never dropped
silently, so a reviewer can audit the exclusions as easily as the inclusions.

Usage:
    python3 build_taxonomy_candidate.py <out.json>
"""

import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"
NODES = ROOT / "incoming/topic_browser_full_package/db_exports/nodes.jsonl"
ONTOLOGY = Path(__file__).resolve().parent / "ontology_registry.yaml"

# Labels that are page furniture or difficulty bands, not subject matter.
EXCLUDE = [
    (re.compile(r"^\s*part\s+[ivxl]+\b", re.I), "book-structure: Schaum part title, not a subject"),
    (re.compile(r"^\s*\d+\.\s", re.I), "book-structure: numbered chapter heading"),
    (re.compile(r"^\s*(appendix|appendices|front\s*matter|preface|contents|index)\b", re.I),
     "book-structure: front/back matter"),
    (re.compile(r"answer[\s_-]*key", re.I),
     "extraction artifact: an answer-key section header captured as a topic"),
    (re.compile(r"^\s*(basic|intermediate|advance[d]?|beginner|expert)\s+level\s*$", re.I),
     "difficulty band, not a subject — belongs in a difficulty field"),
]


def norm_key(s):
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = re.sub(r"[_\-\s]+", " ", s)
    s = re.sub(r"\s*:\s*", ": ", s)
    s = re.sub(r"[^\w\s:&/+]", "", s)
    return s.casefold().strip()


def slug(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


def excluded_reason(label):
    for pat, why in EXCLUDE:
        if pat.search(label):
            return why
    return None


def display_form(variants):
    """House style: spaced Title-ish form wins over hyphenated/lowercase."""
    def score(item):
        label, count = item
        spaced = "_" not in label and "-" not in label
        acronym = label.isupper() and len(label) <= 5
        titleish = acronym or (any(c.isupper() for c in label) and not label.isupper())
        return (not spaced, not titleish, -count, len(label), label)
    return sorted(variants.items(), key=score)[0][0]


def load_ontology():
    """Minimal reader for the registry's canonical/aliases/description shape."""
    out, section, cur = [], None, None
    for line in ONTOLOGY.read_text().splitlines():
        m = re.match(r"^(\w+):\s*$", line)
        if m:
            section = m.group(1)
            continue
        if re.match(r"\s*-\s+canonical:", line):
            if cur:
                out.append(cur)
            val = re.sub(r'\s*-\s+canonical:\s*"?(.*?)"?\s*$', r"\1", line)
            cur = {"section": section, "canonical": val, "aliases": [], "description": ""}
        elif cur is not None:
            a = re.match(r'\s*aliases:\s*\[(.*)\]\s*$', line)
            if a:
                cur["aliases"] = [x.strip().strip('"') for x in a.group(1).split(",") if x.strip()]
            d = re.match(r'\s*description:\s*"?(.*?)"?\s*$', line)
            if d:
                cur["description"] = d.group(1)
    if cur:
        out.append(cur)
    return out


def main(out_path):
    entries = {}          # norm_key -> entry
    def touch(key, **kw):
        e = entries.setdefault(key, {
            "id": None, "type": None, "label": None, "domain": None,
            "description": "", "aliases": set(), "provenance": [], "status": None,
        })
        for k, v in kw.items():
            if k == "alias":
                e["aliases"].add(v)
            elif k == "provenance":
                e["provenance"].append(v)
            elif v and not e.get(k):
                e[k] = v
        return e

    # ---- source 1: non-stub Neo4j :Skill (curated) ----
    skills = []
    with NODES.open() as f:
        for line in f:
            n = json.loads(line)
            if "Skill" in (n.get("_labels") or []):
                skills.append(n)
    n_skill = 0
    for s in skills:
        name = s.get("name")
        if not name or s.get("is_stub"):
            continue
        k = norm_key(name)
        e = touch(k, type="skill", label=name, domain=s.get("topic"),
                  description=s.get("sub_topic") or "",
                  provenance={"source": "neo4j_skill_nonstub", "name": name,
                              "topic": s.get("topic"), "sub_topic": s.get("sub_topic")})
        e["aliases"].add(name)
        e["status"] = "curated"
        n_skill += 1

    # ---- source 2: ontology_registry (curated) ----
    TYPE = {"sutras": "sutra", "techniques": "technique", "traps": "trap",
            "skills": "skill", "strategies": "strategy"}
    n_ont = 0
    for o in load_ontology():
        k = norm_key(o["canonical"])
        e = touch(k, type=TYPE.get(o["section"], "concept"), label=o["canonical"],
                  domain="VedicMath" if o["section"] in ("sutras", "strategies") else None,
                  description=o.get("description") or "",
                  provenance={"source": "ontology_registry", "section": o["section"],
                              "canonical": o["canonical"]})
        e["aliases"].add(o["canonical"])
        for a in o["aliases"]:
            e["aliases"].add(a)
        e["status"] = "curated"
        n_ont += 1

    # ---- source 3: corpus explainer.topic (derived) ----
    topics = collections.Counter()
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            ex = r.get("explainer")
            if isinstance(ex, dict) and ex.get("topic"):
                topics[ex["topic"]] += 1
    clusters = collections.defaultdict(collections.Counter)
    for label, c in topics.items():
        clusters[norm_key(label)][label] = c

    n_excl = n_new = n_reinforced = 0
    for k, variants in clusters.items():
        label = display_form(variants)
        why = excluded_reason(label)
        occurrences = sum(variants.values())
        if why:
            n_excl += 1
            entries["__excluded__" + k] = {
                "id": "excluded." + slug(label), "type": "excluded", "label": label,
                "domain": None, "description": "", "aliases": sorted(variants),
                "provenance": [{"source": "corpus_explainer_topic",
                                "occurrences": occurrences}],
                "status": "excluded", "exclusion_reason": why,
            }
            continue
        existing = entries.get(k)
        e = touch(k, type="topic", label=label,
                  provenance={"source": "corpus_explainer_topic",
                              "occurrences": occurrences,
                              "variants": sorted(variants)})
        for v in variants:
            e["aliases"].add(v)
        if existing:
            n_reinforced += 1          # corpus label confirms a curated entry
        else:
            e["status"] = "derived"
            n_new += 1

    # ---- finalize ----
    final = []
    for k, e in entries.items():
        if e["status"] == "excluded":
            final.append(e)
            continue
        dom = e.get("domain")
        e["id"] = "vmsg.%s.%s%s" % (e["type"], (slug(dom) + ".") if dom else "", slug(e["label"]))
        e["aliases"] = sorted(a for a in e["aliases"] if a != e["label"])
        e["confidence"] = {"curated": "high", "derived": "low"}[e["status"]]
        occ = sum(p.get("occurrences", 0) for p in e["provenance"])
        e["occurrences"] = occ
        if e["status"] == "derived":
            # Triage hint for the reviewer: usage weight separates real subject
            # areas from one-off extraction noise, and " / " compounds are
            # over-specified labels that likely split into existing entries.
            e["review_tier"] = "substantive" if occ >= 4 else "long_tail"
            if " / " in e["label"]:
                e["review_tier"] = "compound_needs_split"
        e["review_note"] = ("confirmed by both a curated source and corpus usage"
                            if e["status"] == "curated" and any(
                                p["source"] == "corpus_explainer_topic" for p in e["provenance"])
                            else "")
        final.append(e)
    # Reviewer aid: surface likely same-concept pairs that the surface
    # normalizer correctly kept apart because the WORDS differ ("Logical
    # Reasoning" vs "Logic Reasoning"). Merging these is a semantic judgement,
    # so this only points at them — it never merges.
    STOP = {"and", "of", "the", "in", "to", "for", "a"}
    def stem_set(label):
        ws = [w for w in re.findall(r"[a-z]+", label.lower()) if w not in STOP]
        return {w[:5] for w in ws}          # crude stem: 'logical'/'logic' -> 'logic'
    live = [e for e in final if e["status"] != "excluded"]
    for i, a in enumerate(live):
        sa = stem_set(a["label"])
        if not sa:
            continue
        hits = []
        for b in live[i + 1:]:
            sb = stem_set(b["label"])
            if not sb:
                continue
            j = len(sa & sb) / len(sa | sb)
            if j >= 0.6:
                hit = {"id": b["id"], "label": b["label"], "overlap": round(j, 2)}
                # Token overlap cannot see negation: "Non-Verbal Reasoning" and
                # "Verbal Reasoning" score 0.67 but are OPPOSITES. Warn loudly
                # so a reviewer never merges them on this hint alone.
                neg = re.compile(r"\b(non|un|in)[\s-]?", re.I)
                if bool(neg.match(a["label"])) != bool(neg.match(b["label"])):
                    hit["warning"] = ("NEGATION MISMATCH — one label is a negated form "
                                      "of the other; these are opposites, not duplicates")
                hits.append(hit)
        if hits:
            a.setdefault("possible_duplicates", []).extend(hits)
            for h in hits:
                nb = next(x for x in live if x["id"] == h["id"])
                nb.setdefault("possible_duplicates", []).append(
                    {"id": a["id"], "label": a["label"], "overlap": h["overlap"]})

    final.sort(key=lambda x: (x["status"], x["type"], x["label"].lower()))

    # ---- explicit old -> new label mappings ----
    # Backend constraint (2026-09-03): any merge/rename in an accepted v1 needs a
    # matching migration of user mastery keys plus a closure rebuild, so this file
    # must always ship old->new mappings, never just the surviving label list.
    # Every raw label ever observed appears here exactly once.
    label_mappings = {}
    for e in final:
        if e["status"] == "excluded":
            for raw in e["aliases"]:
                label_mappings[raw] = {"to_id": None, "kind": "excluded",
                                       "reason": e["exclusion_reason"]}
            label_mappings[e["label"]] = {"to_id": None, "kind": "excluded",
                                          "reason": e["exclusion_reason"]}
            continue
        label_mappings[e["label"]] = {"to_id": e["id"], "kind": "canonical"}
        for raw in e["aliases"]:
            label_mappings.setdefault(raw, {"to_id": e["id"], "kind": "surface_variant"})

    doc = {
        "version": "taxonomy_v1_candidate",
        "generated": "2026-09-03",
        "authority": "CANDIDATE ONLY — not authoritative until reviewed by RAG "
                     "(against graph + ontology) and accepted by backend for BKT joins",
        "rename_constraint": (
            "Backend requirement: every merge/rename decided during review MUST be "
            "recorded in label_mappings as an old->new pair, because accepting it "
            "requires migrating user mastery keys and rebuilding the prerequisite "
            "closure. A reviewer who merges two entries must add the losing label "
            "with kind='semantic_merge' pointing at the surviving id — never delete "
            "the losing label from this file."),
        "label_mappings_note": (
            "Complete old->new map for every raw label observed anywhere. kind: "
            "'canonical' (the surviving display form), 'surface_variant' (casing/"
            "separator spelling of the same label), 'semantic_merge' (added by "
            "review when two different labels are judged the same concept), or "
            "'excluded' (to_id null, with reason)."),
        "label_mappings": label_mappings,
        "sources": {
            "neo4j_skill_nonstub": n_skill,
            "ontology_registry": n_ont,
            "corpus_explainer_topic_new": n_new,
            "corpus_explainer_topic_reinforcing": n_reinforced,
            "excluded": n_excl,
        },
        "status_meaning": {
            "curated": "from a hand-built source (non-stub :Skill with domain, or "
                       "ontology_registry) — high confidence",
            "derived": "seen only as a corpus extraction label — LOW confidence, "
                       "review before any downstream join",
            "excluded": "book structure or difficulty band, not subject matter — "
                        "listed with a reason so exclusions are auditable",
        },
        "entries": final,
    }
    Path(out_path).write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(json.dumps(doc["sources"], indent=1))
    print("total entries: %d (curated %d, derived %d, excluded %d) -> %s"
          % (len(final),
             sum(1 for e in final if e["status"] == "curated"),
             sum(1 for e in final if e["status"] == "derived"),
             sum(1 for e in final if e["status"] == "excluded"), out_path))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
