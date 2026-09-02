-- ============================================================================
-- VMSG migration 10 — core tables (users, mastery, sessions, attempts)
-- Source of record: vedic_speed_gym_backend.md §3.1 (v5.2 corpus), reconciled
-- against VMSG_TECHNICAL_ARCHITECTURE.md (RFP v7.2 wins on conflict).
-- FIX #1 baked in: users.tier enum is free/pro/bundle_2/bundle_3 (SUB-01..04),
--   never 'master'.
-- Note: user_growth is owned by 30_growth_ops.sql (v2.0 shape from
--   updated_schemas.sql); sinking_skills is owned by 40_exam_v5.sql (v5 shape).
-- ============================================================================

-- ============================================================
-- 1. USER MANAGEMENT
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),                -- nullable: OAuth/phone accounts
    display_name VARCHAR(100),

    -- Subscription tier (RFP SUB-01..04; FIX #1)
    tier VARCHAR(20) NOT NULL DEFAULT 'free'
        CHECK (tier IN ('free', 'pro', 'bundle_2', 'bundle_3')),

    -- Profile fields
    age INTEGER CHECK (age BETWEEN 8 AND 100),
    grade INTEGER CHECK (grade BETWEEN 1 AND 12),

    -- Persona & preferences (from onboarding)
    persona VARCHAR(20) CHECK (persona IN (
        'SchoolSupport', 'BrainTrainer', 'SpeedDemon'
    )),
    experience_level VARCHAR(20) CHECK (experience_level IN (
        'beginner', 'intermediate', 'advanced', 'expert'
    )),
    math_comfort INTEGER CHECK (math_comfort BETWEEN 1 AND 10),
    vedic_familiarity INTEGER CHECK (vedic_familiarity BETWEEN 0 AND 10),
    learning_style VARCHAR(20) CHECK (learning_style IN (
        'visual', 'auditory', 'kinesthetic', 'reading'
    )),
    challenge_tolerance INTEGER CHECK (challenge_tolerance BETWEEN 1 AND 10),

    -- Goals
    primary_goal VARCHAR(20) CHECK (primary_goal IN (
        'speed', 'accuracy', 'exam_prep', 'basics'
    )),
    target_speed INTEGER,              -- seconds per problem
    behavioral_profile JSONB,          -- computed from first 20 attempts

    -- Session constraints
    focus_budget INTEGER DEFAULT 20,   -- minutes
    daily_goal INTEGER DEFAULT 20,     -- problems
    weekly_goal INTEGER DEFAULT 5,     -- sessions

    -- Temporal
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_session_at TIMESTAMPTZ
);
-- (target_exam / exam_date / active_path / coverage_pct / days_to_exam are
--  added by 40_exam_v5.sql, matching the delivered v5 ALTER chain.)

CREATE INDEX IF NOT EXISTS idx_users_persona ON users(persona);
CREATE INDEX IF NOT EXISTS idx_users_last_session ON users(last_session_at);

-- ============================================================
-- 2. TECHNIQUE MASTERY (FIX #3: user_technique_states was referenced by the
--    delivered schemas but never created — authored here)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_technique_states (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    technique_id VARCHAR(100) NOT NULL,        -- references Neo4j :Skill

    state VARCHAR(20) CHECK (state IN ('fluid', 'fragile', 'fractured')),

    mastery_score INTEGER CHECK (mastery_score BETWEEN 0 AND 100),
    accuracy_score INTEGER CHECK (accuracy_score BETWEEN 0 AND 100),
    speed_score INTEGER CHECK (speed_score BETWEEN 0 AND 100),

    consecutive_correct INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,

    total_attempts INTEGER DEFAULT 0,
    total_correct INTEGER DEFAULT 0,
    avg_time_seconds DECIMAL(6,2),
    last_practiced_at TIMESTAMPTZ,
    decay_days INTEGER DEFAULT 0,

    needs_practice BOOLEAN GENERATED ALWAYS AS (
        state IN ('fragile', 'fractured') OR decay_days > 7
    ) STORED,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, technique_id)
);

CREATE INDEX IF NOT EXISTS idx_uts_user_state ON user_technique_states(user_id, state);
CREATE INDEX IF NOT EXISTS idx_uts_needs_practice ON user_technique_states(user_id, needs_practice);

