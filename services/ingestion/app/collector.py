import argparse
import json
import os
import time
from typing import Any, Dict

import psycopg2
import requests


def env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def get_pg_conn():
    return psycopg2.connect(
        host=env("POSTGRES_HOST", "localhost"),
        port=int(env("POSTGRES_PORT", "5432")),
        dbname=env("POSTGRES_DB", "livelab"),
        user=env("POSTGRES_USER", "app"),
        password=env("POSTGRES_PASSWORD", "app"),
    )


def fetch_bikes(network_id: str) -> Dict[str, Any]:
    url = f"https://api.citybik.es/v2/networks/{network_id}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_weather(lat: float, lon: float) -> Dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,precipitation,wind_speed_10m"
        "&timezone=auto"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def insert_json(cur, table: str, cols: tuple[str, ...], values: tuple[Any, ...]):
    placeholders = ", ".join(["%s"] * len(values))
    colnames = ", ".join(cols)
    sql = f"INSERT INTO {table} ({colnames}) VALUES ({placeholders})"
    cur.execute(sql, values)


def run_once():
    network_id = env("BIKE_NETWORK_ID", "bicincitta-siena")
    lat = float(env("LAT", "45.0703"))
    lon = float(env("LON", "7.6869"))

    bikes = fetch_bikes(network_id)
    weather = fetch_weather(lat, lon)

    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            insert_json(cur, "raw_bikes", ("network_id", "payload"), (network_id, json.dumps(bikes)))
            insert_json(cur, "raw_weather", ("lat", "lon", "payload"), (lat, lon, json.dumps(weather)))
        conn.commit()

    print(f"[OK] Inserted 1 row into raw_bikes ({network_id}) and raw_weather ({lat},{lon})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Run a single ingestion cycle")
    ap.add_argument("--loop", action="store_true", help="Run forever")
    ap.add_argument("--sleep", type=int, default=300, help="Sleep seconds between cycles (loop mode)")
    args = ap.parse_args()

    if args.once:
        run_once()
        return

    if args.loop:
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[ERROR] ingestion failed: {e}")
            time.sleep(args.sleep)
        return

    ap.error("Specify --once or --loop")


if __name__ == "__main__":
    main()
