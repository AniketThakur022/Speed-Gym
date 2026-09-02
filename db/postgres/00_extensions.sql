-- ============================================================================
-- VMSG migration 00 — extensions
-- Rebuild of the lost repo's locale-safe migration chain (00/10/.../70).
-- FIX #5 (of the 7 documented schema fixes): pg_partman and pg_cron are NOT
-- created here — they are unavailable on dev/cloud tiers. Partition maintenance
-- runs via native DDL + Celery beat; pg_cron jobs are documented but deferred
-- to Phase-2a infra (see 30_growth_ops.sql SECTION G/I).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;
