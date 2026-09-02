-- ============================================================================
-- VMSG migration 80 — prerequisite-closure precompute tables
-- DDL per the RAG chat's docs/rag/STRATEGY_A_CLOSURE_DESIGN.md (they own the
-- closure build + shadow-diff promotion; this side only provides the tables).
-- Closure runs in the nightly factory window — never at practice time.
-- ============================================================================

CREATE TABLE IF NOT EXISTS prerequisite_closure (
  descendant_skill TEXT NOT NULL,   -- the skill being asked about
  ancestor_skill   TEXT NOT NULL,   -- must be known first
  depth            SMALLINT NOT NULL CHECK (depth BETWEEN 1 AND 5),
  min_depth        SMALLINT NOT NULL,          -- MIN over paths (Strategy-C convention)
  support          SMALLINT NOT NULL DEFAULT 1,
  computed_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (descendant_skill, ancestor_skill)
);

CREATE INDEX IF NOT EXISTS idx_prereq_closure_lookup
  ON prerequisite_closure (descendant_skill, min_depth);

-- Depth-1 Q-matrix export of PREREQUISITE_OF (Skill→Problem)
CREATE TABLE IF NOT EXISTS problem_requirements (
  skill_name  TEXT NOT NULL,
  template_id TEXT NOT NULL,               -- :Problem key
  PRIMARY KEY (skill_name, template_id)
);

-- Shadow table for the dry_run → diff → promote protocol
CREATE TABLE IF NOT EXISTS prerequisite_closure_test (
  descendant_skill TEXT NOT NULL,
  ancestor_skill   TEXT NOT NULL,
  depth            SMALLINT NOT NULL CHECK (depth BETWEEN 1 AND 5),
  min_depth        SMALLINT NOT NULL,
  support          SMALLINT NOT NULL DEFAULT 1,
  computed_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (descendant_skill, ancestor_skill)
);

CREATE TABLE IF NOT EXISTS sync_manifest (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,                     -- e.g. factory/closure/build_closure.py
  target_table TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('dry_run', 'production', 'failed')),
  rows_written INTEGER,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  duration_ms INTEGER,
  peak_memory_mb INTEGER,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_manifest_target ON sync_manifest(target_table, started_at DESC);
