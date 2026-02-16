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
