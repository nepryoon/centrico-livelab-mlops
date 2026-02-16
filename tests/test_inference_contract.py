import json
import os
import tempfile
import importlib

import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURES = [
    "stations_count", "free_bikes", "empty_slots", "total_slots", "free_ratio",
    "temp_2m", "precipitation", "wind_speed_10m",
]


def _build_test_model():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({
        "stations_count": rng.integers(10, 200, 300).astype(float),
        "free_bikes": rng.integers(0, 80, 300).astype(float),
        "empty_slots": rng.integers(0, 80, 300).astype(float),
        "total_slots": rng.integers(10, 120, 300).astype(float),
        "free_ratio": rng.random(300),
        "temp_2m": rng.normal(15, 7, 300),
        "precipitation": np.clip(rng.normal(0.5, 1.0, 300), 0, None),
        "wind_speed_10m": np.clip(rng.normal(10, 4, 300), 0, None),
    })
    y = (X["free_ratio"] < 0.3).astype(int).values

    pre = ColumnTransformer([("num", StandardScaler(), FEATURES)], remainder="drop")
    clf = LogisticRegression(max_iter=300, class_weight="balanced")
    pipe = Pipeline([("pre", pre), ("clf", clf)])
    pipe.fit(X[FEATURES], y)
    return pipe


def test_inference_predict_with_artifacts():
    with tempfile.TemporaryDirectory() as td:
        model = _build_test_model()

        with open(os.path.join(td, "metadata.json"), "w") as f:
            json.dump({"model_version": "test-0", "features": FEATURES}, f)

        joblib.dump(model, os.path.join(td, "model.joblib"))

        # Ensure module reads ARTIFACT_DIR at import time
        os.environ["ARTIFACT_DIR"] = td

        from services.inference.app import main as inf_main
        importlib.reload(inf_main)

        # IMPORTANT: use context manager so startup event runs (model loads)
        with TestClient(inf_main.app) as client:
            r = client.get("/model")
            assert r.status_code == 200
            assert r.json()["version"] == "test-0"

            payload = {f: 1.0 for f in FEATURES}
            payload["free_ratio"] = 0.1

            r = client.post("/predict", json={"features": payload})
            assert r.status_code == 200
            out = r.json()
            assert "proba" in out and "y" in out and out["version"] == "test-0"
            assert 0.0 <= out["proba"] <= 1.0
