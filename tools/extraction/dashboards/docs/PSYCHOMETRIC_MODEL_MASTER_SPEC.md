# Psychometric Model Master Spec — CAT Content Pipeline

> **Last Updated:** 2026-07-08
> **Purpose:** DINA model + Q-matrix + BKT integration spec for the adaptive engine

---

## 1. DINA Model Overview

**DINA** (Deterministic Inputs, Noisy "And" gate) is the psychometric model used for the CAT content pipeline's Q-matrix. It models whether a student has the *required* skills to answer a question correctly, with noise for slip and guess.

### Core Formula

For a question *q* requiring skills *Kq* (from the Q-matrix) and a student with mastery vector *α*:

```
η_q = ∏_{k∈Kq} α_k   (deterministic: 1 only if ALL required skills mastered)
```

```
P(correct | α) = (1 - s_q)^η_q * g_q^(1 - η_q)
```

Where:
- `η_q` = ideal response (1 if student has all required skills, 0 otherwise)
- `s_q` = **slip probability** (P(wrong | has all skills)) — set to **0.2**
- `g_q` = **guess probability** (P(correct | missing a skill)) — set to **0.25**

### Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `slip_probability` | 0.20 | 20% chance a mastered student slips |
| `guess_probability` | 0.25 | 25% chance an unmastered student guesses right |
| `psychometric_model` | DINA | Model name |

---

## 2. Q-Matrix Structure

### File: `qmatrix/qmatrix_entries.jsonl`

738 entries, one per record. Each entry:

```json
{
  "record_book": "CAT_DI_LR_Nishit_K_Sinha",
  "record_idx": 0,
  "subject": "DI",
  "subtopic": "Table Interpretation",
  "technique": "Percentage Calculation",
  "difficulty": 3,
  "q_matrix": [1, 0, 1, 0, 0, 0, 1, 0, 0, 0],
  "skill_names": ["DATA_READING", "RATIO", "PERCENTAGE", ...],
  "k_skills": 10,
  "slip_probability": 0.2,
  "guess_probability": 0.25,
  "psychometric_model": "DINA"
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `record_book` | string | Source book name |
| `record_idx` | int | Record index within book (0-based) |
| `subject` | string | `DI` or `VARC` |
| `subtopic` | string | Sub-topic (e.g., `Table Interpretation`) |
| `technique` | string | Technique (e.g., `Percentage Calculation`) |
| `difficulty` | int | 1–5 difficulty rating |
| `q_matrix` | array[int] | Binary skill vector (0/1) |
| `skill_names` | array[string] | Human-readable skill names |
| `k_skills` | int | Total number of skills in the subject |
| `slip_probability` | float | DINA slip parameter (0.2) |
| `guess_probability` | float | DINA guess parameter (0.25) |
| `psychometric_model` | string | `DINA` |

---

## 3. Skill Taxonomies

### VARC Skills (k=5)

| Skill | Code | Description |
|-------|------|-------------|
| Main Idea Identification | `MAIN_IDEA` | Identify the central theme/main point |
| Inference | `INFERENCE` | Draw conclusions from passage |
| Critical Reasoning | `CRITICAL_REASONING` | Evaluate arguments, assumptions |
| Grammar Usage | `GRAMMAR_USAGE` | Sentence correction, grammar rules |
| Vocabulary | `VOCABULARY` | Word meaning, contextual usage |

### DI Skills (k=10)

| Skill | Code | Description |
|-------|------|-------------|
| Data Reading | `DATA_READING` | Extract values from tables/charts |
| Percentage | `PERCENTAGE` | Percentage calculation |
| Ratio | `RATIO` | Ratio and proportion |
| Average | `AVERAGE` | Mean/median/mode |
| Growth Rate | `GROWTH_RATE` | YoY/moM growth |
| Logical Deduction | `LOGICAL_DEDUCTION` | Multi-step logical reasoning |
| Arrangement | `ARRANGEMENT` | Seating/ordering arrangements |
| Syllogism | `SYLLOGISM` | Valid/invalid conclusion |
| Set Theory | `SET_THEORY` | Venn diagrams, set operations |
| Data Sufficiency | `DATA_SUFFICIENCY` | Evaluate statement sufficiency |

---

## 4. Cognitive Profile Fields

### VARC (`cognitive_profile`)

```json
{
  "reading_load": 7,
  "inference_demand": 8,
  "vocabulary_level": 8,
  "cognitive_taxonomy": "ANALYSIS",
  "working_memory_chunks": 5,
  "time_estimate_seconds": 90
}
```

| Field | Range | Description |
|-------|-------|-------------|
| `reading_load` | 1–10 | Passage reading difficulty |
| `inference_demand` | 1–10 | Inference requirement |
| `vocabulary_level` | 1–10 | Vocabulary difficulty |
| `cognitive_taxonomy` | string | Bloom's: `COMPREHENSION`, `ANALYSIS`, `EVALUATION` |
| `working_memory_chunks` | int | Working memory chunks needed |
| `time_estimate_seconds` | int | Estimated solve time |

### DI (`data_points._di_cognitive_profile`)

```json
{
  "chart_type": "TABLE",
  "base_cognitive_load": 0.45,
  "working_memory_chunks": 4,
  "trap_cognitive_taxonomy": ["MEDIUM_LOAD", "PERCENTAGE_TRAP"],
  "session_alignment_tag": "FOCUSED_TIMER"
}
```

| Field | Range | Description |
|-------|-------|-------------|
| `chart_type` | string | `TABLE`, `BAR`, `PIE`, `LINE`, `MIXED`, `UNKNOWN` |
| `base_cognitive_load` | 0.0–1.0 | Base cognitive load |
| `working_memory_chunks` | int | Working memory chunks |
| `trap_cognitive_taxonomy` | array | Trap-based load tags |
| `session_alignment_tag` | string | `FRIENDLY_TIMER`, `FOCUSED_TIMER`, `PRESSURE_TIMER` |

---

## 5. How Q-Matrix Drives the Adaptive Engine

### Mastery Estimation (DINA)

1. Student answers question *q*
2. System looks up `q_matrix[q]` to get required skills
3. Updates mastery `α_k` for each skill *k* via Bayes:

```
P(α_k | response) ∝ P(response | α_k) * P(α_k)
```

4. Slip and guess parameters modulate the update:
   - Correct + has skill → slight decrease (slip is possible)
   - Wrong + has skill → strong decrease (likely slipped)
   - Correct + missing skill → slight increase (possible guess)
   - Wrong + missing skill → no change (expected)

### Difficulty Adjustment

- `difficulty` (1–5) + `cognitive_profile` + BKT mastery → adaptive difficulty selection
- Target zone: ~70% expected correctness (Vygotsky's ZPD)

---

## 6. BKT (Bayesian Knowledge Tracing) Integration — Phase 3

### Standard BKT Parameters

| Parameter | Default | Meaning |
|-----------|---------|---------|
| P(L0) | 0.1 | Initial probability of knowing a skill |
| P(T) | 0.1 | Probability of learning per practice |
| P(S) | 0.2 | Slip (= DINA `slip_probability`) |
| P(G) | 0.25 | Guess (= DINA `guess_probability`) |

### Per-Skill Calibration (Phase 3)

BKT parameters will be calibrated per skill using:
1. Initial values from DINA Q-matrix (P(S)=slip, P(G)=guess)
2. EM (Expectation-Maximization) fitting on student response data
3. Per-skill L0 and T learned from empirical data

### Data Flow

```
Student Response
    → DINA Q-Matrix lookup (required skills)
    → BKT mastery update (per skill)
    → Difficulty adjustment (cognitive_profile + mastery)
    → Next question selection (ZPD targeting)
