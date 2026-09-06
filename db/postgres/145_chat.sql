-- ============================================================================
-- VMSG migration 145 — study chatbot (block 7): hints only, NO RAG (owner,
-- 2026-09-02), online-only, isolated from the game loop. Token budget +
-- cost ledger (RAG-EXP-01/02 "token-budget limiter + cost dashboard").
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_usage (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    hint_requests INTEGER NOT NULL DEFAULT 0,
    llm_requests INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS chat_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template_id VARCHAR(200) NOT NULL,
    mode VARCHAR(12) NOT NULL CHECK (mode IN ('hint_ladder', 'llm', 'refused')),
    level SMALLINT,
    model VARCHAR(60),
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    leak_redacted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_log_user ON chat_log(user_id, created_at DESC);

INSERT INTO feature_flags (flag_name, enabled, description) VALUES
    ('chatbot',     TRUE,  'Study chatbot: deterministic hint ladder from solution steps (block 7)'),
    ('chatbot_llm', FALSE, 'Chatbot LLM path (Claude, hints only, budgeted) — dark until the owner key + copy are in place')
ON CONFLICT (flag_name) DO NOTHING;
