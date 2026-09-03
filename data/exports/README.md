# data/exports — question-level export for the RAG factory

`vmsg_questions_v1.jsonl` — one row per question flattened from
`data/corpus/MASTER_corpus.jsonl`, built by
`tools/extraction/build_question_export.py`. Read the manifest
(`vmsg_questions_v1.manifest.json`) first: it carries the counts, the blocker
histogram, and the three contracts below in-band.

**Row key.** `question_id` = `<set_id>#<number>`, unique across the file. Where
one record holds two entries under the same number (12 Sinha records, 53 rows —
a known extraction defect where a hint/solution was captured as a question), the
2nd+ occurrence gets a `~N` suffix, `duplicate_number_in_record` is true, and
every twin is blocked, because we cannot tell which one is the real question.

**Verification.** `answer_provenance` (where the key came from),
`answer_check` and `derivation_check` are three separate signals.
`derivation_check` is `"none"` on every row — no pipeline has ever validated a
walkthrough. Never collapse these into one "verified" flag.

**Taxonomy.** `taxonomy.skill_key` mirrors the live `:Skill` name and is the BKT
join key; `display_label` is owner-changeable with zero migration. Unresolved
rows carry `raw_label` + `normalized_key` + `taxonomy_status: "unresolved"`,
never a fabricated id. Coverage is thin on purpose: question records carry no
topic field, so the only signal is the book chapter.

**Playability.** `playable` is a verdict; `playable_blockers` lists why not, so
a consumer can widen or narrow the filter without re-deriving it.