```

---

## 7. Cluster Explainer Integration

90 cluster explainers provide the pedagogical content:

| Component | Source | Usage |
|-----------|--------|-------|
| Concept Core (150–200w) | `explainers.jsonl` | Pre-question concept primer |
| Trap Addendum (100–150w) | `explainers.jsonl` | Post-answer trap explanation |
| Skill mapping | `q_matrix_entry` | Which skills this question tests |
| Cognitive profile | `cognitive_profile` / `_di_cognitive_profile` | Difficulty estimation |

### Render Flow

1. Student sees question → optional Concept Core primer
2. Student answers → BKT updates mastery
3. If wrong → Trap Addendum + skill-specific remediation
4. Difficulty adjusts for next question

---

## 8. File Locations

| File | Path | Purpose |
|------|------|---------|
| Q-Matrix | `qmatrix/qmatrix_entries.jsonl` | 738 DINA entries |
| Q-Matrix Ingest | `qmatrix/qmatrix_ingest.cypher` | Neo4j load script |
| Explainers | `explainers/explainers.jsonl` | 90 cluster explainers |
| Cluster Registry | `explainers/cluster_registry.json` | Cluster metadata |
| Record Map | `explainers/cluster_record_map.json` | Cluster→record mapping |
| DI Records | `CAT_DI_LR_Nishit_K_Sinha/records.jsonl` | 295 DI records |
| VARC P1 Records | `CAT_VARC_Part1/records.jsonl` | 300 VARC records |
| VARC P2 Records | `CAT_VARC_Part2/records.jsonl` | 143 VARC records |

---

## 9. Validation & Quality Assurance

### Validation Statuses

| Status | Meaning | Action |
|--------|---------|--------|
| `JURY_VERIFIED` | Both models agree with stored answer | ✅ Production-ready |
| `JURY_PARTIAL` | One model agrees | ⚠️ Review |
| `JURY_REJECTED` | Neither model agrees | ❌ Needs fix |
| `ANSWER_KEY_SUSPECT` | Both models agree on different answer | 🔍 Human review |
| `VERIFIED` | Legacy validation (VARC P1/P2) | ✅ Accepted |

### Answer Key Suspect Handling

Records flagged `_answer_key_suspect = True`:
- Original `correct_answer` preserved (not overwritten)
- `_model_consensus_answer` field added with models' agreement
- `_human_review_note` explains the discrepancy
- These records should NOT be used for BKT calibration until resolved