from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import time

app = FastAPI(title="Centrico LiveLab - Inference API", version="0.1.0")

REQ_COUNT = Counter("http_requests_total", "Total HTTP requests", ["endpoint", "status"])
REQ_LAT = Histogram("http_request_duration_seconds", "Request latency (seconds)", ["endpoint"])

class PredictRequest(BaseModel):
    x: float

class PredictResponse(BaseModel):
    y: float
    model_version: str

MODEL_VERSION = "dev-0"

@app.get("/health")
def health():
    return {"status": "ok", "service": "inference", "model_version": MODEL_VERSION}

@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    t0 = time.time()
    try:
        # placeholder: per ora una funzione banale (poi caricheremo model.joblib da S3)
        y = 2.0 * req.x + 1.0
        REQ_COUNT.labels(endpoint="/predict", status="200").inc()
        return PredictResponse(y=y, model_version=MODEL_VERSION)
    finally:
        REQ_LAT.labels(endpoint="/predict").observe(time.time() - t0)

@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
