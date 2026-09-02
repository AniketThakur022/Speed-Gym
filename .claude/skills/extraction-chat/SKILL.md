---
name: extraction-chat
description: Boot this chat as "Speed Gym data extraction" — the workstream chat owning MASTER_corpus.jsonl completion and verification tooling. Run once in a fresh chat.
---

This chat is now the **Speed Gym data extraction** chat — one of three coordinated VMSG workstream chats (the others: "Speed Gym main backend" and "Speed Gym RAG"). Do the following kickoff, then stop and wait for the user:

1. If the session-title tool is available, rename this session to `Speed Gym data extraction`.
2. Read `CLAUDE.md` in the project root, plus these memories: `workstream-map-three-chats`, `corpus-master-jsonl`, `extraction-pipeline-state`, `restart-context-data-loss`, `contradictions-to-resolve`.
3. Skim `docs/analysis/report_corpus.json` and `report_dashboards.json`.
4. Reply with: a 5-line charter (you own completing `data/corpus/MASTER_corpus.jsonl` — vision re-pass for 4,133 flagged questions, answer-key recovery with Sinha's ~706 unkeyed first, format classification, taxonomy normalization, dedup, verification dashboards — and you deliver a flattened question-level export with canonical taxonomy, filtered to playable items, to the RAG chat); your blocked-on-user item (the auth-gated Google Drive recovery zip with the extraction scripts, per-book JSONLs, page_view.html/explore.html, and source book PDFs — do NOT rebuild tooling that may exist in it until it lands or is declared unrecoverable); and your priority-ordered work queue for once the zip arrives.

Kickoff is read-only: do not create or modify files during it. `gre_essays_corrected.jsonl` is already subsumed in MASTER — never re-ingest it. When you settle formats or taxonomy, write them to a memory file so the other chats inherit them.
