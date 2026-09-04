#!/usr/bin/env python3
"""Prepare templatization packets: extracted questions -> SolveAlongTemplate inputs.

The frontend consumes SolveAlongTemplate (recovered/exam-arena-src/src_lib_types_template.ts):
concept{technique_name,category,sub_category}, difficulty 1-5, expected_time,
visual_scaffold{type,config}, examples[{problem_statement,solution[{step_num,operation,
result,description}],answer}], key_reminders, common_mistakes, version,
sourceDocumentId, generationMethod.

A question in the corpus carries text/options/answer_key plus (crucially) the BOOK'S OWN
solution_note. Templatizing means restructuring that printed solution into ordered steps —
grounded in what the book actually says, never invented. Questions without a solution_note
are excluded: fabricating a derivation is precisely the defect class the stage-7 panels
found in the recovered bank.

Emits packets of N questions each, carrying everything a converter needs so it never has
to guess: the stem, options, verified key, the book's solution prose, stimulus/directions,
difficulty, taxonomy skill_key, and provenance.

Usage: python3 tools/qa/build_template_packets.py --limit 500 --per-packet 5 --out DIR
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/harshahirrao/Speed gym")
EXPORT = ROOT / "data/exports/vmsg_questions_v1.jsonl"
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"


def truthy(v):
    return str(v).lower() in ("true", "1")


def load_corpus_index():
    """(set_id, number) -> question dict, plus set_id -> record-level context."""
    qidx, sidx = {}, {}
    with MASTER.open() as fh:
        for line in fh:
            rec = json.loads(line)
            sid = rec.get("set_id")
            sidx[sid] = {
                "book_title": rec.get("book_title"),
                "chapter": rec.get("chapter"),
                "directions": rec.get("directions"),
                "stimulus": rec.get("stimulus") or [],
                "pdf_pages": rec.get("pdf_pages") or [],
            }
            for q in rec.get("questions") or []:
                qidx[(sid, str(q.get("number")))] = q
    return qidx, sidx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--per-packet", type=int, default=5)
    ap.add_argument("--out", default="/private/tmp/claude-501/-Users-harshahirrao-Speed-gym/"
                                     "9e5da183-7e68-48e6-be30-660db64bf5ce/scratchpad/templatize")
    ap.add_argument("--seed", type=int, default=20260904)
    args = ap.parse_args()

    qidx, sidx = load_corpus_index()
    rows = [json.loads(l) for l in EXPORT.read_text().splitlines() if l.strip()]

    # Eligible: playable, has a book solution to ground the derivation in, and the
    # solution text is actually present in the corpus.
    eligible = []
    for r in rows:
        if not truthy(r.get("playable")):
            continue
        if not truthy(r.get("has_solution_note")):
            continue
        q = qidx.get((r["set_id"], str(r["number"])))
        if not q or not (q.get("solution_note") or "").strip():
            continue
        eligible.append((r, q))

    # Stratify by (book, question_format) so the pilot spans the corpus rather than
    # one book's exercises.
    strata = defaultdict(list)
    for r, q in eligible:
        strata[(r.get("book"), r.get("question_format"))].append((r, q))
    rng = random.Random(args.seed)
    keys = sorted(strata, key=lambda k: (-len(strata[k]), str(k)))
    picked, i = [], 0
    while len(picked) < min(args.limit, len(eligible)) and keys:
        k = keys[i % len(keys)]
        if strata[k]:
            picked.append(strata[k].pop(rng.randrange(len(strata[k]))))
        else:
            keys.remove(k)
            if not keys:
                break
            continue
        i += 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("packet_*.json"):
        old.unlink()

    items = []
    for r, q in picked:
        ctx = sidx.get(r["set_id"], {})
        tax = r.get("taxonomy") or {}
        items.append({
            "question_id": r["question_id"],
            "set_id": r["set_id"],
            "number": r["number"],
            "book": r.get("book"),
            "book_title": ctx.get("book_title"),
            "book_canonical_id": r.get("book_canonical_id"),
            "chapter": r.get("chapter"),
            "pdf_pages": ctx.get("pdf_pages"),
            "stem": q.get("text") or r.get("text"),
            "options": q.get("options") or r.get("options") or [],
            "question_format": r.get("question_format"),
            "answer_key": r.get("answer_key"),
            "answer_provenance": r.get("answer_provenance"),
            "book_solution": q.get("solution_note"),
            "directions": ctx.get("directions"),
            "stimulus": ctx.get("stimulus"),
            "difficulty": r.get("difficulty"),
            "difficulty_source": r.get("difficulty_source"),
            "skill_key": tax.get("skill_key"),
            "skill_display": tax.get("display_label"),
            "bkt_joinable": tax.get("bkt_joinable"),
        })

    n = args.per_packet
    packets = [items[i:i + n] for i in range(0, len(items), n)]
    for pi, p in enumerate(packets):
        (out / f"packet_{pi:03d}.json").write_text(json.dumps({"packet": pi, "items": p}, ensure_ascii=False))

    print(json.dumps({
        "eligible_total": len(eligible),
        "selected": len(items),
        "packets": len(packets),
        "per_packet": n,
        "out": str(out),
        "strata_spanned": len({(i["book"], i["question_format"]) for i in items}),
    }, indent=1))


if __name__ == "__main__":
    main()
