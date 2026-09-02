# Template Renderer Schema — CAT Records

> **Last Updated:** 2026-07-08
> **Purpose:** Document the record schema for frontend/backend template rendering

---

## Record Structure

Each record in `records.jsonl` is a JSON object with top-level fields and a `data_points` sub-object.

```json
{
  "summary": "...",
  "content": "...",
  "record_type": "CAT_DI_RECORD",
  "exam_type": "CAT",
  "topic": "DI",
  "sub_topic": "Table Interpretation",
  "source_reference": "...",
  "source_book": "CAT_DI_LR_Nishit_K_Sinha",
  "chunk_idx": 5,
  "model": "glm-5.1",
  "schema_version": "1.0",
  "status": "active",
  "page_type": "question",
  "exam_section": "DI",
  "data_points": { ... },
  "pedagogical_notes": "...",
  "tags": [...],
  "logic_steps": [...],
  "trap_tags": [...],
  "explainer_cluster_id": "55bb77ea30a1",
  "correct_answer": "b",
  "_validation_status": "JURY_VERIFIED",
  ...
}
```

---

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `summary` | string | ✅ | Brief summary of the question |
| `content` | string | ✅ | Full question text |
| `record_type` | string | ✅ | `CAT_DI_RECORD` or `CAT_VARC_RECORD` |
| `exam_type` | string | ✅ | Always `CAT` |
| `topic` | string | ✅ | `DI`, `VARC`, `LR` |
| `sub_topic` | string | ✅ | e.g., `Table Interpretation`, `Syllogisms`, `Reading Comprehension` |
| `source_reference` | string | ✅ | Page/section reference in source book |
| `source_book` | string | ✅ | Source book name |
| `chunk_idx` | int | ✅ | Chunk index within book |
| `model` | string | ✅ | Model used for extraction |
| `schema_version` | string | ✅ | Schema version |
| `status` | string | ✅ | `active` |
| `page_type` | string | ✅ | `question`, `passage`, `table` |
| `exam_section` | string | ✅ | `DI`, `VARC`, `LR` |
| `data_points` | object | ✅ | Core question data (see below) |
| `pedagogical_notes` | string | ⚪ | Teaching notes |
| `tags` | array[string] | ⚪ | Categorization tags |
| `raw_formulas` | array | ⚪ | Extracted formulas |
| `entities` | array | ⚪ | Named entities |
| `diagram_ids` | array | ⚪ | Diagram references |
| `table_ids` | array | ⚪ | Table references |
| `logic_steps` | array[string] | ✅ | L2 step-by-step solution |
| `prerequisite_topics` | array[string] | ⚪ | Prerequisites |
| `cross_references` | array | ⚪ | Related records |
| `worked_examples` | array | ⚪ | Example solutions |
| `_bundle_source` | string | ⚪ | Extraction bundle origin |
| `_routing_label` | string | ⚪ | Routing classification |
| `technique_id` | string | ⚪ | Technique identifier |
| `technique_name` | string | ⚪ | Technique display name |
| `_classification_method` | string | ⚪ | How record was classified |
| `trap_tags` | array[string] | ✅ | L5 trap taxonomy tags |
| `correct_answer` | string | ✅ | Stored correct answer |
| `answer_source` | string | ⚪ | Answer provenance |
| `cognitive_profile` | object | ⚪ (VARC) | L3 cognitive profile (VARC) |
| `explainer_cluster_id` | string | ✅ | L6 cluster ID link |
| `foundational_concept` | string | ⚪ | Foundational concept |

---

## `data_points` Sub-Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `problem_format` | string | ✅ | `PS`, `MCQ`, `LR`, `TITA` |
| `options` | array[string] | ⚪ | Answer options (empty for TITA) |
| `correct_answer` | string | ✅ | Correct answer letter or text |
| `difficulty` | int | ✅ | 1–5 difficulty rating |
| `statement_1` | string | ⚪ (DS) | Data Sufficiency statement 1 |
| `statement_2` | string | ⚪ (DS) | Data Sufficiency statement 2 |
| `quantity_a` | string | ⚪ | Comparison quantity A |
| `quantity_b` | string | ⚪ | Comparison quantity B |
| `blanks` | array | ⚪ | Fill-in-the-blank fields |
| `trap_tags` | array[string] | ✅ | L5 trap tags |
| `pedagogical_notes` | string | ⚪ | Teaching notes |
| `_extraction_jesters` | array | ⚪ | Extraction jester metadata |
| `_extraction_timestamp` | string | ⚪ | Extraction time |
| `matched_question_number` | int | ⚪ | Source question number |
| `sub_topic` | string | ⚪ | Sub-topic override |
| `technique` | string | ⚪ | Technique name |
| `tags` | array[string] | ⚪ | Tags |
| `prerequisite_topics` | array | ⚪ | Prerequisites |
| `cross_references` | array | ⚪ | Cross refs |
| `logic_steps` | array[string] | ✅ | L2 logic steps |
| `_psychometric_model` | string | ⚪ | Psychometric model name |
| `_di_cognitive_profile` | object | ⚪ (DI) | L3 DI cognitive profile |
| `_dina_parameters` | object | ⚪ (VARC) | L7 DINA parameters |
| `foundational_concept` | string | ⚪ | Foundational concept |
| `hints` | array[string] | ✅ | L4 hints |
| `explainer` | string | ⏳ (L6) | L6 explainer text (after embedding) |
| `explainer_cluster_id` | string | ⏳ (L6) | L6 cluster ID |
| `q_matrix_entry` | object | ⏳ (L7) | L7 Q-matrix data (after embedding) |

