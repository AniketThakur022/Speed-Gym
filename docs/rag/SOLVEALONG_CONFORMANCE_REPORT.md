# SolveAlong template conformance report — recovered bank vs frontend zod schema

**Workstream:** Speed Gym RAG · **Date:** 2026-09-02
**Input:** `incoming/topic_browser_full_package/content_data/templates/solve_along/*.jsonl` (9 files, 915 records, **861 unique template_ids**)
**Target contract:** `SolveAlongTemplateSchema` in `recovered/exam-arena-src/src_lib_types_template.ts_cf55` (the only surviving frontend; schema frozen by the APK)

## Verdict

**0 / 915 records pass the frontend zod schema as-is.** This is a format-generation gap, not a content-quality gap: the recovered bank is the *factory-side* template shape (rich enrichment metadata, `formula`/`reasoning` steps), while the frontend expects the *delivery* shape. A deterministic, no-AI adapter closes everything except **one universally missing field (`expected_time`)** and **96 missing visual scaffolds**.

The 861 unique IDs decompose exactly as the June architecture doc says: **807 original + 54 new** (Dhvajanka 20, Yavadunam 28, Magic Squares 6). The 54 completion records are duplicated — present both in their own `vedic_completion_*.jsonl` files and merged into `Tirthaji_Vedic_Math_solvealong.jsonl`. Dedup by `template_id` before adapting.

## Field mapping (mechanical, lossless where a counterpart exists)

| Frontend (zod) | Recovered bank | Notes |
|---|---|---|
| `id` | `template_id` | present in all 915 |
| `domain` | — (derive) | from `concept.topic` + source book → `vedic-math` for all 9 current books; CAT/GMAT/GRE banks will map via a book→domain table |
| `concept.technique_name` | `concept.technique_name` | **7 records missing** (Schaums) — backfill from `sub_topic` |
| `concept.category` | `concept.topic` | always present (VedicMath 368, Algebra 166, Arithmetic 98, …) |
| `concept.sub_category` | `concept.sub_topic` | optional in target |
| `difficulty` (int 1–5) | `difficulty` | **2 records = 6** (`Magic_Squares_sa_5x5_panchadasi`, both copies) — clamp to 5 or re-tier |
| `expected_time` (int >0, required) | **MISSING in all 915** | must synthesize: `f(difficulty, cognitive_load_score, step_count)`; calibrate against age-default time targets in the decision-engine spec |
| `visual_scaffold.type` | `visual_scaffold.type` | present in 819/915; all present values are within the frontend's 11-type enum (arrow_matrix 405, place_value_chart 183, coordinate_grid 112, …). **96 missing**: 48 Tirthaji + 20 dhvajanka + 28 yavadunam (the completion files never got visual enrichment) → run the visual-enrichment pass or default to `textual_scaffold` |
| `examples[].problem_statement` | same | 3 records empty |
| `examples[].solution[].step_num` | same | ✓ |
| `examples[].solution[].operation` | same | ✓ |
| `examples[].solution[].result` | `solution[].formula` | uniform across all 10,832 steps |
| `examples[].solution[].description` | `solution[].reasoning` | uniform across all 10,832 steps |
| `examples[].answer` | `final_answer`/`answer` | all 2,105 examples carry an answer |
| `key_reminders`, `common_mistakes` | same names | present in 819/875 records respectively; optional in target |
| `version` | — | default 1 |
| `sourceDocumentId` | `source.book` + `source.page` (`source_reference`) | serialize e.g. `"Tirthaji_Vedic_Math#p43"` |
| `generationMethod` | — | `"template"` for the whole recovered bank |

Factory-side fields with no frontend counterpart (`prerequisite_chain`, `cognitive_load_score`, `lock_threshold`, `ui_mode_mapping`, `tags`, all `_enrichment/_audit/_validation` metadata, `phase_*` flags) stay in the Ledger; they are dropped at delivery time, not deleted. `prerequisite_chain` in particular feeds the closure build (see `STRATEGY_A_CLOSURE_DESIGN.md`).

## Defect queue (small, enumerable)

| Defect | Count | Fix |
|---|---|---|
| `expected_time` missing | 915 | synthesize (blocking for delivery; the only universal gap) |
| `visual_scaffold` missing | 96 | visual-enrichment pass or `textual_scaffold` default |
| empty `examples[].solution` | 11 | route through 7-stage auditor as QUARANTINED; repair or drop |
| `concept.technique_name` missing | 7 | backfill from `sub_topic` |
| empty `problem_statement` | 3 | quarantine |
| `difficulty` out of range (6) | 2 (1 unique) | clamp/re-tier |
| duplicate `template_id` across files | 54 | dedup before ingest |

## Consequences for the factory

1. **The T1 lane needs a `to_solvealong_template()` adapter** (pure function, no AI) as its final write-out stage; every generated/replenished item must round-trip through it and re-validate against the zod schema (port the schema to the factory as a shared contract test — pin these fixtures).
2. `expected_time` synthesis needs a settled formula — propose: `expected_time = base(difficulty) × (1 + 0.15·(cognitive_load−2)) `, calibrated per render mode; to be confirmed with backend chat (they own the decision-engine timing tables).
3. The 819 already-enriched records validate cleanly post-adapter → an immediately deliverable TRUSTED-candidate bank of ~800 templates once `expected_time` lands.
