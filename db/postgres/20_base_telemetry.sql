-- ============================================================================
-- VMSG migration 20 — base telemetry + content stores
-- FIX #3 baked in: the delivered v2/v5 schemas referenced raw_events and
-- chunks without ever creating them — they are authored here, matching the
-- lost build's 20_base_telemetry.sql.
-- raw_events uses NATIVE monthly range partitioning (pg_partman deferred,
-- FIX #5); Celery beat owns partition maintenance in Phase 1.
-- ============================================================================

-- ============================================================
-- RAW EVENT STREAM (Path A — immutable, 90-day retention)
-- client_timestamp is UNIX ms (BIGINT) to match the client event envelope.
-- ============================================================

CREATE TABLE IF NOT EXISTS raw_events (
    event_id UUID NOT NULL,               -- client-minted; idempotency key
    user_id UUID,
    session_id UUID,
    event_type VARCHAR(60) NOT NULL,
    priority SMALLINT DEFAULT 5,
    client_timestamp BIGINT NOT NULL,     -- UNIX ms
    server_timestamp TIMESTAMPTZ DEFAULT NOW(),
    session_elapsed_ms INTEGER,
    feature_flag VARCHAR(60),
    phase_tag VARCHAR(30) DEFAULT 'phase_1_build' CHECK (phase_tag IN (
        'phase_1_build', 'phase_2_activation'
    )),
    metadata JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (event_id, client_timestamp)
) PARTITION BY RANGE (client_timestamp);

-- Default partition catches anything outside pre-created windows; Celery beat
-- creates month partitions ahead and detaches expired ones (90-day retention).
CREATE TABLE IF NOT EXISTS raw_events_default PARTITION OF raw_events DEFAULT;

CREATE INDEX IF NOT EXISTS idx_raw_events_user ON raw_events(user_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_type ON raw_events(event_type);
CREATE INDEX IF NOT EXISTS idx_raw_events_time ON raw_events(client_timestamp);

-- ============================================================
-- BKT STATE SNAPSHOTS (Path D — session_end rollup, 20:1, 365-day retention)
-- ============================================================

CREATE TABLE IF NOT EXISTS bkt_state_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID,
    technique_states JSONB NOT NULL,   -- {technique_id: {pLearned, state, attempts}}
    snapshot_reason VARCHAR(30) DEFAULT 'session_end' CHECK (snapshot_reason IN (
        'session_end', 'multi_device_recompute', 'server_refit', 'manual'
    )),
    device_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bkt_snapshots_user ON bkt_state_snapshots(user_id, created_at DESC);

-- ============================================================
-- FATIGUE & BEHAVIORAL PROFILES
-- ============================================================

CREATE TABLE IF NOT EXISTS fatigue_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID,
    fatigue_index DECIMAL(4,3),        -- 0.40*F_latency + 0.35*F_accuracy + 0.25*F_entropy
    f_latency DECIMAL(4,3),
    f_accuracy DECIMAL(4,3),
    f_entropy DECIMAL(4,3),
    clr_triggered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fatigue_user ON fatigue_snapshots(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_behavioral_clusters (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    cluster VARCHAR(20) CHECK (cluster IN (
        'sprinter', 'deliberate', 'perfectionist', 'balanced', 'rebuilder', 'wanderer'
    )),
    features JSONB,                     -- {speedAccuracyRatio, hintDependency, ...}
    confidence DECIMAL(3,2),
    assigned_after_attempts INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- CONTENT STORES (seeded from db_exports/)
-- ============================================================

-- pgvector chunk store (chunks.jsonl; 1536-d OpenAI text-embedding-3-small)
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY,
    book_id VARCHAR(200),
    page_number INTEGER,
    chunk_type VARCHAR(50),            -- explanation | problem | worked_example | insight
    content TEXT,
    content_md TEXT,
    embedding vector(1536),
    logic_bundle JSONB DEFAULT '{}'::jsonb,
    station_audit JSONB DEFAULT '{}'::jsonb,
    content_hash VARCHAR(16) UNIQUE,   -- Postgres↔Neo4j linkage (v2.0 SECTION J)
    schema_version VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(chunk_type);

-- Extraction-layer problem records (problems.jsonl)
CREATE TABLE IF NOT EXISTS problems (
    id UUID PRIMARY KEY,
    chunk_id UUID,
    book_id VARCHAR(200),
    source_reference TEXT,
    chunk_idx INTEGER,
    record_type VARCHAR(40),
    topic VARCHAR(200),
    sub_topic VARCHAR(200),
    neo4j_problem_node_id VARCHAR(200),
    neo4j_concept_cluster_name VARCHAR(200),
    neo4j_technique_name VARCHAR(200),
    neo4j_sutra_name VARCHAR(200),
    problem_latex TEXT,
    problem_summary TEXT,
    logic_steps JSONB DEFAULT '[]'::jsonb,
    raw_formulas JSONB DEFAULT '[]'::jsonb,
    answer_key_entry TEXT,
    answer_key_numeric DOUBLE PRECISION,
    answer_key_latex TEXT,
    answer_key_structured JSONB,
    target_variable VARCHAR(100),
    data_points JSONB DEFAULT '{}'::jsonb,
    -- LEGACY v1 verifier verdict. Never a quality gate: ALL_FAILED on 806 of
    -- 807 is unusable per item, and the verifier had a documented 63.7% FP
    -- rate. But do NOT read it as known-meaningless — it checked step RESULTS,
    -- and those are genuinely contaminated at scale, so it may have detected
    -- something real. Unresolved; RAG owns the re-test. The live serving signal
    -- is the graph's validation_status (question + answer).
    verification_status VARCHAR(50),
    verification_error TEXT,
    verified_roots JSONB DEFAULT '[]'::jsonb,
    verified_at TIMESTAMPTZ,
    verification_payload JSONB,
    difficulty_level INTEGER,
    digit_size TEXT,               -- descriptive in the export ("2-digit × 3-digit")
    operation_type VARCHAR(100),
    strategy_type VARCHAR(100),
    is_multi_step BOOLEAN DEFAULT FALSE,
    detected_traps JSONB DEFAULT '[]'::jsonb,
    required_skills JSONB DEFAULT '[]'::jsonb,
    min_speed_level INTEGER,
    lesson_node_id VARCHAR(200),
    pedagogical_sequence_id VARCHAR(200),
    lesson_order INTEGER,
    schema_version VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_problems_book ON problems(book_id);
CREATE INDEX IF NOT EXISTS idx_problems_topic ON problems(topic);
CREATE INDEX IF NOT EXISTS idx_problems_verification ON problems(verification_status);

-- Ontology registry (registry.jsonl; grounding for trive-v2 extraction)
CREATE TABLE IF NOT EXISTS ontology_registry (
    id UUID PRIMARY KEY,
    label VARCHAR(200) NOT NULL,
    category VARCHAR(100),
    description TEXT,
    embedding vector(1536),            -- NOTE: export has zeroed vectors; RAG chat regenerates
    aliases JSONB DEFAULT '[]'::jsonb,
    source_book VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_label ON ontology_registry(label);

-- ============================================================
-- CONTENT GOVERNANCE (5-gate pipeline + trust ladder)
-- ============================================================

CREATE TABLE IF NOT EXISTS content_validation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id VARCHAR(200) NOT NULL,
    content_kind VARCHAR(30) DEFAULT 'generated_problem',
    gate VARCHAR(30) CHECK (gate IN (
        'sympy', 'consensus', 'hallucination', 'trap_taxonomy', 'dedup'
    )),
    passed BOOLEAN,
    score DECIMAL(4,3),
    details JSONB,
    verifier_version VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cvl_content ON content_validation_log(content_id);

-- Canonical 5-value trust enum (RUNTIME_SAFETY wins over the 4-value variant)
--
-- VERIFICATION SEMANTICS: sympy_score is an ANSWER check (it recomputes the
-- result), NOT a check of the worked solution — a template can hold a correct
-- answer with a broken derivation and still score 1.0 here. Solution
-- correctness comes only from the stage-7 jester consensus, which lands in
-- consensus_score. Never collapse these into a single "verified" flag in an
-- API field, admin column, or trust badge.
CREATE TABLE IF NOT EXISTS problem_health_scores (
    content_id VARCHAR(200) PRIMARY KEY,
    trust_level VARCHAR(20) NOT NULL DEFAULT 'QUARANTINED_SOFT' CHECK (trust_level IN (
        'LIVE', 'TRUSTED', 'SANDBOX', 'QUARANTINED_SOFT', 'QUARANTINED_HARD'
    )),
    health_score DECIMAL(4,3),         -- sympy*0.40 + trap*0.20 + consensus*0.25 + hallucination*0.15
    sympy_score DECIMAL(4,3),          -- ANSWER equivalence only (see note above)
    trap_score DECIMAL(4,3),
    consensus_score DECIMAL(4,3),
    hallucination_score DECIMAL(4,3),
    primary_confidence DECIMAL(4,3),
    secondary_confidence DECIMAL(4,3),
    exposure_count INTEGER DEFAULT 0,
    distinct_users INTEGER DEFAULT 0,
    accuracy_observed DECIMAL(4,3),
    accuracy_expected DECIMAL(4,3),
    promoted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- FIX (Sprint-0 note in architecture §5.1): the delivered idx_ubc_confidence
-- referenced non-existent primary_confidence — canonical index targets
-- secondary_confidence.
CREATE INDEX IF NOT EXISTS idx_ubc_confidence ON problem_health_scores(secondary_confidence);
CREATE INDEX IF NOT EXISTS idx_phs_trust ON problem_health_scores(trust_level);

-- LLM traceability (audit_log INSERT after every LLM call — architecture §8.5)
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor VARCHAR(60) NOT NULL,          -- celery task / service name
    action VARCHAR(60) NOT NULL,         -- llm_call | promotion | quarantine | ...
    model VARCHAR(100),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_usd NUMERIC(10,6),
    content_id VARCHAR(200),
    request_hash VARCHAR(64),
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_generation_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generation_pattern_id VARCHAR(100),
    template_id VARCHAR(100),
    model VARCHAR(100),
    input_params JSONB,
    output JSONB,
    gates_passed JSONB,
    final_trust VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Dead-letter for Gate-1 SymPy failures
CREATE TABLE IF NOT EXISTS content_dead_letter (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id VARCHAR(200),
    payload JSONB,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
