-- ============================================================================
-- VMSG migration 30 — growth, ops, revenue (updated_schemas.sql v2.0, FIXED)
-- Source: incoming/topic_browser_full_package/schemas/postgres/updated_schemas.sql
-- The recovered file is the ORIGINAL delivered schema and still carries the
-- documented defects; this migration re-applies the lost build's fixes:
--   FIX #1: plan_tier / tier CHECK free|pro|bundle_2|bundle_3 (was 'master')
--   FIX #2: user_id columns are UUID REFERENCES users(id) (were TEXT)
--   FIX #4: DATE_TRUNC index replaced by a plain server_timestamp index
--           (DATE_TRUNC on timestamptz is not IMMUTABLE)
--   FIX #5: pg_partman / pg_cron sections retained as comments only
--   FIX #6: no users(user_id) index (column is users.id)
-- update_updated_at_column() already exists (10_create_core.sql) before use.
-- ============================================================================

-- ══════════════════════════════════════════════════════════════
-- SECTION A: USER LIFECYCLE & COHORT TRACKING
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS user_goals (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,

  active_goals JSONB DEFAULT '[]'::jsonb,
  target_exam TEXT,                        -- v2.4: DEPRECATED for multi-exam
  exam_date DATE,                          -- v2.4: DEPRECATED — per-track dates

  -- v2.4 Phase C: multi-exam tracking (ADD-ONLY)
  active_tracks JSONB DEFAULT '[]'::jsonb,

  -- DFV calibration
  ans_baseline_ms INTEGER,
  calibration_confidence NUMERIC(3,2) DEFAULT 0.5,

  -- Stamina mode state
  stamina_mode_enabled BOOLEAN DEFAULT false,
  dfv_trigger_count_12h INTEGER DEFAULT 0,
  last_dfv_trigger_at TIMESTAMPTZ,

  behavioral_profile JSONB,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_goals_exam_date ON user_goals(exam_date) WHERE target_exam IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_user_goals_target_exam ON user_goals(target_exam);

DROP TRIGGER IF EXISTS update_user_goals_updated_at ON user_goals;
CREATE TRIGGER update_user_goals_updated_at BEFORE UPDATE ON user_goals
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS user_growth (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  cohort_week DATE NOT NULL,
  acquisition_channel TEXT,

  first_landed_at BIGINT,
  onboarding_completed_at BIGINT,
  first_session_at BIGINT,
  first_purchase_at BIGINT,

  sessions_count INTEGER DEFAULT 0,
  problems_solved INTEGER DEFAULT 0,
  streak_max INTEGER DEFAULT 0,
  referral_count INTEGER DEFAULT 0,

  lifetime_value_cents INTEGER DEFAULT 0,
  last_payment_at BIGINT,
  plan_tier TEXT DEFAULT 'free' CHECK (plan_tier IN ('free', 'pro', 'bundle_2', 'bundle_3')),

  engagement_score INTEGER DEFAULT 0 CHECK (engagement_score BETWEEN 0 AND 100),
  churn_risk INTEGER DEFAULT 50 CHECK (churn_risk BETWEEN 0 AND 100),

  detected_persona TEXT CHECK (detected_persona IN (
    'sprinter', 'rebuilder', 'parent', 'perfectionist', 'wanderer', 'undetermined'
  )),
  persona_confidence NUMERIC(3,2) DEFAULT 0.0,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_growth_cohort_week ON user_growth(cohort_week);
CREATE INDEX IF NOT EXISTS idx_user_growth_channel ON user_growth(acquisition_channel);
CREATE INDEX IF NOT EXISTS idx_user_growth_churn ON user_growth(churn_risk) WHERE churn_risk > 70;
CREATE INDEX IF NOT EXISTS idx_user_growth_persona ON user_growth(detected_persona);

DROP TRIGGER IF EXISTS update_user_growth_updated_at ON user_growth;
CREATE TRIGGER update_user_growth_updated_at BEFORE UPDATE ON user_growth
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ══════════════════════════════════════════════════════════════
-- SECTION B: KPI METRICS & DASHBOARD
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS kpi_metrics (
  metric_id TEXT PRIMARY KEY,
  metric_category TEXT NOT NULL CHECK (metric_category IN (
    'growth', 'engagement', 'revenue', 'ops', 'marketing'
  )),
  value NUMERIC NOT NULL,
  value_type TEXT DEFAULT 'absolute' CHECK (value_type IN (
    'absolute', 'percentage', 'ratio', 'currency'
  )),
  dimension TEXT DEFAULT 'all',
  computed_at TIMESTAMPTZ DEFAULT now(),
  period_start TIMESTAMPTZ,
  period_end TIMESTAMPTZ,
  target_value NUMERIC,
  target_deadline TIMESTAMPTZ,
  computed_by TEXT DEFAULT 'cron' CHECK (computed_by IN (
    'cron', 'realtime', 'manual', 'agent_skill'
  )),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kpi_metrics_category ON kpi_metrics(metric_category);
CREATE INDEX IF NOT EXISTS idx_kpi_metrics_computed_at ON kpi_metrics(computed_at);

-- raw_events exists (20_base_telemetry.sql) before this view — the delivered
-- file referenced it without creating it (part of FIX #3).
CREATE MATERIALIZED VIEW IF NOT EXISTS kpi_dashboard_core AS
SELECT
  'dau' AS metric,
  COUNT(DISTINCT user_id)::numeric AS value,
  CURRENT_DATE AS computed_at
FROM raw_events
WHERE event_type = 'session_start'
  AND client_timestamp >= EXTRACT(EPOCH FROM CURRENT_DATE) * 1000

UNION ALL

SELECT
  'mau' AS metric,
  COUNT(DISTINCT user_id)::numeric AS value,
  CURRENT_DATE AS computed_at
FROM raw_events
WHERE event_type = 'session_start'
  AND client_timestamp >= EXTRACT(EPOCH FROM (CURRENT_DATE - INTERVAL '30 days')) * 1000

UNION ALL

SELECT
  'avg_session_length' AS metric,
  ROUND(AVG(session_elapsed_ms) / 60000.0, 1) AS value,
  CURRENT_DATE AS computed_at
FROM sessions
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days';

CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_dashboard_core ON kpi_dashboard_core(metric);

-- ══════════════════════════════════════════════════════════════
-- SECTION C: EMAIL MARKETING AUTOMATION
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS email_campaigns (
  campaign_id TEXT PRIMARY KEY,
  campaign_type TEXT NOT NULL CHECK (campaign_type IN (
    'onboarding', 'retention', 'upsell', 'reactivation', 'nurture'
  )),
  trigger_event TEXT,
  trigger_delay_hours INTEGER DEFAULT 0,
  subject_line TEXT NOT NULL,
  template_name TEXT NOT NULL,
  sent_count INTEGER DEFAULT 0,
  open_count INTEGER DEFAULT 0,
  click_count INTEGER DEFAULT 0,
  conversion_count INTEGER DEFAULT 0,
  unsubscribe_count INTEGER DEFAULT 0,
  variant TEXT DEFAULT 'control' CHECK (variant IN ('control', 'variant_a', 'variant_b')),
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  campaign_id TEXT NOT NULL REFERENCES email_campaigns(campaign_id),
  sent_at TIMESTAMPTZ,
  opened_at TIMESTAMPTZ,
  clicked_at TIMESTAMPTZ,
  converted_at TIMESTAMPTZ,
  status TEXT DEFAULT 'queued' CHECK (status IN (
    'queued', 'sent', 'delivered', 'bounced', 'complained', 'unsubscribed'
  )),
  provider_message_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_logs_user ON email_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_campaign ON email_logs(campaign_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs(status);

-- ══════════════════════════════════════════════════════════════
-- SECTION D: AD & REVENUE TRACKING
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ad_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL CHECK (event_type IN (
    'impression', 'click', 'reward_earned', 'reward_claimed'
  )),
  placement TEXT NOT NULL,
  screen TEXT NOT NULL,
  plan_tier TEXT NOT NULL,
  session_id TEXT,
  session_elapsed_ms INTEGER,
  cumulative_ad_seconds_today INTEGER DEFAULT 0,
  estimated_revenue_cents NUMERIC(10,4),
  client_timestamp BIGINT NOT NULL,
  server_timestamp TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ad_events_user ON ad_events(user_id);
CREATE INDEX IF NOT EXISTS idx_ad_events_placement ON ad_events(placement);
-- FIX #4: plain column index (delivered file used non-IMMUTABLE DATE_TRUNC)
CREATE INDEX IF NOT EXISTS idx_ad_events_date ON ad_events(server_timestamp);

CREATE TABLE IF NOT EXISTS subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT UNIQUE,

  tier TEXT NOT NULL CHECK (tier IN ('free', 'pro', 'bundle_2', 'bundle_3')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
    'active', 'trialing', 'cancelled', 'past_due', 'unpaid'
  )),

  trial_started_at TIMESTAMPTZ,
  trial_ends_at TIMESTAMPTZ,
  current_period_start TIMESTAMPTZ,
  current_period_end TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  cancellation_reason TEXT,

  monthly_recurring_revenue_cents INTEGER DEFAULT 0,
  total_revenue_cents INTEGER DEFAULT 0,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tier ON subscriptions(tier);

CREATE OR REPLACE VIEW mrr_live AS
SELECT
  tier,
  COUNT(*) AS subscriber_count,
  SUM(monthly_recurring_revenue_cents) / 100.0 AS monthly_revenue_usd
FROM subscriptions
WHERE status IN ('active', 'trialing')
GROUP BY tier;

-- ══════════════════════════════════════════════════════════════
-- SECTION E: OPERATIONS & MONITORING
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ops_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  alert_type TEXT NOT NULL CHECK (alert_type IN (
    'disk_full', 'db_slow', 'queue_backlog', 'error_spike',
    'latency_p95_high', 'neo4j_connection_failure', 'postgres_connection_failure'
  )),
  severity TEXT NOT NULL CHECK (severity IN ('critical', 'warning', 'info')),
  threshold_value NUMERIC,
  actual_value NUMERIC,
  message TEXT NOT NULL,
  acknowledged_by TEXT,
  acknowledged_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  resolution_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_alerts_type ON ops_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_ops_alerts_severity ON ops_alerts(severity) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS health_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  check_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('healthy', 'degraded', 'unavailable')),
  response_time_ms INTEGER,
  details JSONB,
  checked_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_health_checks_type ON health_checks(check_type);
CREATE INDEX IF NOT EXISTS idx_health_checks_time ON health_checks(checked_at);

-- ══════════════════════════════════════════════════════════════
-- SECTION F: REFERRAL SYSTEM
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS referrals (
  referral_code TEXT PRIMARY KEY,
  referrer_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  referred_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN (
    'pending', 'verified', 'rejected', 'converted', 'rewarded'
  )),
  reward_claimed_at TIMESTAMPTZ,
  reward_tier TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_user_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_user_id);

-- ══════════════════════════════════════════════════════════════
-- SECTION G: PARTITIONING & ARCHIVAL — DEFERRED (FIX #5)
-- pg_partman is unavailable on dev/cloud tiers. raw_events uses native range
-- partitioning (20_base_telemetry.sql); Celery beat creates month partitions
-- ahead and detaches those past 90 days. The original partman calls are kept
-- below for the Phase-2a infra pass:
--   SELECT partman.create_parent('public.raw_events', 'client_timestamp',
--          'native', 'monthly', p_premake := 2);
--   UPDATE partman.part_config SET retention='90 days',
--          retention_keep_table=false WHERE parent_table='public.raw_events';
-- ══════════════════════════════════════════════════════════════

-- ══════════════════════════════════════════════════════════════
-- SECTION H: AUDIT & COMPLIANCE
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS gdpr_deletion_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  request_type TEXT NOT NULL CHECK (request_type IN ('deletion', 'export', 'rectification')),
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
  delete_postgres BOOLEAN DEFAULT true,
  delete_neo4j BOOLEAN DEFAULT true,
  delete_email_logs BOOLEAN DEFAULT true,
  delete_ad_events BOOLEAN DEFAULT true,
  requested_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ,
  verification_code TEXT,
  verification_completed_at TIMESTAMPTZ
);

-- ══════════════════════════════════════════════════════════════
-- SECTION I: MATERIALIZED VIEW REFRESH — DEFERRED (FIX #5)
-- pg_cron jobs move to Celery beat in Phase 1. Originals for Phase-2a:
--   SELECT cron.schedule('refresh-kpi-dashboard', '*/15 * * * *',
--     'REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_dashboard_core');
--   SELECT cron.schedule('nightly-engagement-update', '0 2 * * *', ...);
--   SELECT cron.schedule('weekly-churn-prediction', '0 3 * * 0', ...);
-- ══════════════════════════════════════════════════════════════

-- ══════════════════════════════════════════════════════════════
-- SECTION J: POSTGRES ↔ NEO4J GRAPH LINKAGE
-- (columns already created in 20_base_telemetry.sql; kept idempotent to
-- mirror the delivered file)
-- ══════════════════════════════════════════════════════════════

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_hash VARCHAR(16);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(50);
