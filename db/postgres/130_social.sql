-- ============================================================================
-- VMSG migration 130 — social / gamification / COPPA kids mode (block 5)
-- Basic social per architecture §9.2 Phase 1: friends, leaderboards, QR
-- pairing, ghost recording, shareable clips, comedy taunts, daily challenge;
-- XP + streaks + achievements; kids-mode fields (FAM-05 / SEC-08).
-- ============================================================================

CREATE TABLE IF NOT EXISTS friendships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    addressee_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'blocked')),
    source VARCHAR(10) NOT NULL DEFAULT 'request' CHECK (source IN ('request', 'qr')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    CHECK (requester_id <> addressee_id)
);
-- One row per pair, whichever direction it was requested in.
CREATE UNIQUE INDEX IF NOT EXISTS idx_friendships_pair
    ON friendships (LEAST(requester_id, addressee_id), GREATEST(requester_id, addressee_id));
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships(addressee_id, status);

CREATE TABLE IF NOT EXISTS user_xp (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_xp_rank ON user_xp(xp DESC);

-- Every award is keyed (user, reason, ref) so a replayed sync batch or a
-- redelivered match result can never pay twice.
CREATE TABLE IF NOT EXISTS xp_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delta INTEGER NOT NULL,
    reason VARCHAR(40) NOT NULL,
    ref VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, reason, ref)
);

CREATE TABLE IF NOT EXISTS streaks (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    last_activity_date DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS streak_days (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_date DATE NOT NULL,
    problems INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, activity_date)
);

CREATE TABLE IF NOT EXISTS achievements_unlocked (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    achievement_key VARCHAR(40) NOT NULL,
    unlocked_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, achievement_key)
);

-- Ghost = a recorded solo run: problem ids + per-problem times, no identity.
CREATE TABLE IF NOT EXISTS ghost_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain VARCHAR(20) NOT NULL DEFAULT 'vedic-math',
    skill VARCHAR(160),
    problem_ids JSONB NOT NULL,
    answer_times_ms JSONB NOT NULL,
    correct JSONB NOT NULL,
    trap_triggers JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_time_ms INTEGER NOT NULL,
    problems_correct INTEGER NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '30 days'
);
CREATE INDEX IF NOT EXISTS idx_ghost_sessions_user ON ghost_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ghost_sessions_public ON ghost_sessions(is_public, created_at DESC) WHERE is_public;

CREATE TABLE IF NOT EXISTS ghost_races (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ghost_id UUID NOT NULL REFERENCES ghost_sessions(id) ON DELETE CASCADE,
    challenger_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    challenger_time_ms INTEGER NOT NULL,
    challenger_correct INTEGER NOT NULL,
    won BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Daily challenge: same 10 problems for everyone, server-scored, NEVER bots.
-- Answers live here and are never sent to a client.
CREATE TABLE IF NOT EXISTS daily_challenges (
    challenge_date DATE PRIMARY KEY,
    domain VARCHAR(20) NOT NULL DEFAULT 'vedic-math',
    problems JSONB NOT NULL,          -- [{problem_id, text, difficulty}]
    answers JSONB NOT NULL,           -- [number] aligned with problems
    seed VARCHAR(64) NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_challenge_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_date DATE NOT NULL REFERENCES daily_challenges(challenge_date) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problems_correct INTEGER NOT NULL,
    problems_total INTEGER NOT NULL,
    total_time_ms INTEGER NOT NULL,
    score INTEGER NOT NULL,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (challenge_date, user_id)
);
CREATE INDEX IF NOT EXISTS idx_dca_rank ON daily_challenge_attempts(challenge_date, score DESC, submitted_at);

-- Shareable clips need DUAL consent; opponents are anonymised (SOC-18).
CREATE TABLE IF NOT EXISTS clips (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id VARCHAR(40) NOT NULL REFERENCES game_matches(match_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opponent_id UUID REFERENCES users(id) ON DELETE SET NULL,
    owner_consent BOOLEAN NOT NULL DEFAULT TRUE,
    opponent_consent BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'revoked')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, owner_id)
);

CREATE TABLE IF NOT EXISTS taunt_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_id VARCHAR(40) NOT NULL,
    taunt_id VARCHAR(40) NOT NULL,
    text TEXT NOT NULL,
    shown_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, match_id)
);

-- Kids mode (FAM-05 / SEC-08): session cap 10 min, parent may raise to 20.
ALTER TABLE family_seats ADD COLUMN IF NOT EXISTS session_cap_minutes SMALLINT NOT NULL DEFAULT 10
    CHECK (session_cap_minutes BETWEEN 1 AND 20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS taunts_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ghosts_public_default BOOLEAN NOT NULL DEFAULT FALSE;
