# Centrico LiveLab — End-to-End MLOps (Data → Train → Serve → Monitor → CI Gate)

![CI](https://github.com/nepryoon/centrico-livelab-mlops/actions/workflows/ci.yml/badge.svg)

A **working, end-to-end MLOps pipeline** built to showcase the skill-set required for Centrico (Open Banking / AI Competence Center):  
**data engineering + ML training + deployment-ready inference API + monitoring + automated CI quality gate**.

This project is designed to be demoed live during the interview and used as a “Trojan horse” to drive technical discussion toward architecture, production constraints, and operational excellence.

---

## What you get (features)

- **Data ingestion** from **public APIs** (CityBikes + Open-Meteo) into **PostgreSQL** (raw JSONB)
- **Trainer** (Docker) that reads from Postgres, builds features (pandas), trains a **scikit-learn** pipeline and outputs versioned **artifacts**
- **Inference API** (FastAPI) that:
  - loads `model.joblib` + `metadata.json`
  - fetches **latest features from DB**
  - returns prediction via `/predict`
  - exposes Prometheus metrics via `/metrics`
- **Monitoring** with **Prometheus + Grafana**
- **CI pipeline** (GitHub Actions):
  - unit/contract tests
  - synthetic training test (DB-free)
  - explicit **model quality gate** on `f1`

---

## Architecture (high level)

```text
Public APIs
  ├── CityBikes (bike availability snapshots)
  └── Open-Meteo (current weather)

      │
      ▼
[Ingestion Container]  --->  [PostgreSQL (raw JSONB)]
                                   │
                                   ▼
                            [Trainer Container]
                            - feature engineering (pandas)
                            - scikit-learn pipeline
                            - artifacts -> ./artifacts
                                   │
                                   ▼
                            [Inference API (FastAPI)]
                            - loads artifacts
                            - reads latest DB rows
                            - /predict, /model, /health
                            - /metrics (Prometheus)
                                   │
                                   ▼
                          [Prometheus] ---> [Grafana]
Repo structure
.
├── db/
│   └── init.sql
├── services/
│   ├── ingestion/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/collector.py
│   ├── trainer/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/train.py
│   └── inference/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/main.py
├── tests/
│   ├── conftest.py
│   ├── test_inference_contract.py
│   └── test_trainer_synthetic.py
├── artifacts/                 # generated locally (gitignored)
├── docker-compose.local.yml   # inference API
├── docker-compose.data.yml    # postgres + ingestion
├── docker-compose.train.yml   # trainer
├── docker-compose.monitoring.yml
├── requirements-dev.txt
└── .github/workflows/ci.yml
Prerequisites

Docker + Docker Compose plugin

curl

Note: on some Debian setups (e.g. trixie with Python 3.13), local pip install numpy/pandas may try to compile from source.
Tests are CI-first and also runnable using a Python 3.11 Docker container (see below).

Quickstart (local demo)
1) Start the stack (API + DB + monitoring)

From repo root:

docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  up --build
2) Check services
curl -s http://localhost:8000/health
curl -s http://localhost:8000/metrics | head
Data ingestion

The ingestion container fetches:

CityBikes network snapshot → raw_bikes

Open-Meteo current weather → raw_weather

Run a single ingestion cycle:

docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  run --rm ingestion python app/collector.py --once

Bootstrap more samples (recommended before training):

for i in $(seq 1 30); do
  docker compose \
    -f docker-compose.local.yml \
    -f docker-compose.monitoring.yml \
    -f docker-compose.data.yml \
    run --rm ingestion python app/collector.py --once
done

Verify counts:

docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  exec postgres psql -U app -d livelab -c "select count(*) from raw_bikes;"

docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  exec postgres psql -U app -d livelab -c "select count(*) from raw_weather;"
Model training (scikit-learn)

Training writes:

artifacts/model.joblib

artifacts/metrics.json

artifacts/metadata.json (includes model_version and feature list)

Run training:

docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  -f docker-compose.train.yml \
  run --rm trainer

Inspect artifacts:

ls -lah artifacts/
cat artifacts/metrics.json
cat artifacts/metadata.json

Note: DB-mode target uses an adaptive quantile threshold to reduce “single class” failures.

Inference API

The inference service mounts ./artifacts read-only, loads the model and serves predictions.

Endpoints

GET /health → liveness + model_loaded + version

GET /model → model version + expected feature list

POST /predict:

body {} → uses latest DB snapshot

body {"features": {...}} → predict on provided features

GET /metrics → Prometheus metrics

Example
curl -s http://localhost:8000/model

curl -sS -w "\nHTTP %{http_code}\n" -X POST "http://localhost:8000/predict" \
  -H "Content-Type: application/json" \
  -d '{}'
Monitoring (Prometheus + Grafana)

Prometheus scrapes /metrics from the inference API.

Grafana connects to Prometheus as datasource.

Typical metrics:

http_requests_total{endpoint="/predict",status="200"}

http_request_duration_seconds_*

model_loaded

model_version_info{version="..."} 1

Grafana UI:

http://localhost:3000
 (credentials depend on your docker-compose.monitoring.yml)

Prometheus UI:

http://localhost:9090

CI (GitHub Actions) + Model Quality Gate

Workflow: .github/workflows/ci.yml

What runs on each push / PR:

pytest -q (contract test for inference + synthetic trainer test)

Model Quality Gate: runs synthetic training and asserts f1 >= 0.60

uploads ci_artifacts/ as build artifact

This ensures:

API contract stays stable

training pipeline is reproducible without DB

minimum quality threshold is enforced automatically

Run tests locally (recommended via Docker)
docker run --rm -t \
  -v "$PWD":/repo -w /repo \
  python:3.11-slim \
  bash -lc "python -m pip install -U pip && \
            pip install -r requirements-dev.txt && \
            pip install -r services/inference/requirements.txt && \
            pip install -r services/trainer/requirements.txt && \
            pytest -q"
Configuration
Postgres (docker-compose.data.yml)

DB: livelab

user/pass: app/app

exposed port: 5432

Ingestion (docker-compose.data.yml)

BIKE_NETWORK_ID (default: bicincitta-siena)

LAT, LON for Open-Meteo

Why this is relevant for Centrico

Data engineering (raw storage in Postgres, repeatable schema via SQL init)

ML development (scikit-learn pipeline + artifacts + metadata)

Operationalization (FastAPI service, model reload, DB-backed inference)

Monitoring (Prometheus metrics, Grafana dashboards)

MLOps discipline (CI tests + explicit quality gate)

The same pattern maps cleanly to Open Banking use-cases (credit/marketing propensity, anomaly/fraud signals, process automation) where:

ingestion may be PSD2/OpenAPI sources

raw events land in a datastore

training produces governed artifacts

inference is served through APIs with monitoring & rollout controls

Roadmap (next steps)

Step 7: AWS deployment (OIDC → ECR → staging deploy) + Terraform + GitHub Environments

Step 8: alerts + retraining trigger (Prometheus alert rules + scheduled trainer)

Step 9: optional LLM block (RAG over model cards/run logs + “explain prediction” endpoint)

License

MIT (or choose your preferred license)

::contentReference[oaicite:0]{index=0}
