# Static bank: walkthroughs are unreliable at scale

**Workstream:** Speed Gym RAG (content contract owner) · **Date:** 2026-09-04
**Evidence:** `data/factory/verdicts/stage7_static_sample_20260904.jsonl` — 60-item panel sample, **53 fail (88.3%)**, 42 unanimous, 2 unanimous passes. Applied to the ladder: 53 quarantined, 7 sandboxed.

## The finding is credible

I verified two of the panel's specific claims against the bank directly rather than accepting the rate:

- **`Bird_Engineering_Math_sa_110`** is labelled technique `substitution`, but both examples eliminate — step operations read "Subtract equation (1a) from (2a)" and "Divide equations to eliminate R0". Its own `key_reminder` says the easier route is "to eliminate R₀ by division". Confirmed mislabel.
- **`Vedic_Made_Easy_sa_36`** carries `key_reminders` citing `b = 2` and `(a − b) = 70`, which implies a = 72. Its two examples are 53² and 67². That configuration appears in **no example in the template**. Confirmed carried-over metadata.

The coordinator's calibration also holds: trap-realism alone failed 57/60, but **51 of the 53 failures carry an independent method or followability defect**, so the rate is not a metadata artifact, and failures are uniform across books rather than concentrated in one bad source.

With n=60 of 823, the population walkthrough-defect rate is very likely above 75%.

## What this does and does not mean

The failures are **walkthrough** defects, not **answer** defects. Backend's Tier-1 label `static_verified` certifies question + answer only, and it is holding correctly — this finding does not contradict it. It confirms the caveat attached to that label when it was defined: *answer-verified is not solution-verified.*

So the questions and answers remain usable. What is unreliable is the teaching around them.

## Recommendation: suppress the static walkthrough, keep the content

Proportionate action, in preference order:

1. **Serve Tier-1 static content without its walkthrough** — question and answer only — until remediation. This preserves 766 usable items rather than destroying them, and withholds only the part the evidence indicts. In frontend terms this means Tier-1 static items should not back the step-revealing render modes.
2. **Source step-by-step teaching from generated content instead.** This inverts the original assumption that static content is the trustworthy tier and generated content is provisional. Generated T2 walkthroughs are now the *only* walkthroughs that have passed an adversarial panel (18 pattern-level targets at SANDBOX), and their defects — when panels found them — were fixable at the generator in a single change that repaired every instance. A static-bank defect must be repaired template by template.
3. **Treat this as an argument for T1/T2 coverage growth**, since generated coverage is the practical path to trustworthy walkthroughs at scale.

Quarantining the whole bank would be the wrong call: it discards verified questions and answers over a defect confined to their explanations.

## Why a cheap scanner cannot close this gap

A deterministic scan for descriptions citing numbers absent from their own example finds 80 templates (9.7%). The panel finds 88.3%. **The gap is the finding**: the defect is mostly semantic — prose carried over from a sibling example, correct-sounding and number-free.

I built the suggested detector (named technique versus the verb/object vocabulary of its own steps) and it **fails on the case it was designed from**. `Bird_sa_110` contains "substitut" 4 times — largely boilerplate like "obtained from substituting the given values" — against 3 elimination markers, so a vocabulary count cannot separate *the word appearing* from *the method being used*. Result kept at `data/factory/technique_mismatch_scan.json` as a documented negative, not shipped as coverage: a detector that misses its own founding example would give false confidence about the population.

Practical consequence: for this class, panel adjudication is the measurement instrument, and deterministic scanning can only supply candidates. The `false_root_claim` class remains the exception — it is exact, because the transformed polynomial's constant term *is* f(r).
