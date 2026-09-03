#!/usr/bin/env python3
"""Flatten MASTER_corpus.jsonl to a question-level export for the RAG factory.

The deliverable this chat owes RAG: one row per question, keyed by
set_id + question number, with canonical taxonomy where it exists, honest
verification semantics, and an explicit playability verdict.

Three contracts are enforced here rather than left to the consumer:

1. VERIFICATION SEMANTICS ([[content-verification-semantics]]). Answer
   correctness, answer provenance and derivation correctness are three
   separate fields. `derivation_check` is emitted as "none" on every row —
   no pipeline has ever validated a walkthrough — so absence can never be
   misread as a pass.

2. TAXONOMY ([[taxonomy_v1]]). `skill_key` mirrors the live :Skill name and is
   the BKT join key; `display_label` is owner-changeable with zero migration.
   Where a label does not resolve, the row carries raw + normalized key +
   taxonomy_status "unresolved" — never a fabricated id.

3. PLAYABILITY. `playable` is a verdict with its reasons listed in
   `playable_blockers`, so a consumer can widen or narrow the filter without
   re-deriving it. A question is playable only if it has an answer key, text
   we trust, an answerable format, and options when its format needs them.

Note on taxonomy coverage: question_set records carry NO topic field — the
only per-question signal is the book chapter (72% of records). So taxonomy
here is chapter-derived and thin by nature; that is a property of the corpus,
not a bug in this export.

Usage:
    python3 build_question_export.py <out.jsonl> [--manifest <out.json>]
"""

import argparse
import collections
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"
TAXONOMY = ROOT / "data/taxonomy/taxonomy_v1.json"
TAXONOMY_V1_1 = ROOT / "data/taxonomy/taxonomy_v1_1.json"
BOOK_MAP = ROOT / "data/taxonomy/book_name_map.json"

CH_PREFIX = re.compile(r"^\s*(ch(apter)?\.?\s*)?\d+\s*[.:)\-]?\s*", re.I)
TRAIL_PAREN = re.compile(r"\s*\([^)]*\)\s*$")

# Formats whose answer is chosen from printed options.
OPTION_FORMATS = {"multiple_choice", "multi_select", "quantitative_comparison",
                  "text_completion", "select_in_passage"}
# Formats that cannot be auto-graded as-is.
UNPLAYABLE_FORMATS = {"unclassified", "options_are_images"}


def norm_key(s, strip_chapter=False):
    s = unicodedata.normalize("NFKC", str(s)).strip()
    if strip_chapter:
        s = CH_PREFIX.sub("", s)
        s = TRAIL_PAREN.sub("", s)
    s = re.sub(r"[_\-\s]+", " ", s)
    s = re.sub(r"\s*:\s*", ": ", s)
    s = re.sub(r"[^\w\s:&/+]", "", s)
    return s.casefold().strip()


def load_taxonomy():
    """Resolve against the newest taxonomy present.

    v1.1 introduced rules keyed on (book, chapter) rather than the label alone,
    because one chapter title means different things in different books. Those
    rules win; a bare label match is the fallback. v1.1 also declines 285
    structural-container chapters WITH reasons — carrying that reason through is
    strictly better than reporting them as generically unresolved.
    """
    path = TAXONOMY_V1_1 if TAXONOMY_V1_1.exists() else TAXONOMY
    if not path.exists():
        return {}, {}, {}, None
    doc = json.loads(path.read_text())

    by_label = {}
    for e in doc.get("entries", []):
        for lab in [e.get("label")] + (e.get("aliases") or []):
            if lab:
                by_label.setdefault(norm_key(lab), e)

    by_skill_key = {}
    for e in doc.get("entries", []):
        if e.get("skill_key"):
            by_skill_key.setdefault(e["skill_key"], e)

    by_book_chapter = {}
    for rule in doc.get("chapter_rules", []):
        key = (rule.get("book"), norm_key(rule.get("chapter") or "", strip_chapter=True))
        rule = dict(rule)
        # rules name a skill_key but no stable id — recover it where the entry
        # list has one, so a consumer gets both the join key and the id.
        ent = by_skill_key.get(rule.get("skill_key"))
        if ent and ent.get("id"):
            rule.setdefault("id", ent["id"])
        by_book_chapter[key] = rule

    declined = {}
    for k, v in (doc.get("declined_chapters") or {}).items():
        # keys look like "Book :: Chapter"
        if " :: " in k:
            book, chap = k.split(" :: ", 1)
            declined[(book, norm_key(chap, strip_chapter=True))] = v
    return by_label, by_book_chapter, declined, doc.get("version")


def load_book_map():
    """master_book -> canonical book record.

    Three vocabularies name the same book differently (MASTER, the graph, the
    page store), and comparing them as strings has already caused three
    cross-workstream errors. Rows therefore carry canonical_id so nobody has
    to string-match a display name.
    """
    if not BOOK_MAP.exists():
        return {}
    doc = json.loads(BOOK_MAP.read_text())
    return {b["master_book"]: b for b in doc.get("books", []) if b.get("master_book")}


