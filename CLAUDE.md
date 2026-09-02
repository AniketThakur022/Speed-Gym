# Vedic Math Speed Gym (VMSG) — project rebuild

Offline-first Vedic-math speed-training + CAT/GMAT/GRE prep app (web PWA + Android/iOS via Capacitor), consumer brand **"Exam Arena"**. Built by AMH Solutions against **RFP v7.2 (365 specs)**. The original codebase was **lost on 2026-09-01** (dev laptop disk failure, no backup); this directory is the from-scratch rebuild working from recovered docs, corpus, and an APK teardown.

## Three chats, one project

Work is split across three chats that all run in THIS directory and share the same persistent memory (`~/.claude/projects/-Users-harshahirrao-Speed-gym/memory/`) and this file:

1. **Speed Gym main backend** — monorepo, FastAPI, Node Socket.IO game server, Postgres+pgvector "Ledger", Neo4j "GPS", Redis, PWA frontend (seed from `recovered/exam-arena-src/`), client-side BKT/Decision Engine packages, feature flags, sync, auth, payments.
2. **Speed Gym data extraction** — `data/corpus/MASTER_corpus.jsonl` completion: vision re-pass, answer-key recovery, taxonomy normalization, verification dashboards; delivers a flattened, playable, canonically-tagged question export.
3. **Speed Gym RAG** — the batch content factory (nightly + hourly, ZERO runtime consumers): 6-station ingestion, 7-stage auditor, QUARANTINED→SANDBOX→TRUSTED→LIVE trust ladder, T1/T2 template generation + SymPy, prerequisite-closure precompute; output conforms to the frontend's `SolveAlongTemplate` zod schema.

When you make a decision other workstreams depend on (API contract, graph schema, taxonomy, file formats), **write/update a memory file** so the other chats inherit it.

## Directory layout

- `docs/reference/` — surviving specs of record: `VMSG_TECHNICAL_ARCHITECTURE.md` (the 510-line blueprint), `VMSG_CLIENT_BRIEF.md`, `VMSG_CONTENT_READINESS.md`, `VMSG_PROGRESS_REPORT.pdf` (what was built pre-loss), `VMSG_RAG_Content_Factory.pdf` (factory spec, scope-locked 2026-07-17), `pipeline-untitled.pdf` (graph-closure strategies A–D), `system-design.excalidraw`, preview dashboards (`preview-1.html`, `preview-2.html`, `gre_preview.html`).
- `docs/analysis/report_*.json` — deep structured digests of every source (produced at restart, 2026-09-02), including `report_critic.json` listing cross-source contradictions and gaps. Read these before re-reading the big sources.
- `data/corpus/MASTER_corpus.jsonl` — canonical corpus: 4,805 records, 19,619 questions, 25 books, 68.5% keyed. `gre_essays_corrected.jsonl` is subsumed in it — never re-ingest.
- `recovered/exam-arena-src/` — 70 TypeScript sources recovered from the APK's dev-build chunks (the only surviving frontend code; includes `src_services_api.ts` contract and `src_lib_types_template.ts` SolveAlongTemplate schema).
- `apk/Exam Arena.apk` — debug build, mock-data only. `media/` — demo video (auth flow demo).

## Ground rules (from the surviving specs)

- Offline-first: the whole practice loop incl. psychometrics runs client-side; **no live LLM in the game loop, ever**; all content pre-verified.
- Psychometric events are never sampled. Dual DB (Postgres Ledger + Neo4j GPS) never collapsed. Phase-2 features dark-launch behind feature flags.
- Neo4j: code against `:Skill` (live label), not `:Technique` (stale schema files).
- Docs disagree in places (counts, edges, QA gates, chatbot-RAG, hosting) — check the `contradictions-to-resolve` memory / `docs/analysis/report_critic.json` before trusting a single source.
- Everything gets committed to git and pushed to a remote — the project already died once from having no backup.

## Recovered resources (2026-09-02, in `incoming/` — gitignored for size)

- `incoming/Resources/` — 53 source book PDFs by pillar, per-book intermediate JSONLs, and `6-19-26-full architect/` = the complete Architecture v5.2 spec corpus (complete_coder_spec.md, vedic_speed_gym_backend.md, decision_engine/, gaming/, v5_specs/, …) + June-19 package + unexplored `docs_archive.zip`.
- `incoming/topic_browser_full_package/` — July-12 package: `dashboards/` (page_view.html, explorer.html, problem_view.html), `scripts/` (page_ocr_pipeline.py + Dockerfile.ocr stack, enrichment, audit_and_validation, pattern_identification, quant_extraction), `schemas_and_taxonomy/ontology_registry.yaml`, `schemas/` (SQL + Cypher), `runtime_config/` (6 factory configs), per-book `cat_data/` working dirs, and `db_exports/` (chunks.jsonl 110MB, nodes.jsonl, relationships.jsonl, problems.jsonl, registry.jsonl — **re-seed the DBs from these**).

## Open items

1. RFP v7.2 still not recovered — check `incoming/Resources/6-19-26-full architect/docs_archive.zip`, WhatsApp media, client email.
2. Rotate the Anthropic API key leaked in WhatsApp (2026-03-20).
3. App source code (backend monorepo, full frontend) remains lost — rebuild from specs + `recovered/exam-arena-src/`.
4. Remote is wired: `origin = https://github.com/AniketThakur022/Speed-Gym.git` (histories merged). A LaunchAgent (`com.speedgym.daily-commit`, daily 03:00, script `tools/daily_commit.sh`) auto-commits and pushes — do not add another auto-commit mechanism. **Pushes fail until the owner authenticates once** (`brew install gh && gh auth login`); never create or paste credentials on their behalf. Back up `incoming/` somewhere durable (it is gitignored).
