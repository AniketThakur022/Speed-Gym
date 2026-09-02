-- ============================================================================
-- VMSG migration 40 — exam prep, mocks, sinking skills, 3-path (schema v5.0)
-- Source: incoming/topic_browser_full_package/schemas/postgres/updated_schemas_v5.sql
-- Applied on top of 10/20/30. FIX #2 holds: user_id is UUID throughout
-- (the delivered v5 file already used UUID — verified, not re-derived).
-- ============================================================================

-- ============================================================================
-- SECTION 1: USER PATH & EXAM FIELDS
-- ============================================================================

ALTER TABLE users
ADD COLUMN IF NOT EXISTS active_path VARCHAR(50)
    CHECK (active_path IN ('core_math_vedic', 'vedic_standalone', 'exam_prep'))
    DEFAULT 'core_math_vedic';

ALTER TABLE users
ADD COLUMN IF NOT EXISTS target_exam VARCHAR(20)
    CHECK (target_exam IN ('CAT', 'GMAT', 'GRE', 'School'));

ALTER TABLE users
ADD COLUMN IF NOT EXISTS exam_date DATE;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS coverage_pct DECIMAL(5,2) DEFAULT 0.00;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS days_to_exam INTEGER;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS technique_count INTEGER DEFAULT 0;

-- ============================================================================
-- SECTION 2: CONTENT TYPE PROGRESSION
-- ============================================================================

ALTER TABLE user_technique_states
ADD COLUMN IF NOT EXISTS seen_learn BOOLEAN DEFAULT FALSE;

ALTER TABLE user_technique_states
ADD COLUMN IF NOT EXISTS seen_hybrid BOOLEAN DEFAULT FALSE;

ALTER TABLE user_technique_states
ADD COLUMN IF NOT EXISTS exposure_state VARCHAR(20) DEFAULT 'unexposed'
    CHECK (exposure_state IN ('unexposed', 'learning', 'hybriding', 'practicing', 'completed'));

ALTER TABLE user_technique_states
ADD COLUMN IF NOT EXISTS vedic_seen_hybrid BOOLEAN DEFAULT FALSE;

-- ============================================================================
-- SECTION 3: PATH ENROLLMENT AUDIT
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_path_enrollment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path_id VARCHAR(50) NOT NULL,
    enrolled_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    sequence_position INTEGER DEFAULT 0,
    UNIQUE(user_id, path_id)
);

CREATE INDEX IF NOT EXISTS idx_upe_user_active
    ON user_path_enrollment(user_id, is_active);

CREATE TABLE IF NOT EXISTS user_path_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_path_id VARCHAR(50),
    to_path_id VARCHAR(50) NOT NULL,
    switched_at TIMESTAMPTZ DEFAULT NOW(),
    reason VARCHAR(100)
);

-- ============================================================================
-- SECTION 4: MOCK EXAM ATTEMPTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS mock_exam_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mock_id VARCHAR(100) NOT NULL,
    exam_type VARCHAR(20) NOT NULL,

    total_score DECIMAL(5,2),
    max_score DECIMAL(5,2) DEFAULT 300,
    percentile DECIMAL(5,2),

    section_scores JSONB DEFAULT '{}',
    total_time_taken_seconds INTEGER,
    section_times JSONB DEFAULT '{}',
    weak_areas JSONB DEFAULT '[]',
    deferred_sinking_skills JSONB DEFAULT '[]',

    status VARCHAR(20) DEFAULT 'completed'
        CHECK (status IN ('started', 'in_progress', 'completed', 'abandoned')),

    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    synced_from_device VARCHAR(100),
    sync_timestamp TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_mea_user_mock
    ON mock_exam_attempts(user_id, mock_id);

CREATE INDEX IF NOT EXISTS idx_mea_completed
    ON mock_exam_attempts(user_id, completed_at);

-- ============================================================================
-- SECTION 5: SINKING SKILLS (v5 canonical shape — architecture §5.1)
-- ============================================================================

CREATE TABLE IF NOT EXISTS sinking_skills (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    technique_id VARCHAR(100) NOT NULL,
    technique_canonical_id VARCHAR(50),

    decay_priority DECIMAL(3,2) DEFAULT 0.0
        CHECK (decay_priority BETWEEN 0.0 AND 1.0),

    consecutive_errors INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    total_attempts INTEGER DEFAULT 0,

    triggered_by VARCHAR(50)
        CHECK (triggered_by IN ('mock_wrong_answer', 'session_wrong', 'decay', 'manual')),
    source_problem_ids TEXT[] DEFAULT ARRAY[]::TEXT[],
    trap_types TEXT[] DEFAULT ARRAY[]::TEXT[],

    last_practiced TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (user_id, technique_id)
);

CREATE INDEX IF NOT EXISTS idx_ss_priority
    ON sinking_skills(user_id, decay_priority DESC);

CREATE INDEX IF NOT EXISTS idx_ss_errors
    ON sinking_skills(user_id, consecutive_errors DESC);

-- ============================================================================
-- SECTION 6: EXAM DEADLINES & STATUS
-- ============================================================================

CREATE TABLE IF NOT EXISTS exam_deadlines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exam_type VARCHAR(20) NOT NULL,
    exam_date DATE NOT NULL,
    priority INTEGER DEFAULT 1
        CHECK (priority BETWEEN 1 AND 5),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, exam_type)
);

CREATE INDEX IF NOT EXISTS idx_ed_user_active
    ON exam_deadlines(user_id, is_active);

-- ============================================================================
-- SECTION 7: DAMAGE CONTROL TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS damage_control_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    days_to_exam INTEGER NOT NULL,
    coverage_pct DECIMAL(5,2) NOT NULL,

    user_action VARCHAR(30) NOT NULL
        CHECK (user_action IN ('accepted', 'postponed_exam', 'ignored', 'dismissed')),

    plan_hours_per_day INTEGER DEFAULT 4,
    plan_expected_score_range VARCHAR(20),
    plan_was_honest BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dce_user
    ON damage_control_events(user_id, created_at);

-- ============================================================================
-- SECTION 8: TOPIC WEIGHT AGGREGATION
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_topic_weights (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id VARCHAR(100) NOT NULL,
    exam_type VARCHAR(20) NOT NULL DEFAULT '',

    mastery_score DECIMAL(5,2) DEFAULT 0,
    decay_days INTEGER DEFAULT 0,
    current_weight DECIMAL(5,2) DEFAULT 0,

    exam_weight DECIMAL(5,2),
    is_high_yield BOOLEAN DEFAULT FALSE,

    updated_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (user_id, topic_id, exam_type)
);

-- ============================================================================
-- SECTION 9: TRIGGERS
-- ============================================================================

CREATE OR REPLACE FUNCTION update_days_to_exam()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.exam_date IS NOT NULL THEN
        NEW.days_to_exam = (NEW.exam_date - CURRENT_DATE);
    ELSE
        NEW.days_to_exam = NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_days_to_exam ON users;
CREATE TRIGGER trg_update_days_to_exam
    BEFORE INSERT OR UPDATE OF exam_date ON users
    FOR EACH ROW EXECUTE FUNCTION update_days_to_exam();

CREATE OR REPLACE FUNCTION update_sinking_skills_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_ss_timestamp ON sinking_skills;
CREATE TRIGGER trg_update_ss_timestamp
    BEFORE UPDATE ON sinking_skills
    FOR EACH ROW EXECUTE FUNCTION update_sinking_skills_timestamp();