-- ============================================================
-- 2a. MULTI-SUBJECT COGNITIVE TRACKING
-- ============================================================

CREATE TABLE IF NOT EXISTS cognitive_attributes (
    code VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    section VARCHAR(10) CHECK (section IN ('VARC', 'LR', 'DI', 'QUANT')),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_attribute_mastery (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    attribute_code VARCHAR(50) REFERENCES cognitive_attributes(code),
    section VARCHAR(10) CHECK (section IN ('VARC', 'LR', 'DI', 'QUANT')),
    mastery_prob FLOAT CHECK (mastery_prob BETWEEN 0 AND 1),
    confidence FLOAT CHECK (confidence BETWEEN 0 AND 1),
    attempts_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    last_practiced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, attribute_code)
);

CREATE INDEX IF NOT EXISTS idx_attribute_mastery_user ON user_attribute_mastery(user_id);
CREATE INDEX IF NOT EXISTS idx_attribute_mastery_section ON user_attribute_mastery(section);

-- ============================================================
-- 3. SESSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,

    prescription JSONB NOT NULL,

    session_type VARCHAR(20) DEFAULT 'learning' CHECK (session_type IN (
        'learning', 'topic_browser', 'mock_exam', 'remediation'
    )),
    execution_mode VARCHAR(20) DEFAULT 'PRACTICE' CHECK (execution_mode IN (
        'PRACTICE', 'MOCK_EXAM'
    )),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN (
        'active', 'paused', 'completed', 'abandoned'
    )),

    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    total_duration_seconds INTEGER,
    session_elapsed_ms INTEGER,

    problems_attempted INTEGER DEFAULT 0,
    problems_correct INTEGER DEFAULT 0,
    avg_time_per_problem DECIMAL(6,2),
    accuracy_pct DECIMAL(5,2),

    technique_transitions JSONB DEFAULT '[]',

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(started_at);

-- ============================================================
-- 4. PROBLEM ATTEMPTS (aggregated Path-B record; raw stream in 20_base_telemetry)
-- ============================================================

CREATE TABLE IF NOT EXISTS problem_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,

    problem_id VARCHAR(100) NOT NULL,
    technique_id VARCHAR(100),
    bucket VARCHAR(20) CHECK (bucket IN ('primary', 'sinking', 'frontier')),

    user_answer TEXT,
    correct_answer TEXT,
    is_correct BOOLEAN,

    -- Multi-phase time (v3.0)
    reading_time_ms INTEGER,
    setup_time_ms INTEGER,
    solving_time_ms INTEGER,
    answering_time_ms INTEGER,
    total_time_ms INTEGER,

    -- Legacy timing
    time_spent_seconds DECIMAL(6,2),
    target_time_seconds INTEGER,
    was_under_target BOOLEAN,
    cognitive_latency_ms INTEGER,

    -- Multi-subject tracking (v3.0)
    subject_type VARCHAR(10) CHECK (subject_type IN ('QUANT', 'VARC', 'LR', 'DI')),
    content_unit_id VARCHAR(100),
    phase VARCHAR(20),

    -- UI interactions
    hints_used INTEGER DEFAULT 0,
    hint_level INTEGER DEFAULT 0,
    solve_along_steps_viewed INTEGER DEFAULT 0,
    ui_mode VARCHAR(20),

    trap_triggered VARCHAR(100),
    events JSONB DEFAULT '[]',

    validated_by VARCHAR(20) CHECK (validated_by IN ('sympy', 'llm', 'manual', 'client')),
    validation_confidence DECIMAL(3,2),
    verifier_version VARCHAR(20),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attempts_session ON problem_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user_technique ON problem_attempts(user_id, technique_id);
CREATE INDEX IF NOT EXISTS idx_attempts_time ON problem_attempts(created_at);

-- ============================================================
-- 5. AGGREGATED SKILL PROGRESSION
-- ============================================================

