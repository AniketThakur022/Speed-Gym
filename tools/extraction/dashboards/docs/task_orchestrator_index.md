# Task Orchestrator Index — CAT Wave 2

> **Last Updated:** 2026-07-08
> **Quick reference for all scripts, data, and next phases**

---

## Script Index

| Script | Purpose | Status | Location |
|--------|---------|--------|----------|
| `wave2_validation_final.py` | TITA-aware validation re-run (max_tokens=4096, reasoning fallback) | Running (PID 710) | `/workspace/assembly_line/` |
| `wave2_validation_di_hard.py` | Targeted fix for 77 EMPTY DI records (2000-char, 3-model tiebreaker) | Ready | `/workspace/assembly_line/` |
| `embed_l6_explainers.py` | Embed L6 explainer text into records | Ready | `/workspace/assembly_line/` |
| `link_qmatrix_to_records.py` | Populate record_idx + embed L7 Q-matrix | record_idx DONE, records pending | `/workspace/assembly_line/` |
| `flag_syllogism_suspects.py` | Flag answer-key-suspect records for human review | Ready (re-run after validation) | `/workspace/assembly_line/` |

---

## Data Locations

```
/workspace/data/extraction_phase3/cat/
├── CAT_DI_LR_Nishit_K_Sinha/
│   ├── records.jsonl              (295 records, 2.2 MB)
│   ├── raw.md                     (source markdown)
│   └── bundles/                   (extraction bundles)
├── CAT_VARC_Part1/
│   ├── records.jsonl              (300 records, 2.8 MB)
│   └── bundles/
├── CAT_VARC_Part2/
│   ├── records.jsonl              (143 records, 1.3 MB)
│   └── bundles/
├── explainers/
│   ├── explainers.jsonl           (90 entries, 223 KB)
│   ├── cluster_registry.json      (90 clusters, 114 KB)
│   └── cluster_record_map.json    (738 mappings, 39 KB)
├── qmatrix/
│   ├── qmatrix_entries.jsonl       (738 entries, 332 KB)
│   └── qmatrix_ingest.cypher       (Neo4j ingest, 29 KB)
├── docs/
│   ├── pipeline_tracking.md
│   ├── handover_checklist.md
│   ├── COMPLETED_TASKS.md
│   ├── task_orchestrator_index.md  (this file)
│   ├── TEMPLATE_RENDERER_SCHEMA.md
│   └── PSYCHOMETRIC_MODEL_MASTER_SPEC.md
├── cat.html                        (dashboard — pending)
├── index.html                      (root hub — pending)
└── neo4j_cat_classification.cypher  (6 KB)
```

---

## Key File Paths

| File | Path |
|------|------|
| DI Records | `/workspace/data/extraction_phase3/cat/CAT_DI_LR_Nishit_K_Sinha/records.jsonl` |
| VARC P1 Records | `/workspace/data/extraction_phase3/cat/CAT_VARC_Part1/records.jsonl` |
| VARC P2 Records | `/workspace/data/extraction_phase3/cat/CAT_VARC_Part2/records.jsonl` |
| Explainers | `/workspace/data/extraction_phase3/cat/explainers/explainers.jsonl` |
| Q-Matrix | `/workspace/data/extraction_phase3/cat/qmatrix/qmatrix_entries.jsonl` |
| Neo4j Classification | `/workspace/data/extraction_phase3/cat/neo4j_cat_classification.cypher` |
| Neo4j Q-Matrix Ingest | `/workspace/data/extraction_phase3/cat/qmatrix/qmatrix_ingest.cypher` |
| API Keys | `/workspace/.env` (OLLAMA_CLOUD_API_KEY, _2, _3) |

---

## Execution Order (Post-Validation)

```bash
# 1. Run hard-fix for remaining EMPTY records
python3 /workspace/assembly_line/wave2_validation_di_hard.py

# 2. Re-flag syllogism suspects (overwritten by validation)
python3 /workspace/assembly_line/flag_syllogism_suspects.py

# 3. Embed L6 explainers
python3 /workspace/assembly_line/embed_l6_explainers.py

# 4. Embed L7 Q-matrix into records
python3 /workspace/assembly_line/link_qmatrix_to_records.py

# 5. Verify embedding
python3 -c "
import json
for book in ['CAT_DI_LR_Nishit_K_Sinha','CAT_VARC_Part1','CAT_VARC_Part2']:
    recs = [json.loads(l) for l in open(f'/workspace/data/extraction_phase3/cat/{book}/records.jsonl') if l.strip()]
    l6 = sum(1 for r in recs if r.get('_l6_embedded'))
    l7 = sum(1 for r in recs if r.get('_l7_embedded'))
    print(f'{book}: L6={l6} L7={l7} total={len(recs)}')
"

# 6. Run Neo4j Cypher (requires Neo4j instance)
cypher-shell -u neo4j -p password -f /workspace/data/extraction_phase3/cat/neo4j_cat_classification.cypher
cypher-shell -u neo4j -p password -f /workspace/data/extraction_phase3/cat/qmatrix/qmatrix_ingest.cypher
```

---

## Next Phase: Phase 3 — Adaptive Engine

| Component | Description |
|-----------|-------------|
| BKT Calibration | Bayesian Knowledge Tracing parameter calibration using Q-matrix |
| Student Model | Per-student skill mastery estimation |
| Difficulty Adjustment | Adaptive difficulty based on cognitive profile + BKT state |
| Sutra Linking | Map techniques to Sutras (Vedic math patterns) |
| Gaming Readiness | Gamification layer (XP, streaks, badges) |
| Cognitive State Tagging | Real-time cognitive load estimation |