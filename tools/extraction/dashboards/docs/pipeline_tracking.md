# CAT Wave 2 Pipeline Tracking

> **Last Updated:** 2026-07-08
> **Status:** Enrichment complete, validation in progress, Neo4j-ready

---

## Overview

The CAT Content Pipeline contains **738 records** extracted from 3 source books and enriched across **7 layers (L1–L7)**. Wave 2 focuses on algorithmic/per-cluster enrichment to achieve production-ready content for the adaptive engine.

| Metric | Value |
|--------|-------|
| Total Records | 738 |
| Books | 3 |
| Enrichment Layers | L1–L7 |
| Cluster Explainers | 90 |
| Q-Matrix Entries | 738 |
| Neo4j Cypher Scripts | 2 |

---

## Data Sources

| Book | Records | Source File |
|------|---------|-------------|
| CAT_DI_LR_Nishit_K_Sinha | 295 | `CAT_DI_LR_Nishit_K_Sinha/records.jsonl` |
| CAT_VARC_Part1 | 300 | `CAT_VARC_Part1/records.jsonl` |
| CAT_VARC_Part2 | 143 | `CAT_VARC_Part2/records.jsonl` |
| **Total** | **738** | |

---

## Enrichment Status (L1–L7)

### L1: Content Extraction — ✅ 100%
All 738 records have `content`, `summary`, and `data_points` fields. Options and correct answers extracted.

### L2: Logic Steps — ✅ 99.9% (737/738)
- **Issue:** 1 DI record (idx 235, Caselet DI "Chef Sudhir toast order") has empty `logic_steps: []`
- **Action:** Pending L2 regeneration for this single record

### L3: Cognitive Profile — ✅ 100%
- **DI:** Stored in `data_points._di_cognitive_profile` (chart_type, base_cognitive_load, working_memory_chunks, trap_cognitive_taxonomy, session_alignment_tag)
- **VARC:** Stored in top-level `cognitive_profile` (reading_load, inference_demand, vocabulary_level, cognitive_taxonomy, working_memory_chunks, time_estimate_seconds)

### L4: Hints — ✅ 100%
All records have hints in `data_points.hints`.

### L5: Trap Tags — ✅ 100%
All records have `data_points.trap_tags`. DI uses 23 custom LogicTrap types; VARC uses standard trap taxonomy.

### L6: Cluster Explainers — ✅ Linked (text embedding in progress)
- 90 clusters generated (hybrid format: CONCEPT CORE 150–200w + TRAP ADDENDUM 100–150w)
- Avg word count: 312 | Total: ~28K words
- All 738 records have `explainer_cluster_id` linking to a cluster
- **Embedding script:** `assembly_line/embed_l6_explainers.py` (ready, run after validation)
- **Storage:** `explainers/explainers.jsonl`, `explainers/cluster_registry.json`, `explainers/cluster_record_map.json`

### L7: DINA Q-Matrix — ✅ 738 entries (embedding in progress)
- 738 Q-matrix entries in `qmatrix/qmatrix_entries.jsonl`
- `record_idx` populated for all 738 entries ✅
- **Embedding script:** `assembly_line/link_qmatrix_to_records.py` (ready, run after validation)
- VARC: 5 skills (MAIN_IDEA, INFERENCE, CRITICAL_REASONING, GRAMMAR_USAGE, VOCABULARY)
- DI: 10 skills (Data Interpretation + Logical Reasoning)
- Parameters: slip_probability=0.2, guess_probability=0.25, psychometric_model=DINA

---

## Per-Book Coverage

| Book | Records | L1 | L2 | L3 | L4 | L5 | L6 | L7 |
|------|---------|----|----|----|----|----|----|-----|
| CAT_DI_LR_Nishit_K_Sinha | 295 | 100% | 99.7% | 100% | 100% | 100% | 100% | 100% |
| CAT_VARC_Part1 | 300 | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| CAT_VARC_Part2 | 143 | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

---

## Subtopic Coverage

| Subject | Subtopic | Records | L2% | L3% | L5% | L6% | L7% |
|---------|----------|---------|-----|-----|-----|-----|-----|
| DI | Data Interpretation | 174 | 99% | 100% | 100% | 100% | 100% |
| DI | Logical Reasoning | 121 | 100% | 100% | 100% | 100% | 100% |
| VARC | Reading Comprehension | 420 | 100% | 100% | 100% | 100% | 100% |
| VARC | Verbal Ability | 23 | 100% | 100% | 100% | 100% | 100% |

---

## Validation Status

> Validation re-run complete (`wave2_validation_final.py`)
> v2 fixes: max_tokens=4096, reasoning field fallback, TITA-aware prompts

| Book | Verified | Partial | Rejected | Rate |
|------|----------|---------|----------|------|
| CAT_DI_LR_Nishit_K_Sinha | 138 | 122 | 35 | 88.1% |
| CAT_VARC_Part1 | 293 | 1 | 6 | 98.0% |
| CAT_VARC_Part2 | 143 | 0 | 0 | 100% |
| **Total** | **574** | **123** | **41** | **94.4%** |

