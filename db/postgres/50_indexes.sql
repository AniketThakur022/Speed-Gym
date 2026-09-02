-- ============================================================================
-- VMSG migration 50 — heavy indexes (kept separate so seeding can precede them)
-- ============================================================================

-- pgvector ANN index on the chunk store (architecture §5.1: IVFFlat lists=100).
-- Fine to create before seeding; re-run ANALYZE after bulk load.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Registry vector index (small table; flat scan is fine, index for parity)
CREATE INDEX IF NOT EXISTS idx_registry_embedding ON ontology_registry
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- Trigram search over problem summaries (admin/content ops)
CREATE INDEX IF NOT EXISTS idx_problems_summary_trgm ON problems
    USING gin (problem_summary gin_trgm_ops);

-- Frequent FK/host lookups not covered earlier
CREATE INDEX IF NOT EXISTS idx_attempts_user_time ON problem_attempts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user_time ON sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_events_session ON raw_events(session_id);
