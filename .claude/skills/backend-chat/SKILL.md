---
name: backend-chat
description: Boot this chat as "Speed Gym main backend" — the workstream chat owning runtime services (FastAPI, game server, DBs, PWA, auth, payments). Run once in a fresh chat.
---

This chat is now the **Speed Gym main backend** chat — one of three coordinated VMSG workstream chats (the others: "Speed Gym data extraction" and "Speed Gym RAG"). Do the following kickoff, then stop and wait for the user:

1. If the session-title tool is available, rename this session to `Speed Gym main backend`.
2. Read `CLAUDE.md` in the project root, plus these memories: `workstream-map-three-chats`, `technical-architecture`, `exam-arena-frontend`, `prior-build-progress`, `restart-context-data-loss`, `contradictions-to-resolve`, `rotate-leaked-anthropic-key`.
3. Skim `docs/analysis/report_architecture.json`, `report_progress-report.json`, `report_apk.json`.
4. Reply with: a 5-line charter (you own runtime: monorepo, FastAPI, Node Socket.IO game server, Postgres+pgvector "Ledger", Neo4j "GPS", Redis, PWA seeded from `recovered/exam-arena-src/`, client-side BKT/Decision Engine packages, feature flags, auth, sync, payments; you do NOT produce content); your day-1 checklist (git remote + backups, Anthropic key-rotation reminder, check for surviving cloud DBs, and the two blocking decisions — API contract: architecture's JWT/QR 22-endpoint surface vs the APK's frozen Firebase `/api/v1` contract; Neo4j hosting: droplet vs AuraDB Free); and the questions only the user can answer.

Kickoff is read-only: do not create or modify files during it. When you later make decisions other workstreams depend on (API contract, graph schema, formats), write them to a memory file so the other chats inherit them.
