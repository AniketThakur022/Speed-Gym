# Topic Browser Full Package — Vedic Math Speed Gym + CAT Phase 1 (DI/LR, VARC, Quant)

A self-contained deliverable that merges the original **subtopic-centric Topic Browser Reference Library** for *Vedic Math Speed Gym* with the new **CAT Phase 1 L1-L7 pipeline** covering **DI/LR, VARC, and Quantitative Aptitude**.

## What This Package Contains

```text
topic_browser_full_package/
├── README.md                              # This file
├── manifest.json                          # Package inventory + version
├── dashboards/                            # CAT Phase 1 verification UIs
│   ├── index.html                         # Pipeline status dashboard
│   ├── cat.html                           # CAT pillar overview
│   ├── explorer.html                      # Topic browser / bundle explorer
│   ├── page_view.html                     # OCR page verifier
│   ├── problem_view.html                  # Problem workbench
│   └── docs/                              # Pipeline documentation
├── cat_data/                              # CAT L1-L7 data
│   ├── CAT_DI_LR_Nishit_K_Sinha/
│   ├── CAT_LR_LSAT_Logic_Games/
│   ├── CAT_VARC_Part1/
│   ├── CAT_VARC_Part2/
│   ├── CAT_Quant_Arun_Sharma/
│   ├── CAT_Quant_Higher_Algebra/
│   ├── quant_enriched.jsonl
│   ├── l1l7_enriched/                     # L1-L7 enriched JSON payloads
│   ├── explainers/                        # Cluster explainers
│   └── qmatrix/                           # Q-matrix entries
├── content_data/                          # Original Vedic Math content
│   ├── subtopic_explainer/
│   ├── subtopic_explainer_enriched/
│   └── templates/
├── runtime_config/                        # JSON configs for generators/auditors
├── schemas_and_taxonomy/                  # Schemas + ontology registry
│   ├── subtopic_reference_schema.json
│   └── ontology_registry.yaml
├── schemas/                               # Legacy schema location (preserved)
├── scripts/                               # Orchestrators + new CAT/Quant scripts
│   ├── topic_browser_orchestrator.py
│   ├── bank_exhaustion_handler.py
│   ├── focused_extract.py                 # CAT L1-L7 extractor
│   ├── page_ocr_pipeline.py               # OCR renderer
│   ├── audit_and_validation/              # Multi-LLM + SymPy validators
│   ├── pattern_identification/            # LR/DI pattern engines
│   └── quant_extraction/                  # Quant text-to-math subsystem
└── db_exports/                            # Neo4j + Postgres exports
```

## Quick Start — Dashboards

The dashboards are static HTML files that load data via relative `fetch()` paths. Serve the package root with any static server:

```bash
cd topic_browser_full_package
# Python 3
python3 -m http.server 8000
# Node
npx serve .
```

Then open:

- `http://localhost:8000/dashboards/index.html` — pipeline status
- `http://localhost:8000/dashboards/explorer.html` — bundle/topic explorer
- `http://localhost:8000/dashboards/page_view.html` — OCR page verifier
- `http://localhost:8000/dashboards/problem_view.html` — problem workbench

> **Note:** Opening the HTML files directly with `file://` may block `fetch()` in some browsers. Use a local server for full functionality.

## Quick Start — Scripts

### Validate all Python scripts compile

```bash
cd topic_browser_full_package
python3 -m py_compile scripts/*.py
python3 -m py_compile scripts/audit_and_validation/*.py
python3 -m py_compile scripts/pattern_identification/*.py
python3 -m py_compile scripts/quant_extraction/*.py
python3 -m py_compile scripts/quant_extraction/text_to_math_extractor/*.py
```

### Run the original Topic Browser smoke tests

```bash
python3 scripts/topic_browser_orchestrator.py
python3 scripts/bank_exhaustion_handler.py
```

### Run audit / validation scripts

```bash
# Multi-LLM consensus audit (example invocation — check script argparse for options)
python3 scripts/audit_and_validation/multi_llm_audit.py --help

# SymPy exact-match validation
python3 scripts/audit_and_validation/validate_phase1_sympy.py

# Quant-specific validators
python3 scripts/audit_and_validation/consensus_math_validator_v3.py
python3 scripts/audit_and_validation/fast_python_math_auditor_v3.py
```

### Run the Quant text-to-math subsystem

```bash
python3 scripts/quant_extraction/text_to_math_extractor/cli.py --help
python3 scripts/quant_extraction/quant_option_filler.py --help
```

## Content Status

### Vedic Math (original)

| Subtopic | Status | Completeness |
|----------|--------|--------------|
| nikhilam_sutra | approved | 0.95 |
| urdhva_tiryak | approved | 0.90 |
| yavadunam | approved | 0.95 |
| 40 enriched stubs | complete | 0.70-0.95 |

### CAT Phase 1 (merged)

| Pillar | Books | Records Source | L1-L7 Enriched |
|--------|-------|----------------|----------------|
| DI/LR | CAT_DI_LR_Nishit_K_Sinha | `records.jsonl` | — |
| LR | CAT_LR_LSAT_Logic_Games | `records.jsonl` | — |
| VARC | CAT_VARC_Part1, CAT_VARC_Part2 | `records.jsonl` | ✅ enriched JSON |
| Quant | CAT_Quant_Arun_Sharma, CAT_Quant_Higher_Algebra | `records.jsonl` | ✅ enriched JSON |

## Database Extensions

- **PostgreSQL**: run `db_exports/extend_postgres_subtopic_reference.sql`
- **Neo4j**: run `db_exports/extend_neo4j_subtopic_reference.cypher` with APOC installed

## Known Issues / Notes

- Dashboards were patched to use relative paths (`../cat_data/...`). If you move the package, keep `dashboards/` and `cat_data/` as siblings.
- `CAT_DI_LR_Arun_Sharma` is referenced by the auto-loader in `explorer.html` but was not included in the integration plan; it will be skipped if absent.
- Some audit scripts may still contain hard-coded absolute paths from their original locations; review `scripts/audit_and_validation/*.py` before running in production.
- The Vedic Math `content_data/` is preserved unchanged.
