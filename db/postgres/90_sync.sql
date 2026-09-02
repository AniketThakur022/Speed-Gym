-- ============================================================================
-- VMSG migration 90 — sync support: the Postgres→Neo4j outbox and the one
-- offline mutation the client replays.
-- ============================================================================

-- Path C bridge. Graph intent is written inside the same transaction as the
-- ledger row, then drained by a worker — so a Neo4j outage delays edges but
-- can never lose a ledger write (architecture §5.5).
CREATE TABLE IF NOT EXISTS sync_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id VARCHAR(64) NOT NULL UNIQUE,   -- same idempotency key as raw_events
    event_type VARCHAR(60) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'drained', 'failed')),
    attempts SMALLINT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    drained_at TIMESTAMPTZ
);

-- The drain worker's hot path: oldest pending first.
CREATE INDEX IF NOT EXISTS idx_sync_outbox_pending
    ON sync_outbox(created_at) WHERE status = 'pending';

-- Human-in-the-loop content reports, replayed from the client's Dexie queue
-- via POST /api/v1/sync/content/feedback. Feeds the trust ladder.
CREATE TABLE IF NOT EXISTS content_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template_id VARCHAR(200) NOT NULL,
    -- Trust tier the client held when it served the item: a report against
    -- sandbox content means something different from one against trusted.
    trust_status VARCHAR(40),
    reason VARCHAR(40),
    comment TEXT,
    domain VARCHAR(40),
    reported_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    resolution VARCHAR(30) DEFAULT 'open'
        CHECK (resolution IN ('open', 'confirmed', 'rejected', 'duplicate'))
);

CREATE INDEX IF NOT EXISTS idx_content_feedback_template ON content_feedback(template_id);
CREATE INDEX IF NOT EXISTS idx_content_feedback_open
    ON content_feedback(received_at DESC) WHERE resolution = 'open';