def graph_backing(entry):
    """True only on evidence. Absence of the field is not a claim either way."""
    if entry is None:
        return None
    if "graph_backed" in entry:
        return bool(entry["graph_backed"])
    for p in entry.get("provenance") or []:
        if p.get("source") == "neo4j_skill_nonstub":
            return True
    return False


def classify_answer_provenance(q):
    """What kind of evidence stands behind this answer key?"""
    ks = (q.get("key_source") or "")
    if not q.get("answer_key"):
        return None
    low = ks.lower()
    # A printed answer table/section the book itself supplies. Note the corpus
    # writes this several ways — answer_key_grid, answer_grid, "Answers to
    # Selected Exercises", "... answer section" — so match the family, not one
    # spelling (an earlier version checked "answer key" with a space and so
    # mislabelled ~4,900 grid-sourced keys as generic "other").
    if any(t in low for t in ("answer_key_grid", "answer_grid", "answer key",
                              "answers to practice", "answers to selected",
                              "answer section", "official answer")):
        return "printed_grid"
    if any(t in low for t in ("ans.", "bold at the head", "problem set answer",
                              "inline solution", "answer choice")):
        return "printed_inline_answer"
    if "solution_note" in low:
        return "solution_note_derivation"
    if "hint_verdict" in low:
        return "hint_verdict_derivation"
    if ks:
        return "other_cited"
    return "uncited"


