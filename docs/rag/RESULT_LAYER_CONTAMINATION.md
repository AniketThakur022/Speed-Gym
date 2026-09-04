# The `result` layer is contaminated too — and what it does to the repair plan

**Workstream:** Speed Gym RAG · **Date:** 2026-09-05
**Trigger:** the legacy-bank repair pass reported that cross-example carry-over reaches `result`, not only `description`, invalidating the premise that the operation/result layer is safe ground truth for re-narration.

## Verified independently, and it is real

`Tirthaji_Vedic_Math_sa_172`, read directly: example 1's `answer` is `x = 1/12` and its step-3 `operation` correctly reads "Solve for x: x = 1/12" — but that step's **`result` is `x = -5/12`, which is example 0's answer**. Example 2's step-2 and step-3 results are verbatim copies of example 0's step-1 expression. Operations are right; results are borrowed from a sibling.

## Population scale: 109 of 485 multi-example templates (22.5%)

`factory/audit/cross_example_bleed.py` measures it. Unlike every other detector attempted here, this one is worth building because **the defect is literal copying**: a step result character-identical to content owned by a different example, on a different problem, is copied by construction. It proxies nothing semantic.

Hand-verified beyond the reported case: `Bird_Engineering_Math_sa_103` example 1 step 1 displays `4x - 3y = 18` — example 0's equation — while example 1's own problem is `3x - 2y = 12`.

Two honest limits on the number:
- The check flags **both** copies of a shared string and cannot tell which example is the victim, so the 586 step count over-states. Per-template adjudication is still needed.
- The unambiguous sub-case — a step result equal to a *sibling's answer* — occurs once. Most bleed is shared intermediate expressions, which is suspicious across different problems but not self-evidently wrong.

**It is not a triage tool.** Judged templates with bleed fail 10/10 versus 43/50 without, but at an 88.3% base rate chance predicts 8.8 of 10. That is the same trap as the earlier `sibling_carryover` 14/14: precision numbers are meaningless at this base rate. Its value is *scope* — evidence at population scale that literal copying reaches the protected layer — not selection.

## Consequence for the repaired candidates

Descriptions rewritten to faithfully narrate a contaminated `result` are fluent, self-consistent and wrong — harder to detect than the mess they replaced. The repair pass names this risk itself and did not measure its frequency. So repaired templates get no credit for having been repaired: they enter stage-7 on the same footing as everything else, and a lens should check **result-versus-operation coherence** specifically, since `operation` is the layer that stayed sound in every case examined.

## Re-opening my `_python_audit_status` call — a correction, and a defence

I told this project to ignore the legacy `_python_audit_status` and characterised it as "the broken pre-loss verifier". Measured: **806 ALL_FAILED, 1 ALL_PASSED, 108 null.**

- The **characterisation was probably wrong**. That verifier checked step *results*, and results are now shown to be contaminated at scale. It may have been reporting a real, near-universal defect rather than malfunctioning. I should not have called it broken on the strength of an implausible-looking rate alone.
- The **operational call stands**. A field with 806 fails and 1 pass carries no per-item information: there is nothing to rank, and no contrast to validate against the 60 verdicts. Using it for trust decisions would have quarantined essentially the whole bank on a signal that cannot discriminate.

Both things are true, and the distinction matters: *aggregate truth* and *discriminative power* are different properties. The field was plausibly honest and still unusable.

## Where this leaves remediation

It strengthens the case already made: regeneration from verified sources beats repairing this bank. Repair assumed a sound layer to build on; that assumption is now falsified for `result`, sound only for `operation`, `answer` and `problem_statement`. The 184 unrepairable refusals are the repair pass's most valuable output — a verified list of templates whose damage reaches the arithmetic.
