# CAT Wave 2 Handover Checklist

> **Last Updated:** 2026-07-08
> **Purpose:** Pre-handoff verification for backend/adaptive-engine team

---

## Data Quality

- [x] All 738 records extracted (295 DI + 300 VARC P1 + 143 VARC P2)
- [x] L1 Content extraction — 100% complete
- [x] L2 Logic Steps — 99.9% complete (1 record pending regen)
- [x] L3 Cognitive Profile — 100% complete
- [x] L4 Hints — 100% complete
- [x] L5 Trap Tags — 100% complete
- [x] L6 Explainer clusters — 90 clusters, 738 records linked
- [x] L7 Q-Matrix — 738 entries, record_idx populated
- [ ] L6/L7 text embedded into records (scripts ready, run after validation)
- [ ] Validation ≥ 95% verified rate (currently ~71%, re-run in progress)
- [ ] Answer-key-suspect records flagged for human review

---

## File Inventory

### Records (Primary Data)
- [x] `CAT_DI_LR_Nishit_K_Sinha/records.jsonl` — 295 records (2.2 MB)
- [x] `CAT_VARC_Part1/records.jsonl` — 300 records (2.8 MB)
- [x] `CAT_VARC_Part2/records.jsonl` — 143 records (1.3 MB)

### Explainers (L6)
- [x] `explainers/explainers.jsonl` — 90 entries (223 KB)
- [x] `explainers/cluster_registry.json` — 90 clusters (114 KB)
- [x] `explainers/cluster_record_map.json` — 738 mappings (39 KB)

### Q-Matrix (L7)
- [x] `qmatrix/qmatrix_entries.jsonl` — 738 entries (332 KB)
- [x] `qmatrix/qmatrix_ingest.cypher` — Neo4j ingest script (29 KB)

### Neo4j
- [x] `neo4j_cat_classification.cypher` — Classification script (6 KB)
- [x] `qmatrix/qmatrix_ingest.cypher` — Q-matrix ingest (29 KB)

### Documentation
- [x] `docs/pipeline_tracking.md`
- [x] `docs/handover_checklist.md` (this file)
- [x] `docs/COMPLETED_TASKS.md`
- [x] `docs/task_orchestrator_index.md`
- [x] `docs/TEMPLATE_RENDERER_SCHEMA.md`
- [x] `docs/PSYCHOMETRIC_MODEL_MASTER_SPEC.md`

### Dashboards
- [ ] `cat.html` — Detailed dashboard
- [ ] `index.html` — Root navigation hub

---

## Neo4j Readiness

- [x] `neo4j_cat_classification.cypher` exists and references correct paths
- [x] `qmatrix_ingest.cypher` exists with record_idx populated
- [x] JSONL files parse cleanly (verified)
- [ ] Cypher scripts executed against Neo4j instance

---

## Validation

- [x] Validation script `wave2_validation_final.py` (TITA-aware, max_tokens=4096)
- [x] Hard-fix script `wave2_validation_di_hard.py` (2000-char, 3-model tiebreaker)
- [ ] DI validation ≥ 95% (currently ~30%, re-run in progress)
- [x] VARC P1 validation 96.7%
- [x] VARC P2 validation 100%
- [ ] Answer-key-suspect records flagged (`flag_syllogism_suspects.py`)

---

## Pre-Handoff Steps (Run Order)

1. **Wait for validation re-run** (`wave2_validation_final.py`, PID 710) to complete
2. **Run hard-fix** for remaining EMPTY records:
   ```bash
   python3 /workspace/assembly_line/wave2_validation_di_hard.py
   ```
3. **Re-flag syllogism suspects** (overwritten by validation race):
   ```bash
   python3 /workspace/assembly_line/flag_syllogism_suspects.py
   ```
4. **Embed L6 explainers** into all records:
   ```bash
   python3 /workspace/assembly_line/embed_l6_explainers.py
   ```
5. **Embed L7 Q-matrix** into all records:
   ```bash
   python3 /workspace/assembly_line/link_qmatrix_to_records.py
   ```
6. **Verify embedding**:
   ```python
   # All records should have _l6_embedded=True and _l7_embedded=True
   ```
7. **Run Neo4j Cypher scripts** (requires Neo4j instance):
   ```cypher
   :source neo4j_cat_classification.cypher
   :source qmatrix/qmatrix_ingest.cypher
   ```

---

## Known Limitations for Handoff

1. **1 DI record (idx 235)** missing L2 logic_steps — needs L2 regeneration
2. **~20 answer-key-suspect records** — both models agree on a different answer; flagged for human review, original answer preserved
3. **10 VARC P1 records** from RC passage chunk_idx 35/36 — kimi-k2.6 returns empty
4. **API keys 4–6 exhausted** — only 3 keys active; may need rotation before Phase 3

---

## Sign-off

- [ ] Data quality review passed
- [ ] Validation ≥ 95% achieved
- [ ] L6/L7 embedding verified
- [ ] Documentation review passed
- [ ] Neo4j ingestion tested
- [ ] Ready for Phase 3 (Adaptive Engine)

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Data Lead | | | |
| Validation Lead | | | |
| Backend Lead | | | |
| QA Lead | | | |