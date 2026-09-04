-- ============================================================================
-- VMSG migration 110 — admin access + trust-override audit
-- ============================================================================

-- Admin is a property of the account, not a hardcoded email list, so access can
-- be granted and revoked without a deploy.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_users_admin ON users(id) WHERE is_admin;

-- Every manual trust change is recorded. problem_health_scores decides what
-- reaches a learner, so an override needs to be answerable later: who, when,
-- from what, to what, and why.
CREATE TABLE IF NOT EXISTS content_trust_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id VARCHAR(200) NOT NULL,
    previous_level VARCHAR(20),
    new_level VARCHAR(20) NOT NULL,
    reason TEXT NOT NULL,
    changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trust_overrides_content
    ON content_trust_overrides(content_id, changed_at DESC);
