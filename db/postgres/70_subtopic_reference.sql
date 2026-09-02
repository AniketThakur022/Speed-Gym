-- PostgreSQL extension: Subtopic Reference Library tables
-- Adds subtopic-level Quick Ref storage and links to existing problems/templates.
-- Run this after the main webapp_brain schema is in place.

-- 1. Subtopic reference table (one row per subtopic-level Quick Ref Card)
CREATE TABLE IF NOT EXISTS topic_browser_subtopics (
    subtopic_id          VARCHAR(64) PRIMARY KEY,
    category             VARCHAR(32) NOT NULL,
    topic                VARCHAR(64) NOT NULL,
    sutra                VARCHAR(128),
    sutra_sanskrit       VARCHAR(256),
    translation          TEXT,
    applicability_type   VARCHAR(32) NOT NULL,
    quick_ref_json       JSONB NOT NULL,
    techniques_json      JSONB NOT NULL,
    total_techniques     INTEGER NOT NULL DEFAULT 0,
    total_templates      INTEGER NOT NULL DEFAULT 0,
    metadata_json        JSONB NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookups by topic/category and content status
CREATE INDEX IF NOT EXISTS idx_subtopics_topic
    ON topic_browser_subtopics(topic);
CREATE INDEX IF NOT EXISTS idx_subtopics_category
    ON topic_browser_subtopics(category);
CREATE INDEX IF NOT EXISTS idx_subtopics_applicability
    ON topic_browser_subtopics(applicability_type);
CREATE INDEX IF NOT EXISTS idx_subtopics_metadata_status
    ON topic_browser_subtopics USING GIN ((metadata_json -> 'content_status'));

-- 2. Junction: subtopic -> problem/template records (maps to existing problems table)
CREATE TABLE IF NOT EXISTS topic_browser_subtopic_templates (
    id              BIGSERIAL PRIMARY KEY,
    subtopic_id     VARCHAR(64) NOT NULL REFERENCES topic_browser_subtopics(subtopic_id) ON DELETE CASCADE,
    difficulty_level VARCHAR(8) NOT NULL,  -- L1..L5
    template_id     VARCHAR(128),          -- optional reference to existing template
    problem_id      UUID,                   -- optional reference to problems.id
    technique_id    VARCHAR(128),
    source          VARCHAR(32) NOT NULL DEFAULT 'static_bank', -- static_bank | generative | replenishment
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subtopic_templates_subtopic
    ON topic_browser_subtopic_templates(subtopic_id, difficulty_level);
CREATE INDEX IF NOT EXISTS idx_subtopic_templates_problem
    ON topic_browser_subtopic_templates(problem_id);

-- 3. User mastery snapshot per subtopic (feeds bank exhaustion handler)
CREATE TABLE IF NOT EXISTS topic_browser_subtopic_mastery (
    user_id         VARCHAR(128) NOT NULL,
    subtopic_id     VARCHAR(64) NOT NULL REFERENCES topic_browser_subtopics(subtopic_id) ON DELETE CASCADE,
    mastery_score   NUMERIC(4,3) NOT NULL DEFAULT 0.0,
    streak          INTEGER NOT NULL DEFAULT 0,
    fluid_count     INTEGER NOT NULL DEFAULT 0,
    fragile_count   INTEGER NOT NULL DEFAULT 0,
    fractured_count INTEGER NOT NULL DEFAULT 0,
    context_path    VARCHAR(32) NOT NULL DEFAULT 'foundation',  -- cross-category tracking
    last_seen_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, subtopic_id, context_path)
);

-- 3b. Individual template progress (7-day dedup window)
CREATE TABLE IF NOT EXISTS user_template_progress (
    user_id         VARCHAR(128) NOT NULL,
    template_id     VARCHAR(128) NOT NULL,
    subtopic_id     VARCHAR(64) NOT NULL,
    context_path    VARCHAR(32) NOT NULL DEFAULT 'foundation',
    times_seen      INTEGER DEFAULT 1,
    times_correct   INTEGER DEFAULT 0,
    times_incorrect INTEGER DEFAULT 0,
    last_seen_at    TIMESTAMPTZ DEFAULT NOW(),
    mastery_achieved BOOLEAN DEFAULT false,
    params_hash     VARCHAR(64),  -- md5 of problem params for dedup
    PRIMARY KEY (user_id, template_id, context_path)
);

CREATE INDEX IF NOT EXISTS idx_template_progress_user
    ON user_template_progress(user_id, subtopic_id);
CREATE INDEX IF NOT EXISTS idx_template_progress_seen
    ON user_template_progress(user_id, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_template_progress_params
    ON user_template_progress(user_id, params_hash);

-- View: done templates (auto-exclude from session creation)
CREATE OR REPLACE VIEW user_done_templates AS
SELECT user_id, template_id, subtopic_id
FROM user_template_progress
WHERE mastery_achieved = true
   OR (times_correct >= 3 AND times_incorrect = 0);

-- View: recently seen templates (7-day dedup window)
CREATE OR REPLACE VIEW user_recently_seen AS
SELECT user_id, template_id
FROM user_template_progress
WHERE last_seen_at > NOW() - INTERVAL '7 days';

-- View: dedup params (same problem, different template_id)
CREATE OR REPLACE VIEW user_params_dedup AS
SELECT DISTINCT user_id, params_hash
FROM user_template_progress
WHERE last_seen_at > NOW() - INTERVAL '7 days';

-- 4. Trigger to keep updated_at fresh
CREATE OR REPLACE FUNCTION topic_browser_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_subtopics_touch_updated_at'
          AND tgrelid = 'topic_browser_subtopics'::regclass
    ) THEN
        CREATE TRIGGER trg_subtopics_touch_updated_at
        BEFORE UPDATE ON topic_browser_subtopics
        FOR EACH ROW
        EXECUTE FUNCTION topic_browser_touch_updated_at();
    END IF;
END $$;

-- 5. Helper view: subtopic readiness summary
CREATE OR REPLACE VIEW topic_browser_subtopic_readiness AS
SELECT
    s.subtopic_id,
    s.topic,
    s.category,
    s.applicability_type,
    s.total_techniques,
    s.total_templates,
    s.metadata_json ->> 'content_status' AS content_status,
    s.metadata_json ->> 'review_status' AS review_status,
    (s.metadata_json ->> 'completeness_score')::NUMERIC AS completeness_score,
    COUNT(t.id) AS attached_templates
FROM topic_browser_subtopics s
LEFT JOIN topic_browser_subtopic_templates t
    ON t.subtopic_id = s.subtopic_id
GROUP BY s.subtopic_id;

-- 6. Sample load from JSON files (optional, run after import)
-- COPY topic_browser_subtopics(subtopic_id, category, topic, sutra, sutra_sanskrit,
--                              translation, applicability_type, quick_ref_json,
--                              techniques_json, total_techniques, total_templates, metadata_json)
-- FROM '/docker-entrypoint-initdb.d/subtopic_explainers.jsonl' (FORMAT jsonlines);
