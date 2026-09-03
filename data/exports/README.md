# data/exports — question-level export for the RAG factory

`vmsg_questions_v1.jsonl` — one row per question flattened from
`data/corpus/MASTER_corpus.jsonl`, built by
`tools/extraction/build_question_export.py`. Read the manifest
(`vmsg_questions_v1.manifest.json`) first: it carries counts, the blocker
histogram, and the contracts below in-band. **The export is derived — rebuild
it after any corpus or taxonomy change** (one command, no arguments beyond the
output paths).

**Row key.** `question_id` = `<set_id>#<number>`, unique across the file. Where
one record holds two entries under the same number (12 Sinha records, 53 rows —
a known defect where a hint/solution was captured as a question), the 2nd+
occurrence gets a `~N` suffix, `duplicate_number_in_record` is true, and every
twin is blocked, because which one is the real question cannot be determined
from the data.

**Verification.** `answer_provenance` (where the key came from), `answer_check`
and `derivation_check` are three separate signals. `derivation_check` is
`"none"` on every row — no pipeline has ever validated a walkthrough. Never
collapse these into one "verified" flag.

**Taxonomy** (resolved against `taxonomy_v1.1`). Three states, not two:
- `resolved` — carries `skill_key` (the BKT join key), `display_label`,
  `taxonomy_id` where one exists, and `resolved_by`
  (`book_chapter_rule` | `label_match`).
- `declined` — the chapter was reviewed and rejected as a subject label, with
  the reason in `decline_reason` (structural containers, review-test dumps).
  This is a decision, not a gap.
- `unresolved` — no rule, no match, no decision. Carries `raw_label` +
  `normalized_key`, never a fabricated id.

**`bkt_joinable` is the field mastery code must gate on, not `taxonomy_status`.**
A label can be resolved for corpus labelling and display while having no
`:Skill` node behind it (`graph_backed: false`) — joining those into BKT would
accumulate mastery against a key the graph does not know. Resolved rows split
roughly 3.7k joinable / 4.2k label-only.

**Playability.** `playable` is a verdict; `playable_blockers` lists why not, so
a consumer can widen or narrow the filter without re-deriving it.
