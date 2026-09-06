# Social, gamification & COPPA kids mode (block 5)

Code: `services/api/app/social/` (policy, achievements, taunts, xp, guard, daily),
routers `social.py` and `dashboard.py`, hooks in `internal.py` (match complete) and
`sync.py` (XP/streaks, kids minimisation), worker `tasks/social.py`, game server
`bot.ts`/`index.ts` (account-level bot block). Migration `130_social.sql`. Tests:
`test_social_policy.py` (pure), `test_social_api.py`, `test_dashboard_api.py`,
`apps/game-server/tests/kids-gate.test.ts`.

Every surface sits behind a flag (`social_friends`, `social_leaderboards`,
`social_ghosts`, `social_taunts`, `daily_challenge` live-but-killable; `social_clips`
and `referral_ladder` dark). **Kids mode is not a flag.**

## Dashboard — the frozen APK contract, finally implemented

`GET /api/v1/dashboard/{topics,radar,metrics,stats,streak,events,leaderboard,recent-activity}`
with the exact shapes in `apps/web/src/lib/types/dashboard.ts`. The APK only had
mocks for these, which is why nobody noticed they were missing.

| Route | Source |
| --- | --- |
| topics | latest `bkt_state_snapshots.technique_states` → `{name, value=pLearned×100}` (top 8) |
| radar | last-30-day `problem_attempt` events: Speed (median time), Logic (accuracy), Stamina (problems/session ÷ 25), Focus (share of attempts ≤ 1.5×median), Memory (longest streak ÷ 7), Reflex (p25 time) — all 0..1, zeros for a new learner |
| metrics | Action Delay = median ms, Focus Density = accuracy % |
| stats | accuracy %, questions (all-time), percentile (XP rank), speed (avg s) |
| streak | `{current, xp, days[Mon..Sun], labels}` |
| events | Daily Challenge until submitted; pending friend requests |
| leaderboard | XP top 10 + you, behind the anxiety guard |
| recent-activity | last 5 `session_end` events |

### Event metadata contract (what block 8's client must send)

`problem_attempt.metadata`: `{skill, problem_id, is_correct, time_ms, domain, difficulty?, trap_id?}`
(`technique_id`/`total_time_ms` accepted as aliases). `session_end.metadata`:
`{problems_attempted, problems_correct, session_type, domain, technique_states}`.
Added to `docs/backend/TELEMETRY.md`.

## XP, streaks, achievements

Awards are idempotent on `(user, reason, ref)` — a replayed sync batch or a redelivered
match result pays once. Rules: correct practice attempt 10, session 25, streak day 20,
duel win 50 / loss 15 (halved when a bot was in the match, mirroring 0.5× ELO), daily
challenge 50 + 10/correct, ghost race win 30, friend added 10. Level = xp ÷ 500 + 1.
Streaks are UTC calendar days; a skipped day ends the streak.

Achievements are Appendix A of the multiplayer engine spec verbatim (28 keys);
Phase-2 ones carry `phase_2_activation` and their flag so the client hides them while
dark.

## Friends, QR pairing, ghosts, clips, taunts, daily challenge

- **Friends**: request by email → addressee accepts/declines/blocks; one row per pair.
  **QR pairing**: 300-s one-time HMAC-signed code in Redis; scanning your own code is
  rejected without consuming it.
- **Ghosts**: a recorded solo run (problem ids + per-problem times + correctness; no
  identity), TTL 30 days, private by default; public ghosts are anonymous to
  non-friends; a race is won by more correct, or equal correct and faster.
- **Clips** (dark): dual consent — the opponent must consent; opponents are always
  anonymised ("Opponent"); a bot opponent needs no consent and is never revealed.
- **Taunts**: catalogue from PHASE_B_DESIGN §7.2; chosen at match completion, stable
  per match, gated by SOC-15 (Sprinter every 3, Perfectionist every 5,
  Deliberate/Rebuilder never; unnamed clusters every 4 — an assumption) and SOC-16
  (off after 3 straight losses, off under age 10).
- **Daily challenge**: 10 problems chosen as a pure function of the date over the
  servable pool (same guards as practice: skill edge, verified question+answer, not
  quarantined); answers stored server-side and never sent; one attempt per day;
  score = 100/correct + a speed bonus only on a perfect run; **never bots**.
- **Leaderboard anxiety guard** (§5.4): hidden for 60 s after a match; from the latest
  BKT snapshot, mostly-fractured → hidden, mostly-fragile → percentile only; kids →
  percentile only. "In an active match" lives in the game server's memory.

## COPPA kids mode (FAM-05 / SEC-08)

Age < 13 (the account's age, set by the parent at seat creation). `GET /api/v1/social/policy`
returns the per-user policy: ads off, bots off, taunts off, timers suppressed, session
cap 10 min (parent override up to 20 via the seat), tracking minimised, leaderboard
percentile-only, clips off, friends parent-managed, parental consent required.

Enforced server-side, not just advertised: the game server refuses bots when the
account service says `bots_allowed=false` (and still refuses unknown ages); sync never
stores UI-class telemetry for a child and strips device/IP identifiers from what it
keeps; children cannot send or receive friend requests, generate QR codes, make
clips, or publish ghosts; match completion never selects a taunt for them. Verifiable
parental consent is the paid-card seat creation (`family_seats.parental_consent_at/by`).

## Deferred

Parent-managed friend approval for children (a `/family` endpoint), the referral
ladder REF-01..10 (flag `referral_ladder`, dark), clan/hub achievements (Phase 2).

## Review fixes (blocks 5–9 adversarial pass, 2026-09-06)

- **A clip never reveals a bot opponent.** `internal.py` stores `user_id = NULL`
  for a bot row, so marking a bot-opponent clip instantly `ready` with
  `opponent_consent: true` made the create response a reliable bot oracle —
  the one thing that must not cross the API boundary. Every clip now starts
  `pending` with `opponent_consent: false`; a bot simply never consents, which
  is indistinguishable from a human who declines. Opponent stats are populated
  in both cases (omitting them would leak the same bit) and come from the
  resolved opponent rather than `others[0]`.
- **A future device clock cannot freeze a streak.** `client_timestamp` is
  unvalidated device time; a date set forward wrote a future
  `streaks.last_activity_date`, after which the backfill guard treated every
  real day as older — the streak froze permanently and streak XP never paid
  again. Activity days are clamped to today at both the sync edge and in
  `xp.record_activity_day`, and `streak_state` self-heals a row already poisoned.
- **The anxiety guard holds on every ranking surface.** `/dashboard/stats`
  served the raw XP percentile with no guard call, so a mostly-FRACTURED learner
  saw the number on the same screen where `/dashboard/leaderboard` correctly
  returned `[]`. `hidden` now zeroes the percentile too.
- **An ungraded attempt is not a wrong one.** Server-checked (`server_sympy`)
  attempts arrive with `is_correct: null`; SQL folded NULL in as wrong, so a
  perfect session reported 70%. Accuracy in `/stats`, `/metrics` and `/radar` is
  computed over graded attempts only, `questions` still counts all of them, and
  `/recent-activity` scores out of `attempted - problems_deferred`.
