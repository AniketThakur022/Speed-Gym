# Two panels, one tier — what the disagreement measured

**Workstream:** Speed Gym RAG · **Date:** 2026-09-06

Two stage-7 panels ran over the converted tier concurrently: the coordinator's stratified 60 (lenses grounding-fidelity / learner-followability / metadata-honesty) and mine over all 348 (grounding / followability / result-vs-operation coherence, plus a separate hint-ladder gate). Mine died on the session limit at 45 of 363 agents. The wreckage turned out to be more useful than the verdicts would have been.

## My partial run is not a result, and is not emitted as verdicts

48 templates completed, 47 pass / 1 fail. **That number measures my panel, not the content**, for three reasons, and the verdicts are recorded as a calibration artifact (`data/factory/verdicts/stage7_rag_partial_slice_20260906.json`) rather than fed to the ladder.

1. **It is one book.** Batches were ordered by `(book_title, id)`, so the 48 that finished are all *5 lb. Book of GRE Practice Problems* — 1 of the 10 books in the tier. The coordinator's 60 is stratified across all 10. A 98% pass rate on one book and a 53% pass rate across ten are not in contradiction; they are not the same population.
2. **The stage designed to catch false passes never ran.** My design put adversarial refutation *after* the panel, targeting passes specifically, on the reasoning that a false pass reaches learners while a false fail only withholds content. All 12 refuters died with the rest. So every "pass" above is a panel verdict that was never challenged — incomplete under my own contract.
3. **The panel was lenient, and I can show it.**

## Inter-panel agreement: 3 of 6, all in one direction

Six templates were judged by both panels independently, with different lens sets. They agreed on 3. **Every disagreement is mine passing what theirs failed**, and on inspection their evidence holds:

| template | mine | theirs | what they found |
|---|---|---|---|
| `conv_gre5lb_functionsformulasandsequences_69` | pass 3–0 | fail 3–0 | Stem truncated at "…is approximately" with **no answer choices**, and `answer: "(B)"` — an orphaned option letter pointing at nothing. A learner cannot attempt the item as posed. |
| `conv_gre5lb_numberproperties_14` | pass 3–0 | fail 2–1 | `visual_scaffold: {type: "number_line", config: {}}` — empty, so no number line exists, yet step 1 says "Record what the figure actually gives". |
| `conv_gre5lb_advancedquant_40` | pass 3–0 | fail 2–1 | Step 6 asserts the decisive comparison instead of showing it; a `common_mistakes` entry describes something the entry itself calls "awkward rather than wrong". |

The first two are squarely inside my own followability lens, which says to fail when a step "refers to a figure… not in the template" or when the item cannot be executed from what is on screen. It passed both. Named causes, so a re-run does not repeat them:

- **A leniency prior I wrote in.** My prompt said "a wrong fail withholds real content from learners… do not fail on style". Theirs was refutation-default. On borderline items that difference decides the vote.
- **No metadata lens.** Nothing of mine looks at `visual_scaffold`, difficulty, expected_time, or whether the answer label binds to an option. That is not a lens I judged worse — it is a lens I did not have.
- **Refutation placed last.** The correction mechanism was the first thing lost to the limit.

**This is the strongest evidence yet for the SANDBOX cap.** Two session panels on the same base model, differing only in lens set and prior, disagree half the time on shared items. That is exactly the correlated-but-variable behaviour the cap exists to hedge, and it argues the cap should stay until the configured trio is available.

## The hint-ladder finding, corrected

My panel reported 24 of 48 templates leaking the answer through hints. **That was my prompt's error, not a defect in the content.** I told judges the ladder is built from "operations 1 through n-1"; the implementation caps at `MAX_LEVELS = 3`, where level 1 is a framing hint, so **only steps 1 and 2 are ever shown**. The alarming examples sit at steps 4–6 and never ship.

Measured on the real shipping surface across all 348 (`data/factory/verdicts/hint_ladder_exposure.json`):

- **0 templates** where a shown value rounds to the answer while evading the redactor.
- **11 templates** where the redactor fires on a shipped hint — the answer is blocked to `▮`, so the hint degrades rather than leaks.
- 19 flagged by a "two shown values combine to the answer" check, **all coincidence** on inspection: answer 4 with 10 and 6 present, answer 0 with 7 and 7. The check is recorded as a measured negative, not shipped — the same false-positive trap as the precision-number detector discarded earlier.

**No confirmed answer leak in the hint ladder across the converted tier.** The narrow two-step surface is doing the work.

## Applied

The coordinator's 60 verdicts pass every intake check (0 rejected; panel ≥3, distinct lenses, consensus recomputed from votes rather than trusted) and are **applied**: 32 → SANDBOX, 28 → QUARANTINED, all `stage7_interim: true`. Ladder now 349 quarantined / 50 sandbox / 3 held.

Applied whole rather than narrowed to the 23 unanimous passes. The consensus rule was fixed at 2-of-3 in advance; tightening it after seeing the results would make the gate mean whatever the reader wants. SANDBOX never feeds BKT mastery or mocks, so a wrong pass costs one questionable practice item and is mechanically re-judgeable by the trio.

On the 46.7% defect rate: **treat it as a floor.** The independent panel on shared items was the more lenient one and demonstrably missed real defects, so the true rate is unlikely to be lower.
