-- ============================================================================
-- VMSG migration 100 — gaming tables written by the Internal API
-- The Node game server never touches Postgres directly; it POSTs results to
-- FastAPI over loopback and these tables are written here.
-- ============================================================================

CREATE TABLE IF NOT EXISTS game_matches (
    match_id VARCHAR(40) PRIMARY KEY,          -- ad_YYYYMMDD_NNN
    mode VARCHAR(30) NOT NULL CHECK (mode IN (
        'speed_race', 'accuracy_duel', 'boss_battle', 'relay_race', 'tournament'
    )),
    topology VARCHAR(20) NOT NULL DEFAULT 'online' CHECK (topology IN (
        'online', 'pass_and_play', 'hotspot', 'qr_nearby'
    )),
    -- 'countdown'/'paused' are Redis-only phases and deliberately absent here.
    status VARCHAR(20) NOT NULL DEFAULT 'completed' CHECK (status IN (
        'lobby', 'active', 'completed', 'aborted'
    )),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_ms INTEGER,
    target_problems INTEGER,
    difficulty_range NUMERIC(4,2)[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_game_matches_mode ON game_matches(mode, created_at DESC);

CREATE TABLE IF NOT EXISTS player_match_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id VARCHAR(40) NOT NULL REFERENCES game_matches(match_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Bot identity is INTERNAL ONLY and must be stripped at the API boundary.
    is_bot BOOLEAN NOT NULL DEFAULT FALSE,
    bot_persona VARCHAR(30),

    final_rank SMALLINT NOT NULL,
    final_score INTEGER NOT NULL,
    position_points SMALLINT,
    accuracy_bonus INTEGER,

    problems_attempted SMALLINT DEFAULT 0,
    problems_correct SMALLINT DEFAULT 0,
    accuracy_pct NUMERIC(5,2),
    avg_time_ms INTEGER,
    fastest_time_ms INTEGER,
    slowest_time_ms INTEGER,
    traps_triggered SMALLINT DEFAULT 0,
    combo_max SMALLINT DEFAULT 0,

    elo_before INTEGER,
    elo_after INTEGER,
    elo_change INTEGER,

    theta_u_snapshot NUMERIC(6,4),
    cluster_snapshot VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(match_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_pmr_user ON player_match_results(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS player_elo_ratings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mode VARCHAR(30) NOT NULL DEFAULT 'accuracy_duel',
    -- Seeded from theta on first insert (1000 + 400*theta, clamped); the 1500
    -- default only applies to rows created without an ability estimate.
    rating INTEGER NOT NULL DEFAULT 1500,
    rating_deviation INTEGER NOT NULL DEFAULT 350,
    volatility NUMERIC(6,5) NOT NULL DEFAULT 0.06000,
    matches_played INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_elo_leaderboard ON player_elo_ratings(mode, rating DESC);

-- Which problem each player saw, in their own shuffled order (anti-screen-peek).
CREATE TABLE IF NOT EXISTS match_problem_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id VARCHAR(40) NOT NULL REFERENCES game_matches(match_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    problem_id VARCHAR(200) NOT NULL,
    sequence_index SMALLINT NOT NULL,
    difficulty NUMERIC(4,2),
    answered_correctly BOOLEAN,
    time_ms INTEGER,
    anti_cheat_flag VARCHAR(30),          -- IMPOSSIBLE_SPEED | TIMING_ANOMALY
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mpa_match ON match_problem_assignments(match_id);
-- Flagged submissions are the review queue; keep them cheap to find.
CREATE INDEX IF NOT EXISTS idx_mpa_flagged
    ON match_problem_assignments(created_at DESC) WHERE anti_cheat_flag IS NOT NULL;
