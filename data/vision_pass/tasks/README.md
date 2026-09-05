# data/vision_pass/tasks — staged extraction batches

Built by `tools/extraction/vision_pass_harness.py`. Every prompt is scoped to
**targeted fact extraction for specific numbered exercise items** — not page
transcription. Results are candidate input only: they run through
`tools/extraction/verify_patch.py` (validity + token-preservation against the
source page OCR) and a spot-check before any patch touches MASTER.

| File | Tasks | Questions | What it recovers |
|---|---|---|---|
| `tasks_fact_options_recovery.jsonl` | 557 | 2,401 | Answer options for questions that already have a verified key but lost their option list from the text layer. Each success makes a question playable. |
| `tasks_fact_needs_reextraction.jsonl` | 89 | 244 | The true printed question stem + options where the extractor captured hint/solution prose instead. 133 carry the answer from the printed grid as a hint. |
| `tasks_answer_grid_HK_targeted.jsonl` | 4 | ~19 keys | Re-read of the four Hall & Knight ANSWERS pages whose entries a prior direct read left illegible. |
| `tasks_convertible_all.jsonl` | 558 | 2,402 | Superset of the two fact batches, grouped by page. |
| `tasks_digitize_Arun_Sharma.jsonl` | 123 | — | **Source-limited.** See `tasks_digitize_Arun_Sharma.BLOCKED.md`: 343 of 466 pages are Google Books placeholders. |
| `tasks_Sinha.jsonl` | 10 | — | Chart transcription; delivered, flags cleared (all false positives). |
| `tasks_fact_requestion_v2.jsonl` | 23 | 73 | **v2 (2026-09-05).** Items of the six Sinha families whose cited pages were Hints pages (`QUESTION_PAGE_OVERRIDES`), re-issued against their question pages. Supersedes those items in the two fact batches; everything else in them stands. |

**The 10 held lists — resolved 2026-09-05 from the page images.** Five were
the shared directions block for a group of plotted-graph items (Arun Sharma
Quant p664 #36–38, p677 #33–34): applied with provenance, but each item IS a
graph with no stem text, so it stays blocked until a figure asset exists.
Five were verbal descriptions of printed Venn diagrams (p879 #38–42): the
descriptions are accurate against the image and were applied with provenance,
together with the set's missing directions preamble, but `question_format`
stays `options_are_images` — serving a described diagram in place of the
picture is a product decision for the consumers, not an extraction call.

**Immutability.** Delivered task files are never regenerated in place: each
carries a `build_id`, and a rebuild moves the old file to `.superseded.jsonl`.
Re-targeted work goes out as a new versioned file (as `_v2` above).

**Priority.** `options_recovery` first — 2,401 questions, every one already
carrying a verified answer key, so a successful read converts each straight to
playable. Then `needs_reextraction`, then the H&K targeted re-read.

**Open question for the owner, not resolvable here.** The RFP-era docs list
*"content ownership: confirm with client"* as still open. Per-question fact
extraction for an exam-prep product is the work these batches do; wholesale
verbatim reproduction of copyrighted books is a different activity with a
different rights basis, and the full-page corpus lane should not proceed past
the already-swept text layer until the owner confirms that basis.
