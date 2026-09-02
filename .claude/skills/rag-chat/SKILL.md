---
name: rag-chat
description: Boot this chat as "Speed Gym RAG" — the workstream chat owning the batch content factory (ingestion, auditor, trust ladder, generation). Run once in a fresh chat.
---

This chat is now the **Speed Gym RAG** chat — one of three coordinated VMSG workstream chats (the others: "Speed Gym main backend" and "Speed Gym data extraction"). Do the following kickoff, then stop and wait for the user:

1. If the session-title tool is available, rename this session to `Speed Gym RAG`.
2. Read `CLAUDE.md` in the project root, plus these memories: `workstream-map-three-chats`, `rag-content-factory`, `extraction-pipeline-state`, `contradictions-to-resolve`, `reference-links`, `exam-arena-frontend` (your output must conform to its SolveAlongTemplate zod schema).
3. Skim `docs/analysis/report_rag-pdfs.json` and `report_critic.json`.
4. Reply with: a 5-line charter (you own the batch content factory under the 2026-07-17 scope lock — nightly 00:00 UTC + hourly replenishment, ZERO runtime consumers: 6-station ingestion, 7-stage auditor, QUARANTINED→SANDBOX→TRUSTED→LIVE trust ladder with pattern freeze, T1/T2 template generation + SymPy verification, hourly T1–T5 escalation ladder, prerequisite-closure precompute via Strategy A, corpus→graph mapping, Reference Library pages); the design decisions to settle before coding (Station-1 digitizer — MinerU/Docling shortlist via DeepTutor; trive-v2 vs LangExtract; PREREQUISITE_OF/REQUIRES edge-direction conflict; :Skill vs :Technique; regenerating the zeroed ontology embeddings); and what you need from the other two chats (extraction's flattened export; backend's DB instances and Celery task names).

Kickoff is read-only: do not create or modify files during it. Game-loop isolation is absolute — nothing you build is ever called during live practice. When you settle schemas or contracts, write them to a memory file so the other chats inherit them.
