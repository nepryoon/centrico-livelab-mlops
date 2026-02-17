import json
import logging
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
from starlette.responses import Response, HTMLResponse

# Setup logging
logger = logging.getLogger(__name__)

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

# Custom ML metrics
PREDICTION_SCORE = Histogram(
    "prediction_score_distribution",
    "Distribution of prediction probabilities",
    buckets=[0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
    registry=REGISTRY,
)
PREDICTIONS_TOTAL = Counter(
    "predictions_total",
    "Total predictions by class and model version",
    ["predicted_class", "model_version"],
    registry=REGISTRY,
)
MODEL_F1 = Gauge("model_f1_score", "Current model F1 score", registry=REGISTRY)
PREDICTION_LATENCY = Histogram(
    "prediction_latency_seconds",
    "Inference latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
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
    MODEL_F1.set(meta.get("f1", 0.0))
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
    start = time.perf_counter()
    endpoint = "/predict"
    try:
        row = _prepare_row(req)
        y, proba = _predict_from_row(row)
        latency = time.perf_counter() - start
        
        # Custom ML metrics
        PREDICTION_SCORE.observe(float(proba))
        PREDICTIONS_TOTAL.labels(
            predicted_class=str(y),
            model_version=MODEL_VERSION
        ).inc()
        PREDICTION_LATENCY.observe(latency)
        
        # Log prediction to database
        try:
            with get_pg_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO prediction_log "
                        "(input_json, predicted_class, probability, model_version, latency_ms) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (json.dumps(row), int(y), float(proba),
                         MODEL_VERSION, round(latency * 1000, 2))
                    )
                    conn.commit()
        except Exception as e:
            logger.warning(f"prediction_log insert failed: {e}")
        
        REQ_COUNT.labels(endpoint=endpoint, status="200").inc()
        return PredictResponse(y=y, proba=proba, version=MODEL_VERSION)
    except HTTPException as e:
        REQ_COUNT.labels(endpoint=endpoint, status=str(e.status_code)).inc()
        raise
    except Exception as e:
        REQ_COUNT.labels(endpoint=endpoint, status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        REQ_LAT.labels(endpoint=endpoint).observe(time.perf_counter() - start)


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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Interactive MLOps Dashboard with real-time predictions and system metrics"""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Centrico LiveLab Dashboard</title>
    
    <!-- External Libraries -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        /* Header Styles */
        header {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        h1 {
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1em;
            margin-bottom: 15px;
        }
        
        .badge {
            display: inline-block;
            padding: 6px 12px;
            background: #667eea;
            color: white;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
        }
        
        /* Grid Layout */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .grid-2 {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        /* Card Styles */
        .card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }
        
        .card h2 {
            color: #667eea;
            font-size: 1.4em;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .full-width {
            grid-column: 1 / -1;
        }
        
        /* Status Indicators */
        .status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 15px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9em;
        }
        
        .status-ok {
            background: #d4edda;
            color: #155724;
        }
        
        .status-error {
            background: #f8d7da;
            color: #721c24;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
        
        .status-ok .status-dot {
            background: #28a745;
        }
        
        .status-error .status-dot {
            background: #dc3545;
        }
        
        /* Info Items */
        .info-item {
            margin: 12px 0;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        
        .info-label {
            font-weight: 600;
            color: #495057;
            display: block;
            margin-bottom: 4px;
            font-size: 0.9em;
        }
        
        .info-value {
            color: #212529;
            font-size: 1.1em;
        }
        
        /* Chart Container */
        .chart-container {
            position: relative;
            height: 300px;
            margin-top: 15px;
        }
        
        /* Form Styles */
        .form-group {
            margin: 15px 0;
        }
        
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
            width: 100%;
        }
        
        button:hover {
            background: #5568d3;
        }
        
        button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        
        /* Prediction Result */
        .prediction-result {
            margin-top: 20px;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            display: none;
        }
        
        .prediction-result.show {
            display: block;
        }
        
        .prediction-result.positive {
            background: #d4edda;
            border: 2px solid #28a745;
        }
        
        .prediction-result.negative {
            background: #d1ecf1;
            border: 2px solid #17a2b8;
        }
        
        .prediction-value {
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .prediction-confidence {
            font-size: 1.2em;
            color: #666;
        }
        
        /* Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .metric-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        
        .metric-label {
            font-size: 0.9em;
            opacity: 0.9;
            margin-bottom: 8px;
        }
        
        .metric-value {
            font-size: 2em;
            font-weight: bold;
        }
        
        /* Architecture Diagram */
        .mermaid {
            background: white;
            padding: 20px;
            border-radius: 8px;
            display: flex;
            justify-content: center;
        }
        
        /* Control Panel */
        .controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding: 15px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .toggle-btn {
            padding: 8px 16px;
            background: #28a745;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            width: auto;
        }
        
        .toggle-btn.paused {
            background: #ffc107;
        }
        
        .last-update {
            color: #666;
            font-size: 0.9em;
        }
        
        /* Links */
        .external-links {
            display: flex;
            gap: 15px;
            margin-top: 15px;
            flex-wrap: wrap;
        }
        
        .external-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 18px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: background 0.3s;
        }
        
        .external-link:hover {
            background: #5568d3;
        }
        
        /* Footer */
        footer {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-top: 30px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            color: #666;
        }
        
        /* Loading Spinner */
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(102, 126, 234, 0.3);
            border-radius: 50%;
            border-top-color: #667eea;
            animation: spin 1s ease-in-out infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .error-message {
            color: #dc3545;
            padding: 10px;
            background: #f8d7da;
            border-radius: 6px;
            margin: 10px 0;
            display: none;
        }
        
        .error-message.show {
            display: block;
        }
        
        /* Feature List */
        .feature-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }
        
        .feature-tag {
            background: #e7f3ff;
            color: #0056b3;
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 0.85em;
            font-weight: 500;
        }
        
        /* Responsive Design */
        @media (max-width: 768px) {
            h1 {
                font-size: 1.8em;
            }
            
            .grid, .grid-2 {
                grid-template-columns: 1fr;
            }
            
            .controls {
                flex-direction: column;
                gap: 10px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <h1>🚀 Centrico LiveLab - MLOps Dashboard</h1>
            <p class="subtitle">Real-time inference monitoring and system metrics</p>
            <span class="badge" id="model-version-badge">Loading...</span>
        </header>
        
        <!-- Control Panel -->
        <div class="controls">
            <div>
                <button class="toggle-btn" id="auto-refresh-toggle" onclick="toggleAutoRefresh()">
                    🟢 Auto-Refresh: ON
                </button>
            </div>
            <div class="last-update">
                Last update: <span id="last-update-time">Never</span>
            </div>
        </div>
        
        <!-- Architecture Diagram -->
        <div class="card full-width">
            <h2>📊 MLOps Architecture</h2>
            <div class="mermaid">
                graph LR
                    A[Public APIs] --> B[Ingestion]
                    A1[CityBikes API] --> B
                    A2[Open-Meteo API] --> B
                    B --> C[(PostgreSQL)]
                    C --> D[Trainer]
                    D --> E[Inference API]
                    E --> F[Prometheus]
                    F --> G[Grafana]
                    
                    style A fill:#e1f5ff
                    style B fill:#fff9e6
                    style C fill:#e8f5e9
                    style D fill:#f3e5f5
                    style E fill:#667eea,color:#fff
                    style F fill:#ffe0b2
                    style G fill:#ffcdd2
            </div>
        </div>
        
        <!-- System Health and Model Info -->
        <div class="grid">
            <!-- Health Status -->
            <div class="card">
                <h2>💚 System Health</h2>
                <div id="health-status">
                    <div class="loading"></div> Loading...
                </div>
                <div class="error-message" id="health-error"></div>
            </div>
            
            <!-- Model Information -->
            <div class="card">
                <h2>🤖 Model Information</h2>
                <div id="model-info">
                    <div class="loading"></div> Loading...
                </div>
                <div class="error-message" id="model-error"></div>
            </div>
            
            <!-- Metrics Summary -->
            <div class="card">
                <h2>📈 Metrics Summary</h2>
                <div id="metrics-summary">
                    <div class="loading"></div> Loading...
                </div>
                <div class="error-message" id="metrics-error"></div>
            </div>
        </div>
        
        <!-- Live Predictions Chart -->
        <div class="card full-width">
            <h2>📉 Live Predictions (Real-time)</h2>
            <div class="chart-container">
                <canvas id="predictions-chart"></canvas>
            </div>
        </div>
        
        <!-- Interactive Prediction Form -->
        <div class="card">
            <h2>🎯 Interactive Prediction</h2>
            <div class="form-group">
                <button onclick="triggerPrediction()" id="predict-btn">
                    Get Prediction from Latest DB Data
                </button>
            </div>
            <div class="prediction-result" id="prediction-result"></div>
            <div class="error-message" id="prediction-error"></div>
        </div>
        
        <!-- External Links -->
        <div class="card">
            <h2>🔗 External Services</h2>
            <div class="external-links">
                <a href="http://localhost:3000" target="_blank" class="external-link">
                    📊 Grafana Dashboard
                </a>
                <a href="http://localhost:9090" target="_blank" class="external-link">
                    🔥 Prometheus UI
                </a>
            </div>
        </div>
        
        <!-- Footer -->
        <footer>
            <p><strong>Centrico LiveLab MLOps Pipeline</strong></p>
            <p>Licensed under Apache 2.0 | End-to-End ML Pipeline Demo</p>
        </footer>
    </div>
    
    <script>
        // Initialize Mermaid
        mermaid.initialize({ startOnLoad: true, theme: 'default' });
        
        // Global state
        let autoRefresh = true;
        let predictionData = {
            timestamps: [],
            predictions: [],
            probabilities: []
        };
        let predictionChart = null;
        
        // Initialize Chart
        function initChart() {
            const ctx = document.getElementById('predictions-chart');
            predictionChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Prediction (y)',
                            data: [],
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            tension: 0.4,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Probability',
                            data: [],
                            borderColor: '#764ba2',
                            backgroundColor: 'rgba(118, 75, 162, 0.1)',
                            tension: 0.4,
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false,
                    },
                    scales: {
                        y: {
                            type: 'linear',
                            display: true,
                            position: 'left',
                            min: 0,
                            max: 1,
                            title: {
                                display: true,
                                text: 'Prediction (0/1)'
                            }
                        },
                        y1: {
                            type: 'linear',
                            display: true,
                            position: 'right',
                            min: 0,
                            max: 1,
                            title: {
                                display: true,
                                text: 'Probability'
                            },
                            grid: {
                                drawOnChartArea: false,
                            },
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    }
                }
            });
        }
        
        // Update timestamp
        function updateTimestamp() {
            const now = new Date().toLocaleTimeString();
            document.getElementById('last-update-time').textContent = now;
        }
        
        // Toggle auto-refresh
        function toggleAutoRefresh() {
            autoRefresh = !autoRefresh;
            const btn = document.getElementById('auto-refresh-toggle');
            if (autoRefresh) {
                btn.textContent = '🟢 Auto-Refresh: ON';
                btn.classList.remove('paused');
            } else {
                btn.textContent = '🔴 Auto-Refresh: OFF';
                btn.classList.add('paused');
            }
        }
        
        // Fetch health status
        async function fetchHealth() {
            try {
                const response = await fetch('/health');
                const data = await response.json();
                
                const statusHtml = `
                    <div class="info-item">
                        <span class="info-label">Service Status</span>
                        <div class="status status-ok">
                            <span class="status-dot"></span>
                            ${data.status.toUpperCase()}
                        </div>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Model Loaded</span>
                        <div class="status ${data.model_loaded ? 'status-ok' : 'status-error'}">
                            <span class="status-dot"></span>
                            ${data.model_loaded ? 'YES' : 'NO'}
                        </div>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Model Version</span>
                        <span class="info-value">${data.version}</span>
                    </div>
                `;
                
                document.getElementById('health-status').innerHTML = statusHtml;
                document.getElementById('health-error').classList.remove('show');
            } catch (error) {
                document.getElementById('health-error').textContent = 'Failed to fetch health status';
                document.getElementById('health-error').classList.add('show');
            }
        }
        
        // Fetch model info
        async function fetchModelInfo() {
            try {
                const response = await fetch('/model');
                if (response.status === 503) {
                    throw new Error('Model not loaded');
                }
                const data = await response.json();
                
                // Update badge
                document.getElementById('model-version-badge').textContent = `Model: ${data.version}`;
                
                const featuresHtml = data.features.map(f => 
                    `<span class="feature-tag">${f}</span>`
                ).join('');
                
                const infoHtml = `
                    <div class="info-item">
                        <span class="info-label">Version</span>
                        <span class="info-value">${data.version}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Feature Count</span>
                        <span class="info-value">${data.features.length}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Features</span>
                        <div class="feature-list">
                            ${featuresHtml}
                        </div>
                    </div>
                `;
                
                document.getElementById('model-info').innerHTML = infoHtml;
                document.getElementById('model-error').classList.remove('show');
            } catch (error) {
                document.getElementById('model-error').textContent = 'Model not loaded or unavailable';
                document.getElementById('model-error').classList.add('show');
                document.getElementById('model-version-badge').textContent = 'Model: Not Loaded';
            }
        }
        
        // Fetch metrics
        async function fetchMetrics() {
            try {
                const response = await fetch('/metrics');
                const text = await response.text();
                
                // Parse Prometheus metrics
                const lines = text.split('\\n');
                let totalRequests = 0;
                let modelLoaded = 0;
                
                lines.forEach(line => {
                    if (line.startsWith('http_requests_total{')) {
                        const match = line.match(/}\\s+(\\d+)/);
                        if (match) {
                            totalRequests += parseInt(match[1]);
                        }
                    }
                    if (line.startsWith('model_loaded ')) {
                        const match = line.match(/model_loaded\\s+(\\d+)/);
                        if (match) {
                            modelLoaded = parseInt(match[1]);
                        }
                    }
                });
                
                const metricsHtml = `
                    <div class="metrics-grid">
                        <div class="metric-card">
                            <div class="metric-label">Total Requests</div>
                            <div class="metric-value">${totalRequests}</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-label">Model Status</div>
                            <div class="metric-value">${modelLoaded ? '✓' : '✗'}</div>
                        </div>
                    </div>
                `;
                
                document.getElementById('metrics-summary').innerHTML = metricsHtml;
                document.getElementById('metrics-error').classList.remove('show');
            } catch (error) {
                document.getElementById('metrics-error').textContent = 'Failed to fetch metrics';
                document.getElementById('metrics-error').classList.add('show');
            }
        }
        
        // Fetch live prediction
        async function fetchLivePrediction() {
            try {
                const response = await fetch('/predict', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({})
                });
                
                if (response.status === 503) {
                    return; // Model not loaded, skip update
                }
                
                const data = await response.json();
                
                // Add to data arrays
                const timestamp = new Date().toLocaleTimeString();
                predictionData.timestamps.push(timestamp);
                predictionData.predictions.push(data.y);
                predictionData.probabilities.push(data.proba);
                
                // Keep only last 20 predictions
                if (predictionData.timestamps.length > 20) {
                    predictionData.timestamps.shift();
                    predictionData.predictions.shift();
                    predictionData.probabilities.shift();
                }
                
                // Update chart
                predictionChart.data.labels = predictionData.timestamps;
                predictionChart.data.datasets[0].data = predictionData.predictions;
                predictionChart.data.datasets[1].data = predictionData.probabilities;
                predictionChart.update('none'); // No animation for smooth updates
                
            } catch (error) {
                console.error('Failed to fetch live prediction:', error);
            }
        }
        
        // Trigger manual prediction
        async function triggerPrediction() {
            const btn = document.getElementById('predict-btn');
            const resultDiv = document.getElementById('prediction-result');
            const errorDiv = document.getElementById('prediction-error');
            
            btn.disabled = true;
            btn.textContent = 'Predicting...';
            resultDiv.classList.remove('show');
            errorDiv.classList.remove('show');
            
            try {
                const response = await fetch('/predict', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({})
                });
                
                if (response.status === 503) {
                    throw new Error('Model not loaded');
                }
                
                const data = await response.json();
                
                const confidencePercent = (data.proba * 100).toFixed(1);
                const predictionClass = data.y === 1 ? 'Positive (1)' : 'Negative (0)';
                const resultClass = data.y === 1 ? 'positive' : 'negative';
                
                resultDiv.className = `prediction-result show ${resultClass}`;
                resultDiv.innerHTML = `
                    <div class="prediction-value">${predictionClass}</div>
                    <div class="prediction-confidence">Confidence: ${confidencePercent}%</div>
                    <div style="margin-top: 10px; font-size: 0.9em; color: #666;">
                        Model version: ${data.version}
                    </div>
                `;
                
            } catch (error) {
                errorDiv.textContent = error.message || 'Prediction failed';
                errorDiv.classList.add('show');
            } finally {
                btn.disabled = false;
                btn.textContent = 'Get Prediction from Latest DB Data';
            }
        }
        
        // Update all data
        async function updateDashboard() {
            if (!autoRefresh) return;
            
            await Promise.all([
                fetchHealth(),
                fetchModelInfo(),
                fetchMetrics(),
                fetchLivePrediction()
            ]);
            
            updateTimestamp();
        }
        
        // Initialize dashboard
        async function init() {
            initChart();
            await updateDashboard();
            
            // Set up auto-refresh every 5 seconds
            setInterval(() => {
                if (autoRefresh) {
                    updateDashboard();
                }
            }, 5000);
        }
        
        // Start when page loads
        window.addEventListener('load', init);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)
