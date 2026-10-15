-- ClaimStream operational schema (PostgreSQL 16)

CREATE TABLE IF NOT EXISTS policies (
    policy_id          BIGINT PRIMARY KEY,
    policy_start       DATE        NOT NULL,
    exposure           REAL        NOT NULL,
    veh_power          SMALLINT,
    veh_age            SMALLINT,
    driv_age           SMALLINT,
    bonus_malus        SMALLINT,
    veh_brand          TEXT,
    veh_gas            TEXT,
    area               CHAR(1),
    density            INTEGER,
    region             TEXT        NOT NULL,
    bank_account_hash  TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_policies_bank ON policies (bank_account_hash);

CREATE TABLE IF NOT EXISTS claims (
    claim_id        TEXT PRIMARY KEY,
    policy_id       BIGINT      NOT NULL REFERENCES policies (policy_id),
    loss_ts         TIMESTAMPTZ NOT NULL,
    reported_ts     TIMESTAMPTZ NOT NULL,
    amount          NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    claim_type      TEXT        NOT NULL,
    channel         TEXT        NOT NULL,
    source          TEXT        NOT NULL DEFAULT 'live',   -- 'history' | 'live'
    fraud_label     BOOLEAN,                               -- synthetic ground truth (see README)
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reported_ts >= loss_ts)
);
CREATE INDEX IF NOT EXISTS ix_claims_policy_loss ON claims (policy_id, loss_ts);
CREATE INDEX IF NOT EXISTS ix_claims_reported ON claims (reported_ts);

CREATE TABLE IF NOT EXISTS claim_scores (
    claim_id       TEXT PRIMARY KEY REFERENCES claims (claim_id),
    model_score    REAL        NOT NULL,
    rule_score     SMALLINT    NOT NULL,
    rules_hit      TEXT[]      NOT NULL DEFAULT '{}',
    risk_level     TEXT        NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH')),
    model_version  TEXT        NOT NULL,
    latency_ms     REAL,
    scored_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_scores_risk ON claim_scores (risk_level, scored_at DESC);

CREATE TABLE IF NOT EXISTS dead_letters (
    id          BIGSERIAL PRIMARY KEY,
    payload     JSONB       NOT NULL,
    error       TEXT        NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Written by the Spark batch job
CREATE TABLE IF NOT EXISTS daily_claims (
    claim_date     DATE   NOT NULL,
    region         TEXT   NOT NULL,
    n_claims       INTEGER NOT NULL,
    total_amount   NUMERIC(14,2) NOT NULL,
    avg_amount     NUMERIC(12,2) NOT NULL,
    fraud_rate     REAL,
    PRIMARY KEY (claim_date, region)
);

-- Written by the forecasting job
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_date  DATE  NOT NULL,
    model          TEXT  NOT NULL,
    yhat           REAL  NOT NULL,
    yhat_lo        REAL,
    yhat_hi        REAL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (forecast_date, model)
);

CREATE TABLE IF NOT EXISTS model_metrics (
    model_name   TEXT NOT NULL,
    version      TEXT NOT NULL,
    metric       TEXT NOT NULL,
    value        REAL NOT NULL,
    logged_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (model_name, version, metric)
);
