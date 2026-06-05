-- Pattern Proof initial schema
-- Apply via Supabase SQL editor or CLI

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- Users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT        UNIQUE NOT NULL,
    password_hash   TEXT        NOT NULL,
    display_name    TEXT,
    role            TEXT        NOT NULL DEFAULT 'user'
                                CHECK (role IN ('user', 'admin', 'dev')),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Refresh tokens
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);

-- ---------------------------------------------------------------------------
-- Audits
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audits (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    url                 TEXT        NOT NULL,
    normalized_domain   TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'created',
    config_json         JSONB       NOT NULL DEFAULT '{}',
    progress_percent    FLOAT       NOT NULL DEFAULT 0.0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    error_message       TEXT
);
CREATE INDEX IF NOT EXISTS idx_audits_user_id ON audits(user_id);
CREATE INDEX IF NOT EXISTS idx_audits_status  ON audits(status);

-- ---------------------------------------------------------------------------
-- Audit tasks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_tasks (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id        UUID        NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    task_type       TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'queued',
    worker_id       TEXT,
    input_json      JSONB       DEFAULT '{}',
    output_json     JSONB       DEFAULT '{}',
    attempts        INT         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_tasks_audit_id ON audit_tasks(audit_id);

-- ---------------------------------------------------------------------------
-- Findings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS findings (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id                UUID        NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    pattern                 TEXT        NOT NULL,
    taxonomy_scope          JSONB       NOT NULL DEFAULT '[]',
    category                TEXT        NOT NULL,
    severity                TEXT        NOT NULL
                                        CHECK (severity IN ('low','medium','high','critical')),
    confidence              FLOAT       NOT NULL,
    title                   TEXT        NOT NULL,
    summary                 TEXT        NOT NULL,
    affected_urls           JSONB       NOT NULL DEFAULT '[]',
    evidence_ids            JSONB       NOT NULL DEFAULT '[]',
    reproduction_steps      JSONB       NOT NULL DEFAULT '[]',
    remediation             JSONB       NOT NULL DEFAULT '[]',
    requires_human_review   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_findings_audit_id ON findings(audit_id);

-- ---------------------------------------------------------------------------
-- Reports
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id                UUID        NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    format                  TEXT        NOT NULL
                                        CHECK (format IN ('json','markdown','pdf')),
    report_uri              TEXT        NOT NULL,
    signed_url_expires_at   TIMESTAMPTZ,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reports_audit_id ON reports(audit_id);
