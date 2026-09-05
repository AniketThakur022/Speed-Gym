# Billing — subscriptions, family plans, webhooks, entitlement

Block 4 of the Phase-1 directive. Razorpay is PRIMARY (owner decision 2026-09-04),
Stripe secondary for international cards. Code: `services/api/app/billing/`
(pricing, providers, state, entitlement), routers `billing.py`, `family.py`,
`webhooks.py`; worker `services/workers/worker/tasks/billing.py`; migration
`db/postgres/120_billing.sql`. Tests: `test_billing_pricing.py` (pure),
`test_billing_api.py` (API + webhooks against Postgres with faked providers and
REAL signature checks).

## Prices

RFP USD figures are the source of truth (SUB-01..04). INR is derived at the
configured `USD_INR_RATE` (default 84.0) at quote time, half-up to the paisa, and
frozen onto the checkout intent so a rate change never re-prices a sold plan.

| Tier | Lanes | USD | INR @84 |
| --- | --- | --- | --- |
| free | 1 | $0 | ₹0 |
| pro | 1 | $6.00 | ₹504.00 |
| bundle_2 | 2 | $9.60 | ₹806.40 |
| bundle_3 | 3 | $12.60 | ₹1,058.40 |

Paid tiers carry a 7-day trial (`TRIAL_DAYS`). Razorpay implements the trial as
`start_at` on the subscription (mandate authorised at checkout, first charge at
trial end); Stripe as `trial_period_days`.

## Family (FAM-PRC-*)

Parent anchor + up to 3 child seats. Parent pays full price; seats 1/2/3 cost
100/80/60 % of the tier price, billed as ONE amount on the parent's subscription.
Multiplier by seat count: 0→100 %, 1→200 %, 2→280 %, 3→340 %.

A child is a real user (`account_type='child'`, `parent_user_id`, age 8–17). Its
tier is **derived**: the parent's tier while the seat is active, free otherwise.
Every parent-subscription change and every seat toggle re-derives all children in
one statement. Children cannot check out or manage a family. Age < 13 is flagged
`kids_mode` for block 5 (COPPA) to gate on.

Adding/removing a seat re-prices with the provider (new Razorpay plan +
`PATCH /subscriptions`, or a new Stripe price on the subscription item).
Suspending does not re-price: it is a parental control, not a refund.

## Client surface (`/api/v1`)

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /billing/plans` | none | catalogue in USD + INR, providers available, seat curve |
| `GET /billing/subscription` | user | live subscription + signed entitlement |
| `POST /billing/checkout` | user | `{tier, seats_count?, provider?, currency?}` → intent + provider checkout payload |
| `POST /billing/checkout/verify` | user | Razorpay handler result; HMAC over `payment_id|subscription_id`; grants tier NOW (PAY-04) |
| `POST /billing/cancel` | user | cancel at period end; tier kept until the period closes |
| `POST /billing/resume` | user | undo a scheduled cancel (Stripe only; Razorpay answers 409) |
| `POST /billing/change` | user | move to another paid tier, seats kept and re-priced |
| `GET /family` | user | seats |
| `POST /family/sub-account/create` | parent | `{email, password, display_name?, age}` → seat + reprice |
| `POST /family/sub-account/override` | parent | `{child_user_id, status: active|suspended}` |
| `POST /family/sub-account/remove` | parent | free the seat, reprice down, child → free |

Errors: 503 when the chosen provider has no keys configured (never 501 now that the
decision is made); 402 when a free parent tries to add seats; 409 on a second
checkout while a subscription is live, or on a 4th seat; 403 for child accounts.

## Webhooks (server-to-server, outside `/api/v1`)

`POST /api/webhooks/razorpay` — `X-Razorpay-Signature` = HMAC-SHA256(raw body,
webhook secret). `POST /api/webhooks/stripe` — `Stripe-Signature: t=…,v1=…`, signed
payload `t.body`, ±300 s replay window, any matching `v1` accepted (secret
rotation). Both: 503 if the secret is unset (**an unsigned webhook is never
accepted**), 400 on a bad signature, 200 for every verified event so the provider
stops retrying. Idempotent on the provider event id via `payment_events`; a missing
Razorpay event-id header falls back to a body digest.

Status normalisation (provider → ours):

| ours | Razorpay | Stripe |
| --- | --- | --- |
| trialing | authenticated | trialing |
| active | active | active, invoice.paid |
| past_due | pending, paused | past_due, paused, invoice.payment_failed |
| unpaid | halted | unpaid |
| cancelled | cancelled, completed, expired | canceled, incomplete_expired |

**Tier grant rule:** `trialing`, `active`, `past_due` keep the tier (past_due is the
dunning/grace window); `unpaid` and `cancelled` drop to free immediately. One
function, `apply_subscription_event`, is the only path that changes a tier, used by
both webhooks and checkout-verify, so the processors cannot drift.

An event that cannot be tied to a learner (no subscription ref, no intent, no
user id in notes/metadata) is acknowledged with `handled=false` and logged — never
applied to a guessed account.

## Entitlement (SUB-10 / PAY-05)

`HMAC-SHA256(user_id:expires_at)` signed with `OFFLINE_TOKEN_SECRET`, returned on
every `POST /api/v1/sync` and on checkout-verify. `expires_at` is the real horizon —
the current period end (trial end while trialing) — not "now + 3 days", so a paid
learner offline for a week keeps Pro; the client applies `grace_days` (3) past it.
Children resolve through the parent anchor. A paid tier with no provider
subscription (admin grant, referral reward) is re-signed for one grace window per
sync. UX only: the server re-validates tier on every online action.

## Worker safety net (`billing.enforce_grace_and_expiry`, 02:00 UTC)

- `past_due` older than `BILLING_GRACE_DAYS` → `unpaid`, tier dropped, children synced.
- `cancel_at_period_end` whose period closed → `cancelled`, tier dropped.
- Overdue trials with no provider signal → counted, NOT downgraded (a webhook outage
  must not punish learners; the provider owns that transition).
- Pending checkout intents older than 24 h → `expired`.

## Not done here

Sticky webhook routing to the owner node (PAY-03) is a multi-node concern; Phase 1
runs one API node and the idempotency ledger makes replays safe. Referral ladder
and lifetime ad-free unlocks are block 5. Ad engine is unaffected (`ad_engine`
flag stays off).
