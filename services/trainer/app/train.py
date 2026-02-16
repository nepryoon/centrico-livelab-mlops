import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import joblib
import numpy as np
import pandas as pd
import psycopg2
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


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


def ensure_dict(x: Any) -> Dict[str, Any]:
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        return json.loads(x)
    return json.loads(json.dumps(x))


def bikes_features(payload: Dict[str, Any]) -> Dict[str, float]:
    network = payload.get("network", {})
    stations = network.get("stations", []) or []

    free = 0.0
    empty = 0.0
    for s in stations:
        fb = s.get("free_bikes")
        es = s.get("empty_slots")
        if fb is not None:
            free += float(fb)
        if es is not None:
            empty += float(es)

    total = free + empty
    free_ratio = free / total if total > 0 else 0.0

    return {
        "stations_count": float(len(stations)),
        "free_bikes": free,
        "empty_slots": empty,
        "total_slots": total,
        "free_ratio": free_ratio,
    }


def weather_features(payload: Dict[str, Any]) -> Dict[str, float]:
    cur = payload.get("current", {}) or {}
    return {
        "temp_2m": float(cur.get("temperature_2m", 0.0) or 0.0),
        "precipitation": float(cur.get("precipitation", 0.0) or 0.0),
        "wind_speed_10m": float(cur.get("wind_speed_10m", 0.0) or 0.0),
    }


def load_raw_from_db() -> pd.DataFrame:
    with get_pg_conn() as conn:
        bikes = pd.read_sql_query(
            "SELECT ingested_at, network_id, payload FROM raw_bikes ORDER BY ingested_at ASC;",
            conn,
        )
        weather = pd.read_sql_query(
            "SELECT ingested_at, lat, lon, payload FROM raw_weather ORDER BY ingested_at ASC;",
            conn,
        )

    bikes["ingested_at"] = pd.to_datetime(bikes["ingested_at"], utc=True)
    weather["ingested_at"] = pd.to_datetime(weather["ingested_at"], utc=True)

    bikes["payload"] = bikes["payload"].apply(ensure_dict)
    weather["payload"] = weather["payload"].apply(ensure_dict)

    bikes_feat = bikes["payload"].apply(bikes_features).apply(pd.Series)
    weather_feat = weather["payload"].apply(weather_features).apply(pd.Series)

    bikes_df = pd.concat([bikes[["ingested_at"]], bikes_feat], axis=1).sort_values("ingested_at")
    weather_df = pd.concat([weather[["ingested_at"]], weather_feat], axis=1).sort_values("ingested_at")

    merged = pd.merge_asof(
        bikes_df,
        weather_df,
        on="ingested_at",
        direction="backward",
        tolerance=pd.Timedelta("30min"),
    ).fillna(0.0)

    return merged


def make_synthetic_df(n_samples: int, seed: int = 42) -> Tuple[pd.DataFrame, np.ndarray, Dict[str, Any]]:
    rng = np.random.default_rng(seed)

    # Two-mode free_ratio distribution -> balanced classes with fixed threshold
    free_ratio = np.concatenate([
        rng.normal(0.08, 0.03, n_samples // 2),
        rng.normal(0.65, 0.10, n_samples - n_samples // 2),
    ])
    free_ratio = np.clip(free_ratio, 0.0, 1.0)

    total_slots = rng.integers(20, 80, size=n_samples).astype(float)
    free_bikes = np.clip(np.round(free_ratio * total_slots), 0, total_slots)
    empty_slots = total_slots - free_bikes
    stations_count = rng.integers(10, 200, size=n_samples).astype(float)

    temp_2m = rng.normal(15, 7, size=n_samples)
    precipitation = np.clip(rng.normal(0.5, 1.0, size=n_samples), 0, None)
    wind_speed_10m = np.clip(rng.normal(10, 4, size=n_samples), 0, None)

    df = pd.DataFrame({
        "stations_count": stations_count,
        "free_bikes": free_bikes,
        "empty_slots": empty_slots,
        "total_slots": total_slots,
        "free_ratio": free_ratio,
        "temp_2m": temp_2m,
        "precipitation": precipitation,
        "wind_speed_10m": wind_speed_10m,
    })

    # Synthetic ground truth
    thr = 0.30
    y = (df["free_ratio"] < thr).astype(int).values
    meta = {"target_rule": f"free_ratio < {thr} (synthetic)", "rule_name": "synthetic_fixed", "threshold": thr}
    return df, y, meta


def train_and_save(X: pd.DataFrame, y: np.ndarray, artifact_dir: str, target_meta: Dict[str, Any]):
    os.makedirs(artifact_dir, exist_ok=True)

    feature_cols = [
        "stations_count", "free_bikes", "empty_slots", "total_slots", "free_ratio",
        "temp_2m", "precipitation", "wind_speed_10m",
    ]

    X = X[feature_cols].astype(float)

    counts = np.bincount(y, minlength=2)
    print(f"[INFO] Class distribution: class0={counts[0]}, class1={counts[1]}")
    print(f"[INFO] Target: {target_meta}")

    strat = y if counts.min() >= 2 else None
    if strat is None:
        print("[WARN] Not enough samples per class for stratify; using non-stratified split.")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=strat
    )

    pre = ColumnTransformer(
        transformers=[("num", StandardScaler(), feature_cols)],
        remainder="drop",
    )

    clf = LogisticRegression(max_iter=500, class_weight="balanced")
    pipe = Pipeline([("pre", pre), ("clf", clf)])
    pipe.fit(X_train, y_train)

    proba = pipe.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)

    f1 = float(f1_score(y_test, pred, zero_division=0))
    try:
        auc = float(roc_auc_score(y_test, proba))
    except ValueError:
        auc = float("nan")

    model_version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    model_path = os.path.join(artifact_dir, "model.joblib")
    metrics_path = os.path.join(artifact_dir, "metrics.json")
    meta_path = os.path.join(artifact_dir, "metadata.json")

    joblib.dump(pipe, model_path)

    with open(metrics_path, "w") as f:
        json.dump(
            {"f1": f1, "roc_auc": auc, "n_samples": int(len(X)), "threshold": 0.5},
            f,
            indent=2,
        )

    with open(meta_path, "w") as f:
        json.dump(
            {"model_version": model_version, "features": feature_cols, **target_meta},
            f,
            indent=2,
        )

    print(f"[OK] Trained model. version={model_version}")
    print(f"[OK] Saved: {model_path}")
    print(f"[OK] Metrics: f1={f1:.4f}, auc={auc:.4f}, n={len(X)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="Train on synthetic data (CI-friendly)")
    ap.add_argument("--n-samples", type=int, default=400, help="Synthetic sample size")
    ap.add_argument("--artifact-dir", type=str, default=os.getenv("ARTIFACT_DIR", "/artifacts"))
    args = ap.parse_args()

    if args.synthetic:
        df, y, meta = make_synthetic_df(args.n_samples)
        train_and_save(df, y, args.artifact_dir, meta)
        return

    df = load_raw_from_db()
    if len(df) < 20:
        raise SystemExit(
            f"[ERROR] Not enough samples in DB: {len(df)}. Run ingestion multiple times (>=20) and retry."
        )

    # DB mode target: adaptive threshold (same as before)
    fr = df["free_ratio"].astype(float)
    thr = float(fr.quantile(0.20))
    y = (fr < thr).astype(int).values
    meta = {"target_rule": f"free_ratio < {thr:.6f}", "rule_name": "q20", "threshold": thr}

    train_and_save(df, y, args.artifact_dir, meta)


if __name__ == "__main__":
    main()
