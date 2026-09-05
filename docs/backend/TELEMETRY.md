# Telemetry ingest — registry, 4-path write, sampling policy

Block 2 of the Phase-1 directive. Code: `services/api/app/telemetry.py` (registry +
policy), `services/api/app/routers/sync.py` (ingest), tests in
`services/api/tests/test_telemetry.py` and `test_sync.py`.

## The rule

**Psychometric events are never sampled.** Not at 10k DAU, not at 10M. This is the
architecture doc's Risk #4 reconciliation (§11.3): sampling attempts computes BKT on
a tenth of the evidence and produces P95 ≈ 33pp / P99 ≈ 69pp mastery error.

The recovered v5.2 telemetry spec (§8.1) contradicts this — its sampler thins
`problem_attempt`, `step_check` and `hint_used` to 10% above 10k DAU. **The v5.2
sampler is superseded and must not be ported.** It also hashed with Python's
per-process-salted `hash()`, so the same event could be kept by one worker and
dropped by another.

| Class | Sampling | Members |
| --- | --- | --- |
| psychometric | never | problem_attempt, problem_solved, problem_failed, trap_triggered, bkt_state_snapshot, session_start/end, calibration_completed, phase_transition, skill_level_up, fatigue_index_computed, clr_mode_activated, behavioral_profile_computed, + phase-2 lr/di/passage set completions |
| conversion | never | subscription_*, trial_started, referral_*, onboarding_begin, goal_set, auth_complete, topic_browser_session_* |
| ops | never | buffer_overflow, sync_failed, offline_sync_complete |
| ui | 10 %, only when DAU > 10,000 | page_view, hint_used, hint_requested, topic_selected, widget_expanded, dashboard_loaded, problem_loaded, profile_viewed, help_viewed |

Sampling is SHA-256 over `user_id:event_id`, so a replayed batch reproduces exactly.
DAU comes from the `kpi_dashboard_core` matview; any read failure yields 0, which
**disables** sampling. Losing a little UI volume is the safe direction.

## Numbering caveat

The RFP names these TEL-01..TEL-33. The RFP was never recovered and the ids appear
nowhere in the v5.2 corpus, so the registry's `tel_hint` is a stable ordinal over
the taxonomy in `telemetry_architecture.md` §9.2 — not a citation. If the RFP is
recovered, map the ids in; do not renumber the ordinal.

## Unknown event types

A client shipping an event ahead of the registry is **ingested at 100 %** into
`raw_events` with `metadata._registry_unknown = true`, and the type is echoed in the
sync response's `unknown_event_types`. Dropping would lose data; silent acceptance
would hide the registry gap.

## The four write paths (unchanged, block 2 makes them registry-aware)

- **A** `raw_events` — immutable, `event_id` ON CONFLICT DO NOTHING (resend of a
  partial flush is a no-op).
- **B** aggregates — `sessions` closed on `session_end`.
- **C** `sync_outbox` — graph writes queued in the same transaction, drained by the
  worker every 30 s; Neo4j being down delays the edge, never loses the ledger row.
- **D** `bkt_state_snapshots` — rollup on `session_end` when the client sends
  `technique_states`.

Sync response fields: `accepted`, `duplicates`, `sampled_out`, `psychometric`,
`unknown_event_types`, `entitlement` (HMAC, 3-day grace).

Admin read: `GET /api/admin/telemetry/registry` returns the full table.
