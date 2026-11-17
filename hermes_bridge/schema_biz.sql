-- schema_biz.sql - every table the business side owns, in ~/.hermes-office/hermes.db.
--
-- Read by hermes_bridge/db.py (init_db) by path, not by working directory.
-- Additive only: no DROP here, ever. The office DB (chat.db) is untouched by
-- this file; its one extra table, biz_metrics, is created by server/biz-events.js.
-- The DLQ has its own file (dlq.db) and its own DDL in hermes_bridge/queue.py.

-- 3. Support tickets -------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body          TEXT,
    channel       TEXT DEFAULT 'email',      -- email | form | chat
    priority      TEXT DEFAULT 'normal',     -- low | normal | high | urgent
    status        TEXT DEFAULT 'open',       -- open | pending | resolved | escalated
    received_at   REAL NOT NULL,
    sla_deadline  REAL NOT NULL,
    resolved_at   REAL,
    assignee      TEXT,
    kb_article_id TEXT,
    updated_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_tickets_sla ON tickets (status, sla_deadline);

-- 4. User reports ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_reports (
    id          TEXT PRIMARY KEY,
    user_id     TEXT,
    episode_id  TEXT,
    category    TEXT,                        -- technical | account | content | spam
    description TEXT,
    status      TEXT DEFAULT 'pending',      -- pending | investigating | resolved | forwarded | dismissed
    resolved_at REAL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_episode ON user_reports (episode_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_status  ON user_reports (status, created_at);

-- 4b. Moderation log (Moderator, DB-SCHEMA.md §14) -------------------------
-- Append-only: a ban records the rule it broke and why (SECURITY.md §10).
-- Nothing in the codebase updates or deletes a row here.
CREATE TABLE IF NOT EXISTS moderation_events (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,               -- flag | ban | unflag
    user_id    TEXT,
    subject    TEXT,                        -- comment / item id
    rule       TEXT,                        -- piracy | abuse | spam | spoiler
    reason     TEXT,
    actor      TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moderation_user ON moderation_events (user_id, created_at);

-- 5. Episode schedule ------------------------------------------------------
CREATE TABLE IF NOT EXISTS episode_schedule (
    episode_id     TEXT PRIMARY KEY,
    anime_title    TEXT NOT NULL,
    episode_number INTEGER NOT NULL,
    encoded_path   TEXT NOT NULL,
    embargo_until  REAL NOT NULL,
    regions        TEXT DEFAULT '["*"]',
    status         TEXT DEFAULT 'scheduled', -- scheduled | live | cancelled | failed
    published_at   REAL,
    cancel_reason  TEXT,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedule_embargo ON episode_schedule (embargo_until, status);

-- 6. Subtitle tracks -------------------------------------------------------
CREATE TABLE IF NOT EXISTS subtitle_tracks (
    episode_id TEXT NOT NULL,
    lang       TEXT NOT NULL,               -- 'id', 'en', ...
    source     TEXT,                        -- source | deepl | openai | local
    path       TEXT NOT NULL,
    qa_score   REAL,
    status     TEXT DEFAULT 'ready',        -- ready | needs_review | approved | rejected
    updated_at REAL NOT NULL,
    PRIMARY KEY (episode_id, lang)
);

-- 7. Payments and subscriptions -------------------------------------------
CREATE TABLE IF NOT EXISTS payment_events (
    id             TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    amount_idr     INTEGER,
    payment_method TEXT,
    status         TEXT DEFAULT 'pending',  -- pending | processed | failed | refunded | chargeback
    processed_at   REAL,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payment_events (order_id);
CREATE INDEX IF NOT EXISTS idx_payments_user  ON payment_events (user_id, created_at);

CREATE TABLE IF NOT EXISTS subscription_status (
    user_id     TEXT PRIMARY KEY,
    plan        TEXT NOT NULL,              -- free | premium | premium_plus
    expires_at  REAL,
    retry_count INTEGER DEFAULT 0,
    grace_until REAL,
    updated_at  REAL
);

-- 8. Premium items ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS premium_items (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,           -- border | nameplate | profile_effect
    theme          TEXT,
    design_path    TEXT,
    preview_light  TEXT,
    preview_dark   TEXT,
    qa_score       REAL,
    tier           TEXT,                    -- basic | premium | deluxe
    price_idr      INTEGER,
    -- draft | qa_passed | priced | previewed | pending_approval | approved | rejected | live
    status         TEXT DEFAULT 'draft',
    created_at     REAL NOT NULL,
    updated_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_items_status ON premium_items (status, created_at);

-- 9. Knowledge base --------------------------------------------------------
-- FTS5 (DB-SCHEMA.md §9): `SupportAgent.search_kb` needs `MATCH` and bm25.
-- Ids are UNIQUE inside FTS5 tables too, and `SQLiteKB.upsert` deletes first.
CREATE VIRTUAL TABLE IF NOT EXISTS kb_articles USING fts5(
    id UNINDEXED, title, body, tags, category, updated_at UNINDEXED
);

CREATE TABLE IF NOT EXISTS kb_meta (
    id         TEXT PRIMARY KEY,
    source     TEXT,                        -- notion | markdown | manual
    url        TEXT,
    created_at REAL
);

-- 11. Shared context -------------------------------------------------------
-- Also created by hermes_bridge/shared_context.py in shared.db; kept here so a
-- single hermes.db can carry the same shape for tests and migrations.
CREATE TABLE IF NOT EXISTS context (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,                    -- JSON
    owner TEXT NOT NULL,                    -- the role that wrote it
    ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_ts ON context (ts);
