import json
import os
import time
from typing import Any, Dict, Optional, Tuple

import joblib
import pandas as pd
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

# OpenAI (optional at runtime: endpoint /explain works even without a key)
try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


app = FastAPI(title="Centrico LiveLab - Inference API", version="0.2.3")

# Dedicated registry to avoid duplicated metrics on module reload (CI/tests)
REGISTRY = CollectorRegistry()
REQ_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["endpoint", "status"],
    registry=REGISTRY,
)
REQ_LAT = Histogram(
    "http_request_duration_seconds",
    "Request latency (seconds)",
    ["endpoint"],
    registry=REGISTRY,
)
MODEL_LOADED = Gauge("model_loaded", "1 if a model is loaded, else 0", registry=REGISTRY)
MODEL_VERSION_INFO = Gauge(
    "model_version_info",
    "Model version info",
    ["version"],
    registry=REGISTRY,
)

ARTIFACT_DIR = os.getenv("ARTIFACT_DIR", "/artifacts")

MODEL = None
MODEL_VERSION = "none"
FEATURES: list[str] = []


class PredictRequest(BaseModel):
    # If omitted, uses latest features from DB
    features: Optional[Dict[str, float]] = None


class PredictResponse(BaseModel):
    y: int
    proba: float
    version: str


class ExplainResponse(BaseModel):
    y: int
    proba: float
    version: str
    explanation: str
    llm_used: bool


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


def load_latest_features_from_db() -> Dict[str, float]:
    try:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM raw_bikes ORDER BY ingested_at DESC LIMIT 1;"
                )
                row_b = cur.fetchone()
                if not row_b:
                    raise RuntimeError("raw_bikes is empty")
                bikes = ensure_dict(row_b[0])

                cur.execute(
                    "SELECT payload FROM raw_weather ORDER BY ingested_at DESC LIMIT 1;"
                )
                row_w = cur.fetchone()
                if not row_w:
                    raise RuntimeError("raw_weather is empty")
                weather = ensure_dict(row_w[0])
    except Exception as e:
        raise RuntimeError(f"DB read failed: {e}")

    feat: Dict[str, float] = {}
    feat.update(bikes_features(bikes))
    feat.update(weather_features(weather))
    return feat


def try_load_model() -> Tuple[bool, str]:
    global MODEL, MODEL_VERSION, FEATURES
    meta_path = os.path.join(ARTIFACT_DIR, "metadata.json")
    model_path = os.path.join(ARTIFACT_DIR, "model.joblib")

    if not (os.path.exists(meta_path) and os.path.exists(model_path)):
        MODEL = None
        MODEL_VERSION = "none"
        FEATURES = []
        MODEL_LOADED.set(0)
        try:
            MODEL_VERSION_INFO.clear()
        except Exception:
            pass
        return False, "artifact files not found"

    with open(meta_path) as f:
        meta = json.load(f)

    FEATURES = meta.get("features", [])
    MODEL_VERSION = meta.get("model_version", "unknown")
    MODEL = joblib.load(model_path)

    MODEL_LOADED.set(1)
    try:
        MODEL_VERSION_INFO.clear()
    except Exception:
        pass
    MODEL_VERSION_INFO.labels(version=MODEL_VERSION).set(1)
    return True, f"loaded version={MODEL_VERSION}"


@app.on_event("startup")
def on_startup():
    ok, msg = try_load_model()
    print(f"[startup] model load: {ok} ({msg})")


def _prepare_row(req: PredictRequest) -> Dict[str, float]:
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded (missing artifacts?)")

    feats = load_latest_features_from_db() if req.features is None else req.features
    missing = [f for f in FEATURES if f not in feats]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing features: {missing}")

    return {f: float(feats[f]) for f in FEATURES}


def _predict_from_row(row: Dict[str, float]) -> Tuple[int, float]:
    X_df = pd.DataFrame([row], columns=FEATURES)
    proba = float(MODEL.predict_proba(X_df)[0, 1])
    y = int(proba >= 0.5)
    return y, proba


def _fallback_explanation(row: Dict[str, float], y: int, proba: float) -> str:
    items = ", ".join([f"{k}={row[k]:.4g}" for k in FEATURES[:8]])
    more = "" if len(FEATURES) <= 8 else f" … (+{len(FEATURES)-8} altre)"
    return (
        f"Predizione: y={y} con proba={proba:.3f} (soglia 0.5). "
        f"Valori input (prime feature): {items}{more}. "
        "Per una spiegazione LLM completa imposta OPENAI_API_KEY."
    )


def _llm_explain(row: Dict[str, float], y: int, proba: float) -> Tuple[str, bool]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return _fallback_explanation(row, y, proba), False

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    system = (
        "Sei un assistente MLOps. Spiega una predizione di un modello ML in modo chiaro e breve.\n"
        "Regole: 1) non inventare feature non presenti, 2) non dare consigli medici/legali, "
        "3) usa italiano, 4) massimo 6 bullet."
    )

    user = {
        "model_version": MODEL_VERSION,
        "threshold": 0.5,
        "prediction": {"y": y, "proba": proba},
        "features": row,
    }

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        "Spiega questa predizione (cosa significa y/proba e quali segnali nei dati la guidano). "
                        "Ecco il JSON:\n" + json.dumps(user, ensure_ascii=False)
                    ),
                },
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise RuntimeError("Empty LLM response")
        return text, True
    except Exception:
        # Non fallire mai l'API: torna fallback
        return _fallback_explanation(row, y, proba), False


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "inference",
        "version": MODEL_VERSION,
        "model_loaded": MODEL is not None,
    }


@app.get("/model")
def model_info():
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"version": MODEL_VERSION, "features": FEATURES}


@app.post("/reload_model")
def reload_model():
    ok, msg = try_load_model()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"status": "reloaded", "version": MODEL_VERSION}


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    t0 = time.time()
    endpoint = "/predict"
    try:
        row = _prepare_row(req)
        y, proba = _predict_from_row(row)
        REQ_COUNT.labels(endpoint=endpoint, status="200").inc()
        return PredictResponse(y=y, proba=proba, version=MODEL_VERSION)
    except HTTPException as e:
        REQ_COUNT.labels(endpoint=endpoint, status=str(e.status_code)).inc()
        raise
    except Exception as e:
        REQ_COUNT.labels(endpoint=endpoint, status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        REQ_LAT.labels(endpoint=endpoint).observe(time.time() - t0)


@app.post("/explain", response_model=ExplainResponse)
def explain(req: PredictRequest):
    t0 = time.time()
    endpoint = "/explain"
    try:
        row = _prepare_row(req)
        y, proba = _predict_from_row(row)
        explanation, llm_used = _llm_explain(row, y, proba)

        REQ_COUNT.labels(endpoint=endpoint, status="200").inc()
        return ExplainResponse(
            y=y,
            proba=proba,
            version=MODEL_VERSION,
            explanation=explanation,
            llm_used=llm_used,
        )
    except HTTPException as e:
        REQ_COUNT.labels(endpoint=endpoint, status=str(e.status_code)).inc()
        raise
    except Exception as e:
        REQ_COUNT.labels(endpoint=endpoint, status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        REQ_LAT.labels(endpoint=endpoint).observe(time.time() - t0)


@app.get("/metrics")
def metrics():
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
