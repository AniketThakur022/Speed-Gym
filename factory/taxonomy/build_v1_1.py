#!/usr/bin/env python3
"""taxonomy_v1.1 — lift corpus resolution by routing through book chapters.

v1 resolved 10.4% of the 19,619 exported questions, because question_sets carry no
topic field. 85% DO carry a book chapter, so the chapter is the per-question signal.

This adds two things to v1:
  1. `chapter_rules`: normalized chapter -> taxonomy entry, so a consumer can resolve
     a question by (book, chapter) without re-deriving anything.
  2. new subject entries for real subjects absent from v1's 201.

Discipline carried over from the v1 review:
  - A chapter that is a STRUCTURAL CONTAINER (block extras, mixed review tests,
    practice tests, bare "Chapter 37", miscellaneous example dumps) is NOT a subject.
    Mapping it would attach a confident subject label to mixed content, which is
    worse than leaving it unresolved. These are declined WITH reasons.
  - skill_key is never invented over an existing graph name; where no :Skill exists
    the entry is marked graph_backed=false — usable for corpus labelling, NOT
    joinable to BKT until a skill node exists.
  - Empty normalized keys are rejected: stripping "Chapter 33" and "Chapter 11" both
    yield "", which collided and mislabelled 63 questions in a first pass.
"""

import json
import re
from collections import Counter
from pathlib import Path

EXPORT = Path("data/exports/vmsg_questions_v1.jsonl")
V1 = Path("data/taxonomy/taxonomy_v1.json")
OUT = Path("data/taxonomy/taxonomy_v1_1.json")
SKILLS_CSV = Path("/tmp/skills.csv")

# Chapter strings that are containers of mixed content, not subjects.
STRUCTURAL = re.compile(
    r"block\s+[ivx\d]+\s+extras|review\s+test|taste\s+of\s+the\s+exam|training\s+ground"
    r"|practice\s+test|miscellaneous\s+example|^\s*(ch(apter)?\s*)?\d+\s*$"
    r"|^appendix|^index|^answers?$|^solutions?$|^glossary|^preface|^introduction$",
    re.I)

CHAPTER_PREFIX = re.compile(r"^\s*(ch(apter)?\s*\d+\s*[.:)-]?\s*|\d+\s*[.:)]\s*)", re.I)

# Real subjects seen in the corpus with no matching :Skill node. Canonical name ->
# (domain, aliases seen in chapter strings).
NEW_SUBJECTS = {
    "Number Systems": ("Arithmetic", ["number systems", "number system"]),
    "Geometry and Mensuration": ("Geometry", ["geometry and mensuration", "mensuration"]),
    "Reading Comprehension": ("Verbal", ["reading comprehension"]),
    "Vector Spaces": ("Algebra", ["vector spaces and subspaces", "vector spaces"]),
    "Time, Speed and Distance": ("Arithmetic", ["time speed and distance", "time, speed and distance"]),
    "Eigenvalues and Eigenvectors": ("Algebra", ["eigenvalues and eigenvectors"]),
    "Progressions": ("Algebra", ["progressions"]),
    "Profit and Loss": ("Arithmetic", ["profit loss", "profit and loss", "profit & loss"]),
    "Sentence Equivalence": ("Verbal", ["sentence equivalence"]),
    "Text Completions": ("Verbal", ["text completions", "text completion"]),
    "Quadratic and Other Equations": ("Algebra", ["quadratic and other equations"]),
    "Ratio, Proportion and Variation": ("Arithmetic", ["ratio proportion and variation",
                                                      "ratio, proportion and variation"]),
    "Time and Work": ("Arithmetic", ["time and work"]),
    "Orthogonality": ("Algebra", ["orthogonality"]),
    "Binomial Coefficients": ("Algebra", ["binomial coefficients"]),
    "Theory of Equations": ("Algebra", ["theory of equations"]),
    "Averages and Alligations": ("Arithmetic", ["averages", "alligations", "averages and alligations"]),
    "Percentages": ("Arithmetic", ["percentages", "percentage"]),
    "Interest": ("Arithmetic", ["interest", "simple interest", "compound interest"]),
    "Permutations and Combinations": ("Algebra", ["permutations and combinations",
                                                 "permutation and combination"]),
    # added after auditing the first pass's declines
    "Probability": ("Statistics", ["probability"]),
    "Probability Distributions": ("Statistics", ["distributions of the discrete type",
                                                 "distributions of the continuous type",
                                                 "probability distributions"]),
    "Linear Transformations": ("Algebra", ["linear transformations"]),
    "Vectors": ("Algebra", ["introduction to vectors", "vectors"]),
    "Binomial Theorem": ("Algebra", ["binomial theorem any index",
                                     "binomial theorem positive integral index",
                                     "binomial theorem"]),
    "Special Numbers": ("NumberTheory", ["special numbers"]),
    "Elementary Algebra": ("Algebra", ["elementary algebra"]),
    "Miscellaneous Equations": ("Algebra", ["miscellaneous equations"]),
    "Sequences and Series": ("Algebra", ["sequences and series", "series"]),
    "Set Theory": ("Logic", ["set theory", "sets"]),
}


