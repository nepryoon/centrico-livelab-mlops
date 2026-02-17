CREATE TABLE IF NOT EXISTS raw_bikes (
  id BIGSERIAL PRIMARY KEY,
  network_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_bikes_network_time
  ON raw_bikes (network_id, ingested_at DESC);

CREATE TABLE IF NOT EXISTS raw_weather (
  id BIGSERIAL PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  payload JSONB NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_weather_time
  ON raw_weather (ingested_at DESC);

-- Prediction logging table
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
