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

## Open recovery items

1. **Download the Google Drive zip** (auth-gated; link in `reference-links` memory) — extraction/enrichment scripts, per-book JSONLs, `page_view.html`/`explore.html` dashboards, pipeline PDF. Do this before rebuilding any extraction tooling.
2. RFP v7.2 itself was never recovered — spec-ID references are unverifiable until found (client email / WhatsApp media / Drive).
3. Check whether any cloud DBs survived (Neo4j AuraDB Free, cloud Postgres) before rebuilding from zero.
4. Rotate the Anthropic API key leaked in WhatsApp (2026-03-20).
5. Source book PDFs (25 books) — needed for the vision re-pass; location unknown (likely Drive).