def norm(s: str) -> str:
    s = CHAPTER_PREFIX.sub("", s.strip())
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def main() -> int:
    v1 = json.loads(V1.read_text())
    entries = list(v1["entries"])
    by_norm = {}
    for e in entries:
        # Index the label AND every alias — indexing labels alone silently lost
        # "Vector Spaces and Subspaces" and "Profit & Loss" in the first pass.
        for cand in [e.get("display_label") or e["label"], *(e.get("aliases") or [])]:
            k = norm(cand)
            if k:
                by_norm.setdefault(k, e)

    skills = {}
    if SKILLS_CSV.exists():
        import csv
        for row in csv.reader(SKILLS_CSV.open()):
            if len(row) >= 2 and row[0] != "name":
                skills[row[0].strip('"')] = row[1].strip().lower() == "true"
    skill_by_norm = {}
    for name in skills:
        k = norm(name)
        if k:  # guard: "Chapter 11" normalises to "" and would collide
            skill_by_norm.setdefault(k, name)

    # add new subject entries
    added = []
    for canon, (domain, aliases) in NEW_SUBJECTS.items():
        k = norm(canon)
        if k in by_norm:
            continue
        graph_name = skill_by_norm.get(k)
        e = {
            "id": f"vmsg.skill.{domain.lower()}.{re.sub(r'[^a-z0-9]+', '_', canon.lower()).strip('_')}",
            "type": "skill", "label": canon, "domain": domain, "aliases": aliases,
            "skill_key": graph_name or canon,
            "display_label": canon,
            "graph_backed": bool(graph_name),
            "status": "derived", "confidence": "medium",
            "promotion_status": "promoted_v1_1",
            "provenance": [{"source": "corpus_chapter", "note":
                            "real subject observed as a book chapter, absent from v1"}],
            "note": None if graph_name else
                    "no :Skill node yet — usable for corpus labelling, NOT joinable to BKT "
                    "until a skill node exists",
        }
        entries.append(e)
        # Index the canonical form AND the aliases. Indexing only the canonical name
        # left "Vector Spaces and Subspaces" and "Profit & Loss" unresolved even
        # though both were listed as aliases.
        for cand in [canon, *aliases]:
            ak = norm(cand)
            if ak:
                by_norm.setdefault(ak, e)
        added.append(canon)

    # Book display names differ across the three vocabularies; the shared map exists
    # because comparing them as strings has already caused three cross-workstream
    # errors. Rules carry canonical_book_id so consumers never join on a display name.
    book_map = {}
    bm_path = Path("data/taxonomy/book_name_map.json")
    if bm_path.exists():
        recs = json.loads(bm_path.read_text())["books"]
        recs = list(recs.values()) if isinstance(recs, dict) else recs
        for rec in recs:
            for field in ("master_book", "graph_book", "page_store", "title", "canonical_id"):
                val = rec.get(field)
                for v in (val if isinstance(val, list) else [val]):
                    if isinstance(v, str):
                        book_map.setdefault(v, rec.get("canonical_id"))

    # chapter rules from the export
    counts, resolved_by, declined = Counter(), {}, {}
    for line in EXPORT.open():
        r = json.loads(line)
        ch = (r.get("chapter") or "").strip()
        if not ch:
            continue
        counts[(r["book"], ch)] += 1

    rules, lift = [], 0
    for (book, ch), n in counts.most_common():
        if STRUCTURAL.search(ch):
            declined[f"{book} :: {ch}"] = {
                "questions": n,
                "reason": "structural container of mixed content (block extras / review or "
                          "practice test / miscellaneous dump / bare chapter number), not a "
                          "subject — a confident subject label here would be wrong"}
            continue
        k = norm(ch)
        if not k:
            declined[f"{book} :: {ch}"] = {"questions": n,
                                           "reason": "chapter normalises to an empty key"}
            continue
        e = by_norm.get(k) or ({} if k not in skill_by_norm else None)
        if e is None:  # exists as a graph skill but not as a taxonomy entry
            name = skill_by_norm[k]
            e = {"skill_key": name, "display_label": name, "graph_backed": True,
                 "id": None, "label": name}
            entries.append({**e, "type": "skill", "status": "derived",
                            "confidence": "medium", "promotion_status": "promoted_v1_1",
                            "provenance": [{"source": "graph_skill_matched_by_chapter"}]})
            by_norm[k] = e
        if not e:
            declined[f"{book} :: {ch}"] = {
                "questions": n,
                "reason": "no taxonomy entry or :Skill matches this chapter subject"}
            continue
        rules.append({"book": book, "canonical_book_id": book_map.get(book),
                      "chapter": ch, "normalized": k,
                      "skill_key": e["skill_key"], "display_label": e.get("display_label"),
                      "graph_backed": e.get("graph_backed", True), "questions": n})
        lift += n

    doc = {
        "version": "taxonomy_v1.1",
        "supersedes": "taxonomy_v1",
        "built_by": "factory/taxonomy/build_v1_1.py",
        "why": "v1 resolved 10.4% of exported questions because question_sets carry no topic "
               "field; 85% carry a chapter, so chapters are the per-question signal.",
        "key_architecture": v1["key_architecture"],
        "migration_impact": {**v1["migration_impact"],
                             "note": "v1.1 adds entries and chapter rules only; no skill_key "
                                     "renamed, no mastery migration, no closure rebuild"},
        "counts": {"entries": len(entries), "new_subjects_added": len(added),
                   "chapter_rules": len(rules),
                   "questions_covered_by_rules": lift,
                   "chapters_declined": len(declined),
                   "questions_in_declined_chapters": sum(d["questions"] for d in declined.values())},
        "new_subjects": added,
        "chapter_rules": rules,
        "declined_chapters": declined,
        "class_a_merges_applied": v1["class_a_merges_applied"],
        "class_c_display_aliases": v1["class_c_display_aliases"],
        "rejected_merges": v1["rejected_merges"],
        "gated_not_applied": v1["gated_not_applied"],
        "orphan_problems_declined": v1["orphan_problems_declined"],
        "label_mappings": v1["label_mappings"],
        "entries": entries,
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(f"entries {len(entries)} (+{len(added)} new subjects) | chapter rules {len(rules)} "
          f"covering {lift} questions | declined chapters {len(declined)} "
          f"({doc['counts']['questions_in_declined_chapters']} questions, all with reasons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
