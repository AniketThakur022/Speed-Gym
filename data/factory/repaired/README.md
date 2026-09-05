# repaired/ — legacy bank re-narration pass (candidate, NOT adopted)

Re-narration of the 823-template legacy bank (`solvealong_bank_v1_4.jsonl`), 2026-09-05.
Descriptions rewritten from their own step's operation/result; technique names and scaffolds
corrected; auto-extraction filler removed from `common_mistakes`. **Operation, result, answer,
problem_statement, step_num, id, difficulty, expected_time were protected — audit confirms 0
corruption across every checked template.**

Result: **522 repaired / 297 unrepairable (36%)**, 4,813 descriptions rewritten, 227 technique
names corrected, 337 scaffolds corrected, 303 filler entries removed. All `quarantined_pending_consensus`.

## Why this is a candidate and not a fix — read before adopting anything

**The premise was half wrong.** The pass assumed the `result` layer was verified ground truth.
It is not: `result` fields are cross-contaminated between sibling examples exactly as
descriptions were (hand-verified: `Tirthaji_Vedic_Math_sa_172` ex1 result `x=-5/12` is ex0's
answer). 297 templates were refused for damage in that layer. See the `legacy-bank-anatomy`
memory. **For the 522 "repaired", a description that faithfully narrates a contaminated result
is now fluent and wrong.**

**The audit found the regression it was hunting** (`_audit.json`, 5 shards, 235 templates): 0 corruption, but
**13 fluent-but-wrong descriptions (5.5%)** — the worst (`Number_Sense_sa_243`) turned a hedged
statement about induction in Peano arithmetic into a confident false claim and propagated it
into a new common_mistakes entry. Also: 68 steps still misaligned (mostly in untouched
"unrepairable" content), 1 weak unrepairable call (`Bird_sa_16` could have been re-narrated),
and **`key_reminders` was never touched — 2,357 stringified `{'point': ...}` entries remain**.

## Recommendation on file
Do not adopt wholesale. Use the 297 `unrepairable` refusals as a verified demotion list.
Prefer regeneration from verified sources (T2 patterns; the 348 corpus-converted templates in
`../converted/`) over further repair of this bank. Decision owner: RAG chat + project owner.