def errata_code(v):
    """Collapse errata prose to a stable code (the raw text stays in flags)."""
    s = str(v).strip().lower()
    if "confirmed_book_erratum" in s:
        return "confirmed_book_erratum"
    if "proven_wrong" in s:
        return "proven_wrong"
    if "raster image" in s or "math image" in s:
        return "key_is_raster_image"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--manifest")
    args = ap.parse_args()

    tax_by_label, tax_by_bc, tax_declined, tax_version = load_taxonomy()
    book_map = load_book_map()
    rows = []
    stats = collections.Counter()
    blockers = collections.Counter()
    prov = collections.Counter()
    unresolved_chapters = collections.Counter()

    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("content_type") != "question_set":
                continue
            rex = r.get("extra") or {}
            chapter = r.get("chapter")
            nchap = norm_key(chapter, strip_chapter=True) if chapter else None
            book = r.get("book")
            # (book, chapter) rule first, then a bare-label match, then declined.
            entry = tax_by_bc.get((book, nchap)) if nchap else None
            resolved_by = "book_chapter_rule" if entry else None
            if entry is None and nchap:
                entry = tax_by_label.get(nchap)
                resolved_by = "label_match" if entry else None
            decline = tax_declined.get((book, nchap)) if nchap else None

            # 12 records (all Sinha) hold two entries under one question number:
            # the real question plus a hint/solution capture from the same
            # fused-prose extraction defect. The row key must stay unique, so
            # 2nd+ occurrences get a ~N suffix and the whole group is flagged
            # and blocked — we cannot tell downstream which twin is the question.
            num_counts = collections.Counter(str(q.get("number"))
                                             for q in (r.get("questions") or []))
            seen_num = collections.Counter()

            for q in r.get("questions") or []:
                qex = q.get("extra") or {}
                fmt = q.get("question_format") or "unclassified"
                opts = q.get("options") or []
                text = (q.get("text") or "").strip()
                num = str(q.get("number"))
                seen_num[num] += 1
                dup_number = num_counts[num] > 1

                blk = []
                if dup_number:
                    blk.append("duplicate_question_number_in_record")
                if not q.get("answer_key"):
                    blk.append("no_answer_key")
                if qex.get("needs_reextraction"):
                    blk.append("text_is_misextracted")
                if qex.get("needs_vision"):
                    blk.append("needs_vision")
                if fmt in UNPLAYABLE_FORMATS:
                    blk.append("format_%s" % fmt)
                if fmt in OPTION_FORMATS and len(opts) < 2:
                    blk.append("option_format_without_options")
                if len(text) < 12:
                    blk.append("text_too_short")
                if q.get("errata"):
                    blk.append("errata_%s" % errata_code(q["errata"]))
                if qex.get("key_suspect"):
                    blk.append("key_suspect")

                provenance = classify_answer_provenance(q)
                row = {
                    "question_id": ("%s#%s" % (r["set_id"], num)
                                    if seen_num[num] == 1
                                    else "%s#%s~%d" % (r["set_id"], num, seen_num[num])),
                    "set_id": r["set_id"],
                    "number": num,
                    "duplicate_number_in_record": dup_number,
                    "book": r.get("book"),
                    "book_title": r.get("book_title"),
                    "book_canonical_id": (book_map.get(book) or {}).get("canonical_id"),
                    "book_in_graph": (book_map.get(book) or {}).get("in_graph"),
                    "chapter": chapter,
                    "pdf_pages": r.get("pdf_pages") or [],
                    "text": q.get("text"),
                    "options": opts,
                    "question_format": fmt,
                    "format_source": qex.get("format_source"),
                    "directions": r.get("directions"),
                    "stimulus": r.get("stimulus") or [],
                    "passage": q.get("passage"),
                    "figure": q.get("figure"),
                    # --- answer, with the three signals kept apart ---
                    "answer_key": q.get("answer_key"),
                    "answer_provenance": provenance,
                    "answer_provenance_detail": q.get("key_source"),
                    "answer_check": "none",
                    "derivation_check": "none",
                    "has_solution_note": bool(q.get("solution_note")),
                    # --- difficulty ---
                    "difficulty": q.get("difficulty"),
                    "difficulty_source": qex.get("difficulty_source"),
                    "p_plus": q.get("p_plus"),
                    # --- taxonomy ---
                    "taxonomy": {
                        "raw_label": chapter,
                        "normalized_key": nchap,
                        "taxonomy_version": tax_version,
                        "taxonomy_id": entry.get("id") if entry else None,
                        "skill_key": entry.get("skill_key") if entry else None,
                        "display_label": entry.get("display_label") if entry else None,
                        "graph_backed": graph_backing(entry),
                        # BKT may only join a label that exists as a :Skill node.
                        # A corpus-labelling-only entry is fine for display and
                        # filtering, and must NOT be joined into mastery.
                        "bkt_joinable": bool(entry) and graph_backing(entry) is True,
                        "resolved_by": resolved_by,
                        "taxonomy_status": ("resolved" if entry
                                            else "declined" if decline else "unresolved"),
                        "decline_reason": (decline or {}).get("reason") if decline else None,
                    },
                    # --- flags ---
                    "flags": {
                        "needs_vision": qex.get("needs_vision"),
                        "needs_reextraction": qex.get("needs_reextraction"),
                        "key_suspect": qex.get("key_suspect"),
                        "errata": q.get("errata"),
                        "unanswered_reason": q.get("unanswered_reason"),
                        "record_needs_chart_vision": bool(rex.get("needs_chart_vision")),
                    },
                    "playable": not blk,
                    "playable_blockers": blk,
                }
                rows.append(row)
                stats["questions"] += 1
                stats["playable" if not blk else "not_playable"] += 1
                for b in blk:
                    blockers[b] += 1
                if provenance:
                    prov[provenance] += 1
                if entry:
                    stats["taxonomy_resolved"] += 1
                    stats["taxonomy_via_" + (resolved_by or "unknown")] += 1
                    if graph_backing(entry) is True:
                        stats["taxonomy_bkt_joinable"] += 1
                    if not blk:
                        stats["playable_and_resolved"] += 1
                elif decline:
                    stats["taxonomy_declined"] += 1
                elif chapter:
                    unresolved_chapters[chapter] += 1

    out = Path(args.out)
    with out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "export": "vmsg_questions_v1",
        "generated": "2026-09-03",
        "source": "data/corpus/MASTER_corpus.jsonl",
        "taxonomy_version": tax_version,
        "row_key": "question_id = <set_id>#<number> (unique)",
        "counts": dict(stats),
        "playable_blockers": dict(blockers.most_common()),
        "answer_provenance": dict(prov.most_common()),
        "contracts": {
            "verification": "answer_provenance / answer_check / derivation_check are "
                            "three separate signals. derivation_check is 'none' on every "
                            "row: no pipeline has ever validated a walkthrough. Never "
                            "collapse these into one 'verified' flag.",
            "taxonomy": "skill_key mirrors the live :Skill name and is the BKT join key; "
                        "display_label is owner-changeable with zero migration. "
                        "taxonomy_status 'unresolved' means no id was assigned — the row "
                        "carries raw_label + normalized_key instead of a fabricated id.",
            "playability": "playable is a verdict; playable_blockers lists why not, so a "
                           "consumer can widen or narrow the filter without re-deriving it.",
        },
        "known_limits": {
            "taxonomy_coverage": "question_set records carry NO topic field; the only "
                                 "per-question signal is the book chapter (72% of records). "
                                 "Chapter-derived taxonomy is thin by nature.",
            "top_unresolved_chapters": [
                {"chapter": c, "questions": n}
                for c, n in unresolved_chapters.most_common(15)
            ],
            "difficulty_coverage": "difficulty is set on ~17% of questions (ETS p_plus and "
                                   "Arun Sharma printed bands); NULL elsewhere because no "
                                   "signal exists. Not imputed.",
        },
    }
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(json.dumps({k: manifest[k] for k in ("counts", "answer_provenance")}, indent=1))
    print("playable_blockers:", json.dumps(manifest["playable_blockers"], indent=1))
    print("wrote %d rows -> %s" % (len(rows), out))


if __name__ == "__main__":
    main()
