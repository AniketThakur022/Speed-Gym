-- ============================================================================
-- VMSG migration 140 — mock exams (block 6). Scoring engine is pool-independent:
-- the questions an attempt was served are snapshotted here (with the correct
-- answers, which never leave the server) so scoring is reproducible whatever
-- pool they came from.
-- ============================================================================
ALTER TABLE mock_exam_attempts ADD COLUMN IF NOT EXISTS blueprint_key VARCHAR(20);
ALTER TABLE mock_exam_attempts ADD COLUMN IF NOT EXISTS sections JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE mock_exam_attempts ADD COLUMN IF NOT EXISTS time_limit_seconds INTEGER;
ALTER TABLE mock_exam_attempts ADD COLUMN IF NOT EXISTS timers_suppressed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE mock_exam_attempts ADD COLUMN IF NOT EXISTS late_answers INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mock_exam_attempts ADD COLUMN IF NOT EXISTS scaled_scores JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS mock_exam_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES mock_exam_attempts(id) ON DELETE CASCADE,
    section_key VARCHAR(20) NOT NULL,
    position SMALLINT NOT NULL,
    question_id VARCHAR(200) NOT NULL,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('mcq', 'tita', 'numeric', 'essay')),
    text TEXT NOT NULL,
    options JSONB,
    correct_answer TEXT,
    skill VARCHAR(160),
    difficulty NUMERIC(4,2),
    marks_correct NUMERIC(4,2) NOT NULL,
    marks_wrong NUMERIC(4,2) NOT NULL DEFAULT 0,
    UNIQUE (attempt_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_meq_attempt ON mock_exam_questions(attempt_id, section_key, position);

CREATE TABLE IF NOT EXISTS mock_exam_answers (
    attempt_id UUID NOT NULL REFERENCES mock_exam_attempts(id) ON DELETE CASCADE,
    question_id VARCHAR(200) NOT NULL,
    answer TEXT,
    time_ms INTEGER,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (attempt_id, question_id)
);

INSERT INTO feature_flags (flag_name, enabled, description) VALUES
    ('mock_exams', TRUE, 'Mock exam center (block 6): server-scored CAT/GMAT/GRE, pool pluggable')
ON CONFLICT (flag_name) DO NOTHING;
