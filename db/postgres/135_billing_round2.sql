-- ============================================================================
-- VMSG migration 135 — billing review round 2
-- The dunning grace (SUB-10) must be keyed on WHEN a row entered past_due, not
-- on current_period_end: Stripe advances the period end at the failed renewal,
-- which silently turned a 3-day grace into a month.
-- ============================================================================
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS past_due_since TIMESTAMPTZ;
UPDATE subscriptions SET past_due_since = COALESCE(past_due_since, updated_at)
WHERE status = 'past_due' AND past_due_since IS NULL;