### Validation Methods
- `JURY_VERIFIED`: Both models agree with stored answer
- `JURY_PARTIAL`: One model agrees with stored answer
- `JURY_REJECTED`: Neither model agrees
- `ANSWER_KEY_SUSPECT`: Both models agree on a different answer (flagged for human review)
- `VERIFIED`: Legacy validation (VARC P1/P2)

---

## Cluster Explainers

| Metric | Value |
|--------|-------|
| Total Clusters | 90 |
| Format | CONCEPT CORE (150–200w) + TRAP ADDENDUM (100–150w) |
| Average Word Count | 312 |
| Total Words | ~28,000 |
| Storage | `explainers/explainers.jsonl` (90 entries) |
| Registry | `explainers/cluster_registry.json` |
| Record Map | `explainers/cluster_record_map.json` (738 mappings) |

### Cluster Distribution by Book
| Book | Clusters |
|------|----------|
| CAT_DI_LR_Nishit_K_Sinha | 23 |
| CAT_VARC_Part1 | 41 |
| CAT_VARC_Part2 | 26 |

---

## Q-Matrix (DINA Model)

| Subject | Entries | K Skills | Target | Status |
|---------|---------|----------|--------|--------|
| DI | 295 | 10 | 200 | ✅ Exceeds |
| VARC | 437 | 5 | 200 | ✅ Exceeds |
| **Total** | **738** | — | 400 | ✅ Exceeds |

---

## Known Issues

| # | Issue | Records | Status |
|---|-------|---------|--------|
| 1 | DI record idx 235 missing L2 logic_steps | 1 | Pending L2 regen |
| 2 | DI records NO_FIGURE_LINKED (question position not found) | 43 | Needs attention |
| 3 | DI records with linked table/figure but no extractable numbers | 30 | Low priority |
| 4 | Answer-key-suspect records (both models disagree with stored key) | ~20 | Flag for human review |
| 5 | VARC P1 rejected (RC passage chunk_idx 35/36) | 6 | Targeted re-run |
| 6 | API keys 4–6 exhausted | — | Keys 1–3 active |

---

## DI Data Type Matrix

> Each DI record is classified with `_di_data_type` to avoid confusion about missing data.
> Text-only records (logic puzzles, syllogisms) legitimately have no figures/tables — they are NOT missing data.

| Data Type | Records | % | Description |
|-----------|---------|-----|-------------|
| NUMERIC | 167 | 56.6% | Has structured numeric values from figures/tables |
| TEXT_ONLY | 26 | 8.8% | Expected text-only (syllogisms, calendar logic, etc.) |
| TEXT_ONLY_LOGIC | 29 | 9.8% | Logic puzzles misclassified as Table Interpretation |
| TABLE_NO_NUMERIC | 17 | 5.8% | Linked to table, no extractable numbers |
| FIGURE_NO_NUMERIC | 13 | 4.4% | Linked to figure, no extractable numbers |
| NO_FIGURE_LINKED | 43 | 14.6% | In bundle with figures, question position not found |

**Summary:** 222/295 (75.3%) have expected data state. 73 records (24.7%) need attention.

---

## Figure/Table Linking Status

| Field | Coverage | Note |
|-------|----------|------|
| `diagram_ids` | 53/295 (17%) | Figure references |
| `table_ids` | 239/295 (81%) | Table references |
| `_di_numeric_values` | 167/295 (56%) | Structured numeric data |
| `_di_figure_data` | 292/295 (98%) | Full figure/table structure |
| `_di_relinked` | 292/295 (98%) | Successfully linked |

> Root cause fixed: original `di_figure_relinker.py` was hardcoded to CAT_DI_LR_Arun_Sharma. 
> New `di_figure_relinker_nishit.py` targets CAT_DI_LR_Nishit_K_Sinha and relinked 292/295 records.

---

## API Key Status

| Position | Status |
|----------|--------|
| 1 | ✅ Active |
| 2 | ✅ Active |
| 3 | ✅ Active |
| 4 | ❌ Exhausted (commented out) |
| 5 | ❌ Exhausted (commented out) |
| 6 | ❌ Exhausted (commented out) |

---

## Neo4j Readiness

| Script | Size | Status |
|--------|------|--------|
| `neo4j_cat_classification.cypher` | 6,043 chars | ✅ Ready |
| `qmatrix/qmatrix_ingest.cypher` | 29,063 chars | ✅ Ready |

---

## Scripts Inventory

| Script | Purpose | Status |
|--------|---------|--------|
| `wave2_validation_final.py` | TITA-aware validation re-run | Running (PID 710) |
| `wave2_validation_di_hard.py` | Targeted fix for 77 EMPTY records | Ready (run after v2) |
| `embed_l6_explainers.py` | Embed explainer text into records | Ready (run after validation) |
| `link_qmatrix_to_records.py` | Populate record_idx + embed L7 | record_idx DONE, records part pending |
| `flag_syllogism_suspects.py` | Flag answer-key-suspect records | Ready (re-run after validation) |