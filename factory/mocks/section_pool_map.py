#!/usr/bin/env python3
"""Which corpus questions can serve which mock-exam section.

Backend's mock engine is pool-independent: each blueprint section names a POOL
TAG, and `app/mocks/sources.py` binds a tag to a source. Six of the seven tags
are unbound, so those sections answer 503. This module says, per tag, what the
25-book corpus can actually supply — and, just as importantly, what it cannot.

TWO CORRECTIONS TO THE PROPOSED CONTRACT, both measured here:

1. `taxonomy.skill_key` cannot be the pool-membership join. It resolves on
   5,389 of 12,984 pool-eligible questions (41.5%); joining on it would silently
   discard 58% of playable, keyed content — and the discard is not random, since
   verbal and DI/LR resolve far worse than quant. Membership is decided by
   BOOK + CHAPTER here; skill_key rides along as the pool contract's optional
   `skill` field and as the BKT attribution when it happens to be present.

2. One `quant` tag serves CAT QA, GMAT Quant and GRE Quant. Those sections are
   not interchangeable — CAT quant runs harder and longer than GRE quant, and
   GMAT quant has no geometry. Recommend splitting the tag per blueprint before
   binding; a single tag makes a GRE mock indistinguishable from a CAT one.

Content validity is reported, never silently assumed. A source is `native` when
the book is written for that exam, `cross_exam` when it is another exam's
material borrowed for a shared skill, and `absent` when nothing fits. A
cross_exam binding is a decision for the owner, not for this module: serving GRE
Text Completions inside a CAT verbal section would be a content error a learner
would notice, so those combinations are declined outright rather than offered.

  python3 -m factory.mocks.section_pool_map
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

EXPORT = Path("data/exports/vmsg_questions_v1.jsonl")
OUT = Path("data/mocks/pools/SECTION_SOURCE_MAP.json")

# Section sizes come from the authored blueprints (app/mocks/blueprints.py).
SECTIONS = {
    "cat_varc":    {"blueprint": "cat",  "section": "varc",   "questions": 24, "exam": "CAT"},
    "cat_dilr":    {"blueprint": "cat",  "section": "dilr",   "questions": 20, "exam": "CAT"},
    "quant":       {"blueprint": "cat/gmat/gre", "section": "qa/quant/quant",
                    "questions": 27, "exam": "SHARED"},
    "gmat_verbal": {"blueprint": "gmat", "section": "verbal", "questions": 23, "exam": "GMAT"},
    "gmat_di":     {"blueprint": "gmat", "section": "di",     "questions": 20, "exam": "GMAT"},
    "gre_verbal":  {"blueprint": "gre",  "section": "verbal", "questions": 27, "exam": "GRE"},
    "gre_awa":     {"blueprint": "gre",  "section": "awa",    "questions": 1,  "exam": "GRE"},
}

# Chapter allow-lists, written out rather than pattern-matched. The GRE 5 lb book
# mixes verbal and quant across 36 chapters, and its "Practice Section" chapters
# are labelled by difficulty, not subject — a regex on "verbal" would take the
# diagnostic and miss Logic-Based Reading Comprehension.
GRE5LB_VERBAL = {
    "Reading Comprehension", "Text Completions", "Sentence Equivalence",
    "Logic-Based Reading Comprehension", "Verbal Diagnostic Test",
    "Verbal Practice Section 1: Easy", "Verbal Practice Section 2: Medium",
    "Verbal Practice Section 3: Hard",
}
# The CAT-admissible slice of GRE verbal: passage-based reasoning transfers,
# and CAT's VARC is largely RC. Text Completions and Sentence Equivalence are
# GRE-format items with no CAT analogue — a CAT candidate has never seen one.
GRE5LB_VERBAL_CAT_SAFE = {"Reading Comprehension", "Logic-Based Reading Comprehension"}
GRE5LB_DI = {"Data Interpretation"}

BINDINGS = {
    "cat_varc": [
        {"book": "manhattan_gre_5lb", "chapters": sorted(GRE5LB_VERBAL_CAT_SAFE),
         "validity": "cross_exam",
         "note": "GRE passage reasoning standing in for CAT RC. Transfers reasonably; "
                 "CAT's para-jumble and para-summary item types are absent from every "
                 "book in the corpus and cannot be served at all."},
        {"book": "ets_gre_verbal", "chapters": ["Reading Comprehension"],
         "validity": "cross_exam",
         "note": "Official GRE RC. Same caveat as above."},
    ],
    "cat_dilr": [
        {"book": "sinha_lrdi", "chapters": None, "validity": "native",
         "note": "Native CAT LR/DI. The largest genuinely CAT-shaped non-quant source there is."},
        {"book": "arun_sharma_di_lr", "chapters": None, "validity": "native",
         "note": "Native CAT DI, but every one of its questions carries a figure or "
                 "stimulus and its pages have no text layer — this is the book whose "
                 "466 pages sit in extraction's vision queue. Bind only the rows whose "
                 "chart data survived extraction, or a learner gets a question about an "
                 "invisible chart."},
        {"book": "manhattan_lsat_logic_games", "chapters": None, "validity": "cross_exam",
         "note": "LSAT ordering/grouping games are close cousins of CAT LR set puzzles. "
                 "Defensible substitute; label it so results are not read as CAT-native."},
    ],
    "quant": [
        {"book": "arun_sharma_quant", "chapters": None, "validity": "native",
         "exam_scope": "CAT", "note": "Native CAT quant, and by volume the backbone of any CAT mock."},
        {"book": "tyra_quicker_maths", "chapters": None, "validity": "native",
         "exam_scope": "CAT", "note": "Speed-method quant; fits CAT timing pressure."},
        {"book": "manhattan_gre_quant", "chapters": None, "validity": "native",
         "exam_scope": "GRE", "note": "Native GRE quant."},
        {"book": "manhattan_gre_5lb", "chapters": "QUANT_REMAINDER", "validity": "native",
         "exam_scope": "GRE", "note": "The 5 lb book's quant chapters — everything outside its verbal and DI chapters."},
        {"book": "ets_gre_official_guide", "chapters": ["6 Quantitative Practice"],
         "validity": "native", "exam_scope": "GRE", "note": "Official GRE quant."},
        {"book": "bird_basic_engineering_math", "chapters": None, "validity": "cross_exam",
         "exam_scope": "NONE", "note": "Engineering maths. Correct mathematics, wrong exam: "
                 "no admissions test asks these. Recommended DECLINE for mocks; fine for practice."},
        {"book": "hall_knight_higher_algebra", "chapters": None, "validity": "cross_exam",
         "exam_scope": "NONE", "note": "Classical higher algebra, well above CAT/GRE/GMAT level. "
                 "Recommended DECLINE for mocks."},
    ],
    "gmat_verbal": [
        {"book": "manhattan_gmat_verbal", "chapters": None, "validity": "native",
         "note": "The only GMAT-native verbal source in the corpus."},
    ],
    "gmat_di": [],
    "gre_verbal": [
        {"book": "manhattan_gre_5lb", "chapters": sorted(GRE5LB_VERBAL), "validity": "native"},
        {"book": "ets_gre_verbal", "chapters": None, "validity": "native",
         "note": "Official ETS verbal practice — the highest-fidelity verbal source available."},
        {"book": "ets_gre_official_guide", "chapters": ["4 Verbal Reasoning Practice"],
         "validity": "native"},
    ],
    "gre_awa": [],
}

ABSENT = {
    "gmat_di": "GMAT Data Insights has no source in the corpus. Its item types — data "
               "sufficiency, multi-source reasoning, two-part analysis, table analysis — "
               "are GMAT-specific and appear in no book here. CAT DI is a different "
               "instrument and must not be substituted: data sufficiency asks whether a "
               "question CAN be answered, which no CAT DI item does. This section cannot "
               "be served without new content.",
    "gre_awa": "Zero essay prompts exist anywhere in the corpus or the export — verified by "
               "scanning every question of all 4,805 records for the AWA task wordings. The "
               "section is not auto-scored, so it needs only a prompt, but it needs one. "
               "Two public ETS pools exist and would have to be licensed or authored.",
}


def eligible(rows, book, chapters, quant_remainder=None):
    out = []
    for r in rows:
        if r.get("book_canonical_id") != book:
            continue
        if not (r.get("playable") and r.get("answer_key") and (r.get("text") or "").strip()):
            continue
        ch = r.get("chapter")
        if chapters == "QUANT_REMAINDER":
            if ch in quant_remainder:
                continue
        elif chapters is not None and ch not in chapters:
            continue
        out.append(r)
    return out


def main() -> int:
    rows = [json.loads(l) for l in EXPORT.read_text().splitlines() if l.strip()]
    pool_eligible = [r for r in rows
                     if r.get("playable") and r.get("answer_key") and (r.get("text") or "").strip()]
    resolved = [r for r in pool_eligible if (r.get("taxonomy") or {}).get("skill_key")]

    report = {
        "generated_by": "factory/mocks/section_pool_map.py",
        "export": str(EXPORT),
        "join_key_finding": {
            "proposed": "taxonomy.skill_key",
            "pool_eligible": len(pool_eligible),
            "resolved_to_skill_key": len(resolved),
            "resolution_rate": round(len(resolved) / len(pool_eligible), 4),
            "verdict": "skill_key is an ENRICHMENT, not the membership join — it would drop "
                       "58% of pool-eligible questions. Membership: book + chapter. skill_key "
                       "fills the contract's optional `skill` field where present.",
        },
        "sections": {},
        "recommendations": [],
    }

    for tag, meta in SECTIONS.items():
        binds = BINDINGS.get(tag, [])
        srcs, total, with_skill = [], 0, 0
        for b in binds:
            rs = eligible(rows, b["book"], b["chapters"], GRE5LB_VERBAL | GRE5LB_DI)
            n_skill = sum(1 for r in rs if (r.get("taxonomy") or {}).get("skill_key"))
            fmts = Counter(r.get("question_format") for r in rs)
            stim = sum(1 for r in rs if r.get("figure") or r.get("stimulus"))
            srcs.append({**{k: v for k, v in b.items() if k != "chapters"},
                         "chapters": b["chapters"] if b["chapters"] != "QUANT_REMAINDER"
                                     else "all chapters except the verbal and DI lists",
                         "eligible": len(rs), "with_skill_key": n_skill,
                         "needs_figure_or_stimulus": stim,
                         "formats": dict(fmts.most_common(5))})
            if b.get("exam_scope") != "NONE":
                total += len(rs)
                with_skill += n_skill
        q = meta["questions"]
        rec = [s for s in srcs if s.get("exam_scope") != "NONE"]
        native = sum(s["eligible"] for s in rec if s["validity"] == "native")
        cross = sum(s["eligible"] for s in rec if s["validity"] == "cross_exam")
        # Supply is graded on NATIVE material. A section served only by another
        # exam's questions is not well supplied however many there are — the
        # count is fine and the instrument is wrong, which is the failure a
        # headline number hides.
        def grade(n):
            return ("absent" if n == 0 else "thin" if n < q * 3
                    else "adequate" if n < q * 10 else "ample")
        by_scope = defaultdict(int)
        for s in rec:
            by_scope[s.get("exam_scope") or meta["exam"]] += s["eligible"]
        report["sections"][tag] = {
            **meta,
            "sources": srcs,
            "eligible_total_recommended": total,
            "native_eligible": native,
            "cross_exam_eligible": cross,
            "with_skill_key": with_skill,
            "distinct_mocks_before_repeats": total // q if q else 0,
            "supply": grade(native),
            "supply_if_cross_exam_allowed": grade(native + cross),
            "eligible_by_exam_scope": dict(by_scope),
            "absent_reason": ABSENT.get(tag),
        }

    report["recommendations"] = [
        "Split the shared `quant` tag into cat_quant / gmat_quant / gre_quant before binding. "
        "One tag across three exams makes a GRE mock indistinguishable from a CAT one, and the "
        "corpus has enough native material to keep them apart for CAT and GRE.",
        "GMAT quant has NO native source: with `quant` split, gmat_quant is absent, not thin. "
        "GRE quant is the closest substitute and should be labelled cross_exam if used.",
        "gmat_di and gre_awa cannot be served at all. Answer 503 honestly rather than "
        "substituting CAT DI for Data Insights — they test different things.",
        "gmat_verbal has 36 eligible questions against a 23-question section: barely one mock, "
        "and a second attempt repeats most of it. Treat as thin, not ready.",
        "Bind arun_sharma_di_lr only after extraction's vision pass — every question there "
        "depends on a figure, so an un-rendered row is an unanswerable question.",
        "Pool membership joins on book + chapter; carry taxonomy.skill_key into the contract's "
        "`skill` field where it resolves, and leave it null where it does not, rather than "
        "dropping the question.",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False))

    print(f"join key: skill_key resolves {len(resolved)}/{len(pool_eligible)} "
          f"({len(resolved)/len(pool_eligible):.1%}) of pool-eligible questions\n")
    for tag, s in report["sections"].items():
        cx = (f" (cross-exam would make it {s['supply_if_cross_exam_allowed'].upper()})"
              if s['supply'] != s['supply_if_cross_exam_allowed'] else "")
        print(f"{tag:12s} need {s['questions']:2d}/mock | native {s['native_eligible']:5d} "
              f"cross {s['cross_exam_eligible']:5d} | {s['supply'].upper()}{cx}")
        if s['eligible_by_exam_scope'] and len(s['eligible_by_exam_scope']) > 1:
            print(f"     by exam: {s['eligible_by_exam_scope']}")
        for src in s["sources"]:
            scope = src.get("exam_scope", "")
            print(f"     {src['eligible']:5d}  {src['book']:28s} {src['validity']:10s} {scope}")
        if s["absent_reason"]:
            print(f"     -- {s['absent_reason'][:100]}...")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
