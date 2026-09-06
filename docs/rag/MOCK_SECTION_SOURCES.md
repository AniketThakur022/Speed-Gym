# Mock-exam sections — what the corpus can actually serve

**Workstream:** Speed Gym RAG · **Date:** 2026-09-06
**Builder:** `factory/mocks/section_pool_map.py` → `data/mocks/pools/SECTION_SOURCE_MAP.json`
**Consumes:** `data/exports/vmsg_questions_v1.jsonl` · **Binds into:** `services/api/app/mocks/sources.py`

Backend's mock engine is pool-independent: each blueprint section names a pool tag, and six of the seven tags are unbound, so those sections answer 503. This is the supply side of that decision.

## Two corrections to the proposed contract

**`taxonomy.skill_key` cannot be the pool-membership join.** It resolves on 5,389 of 12,984 pool-eligible questions — **41.5%**. Joining on it would silently discard 58% of playable, keyed content, and the discard is not random: verbal and DI/LR resolve far worse than quant, so the sections that are already short would lose the most. Membership is decided by **book + chapter**; `skill_key` rides along as the contract's optional `skill` field and as BKT attribution where it happens to resolve. A question with no `skill_key` is still a perfectly good mock question.

**The shared `quant` tag should be split per blueprint.** One tag serves CAT QA, GMAT Quant and GRE Quant. Those are not interchangeable, and the split is what exposes the real gap: of 7,075 native quant questions, **CAT has 5,349, GRE has 1,726, and GMAT has 0**. Under one tag that reads as "ample"; split, GMAT quant is absent.

## Supply, graded on native material

Supply is graded on questions from books written for that exam. A section served entirely by another exam's material is reported as absent-with-a-cross-exam-option, not as well supplied — the count can be fine while the instrument is wrong.

| tag | need/mock | native | cross-exam | verdict |
|---|---|---|---|---|
| `cat_dilr` | 20 | 1,891 | 212 | **ample** — Sinha LRDI 1,231 + Arun Sharma DI/LR 660 |
| `quant` | 27 | 7,075 | — | **ample**, but see the split above |
| `gre_verbal` | 27 | 787 | — | **ample** — 5 lb 590, ETS verbal 150, ETS OG 47 |
| `gmat_verbal` | 23 | 36 | — | **thin** — one mock, and a second attempt repeats most of it |
| `cat_varc` | 24 | **0** | 271 | **absent natively**; GRE RC would make it ample |
| `gmat_di` | 20 | 0 | 0 | **absent** |
| `gre_awa` | 1 | 0 | 0 | **absent** |

## What cannot be served, and why substitution is refused

- **`gmat_di`** — GMAT Data Insights has no source in the corpus. Data sufficiency, multi-source reasoning, two-part analysis and table analysis appear in no book here. CAT DI is not a substitute: data sufficiency asks whether a question *can* be answered, which no CAT DI item does. Serving CAT DI under this tag would produce a score the learner reads as a GMAT Data Insights score.
- **`gre_awa`** — zero essay prompts exist anywhere, verified by scanning every question of all 4,805 corpus records for the AWA task wordings. The section is not auto-scored so it needs only a prompt, but it needs one.
- **`cat_varc`** — no CAT verbal book exists in the corpus. GRE Reading Comprehension and Logic-Based RC transfer reasonably and are offered as an explicit cross-exam binding. GRE **Text Completions and Sentence Equivalence are declined**: they are GRE-format items a CAT candidate has never seen. CAT's own para-jumble and para-summary types are in no book here and cannot be served at all.

## Two binding cautions

- **`arun_sharma_di_lr` (660 questions) must wait for extraction's vision pass.** Every question in it carries a figure or stimulus, and its pages have no text layer — this is the book whose 466 pages sit in the vision queue. An un-rendered row is a question about an invisible chart.
- **`bird_basic_engineering_math` (1,094) and `hall_knight_higher_algebra` (817) are declined for mocks.** Correct mathematics, wrong instrument: no admissions test asks these, and Hall & Knight runs well above CAT/GRE/GMAT level. They remain fine for practice.

Nothing here binds anything. Binding is a `sources.py` change and waits on the owner's serving-path decision.
