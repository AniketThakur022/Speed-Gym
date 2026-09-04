# converted/ — extracted questions as SolveAlongTemplates

348 templates converted from `data/exports/vmsg_questions_v1.jsonl`, each grounded in its
book's own printed solution (`generationMethod: "converted"`). Built by
`tools/qa/build_template_packets.py` + a coordinator-session conversion pass, 2026-09-04.

**Every template enters the ladder as `quarantined_pending_consensus`.** These are candidate
content, not verified content: the steps are a restructuring of printed prose, and no
stage-7 panel has judged them.

## Contract

Validated against the frontend's real schema (`recovered/exam-arena-src/src_lib_types_template.ts`):
scaffold types and domains checked against the actual enums, `expected_time` via et-v1 in the
15–300 clamp, difficulty 1–5, sequential step numbering, no `$` delimiters in math fields,
every answer preserved verbatim from the verified key. 348/348 clean, 0 duplicate ids.

## What was refused, and why that matters

152 of 500 (30%) were **not** converted. Reasons are in `_skips.json` — truncated source
formulas, bare cross-references ("Appendix F, Section 3"), chart questions whose chart is
absent from the corpus, and one book erratum where the printed derivation and the printed
answer disagree. Fabricating those walkthroughs is the defect class that made 88% of the
legacy static bank unusable (`data/factory/verdicts/static_sample_report.json`).

## Known quality ceiling

`_audit.json` holds an adversarial grounding audit of 18 templates across 5 random shards:
**3 carried small ungrounded additions** (a reconstructed triangle-area formula where the
source had a PDF hole; an inferential clause the book stops short of), 1 had a
description/operation misalignment, 1 altered an answer. Mathematically defensible, but not
present in the source — so treat ~17% as needing a stage-7 pass before promotion, and do not
read "grounded_in: book_solution" as a guarantee at the step level.

**Open process gap:** skips are recorded here in `_skips.json` but not as in-band rows in the
shards, so a consumer reading only the JSONL sees a silent absence. Emitting decline records
into the data itself would satisfy the project's unlogged-non-write rule.