CREATE TABLE IF NOT EXISTS skill_progression_daily (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    technique_id VARCHAR(100) NOT NULL,
    date DATE NOT NULL,

    attempts_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    accuracy_pct DECIMAL(5,2),
    avg_time_seconds DECIMAL(6,2),

    ending_state VARCHAR(20),
    mastery_score INTEGER,
    decay_factor DECIMAL(3,2),

    UNIQUE(user_id, technique_id, date)
);

CREATE INDEX IF NOT EXISTS idx_spd_user_technique ON skill_progression_daily(user_id, technique_id);
CREATE INDEX IF NOT EXISTS idx_spd_date ON skill_progression_daily(date);

CREATE MATERIALIZED VIEW IF NOT EXISTS user_technique_summary AS
SELECT
    user_id,
    technique_id,
    MAX(date) AS last_practiced_date,
    AVG(accuracy_pct) AS avg_accuracy,
    AVG(avg_time_seconds) AS avg_time,
    (SELECT ending_state FROM skill_progression_daily spd2
     WHERE spd2.user_id = spd.user_id AND spd2.technique_id = spd.technique_id
     ORDER BY date DESC LIMIT 1) AS current_state,
    (SELECT mastery_score FROM skill_progression_daily spd3
     WHERE spd3.user_id = spd.user_id AND spd3.technique_id = spd.technique_id
     ORDER BY date DESC LIMIT 1) AS current_mastery
FROM skill_progression_daily spd
GROUP BY user_id, technique_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_uts_summary ON user_technique_summary(user_id, technique_id);

-- ============================================================
-- 6. GENERATED PROBLEMS CACHE + PATTERNS
-- ============================================================

CREATE TABLE IF NOT EXISTS generated_problems (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_id VARCHAR(100) NOT NULL,
    parameters JSONB NOT NULL,
    problem_text TEXT NOT NULL,
    problem_latex TEXT,
    answer TEXT NOT NULL,
    answer_latex TEXT,
    difficulty_level INTEGER,
    target_time_seconds INTEGER,
    sympy_validated BOOLEAN DEFAULT FALSE,
    validation_result JSONB,
    generation_hash VARCHAR(64) UNIQUE,   -- SHA-256 params_hash dedup (GEN gate 5)
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gp_template ON generated_problems(template_id);
CREATE INDEX IF NOT EXISTS idx_gp_difficulty ON generated_problems(difficulty_level);
CREATE INDEX IF NOT EXISTS idx_gp_hash ON generated_problems(generation_hash);

CREATE TABLE IF NOT EXISTS generation_patterns (
    id VARCHAR(100) PRIMARY KEY,
    category VARCHAR(50),
    title VARCHAR(200),
    parameters JSONB,
    template JSONB,
    validator JSONB,          -- declarative {operator, expected, tolerance} — never eval()
    difficulty_formula JSONB,
    is_frozen BOOLEAN DEFAULT FALSE,   -- pattern freeze at 3+ quarantined children
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 8/9. TOPIC BROWSER + SUBTOPIC MASTERY
-- (topic_browser_subtopics itself is owned by 70_subtopic_reference.sql,
--  the recovered extension file; user_subtopic_mastery lives here)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_subtopic_mastery (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    subtopic_id VARCHAR(100) NOT NULL,
    mastery_score INTEGER CHECK (mastery_score BETWEEN 0 AND 100),
    accuracy_score DECIMAL(5,2),
    avg_time_seconds DECIMAL(6,2),
    state VARCHAR(20) CHECK (state IN ('fluid', 'fragile', 'fractured')),
    attempts_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    last_practiced_at TIMESTAMPTZ,
    decay_days INTEGER DEFAULT 0,
    topic VARCHAR(100),
    category VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, subtopic_id)
);

CREATE INDEX IF NOT EXISTS idx_usm_user ON user_subtopic_mastery(user_id);
CREATE INDEX IF NOT EXISTS idx_usm_subtopic ON user_subtopic_mastery(subtopic_id);
CREATE INDEX IF NOT EXISTS idx_usm_topic_state ON user_subtopic_mastery(topic, state);

-- ============================================================
-- 11. TECHNIQUE STATE TRANSITIONS (audit trail)
-- ============================================================

CREATE TABLE IF NOT EXISTS technique_state_transitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    technique_id VARCHAR(100) NOT NULL,
    from_state VARCHAR(20) CHECK (from_state IN ('fluid', 'fragile', 'fractured', 'new')),
    to_state VARCHAR(20) CHECK (to_state IN ('fluid', 'fragile', 'fractured')),
    mastery_score_before INTEGER,
    mastery_score_after INTEGER,
    trigger_event VARCHAR(50),
    session_id UUID REFERENCES sessions(id),
    problem_id VARCHAR(100),
    attempt_id UUID,
    consecutive_correct INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    total_attempts_at_transition INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tst_user ON technique_state_transitions(user_id);
CREATE INDEX IF NOT EXISTS idx_tst_technique ON technique_state_transitions(technique_id);
CREATE INDEX IF NOT EXISTS idx_tst_time ON technique_state_transitions(created_at);

-- ============================================================
-- 12. USER COGNITIVE PROFILES (multi-model routing base)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_cognitive_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE,

    theta DECIMAL(6,4) DEFAULT 0.0,
    theta_se DECIMAL(6,4) DEFAULT 1.0,

    -- BKT priors: RFP v7.2 BKT-01..05 (P(L0)=0.35, P(T)=0.14, P(S)=0.10, P(G)=0.20)
    p_init DECIMAL(6,4) DEFAULT 0.35,
    p_learn DECIMAL(6,4) DEFAULT 0.14,
    p_guess DECIMAL(6,4) DEFAULT 0.20,
    p_slip DECIMAL(6,4) DEFAULT 0.10,

    subject_profiles JSONB DEFAULT '{
        "quant": {"theta": 0.0, "topic_theta": {}, "se": 1.0},
        "lr": {"overall_rating": 1200, "rd": 350, "volatility": 0.06, "recent_sets": [], "question_type_ratings": {}},
        "di": {"overall_theta": 0.0, "chart_type_theta": {}, "se": 1.0, "recent_sets": []},
        "varc": {"alpha_vector": [0.5, 0.5, 0.5, 0.5, 0.5], "passage_mastery": {}, "seen_passages": []}
    }'::jsonb,

    behavioral_cluster VARCHAR(50),
    cluster_confidence DECIMAL(3,2),

    avg_response_time_ms INTEGER,
    accuracy_velocity DECIMAL(5,4),
    engagement_score DECIMAL(5,2),

    dfv_weights JSONB DEFAULT '{
        "accuracy": 0.4, "speed": 0.3, "consistency": 0.2, "decay": 0.1
    }'::jsonb,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ucp_user ON user_cognitive_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_ucp_theta ON user_cognitive_profiles(theta);
