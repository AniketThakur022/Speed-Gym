-- ============================================================================
-- VMSG migration 120 — billing (Phase-1 block 4)
-- Razorpay PRIMARY (owner decision 2026-09-04), Stripe secondary. Subscriptions
-- live; family plans (parent anchor + ≤3 child seats, 100/80/60% curve);
-- webhook idempotency ledger; checkout intents that bind a provider reference
-- back to the user/tier/seats the client asked for.
-- ============================================================================

-- ── subscriptions: provider-neutral money + lifecycle columns ──────────────
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'INR';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS amount_minor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS seats_count SMALLINT NOT NULL DEFAULT 0
    CHECK (seats_count BETWEEN 0 AND 3);
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_plan_ref TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMPTZ;

-- One live subscription per user. 'cancelled'/'unpaid' rows are history and
-- do not block a fresh checkout.
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_one_live_per_user
    ON subscriptions(user_id) WHERE status IN ('active', 'trialing', 'past_due');

-- ── checkout intents: what the client asked for, before the provider answers ─
CREATE TABLE IF NOT EXISTS checkout_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('razorpay', 'stripe')),
    tier TEXT NOT NULL CHECK (tier IN ('pro', 'bundle_2', 'bundle_3')),
    seats_count SMALLINT NOT NULL DEFAULT 0 CHECK (seats_count BETWEEN 0 AND 3),
    currency VARCHAR(3) NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    usd_inr_rate NUMERIC(10, 4),
    trial_days SMALLINT NOT NULL DEFAULT 0,
    provider_ref TEXT,                 -- razorpay subscription id / stripe checkout session id
    provider_plan_ref TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'failed', 'expired')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_checkout_intents_user ON checkout_intents(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_checkout_intents_provider_ref
    ON checkout_intents(provider, provider_ref) WHERE provider_ref IS NOT NULL;

-- ── payment events: webhook idempotency + audit (PAY-03) ────────────────────
CREATE TABLE IF NOT EXISTS payment_events (
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    user_id UUID,
    handled BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (provider, event_id)
);
CREATE INDEX IF NOT EXISTS idx_payment_events_user ON payment_events(user_id, received_at DESC);

-- ── family: child accounts are real users with a parent anchor ──────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type VARCHAR(10) NOT NULL DEFAULT 'standard'
    CHECK (account_type IN ('standard', 'child'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_users_parent ON users(parent_user_id) WHERE parent_user_id IS NOT NULL;

ALTER TABLE family_seats ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
