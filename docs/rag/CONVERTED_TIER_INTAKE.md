# Converted tier — intake, corrections, and promotion posture

**Workstream:** Speed Gym RAG (content contract owner) · **Date:** 2026-09-04
**Input:** 348 `generationMethod: "converted"` templates in `data/factory/converted/`, handed over by the coordinator's templatization run (500-question pilot, 6% of the 8,103 eligible).

## Promotion posture: all 348 remain `quarantined_pending_consensus`

Nothing is promoted. The tier's own grounding audit measured **3 of 18 sampled templates (17%) carrying ungrounded additions**, so stage-7 is required before any of it moves. That is far better than the legacy static bank's 88% failure rate, but it is not clean, and `grounded_in: book_solution` is true at the template level while not being a guarantee at the step level.

## Two corrections applied on intake

1. **Contract violation, all 348.** `version` was the string `"converted_v1"`; the frozen `SolveAlongTemplateSchema` requires a positive integer, so every template would have been rejected at the frontend. Fixed to `version: 1`, with the pipeline label preserved in `provenance.pipeline_version`. Everything else validated independently and cleanly: zero duplicate ids, scaffold types and domains inside the real enums, `expected_time` inside the et-v1 clamp, sequential step numbering, and **1,697/1,697 formulas rendering in KaTeX with zero `$` delimiters**.

2. **152 refusals were invisible in-band.** The reasons existed only in `_skips.json`, so a consumer reading the shards saw a silent absence — the exact unlogged-non-write failure this project has a rule against. They are now emitted as structured records in `declines.jsonl`: `record_type: "decline"`, parsed `question_id`, a `reason_category`, and the original prose. **141 of 152 carry a question_id, and all 141 resolve to real questions in the export** (11 remain unjoinable because the recorded prose does not begin with an id).

   Categories: 64 other-recorded-reason, 28 truncated/garbled source, 21 bare cross-reference, 18 missing chart or figure, 16 solution merely restates the answer, 5 source contradiction or erratum.

   Refusing to convert a question whose source is truncated, chart-less, or self-contradictory is correct behaviour. It only became a defect when it was invisible.

## A grounding detector that does not work — the third of its kind

Since the ungrounded-addition class looked numeric, I built a check: join each template to its source `solution_note` in MASTER and measure the share of step numbers absent from the source. All 348 join. The population is tight — **median unsourced ratio 0.00, mean 0.03**, and only 3 templates (1%) exceed 50%.

**But it misses the audit's own example.** `conv_greog_6quantitativep_set2discretequestionsm_3` — where the converter filled a PDF-extraction hole with a reconstructed triangle-area derivation — scores **0.00**, ranking 54th of 348. The fabrication reused numbers already present in the source, so a numeric test cannot see it.

This is now the third deterministic detector built here that fails on the case that motivated it:

| detector | intended target | outcome |
|---|---|---|
| technique-vocabulary mismatch | mislabelled technique | missed `Bird_sa_110`, its founding example |
| conjunctive clean-filter | find the sound 12% | 16.7% vs 11.7% base — noise |
| numeric grounding | ungrounded additions | missed the audited example, ratio 0.00 |

The pattern is consistent enough to plan around: **the defect classes that matter in this content are semantic, and rule-based proxies for them systematically fail.** Deterministic scanning earns its place on exact invariants — the `false_root_claim` constant-term test, contract validation, KaTeX rendering, arithmetic recomputation, prose/arithmetic direction — and nowhere else. Panel adjudication is the instrument for meaning, and it should be budgeted as the scarce resource it is rather than backstopped by scanners that look like coverage.

The 3 high-ratio templates are worth a look, as candidates and nothing more.
