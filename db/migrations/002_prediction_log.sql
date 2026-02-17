CREATE TABLE IF NOT EXISTS prediction_log (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    input_json      JSONB       NOT NULL,
    predicted_class INTEGER     NOT NULL,
    probability     FLOAT       NOT NULL,
    model_version   TEXT        NOT NULL,
    latency_ms      FLOAT
);
CREATE INDEX IF NOT EXISTS idx_prediction_log_ts    ON prediction_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_log_class ON prediction_log (predicted_class);
