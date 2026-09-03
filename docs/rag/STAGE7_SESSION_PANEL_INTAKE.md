# Stage 7 — session-panel intake (interim judge backend)

**Decision owner:** Speed Gym RAG (stage 7 is my gate) · **Date:** 2026-09-03
**Question put to me:** accept coordinator session-panel verdicts onto the trust ladder now, or hold stage 7 for the configured `glm-5.1 / kimi-k2.6 / deepseek-v4-flash` trio?

## Decision: ACCEPT — but capped at SANDBOX. Never TRUSTED.

Session panels may promote `QUARANTINED → SANDBOX`. They may **not** promote to `TRUSTED` or `LIVE`. That rung waits for the configured trio.

### Why accept

Adversarial session panels have *demonstrated* efficacy on this exact content. They found defects nothing else did: two dhvajanka templates with correct answers and abandoned derivations, and three teaching defects in my own new T2 patterns (an incomplete complement rule, an unstated write instruction, degenerate difficulty ladders) — none of which arithmetic checks, the auditor, or KaTeX caught. Holding the gate closed keeps the entire generated tier invisible to learners while discarding a review signal that is provably better than nothing.

### Why cap at SANDBOX

The configured trio's value is **cross-family independence**: three different model families fail differently, so 2-of-3 agreement means something. A panel of sub-agents sharing one base model has *correlated* blind spots — lens diversity reduces this but cannot remove it. A same-family panel that is confidently wrong about a Vedic technique will be wrong three times in the same direction.

SANDBOX is precisely the rung designed for this: capped exposures, and it **never feeds BKT mastery or mock exams**. So an interim verdict that turns out wrong costs a learner a questionable practice item — it cannot corrupt the mastery model or a mock score. That is the honest ceiling for a deviating judge backend, and it unblocks serving without overstating what was verified.

Anything a session panel *rejects* is quarantined normally — a fail verdict needs no special warrant, because rejecting content is the safe direction.

## Population order (and a design change worth making)

1. **Nightly generated pool first.** It is 100% blocked today, so it carries all the unblock value, and its quality is mine to fix at the generator when a verdict comes back bad.
2. **Then a 60-item stratified sample of the 776 static `trusted_candidate`s** — *not* all 776. Those are already served as Tier-1 `static_verified`, so judging them is a quality question, not an unblock. Sample first to estimate the defect rate; if it is low, judging all 776 is waste, and if it is high, that is itself the finding.

**Judge patterns, not instances.** T2 items from one pattern share a walkthrough skeleton with different numbers, so 400 verdicts on near-identical items buy almost nothing over one verdict per `(pattern, level)`. Intake therefore accepts `target_kind: "pattern"`, and items inherit their pattern's verdict, on two conditions: every item must already have passed deterministic stages 1–6 individually, and each run must submit a small random spot-check of instances to detect drift between the judged skeleton and what is actually being emitted. This is a deliberate deviation from the config's per-item stage 7, made because the population is template-instantiated; it is recorded per verdict.

## Verdict format

JSONL at `data/factory/verdicts/stage7_<batch>.jsonl`, one object per target:

```json
{
  "target_kind": "pattern",
  "target_id": "urdhva_2x2@L3",
  "judge_backend": "claude-session-panel",
  "panel": [
    {"lens": "sutra-fidelity", "verdict": "pass", "note": "..."},
    {"lens": "learner-followability", "verdict": "pass", "note": "..."},
    {"lens": "trap-realism", "verdict": "fail", "note": "..."}
  ],
  "consensus_rule": "2_of_3",
  "result": "pass",
  "judged_at": "2026-09-03T00:00:00Z",
  "spot_check_ids": ["t2_urdhva_2x2_L3_ab12cd34ef56"]
}
```

Requirements the intake enforces, rejecting the verdict otherwise:
- **at least 3 distinct lenses**, and lens names must differ — redundant lenses are not a panel;
- `result` must actually follow from the panel votes under `consensus_rule` (an intake that trusts a stated result would let a mislabelled verdict through);
- `judge_backend` must be present — provenance is what makes the planned re-judge mechanical;
- `target_kind: "pattern"` requires `spot_check_ids`.

Lenses should be genuinely distinct and, for sutra content, **grounded in the verbatim book chunks** (`data/factory/chunks/`). That grounding is what made the earlier reviews catch real errors rather than produce plausible prose.

## Re-judge plan

Every promoted item records `judge_backend` and `stage7_interim: true`. When the trio comes online, re-judge everything carrying `claude-session-panel`; items the trio fails are demoted to QUARANTINED, and the disagreement rate between the interim panel and the trio is itself a measurement worth having — it tells us how much a same-family panel can be trusted next time.