---

## L3 Cognitive Profile

### VARC (`cognitive_profile` top-level)
| Field | Type | Description |
|-------|------|-------------|
| `reading_load` | int | Reading difficulty (1–10) |
| `inference_demand` | int | Inference requirement (1–10) |
| `vocabulary_level` | int | Vocabulary level (1–10) |
| `cognitive_taxonomy` | string | Bloom's level: `ANALYSIS`, `EVALUATION`, etc. |
| `working_memory_chunks` | int | Working memory chunks |
| `time_estimate_seconds` | int | Estimated solve time |

### DI (`data_points._di_cognitive_profile`)
| Field | Type | Description |
|-------|------|-------------|
| `chart_type` | string | Chart type: `TABLE`, `BAR`, `PIE`, `UNKNOWN` |
| `base_cognitive_load` | float | Base load (0.0–1.0) |
| `working_memory_chunks` | int | Working memory chunks |
| `trap_cognitive_taxonomy` | array[string] | e.g., `LOW_LOAD` |
| `session_alignment_tag` | string | e.g., `FRIENDLY_TIMER` |

---

## L7 Q-Matrix Entry (after embedding)

| Field | Type | Description |
|-------|------|-------------|
| `q_matrix` | array[int] | Binary skill vector (0/1) |
| `skill_names` | array[string] | Skill names |
| `k_skills` | int | Number of skills |
| `slip_probability` | float | Slip probability (0.2) |
| `guess_probability` | float | Guess probability (0.25) |
| `psychometric_model` | string | `DINA` |
| `subject` | string | `DI` or `VARC` |
| `subtopic` | string | Sub-topic |
| `technique` | string | Technique |

---

## Validation Fields

| Field | Type | Description |
|-------|------|-------------|
| `_validation_status` | string | `JURY_VERIFIED`, `JURY_PARTIAL`, `JURY_REJECTED`, `ANSWER_KEY_SUSPECT`, `VERIFIED` |
| `_validation_method` | string | How validated: `textbook_answer_accepted`, `di_sum_computed`, etc. |
| `_validation_confidence` | float | 0.0–1.0 confidence |
| `_model_votes` | array[object] | Per-model votes: `{model, vote, confidence}` |
| `_jury_confidence` | float | Jury confidence (0.0–1.0) |
| `_validated_at` | string (ISO) | Validation timestamp |
| `_validation_rerun` | bool | Re-run v1 flag |
| `_validation_rerun_v2` | bool | Re-run v2 flag (current) |
| `_validation_rerun_v3` | bool | Hard-fix v3 flag |
| `_hard_fix_attempted` | bool | Hard-fix attempted |
| `_answer_key_suspect` | bool | Answer key suspect flag |
| `_model_consensus_answer` | string | Models' consensus answer |
| `_human_review_note` | string | Human review note |

---

## Enrichment Tracking Fields

| Field | Type | Description |
|-------|------|-------------|
| `_l6_embedded` | bool | L6 explainer text embedded |
| `_l7_embedded` | bool | L7 Q-matrix embedded |
| `_l2_cleaned_at` | string | L2 cleanup timestamp |
| `_l2_regen_at` | string | L2 regeneration timestamp |
| `_l2_regen_phase` | string | L2 regen phase |
| `_l3_generated_at` | string | L3 generation timestamp |
| `_l5_generated_at` | string | L5 generation timestamp |
| `_l5_model` | string | L5 model used |

---

## DI-Specific Fields

| Field | Type | Description |
|-------|------|-------------|
| `_di_tables_found` | int | Tables found in content |
| `_di_chart_type` | string | Chart type |
| `_di_figure_data_count` | int | Figure data count |
| `_di_numeric_values` | array | Extracted numeric values |
| `_di_validated` | bool | DI validation flag |
| `_di_validation_method` | string | DI validation method |
| `_di_is_logic_puzzle` | bool | Is logic puzzle |
| `_di_computed_value` | string | Computed answer |
| `_di_stated_answer` | string | Stated answer |
| `_di_data_type` | string | Classification: `NUMERIC`, `TEXT_ONLY`, `TEXT_ONLY_LOGIC`, `TABLE_NO_NUMERIC`, `FIGURE_NO_NUMERIC`, `NO_FIGURE_LINKED` |
| `_di_relinked` | bool | Figure/table successfully relinked |
| `_di_relinked_values` | object | Extracted values from linked figure/table |
| `_di_figure_data` | object | Full structured figure/table data (type, title, values, headers, rows) |
| `_di_chosen_figure` | string | Title/type of chosen figure |
| `_di_relink_status` | string | `NONE`, `question_not_found`, `no_preceding_figure` |