# PWA on the live API (block 8)

`NEXT_PUBLIC_API_MOCK=false` + `NEXT_PUBLIC_API_URL=https://<api>` puts the recovered
client on the rebuilt backend with zero route renames (api-contract-v1).

## What block 8 adds

- **Offline practice queue** (`src/lib/telemetry-core.ts` pure, `src/services/telemetry.ts`
  wiring, Dexie v3 `eventQueue`): every practice event is queued with a client
  `event_id` and flushed to `POST /api/v1/sync` in batches of ≤200 on online /
  visibility / a 30-s timer. A 2xx drops the batch (duplicates, sampled-out and
  minimised are the server's business); failures bump a retry count; psychometric
  events are never dropped, a poison UI event is after 20 retries. Tests:
  `apps/web/tests/telemetry-queue.test.ts`.
- **Practice page** emits the metadata contract (TELEMETRY.md): `session_start`,
  `problem_attempt` `{skill, problem_id, is_correct, time_ms, domain, difficulty,
  feeds_mastery, answer_check, hint_level}`, `session_end` `{problems_attempted,
  problems_correct, technique_states}`; plus a "Need a hint?" widget on
  `POST /chat/query` (hints only; the server withholds answers).
- **Entitlement** (`src/lib/entitlement.ts`, `stores/entitlement-store.ts`): the sync
  response's signed token is persisted; the client enforces `expires_at + grace_days`
  locally (the HMAC secret never leaves the server; tampering only breaks the tamperer).
- **Session boot** (`app/session-boot.tsx`): starts the flush loop and reads the
  server-authoritative kids policy into `stores/policy-store.ts`.
- **Screens**: dashboard hub (replaces the redirect shim), Plans (Razorpay Checkout
  primary, Stripe hosted secondary; the handler result goes to `/billing/checkout/verify`
  and the returned entitlement is stored — PAY-04), Mock Center (configure → take →
  submit → scorecard, offline-honest labels), Leaderboard + Daily Challenge, Friends
  (+ one-time QR pairing; parent-managed on kids accounts).
- **Capacitor shell**: `capacitor.config.json` (appId `com.amhsolutions.examarena`,
  `webDir: out`). `npm run cap:sync` builds the static export and syncs;
  `cap:android` / `cap:ios` add the platform folder on first run (generated, not
  committed) and open the IDE. Native builds need Android Studio / Xcode on the machine.

Not done here: Razorpay's copy for the 409-on-resume, service-worker precaching of
practice sessions (the practice screen already needs one downloaded session), ads.