CREATE INDEX IF NOT EXISTS idx_ucp_cluster ON user_cognitive_profiles(behavioral_cluster);
CREATE INDEX IF NOT EXISTS idx_ucp_subject_profiles ON user_cognitive_profiles USING GIN (subject_profiles jsonb_path_ops);

-- ============================================================
-- 12g. PHASE-3 SET-ATTEMPT TABLES (shadow-mode data collection)
-- ============================================================

CREATE TABLE IF NOT EXISTS lr_set_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    stimulus_id VARCHAR(50) NOT NULL,
    score INTEGER CHECK (score BETWEEN 0 AND 6),
    total_questions INTEGER,
    time_spent_seconds INTEGER,
    difficulty_estimate FLOAT,
    question_types JSONB,
    diagram_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, stimulus_id, created_at)
);

CREATE INDEX IF NOT EXISTS idx_lr_attempts_user ON lr_set_attempts(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS di_set_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    chart_id VARCHAR(50) NOT NULL,
    score INTEGER CHECK (score BETWEEN 0 AND 5),
    total_questions INTEGER,
    time_spent_seconds INTEGER,
    chart_type VARCHAR(50),
    difficulty_estimate FLOAT,
    calculation_steps_used INTEGER,
    used_approximation BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, chart_id, created_at)
);

