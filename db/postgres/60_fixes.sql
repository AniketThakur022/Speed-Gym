-- ============================================================================
-- VMSG migration 60 — RFP v7.2 reconciliation (mirrors the lost build's
-- 60_fixes.sql: tiers, Razorpay, feature flags, family accounts, auth tokens)
-- Tier enums are already correct in 10/30 (FIX #1 baked at authoring time);
-- this migration adds what the delivered v2/v5 schemas never had.
-- ============================================================================

-- ── Razorpay (PAY-01/02: Stripe + Razorpay dual processors) ────────────────
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS razorpay_customer_id TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS razorpay_subscription_id TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'stripe'
    CHECK (provider IN ('stripe', 'razorpay'));
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_razorpay
    ON subscriptions(razorpay_subscription_id) WHERE razorpay_subscription_id IS NOT NULL;

-- ── Feature flags (Postgres-backed, Redis-cached; Phase-2 dark launch) ─────
CREATE TABLE IF NOT EXISTS feature_flags (
    flag_name VARCHAR(60) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    rollout_pct SMALLINT DEFAULT 100 CHECK (rollout_pct BETWEEN 0 AND 100),
    updated_by VARCHAR(100),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO feature_flags (flag_name, enabled, description) VALUES
    ('boss_battle',          FALSE, 'Phase-2 game mode: Boss Battle (SOC-01..04)'),
    ('relay_race',           FALSE, 'Phase-2 game mode: Relay Race (SOC-05/06)'),
    ('tournament',           FALSE, 'Phase-2 Swiss tournaments (SOC-07..09)'),
    ('virtual_hubs',         FALSE, 'Phase-2 Virtual Hubs (SOC-11..14)'),
    ('location_gamification',FALSE, 'Phase-2 location features (LOC-GAM-*)'),
    ('irt_3pl_live',         FALSE, 'IRT-3PL routes learners (shadow until >=200 resp/item)'),
    ('glicko2_live',         FALSE, 'Glicko-2 routes LRDI (shadow until volume met)'),
    ('dina_live',            FALSE, 'DINA routes VARC (shadow until Q-matrix + N>=640)'),
    ('hirt',                 FALSE, 'Phase-2 hierarchical IRT'),
    ('thompson_mab',         FALSE, 'Phase-2 Thompson-sampling bandit'),
    ('churn_gbt',            FALSE, 'Phase-2 weekly churn GBT'),
    ('ad_engine',            FALSE, 'Ad engine master switch (kill-switch capable)')
ON CONFLICT (flag_name) DO NOTHING;

-- ── Family accounts (FAM-PRC-*: parent anchor + ≤3 child seats) ────────────
CREATE TABLE IF NOT EXISTS family_accounts (
    family_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS family_seats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES family_accounts(family_id) ON DELETE CASCADE,
    child_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    seat_number SMALLINT NOT NULL CHECK (seat_number BETWEEN 1 AND 3),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    discount_pct SMALLINT DEFAULT 100 CHECK (discount_pct IN (100, 80, 60)),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(family_id, seat_number)
);

-- ── Auth: refresh-token rotation with replay detection (SEC-01) ────────────
-- Demoed pre-loss: rotating refresh tokens; replay of a rotated token kills
-- the device session. Token value stored only as SHA-256.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    jti UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    device_fingerprint VARCHAR(128),
    issued_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    rotated_to UUID,                    -- successor jti after rotation
    revoked_at TIMESTAMPTZ,
    revoke_reason VARCHAR(50)           -- rotation_replay | logout | admin
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expiry ON refresh_tokens(expires_at);

-- ── Referral milestones (REF-01..04 ladder; 30 refs = offline queue) ───────
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS verification_evidence JSONB;

CREATE TABLE IF NOT EXISTS referral_milestones (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    verified_referrals INTEGER DEFAULT 0,
    milestone_level SMALLINT DEFAULT 0,  -- 0:none 1:+1 lane 2:offline queue 3:custom 4:lifetime
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
