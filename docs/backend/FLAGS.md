# Feature flags & kill-switch (block 3)

Code: `services/api/app/flags.py` (service), admin routes in `routers/admin.py`,
seeds in `db/postgres/60_fixes.sql` and `125_billing_flags.sql`, tests in
`tests/test_flags.py` and `test_admin.py`.

**Why it exists.** Two promises depend on it: Phase-2 features ship code-complete
but DARK until a coordinated flag flip (not a redeploy), and any feature or the ad
engine can be killed within seconds during an incident.

## Semantics

- A flag is ON for a user when `enabled` AND (`rollout_pct` = 100 OR the user's
  stable bucket < `rollout_pct`). Bucket = SHA-256(`user_id:flag`) mod 100, so a
  learner stays in or out of a rollout across requests and processes.
- Anonymous / server-side callers only see full rollouts as on.
- Unknown flag = off. Only KNOWN flags can be set (`POST /api/admin/flags/{name}`
  is 404 for anything not seeded), so nobody creates a flag nothing reads.
- Reads: Redis snapshot of the table (TTL 5 s) → process-local fallback (same TTL)
  → Postgres on miss. A database failure answers "everything off" and is not
  cached, so recovery is immediate. Fail closed = dark.
- Flipping a flag invalidates local + Redis caches: visible on the next request in
  that process, within 5 s everywhere.

## Surfaces

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /api/config` | none | states only (`{flag: {enabled, rollout_pct}}`, `degraded`); the client reads it at session start; answers during an incident even with an expired token |
| `GET /api/admin/flags` | admin | full table incl. description / updated_by |
| `POST /api/admin/flags/{name}` | admin | `{enabled, rollout_pct?}` — the Phase-2 activation and the emergency kill-switch are the same call |
| `GET /api/admin/kpi`, `POST /api/admin/kpi/refresh` | admin | KPI matview read / on-demand refresh (Celery refreshes every 15 min) |
| `/api/admin/content/trust*` | admin | trust-ladder list/detail/override over `problem_health_scores`, reason required, audited |

In code: `await flag_enabled("name", user_id)` for a check, or
`Depends(require_flag("name"))` on a route — dark features answer **404**, so the
response never confirms what is being dark-launched.

## Seeded flags

Phase-2 (dark): `boss_battle`, `relay_race`, `tournament`, `virtual_hubs`,
`location_gamification`, `irt_3pl_live`, `glicko2_live`, `dina_live`, `hirt`,
`thompson_mab`, `churn_gbt`. Kill-switches (on): `ad_engine` is OFF until the ad
engine ships; `billing_checkout` ON. Block-5 gates: `social_friends`,
`social_leaderboards`, `social_ghosts`, `social_taunts`, `daily_challenge` ON;
`social_clips` and `referral_ladder` dark until their copy / verification gates land.
COPPA kids mode is NOT a flag: compliance is not optional.