CREATE INDEX IF NOT EXISTS idx_di_attempts_user ON di_set_attempts(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS varc_passage_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    passage_id VARCHAR(50) NOT NULL,
    reading_time_seconds INTEGER,
    comprehension_score FLOAT CHECK (comprehension_score BETWEEN 0 AND 1),
    questions_correct INTEGER,
    questions_total INTEGER,
    skill_breakdown JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_varc_attempts_user ON varc_passage_attempts(user_id, created_at DESC);

-- ============================================================
-- 14. FEEDBACK CYCLE LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS feedback_cycle_log (
    cycle_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    feedback_path VARCHAR(50) NOT NULL CHECK (feedback_path IN (
        'problem_trap', 'difficulty_recalibration', 'content_addition',
        'trap_upgradation', 'cold_hot_promotion'
    )),
    trigger_reason TEXT,
    source_table VARCHAR(100),
    target_table VARCHAR(100),
    rows_processed INTEGER,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    outcome VARCHAR(20) CHECK (outcome IN ('success', 'partial', 'failed')),
    error_message TEXT,
    snapshot_window_start TIMESTAMPTZ,
    snapshot_window_end TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fcl_path ON feedback_cycle_log(feedback_path);
CREATE INDEX IF NOT EXISTS idx_fcl_outcome ON feedback_cycle_log(outcome);

-- ============================================================
-- TRIGGERS & FUNCTIONS (function defined BEFORE any trigger uses it —
-- the delivered v2.0 file had this ordering inverted)
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_uts_updated_at ON user_technique_states;
CREATE TRIGGER update_uts_updated_at BEFORE UPDATE ON user_technique_states
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_usm_updated_at ON user_subtopic_mastery;
CREATE TRIGGER update_usm_updated_at BEFORE UPDATE ON user_subtopic_mastery
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ucp_updated_at ON user_cognitive_profiles;
CREATE TRIGGER update_ucp_updated_at BEFORE UPDATE ON user_cognitive_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- After-attempt state recompute (vedic_speed_gym_backend.md §3.1 trigger;
-- SET expressions read pre-update column values, so accuracy math is correct)
CREATE OR REPLACE FUNCTION update_technique_state_after_attempt()
RETURNS TRIGGER AS $$
DECLARE
    current_state RECORD;
BEGIN
    SELECT * INTO current_state FROM user_technique_states
    WHERE user_id = NEW.user_id AND technique_id = NEW.technique_id;

    IF NOT FOUND THEN
        INSERT INTO user_technique_states (
            user_id, technique_id, state, mastery_score,
            total_attempts, total_correct, last_practiced_at
        ) VALUES (
            NEW.user_id, NEW.technique_id,
            CASE WHEN NEW.is_correct THEN 'fragile' ELSE 'fractured' END,
            CASE WHEN NEW.is_correct THEN 50 ELSE 30 END,
            1, CASE WHEN NEW.is_correct THEN 1 ELSE 0 END,
            NOW()
        );
    ELSE
        UPDATE user_technique_states SET
            total_attempts = total_attempts + 1,
            total_correct = total_correct + CASE WHEN NEW.is_correct THEN 1 ELSE 0 END,
            consecutive_correct = CASE WHEN NEW.is_correct THEN consecutive_correct + 1 ELSE 0 END,
            consecutive_errors = CASE WHEN NOT NEW.is_correct THEN consecutive_errors + 1 ELSE 0 END,
            accuracy_score = LEAST(100, ROUND(
                ((total_correct + CASE WHEN NEW.is_correct THEN 1 ELSE 0 END)::DECIMAL /
                 (total_attempts + 1)) * 100)),
            last_practiced_at = NOW(),
            decay_days = 0,
            state = CASE
                WHEN consecutive_errors >= 3 OR
                     (accuracy_score < 50 AND total_attempts > 5) THEN 'fractured'
                WHEN accuracy_score >= 80 AND consecutive_correct >= 5 THEN 'fluid'
                ELSE 'fragile'
            END,
            mastery_score = LEAST(100, ROUND(
                (accuracy_score * 0.6) +
                (CASE WHEN NEW.time_spent_seconds < NEW.target_time_seconds
                      THEN 40 ELSE 20 END)))
        WHERE id = current_state.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS after_attempt_update_state ON problem_attempts;
CREATE TRIGGER after_attempt_update_state
    AFTER INSERT ON problem_attempts
    FOR EACH ROW EXECUTE FUNCTION update_technique_state_after_attempt();
