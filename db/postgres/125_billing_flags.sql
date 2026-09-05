-- ============================================================================
-- VMSG migration 125 — billing review follow-ups + feature flags for block 5
-- ============================================================================

-- The USD→INR rate frozen at sale time. MRR/revenue are kept in USD cents (the
-- mrr_live view divides by 100 for dollars), so INR amounts need this rate to
-- convert; using the *current* rate would let a rate change rewrite history.
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS usd_inr_rate NUMERIC(10, 4);

-- Flags block 5 gates on. Phase-1 social basics are live-but-killable; clips
-- and the referral ladder stay dark until their copy / verification gates land.
INSERT INTO feature_flags (flag_name, enabled, description) VALUES
    ('billing_checkout',    TRUE,  'Kill-switch for NEW checkouts; webhooks and entitlement unaffected'),
    ('social_friends',      TRUE,  'Friends list + QR pairing (block 5)'),
    ('social_leaderboards', TRUE,  'XP/ELO leaderboards with the anxiety guard (block 5)'),
    ('social_ghosts',       TRUE,  'Ghost recordings + async races (block 5)'),
    ('social_clips',        FALSE, 'Shareable clips, dual consent (dark until disclosure copy is approved)'),
    ('social_taunts',       TRUE,  'Post-match comedy taunts, SOC-15/16 gated'),
    ('daily_challenge',     TRUE,  'Daily challenge, server-scored, never bots'),
    ('referral_ladder',     FALSE, 'Referral rewards REF-01..10 (dark until verification gates ship)')
ON CONFLICT (flag_name) DO NOTHING;

-- Verifiable parental consent (COPPA "credit card" method): creating a seat on
-- a paid subscription IS the consent act. Backfill seats created before this
-- column existed from their creation time and the family's parent.
ALTER TABLE family_seats ADD COLUMN IF NOT EXISTS parental_consent_at TIMESTAMPTZ;
ALTER TABLE family_seats ADD COLUMN IF NOT EXISTS parental_consent_by UUID REFERENCES users(id) ON DELETE SET NULL;
UPDATE family_seats fs
SET parental_consent_at = fs.created_at, parental_consent_by = fa.parent_user_id
FROM family_accounts fa
WHERE fa.family_id = fs.family_id AND fs.parental_consent_at IS NULL;
