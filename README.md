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
```

---

## Repo structure

```text
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
```

---

## Prerequisites

- Docker + Docker Compose plugin
- curl

> Note: on some Debian setups (e.g. trixie with Python 3.13), local `pip install numpy/pandas` may try to compile from source.  
> Tests are **CI-first** and also runnable using a **Python 3.11 Docker container** (see below).

---

## Quickstart (local demo)

### 1) Start the stack (API + DB + monitoring)

From repo root:

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  up --build
```

### 2) Check services

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/metrics | head
```

---

## Data ingestion

The ingestion container fetches:
- CityBikes network snapshot → `raw_bikes`
- Open-Meteo current weather → `raw_weather`

Run a single ingestion cycle:

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  run --rm ingestion python app/collector.py --once
```

Bootstrap more samples (recommended before training):

```bash
for i in $(seq 1 30); do
  docker compose \
    -f docker-compose.local.yml \
    -f docker-compose.monitoring.yml \
    -f docker-compose.data.yml \
    run --rm ingestion python app/collector.py --once
done
```

Verify counts:

```bash
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
```

---

## Model training (scikit-learn)

Training writes:
- `artifacts/model.joblib`
- `artifacts/metrics.json`
- `artifacts/metadata.json` (includes `model_version` and feature list)

Run training:

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.monitoring.yml \
  -f docker-compose.data.yml \
  -f docker-compose.train.yml \
  run --rm trainer
```

Inspect artifacts:

```bash
ls -lah artifacts/
cat artifacts/metrics.json
cat artifacts/metadata.json
```

> Note: DB-mode target uses an adaptive quantile threshold to reduce “single class” failures.

---

## Inference API

The inference service mounts `./artifacts` read-only, loads the model and serves predictions.

### Endpoints

- `GET /health` → liveness + model_loaded + version
- `GET /model` → model version + expected feature list
- `POST /predict`:
  - body `{}` → uses **latest DB snapshot**
  - body `{"features": {...}}` → predict on provided features
- `GET /metrics` → Prometheus metrics
- `GET /dashboard` → **Interactive MLOps Dashboard** (see below)

### Interactive Dashboard

Access the real-time MLOps dashboard at: **http://localhost:8000/dashboard**

The dashboard provides an interactive web interface with:

- **MLOps Architecture Diagram**: Visual representation of the pipeline using Mermaid.js
- **System Health Status**: Live monitoring of service status and model availability
- **Model Information**: Display of current model version, features, and metadata
- **Real-time Predictions Chart**: Auto-updating line chart showing prediction trends (Chart.js)
- **Interactive Prediction Form**: Manually trigger predictions using latest DB data
- **Metrics Summary**: Parsed Prometheus metrics with key performance indicators
- **Auto-Refresh Control**: Toggle to pause/resume live updates (5-second intervals)
- **External Links**: Quick access to Grafana (port 3000) and Prometheus (port 9090)

The dashboard is:
- Self-contained (embedded CSS/JavaScript)
- Responsive (works on desktop and tablet)
- Real-time (updates every 5 seconds)
- No authentication required
- Built with CDN-hosted libraries (Mermaid.js, Chart.js)

### Example

```bash
curl -s http://localhost:8000/model

curl -sS -w "\nHTTP %{http_code}\n" -X POST "http://localhost:8000/predict" \
  -H "Content-Type: application/json" \
  -d '{}'

# Open dashboard in browser
open http://localhost:8000/dashboard
```

---

## Monitoring (Prometheus + Grafana)

- Prometheus scrapes `/metrics` from the inference API.
- Grafana connects to Prometheus as datasource.

Typical metrics:
- `http_requests_total{endpoint="/predict",status="200"}`
- `http_request_duration_seconds_*`
- `model_loaded`
- `model_version_info{version="..."} 1`
- `prediction_score_distribution` — histogram of prediction probabilities
- `predictions_total{predicted_class,model_version}` — predictions by class
- `model_f1_score` — current model F1 score
- `prediction_latency_seconds` — inference latency

### Dashboard

Grafana is auto-provisioned with a pre-built ML dashboard at startup:
- **Model F1 Score** — current quality gate metric
- **Predictions / min** — throughput
- **P95 Latency** — inference performance
- **Prediction Score Distribution** — heatmap for drift detection
- **Predictions by Class** — class balance over time

Access: http://localhost:3000 (admin / centrico)

Prediction history is also logged to the `prediction_log` table for retrospective analysis.

Grafana UI:
- http://localhost:3000 (admin / centrico)

Prometheus UI:
- http://localhost:9090

---

## CI (GitHub Actions) + Model Quality Gate

Workflow: `.github/workflows/ci.yml`

What runs on each push / PR:
1) `pytest -q` (contract test for inference + synthetic trainer test)
2) **Model Quality Gate**: runs synthetic training and asserts `f1 >= 0.60`
3) uploads `ci_artifacts/` as build artifact

This ensures:
- API contract stays stable
- training pipeline is reproducible without DB
- minimum quality threshold is enforced automatically

---

## Run tests locally (recommended via Docker)

```bash
docker run --rm -t \
  -v "$PWD":/repo -w /repo \
  python:3.11-slim \
  bash -lc "python -m pip install -U pip && \
            pip install -r requirements-dev.txt && \
            pip install -r services/inference/requirements.txt && \
            pip install -r services/trainer/requirements.txt && \
            pytest -q"
```

---

## Configuration

### Postgres (docker-compose.data.yml)
- DB: `livelab`
- user/pass: `app/app`
- exposed port: `5432`

### Ingestion (docker-compose.data.yml)
- `BIKE_NETWORK_ID` (default: `bicincitta-siena`)
- `LAT`, `LON` for Open-Meteo

---

## Why this is relevant for Centrico

- **Data engineering** (raw storage in Postgres, repeatable schema via SQL init)
- **ML development** (scikit-learn pipeline + artifacts + metadata)
- **Operationalization** (FastAPI service, model reload, DB-backed inference)
- **Monitoring** (Prometheus metrics, Grafana dashboards)
- **MLOps discipline** (CI tests + explicit quality gate)

The same pattern maps cleanly to Open Banking use-cases (credit/marketing propensity, anomaly/fraud signals, process automation) where:
- ingestion may be PSD2/OpenAPI sources
- raw events land in a datastore
- training produces governed artifacts
- inference is served through APIs with monitoring & rollout controls

---

## Roadmap (COMPLETED ✅)

- **Step 7**: ✅ **AWS deployment** (OIDC → ECR → staging deploy) + Terraform + GitHub Environments
- **Step 8**: ✅ **Alerts + retraining trigger** (Prometheus alert rules + AlertManager + scheduled trainer)
- **Step 9**: ✅ **LLM block** (OpenAI integration for `/explain` endpoint with prediction explanations)

### Latest Additions (Step 8 & 9)

#### Prometheus Alerts & AlertManager
- **Alert Rules** (`monitoring/prometheus/alert.rules.yml`):
  - `ModelNotLoaded` - Critical alert when model fails to load
  - `HighErrorRate` - Warning when error rate > 5%
  - `HighPredictionLatency` - Warning when P95 latency > 1 second
  - `InferenceServiceDown` - Critical alert when service is unreachable
  - `LowPredictionVolume` - Info alert for potential data pipeline issues

- **AlertManager** (`monitoring/prometheus/alertmanager.yml`):
  - Configured with grouping, inhibition rules, and webhook support
  - Ready for Slack/PagerDuty integration (webhook configs included as examples)
  - Access UI at http://localhost:9093

#### Scheduled Retraining
- **Workflow** (`.github/workflows/scheduled-retrain.yml`):
  - Runs daily at 2 AM UTC (configurable via cron)
  - Includes model quality gate (F1 >= 0.60)
  - Automatic S3 artifact upload and ECS deployment
  - Manual trigger available via GitHub UI

#### LLM Explain Endpoint
- **Fixed OpenAI API integration** in `/explain` endpoint
- Uses `gpt-4o-mini` for cost-efficient explanations
- Italian language output by default
- Graceful fallback when API key not configured

---

## Monitoring & Alerts

### Prometheus UI
- http://localhost:9090
- View active alerts, metrics, and rule status

### AlertManager UI  
- http://localhost:9093
- View fired alerts, silences, and notification status

### Grafana Dashboards
- http://localhost:3000 (admin/centrico)
- Pre-configured datasource for Prometheus
- Auto-provisioned ML Predictions dashboard with:
  - Model F1 Score
  - Predictions / min
  - Request Rate & P95 Latency
  - Prediction Score Distribution (heatmap)
  - Predictions by Class
- Prediction history logged to `prediction_log` table

### Configuring Alert Notifications

Edit `monitoring/prometheus/alertmanager.yml` to add Slack/webhook notifications:

```yaml
receivers:
  - name: 'critical-alerts'
    webhook_configs:
      - url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
        send_resolved: true
```

---

## Scheduled Retraining

The pipeline automatically retrains the model daily. To trigger manually:

```bash
gh workflow run scheduled-retrain.yml
```

Or via GitHub UI: Actions → Scheduled Retraining → Run workflow

The workflow:
1. Fetches fresh data from CityBikes & Open-Meteo
2. Trains a new model with quality gate check
3. Uploads artifacts to S3 (versioned + latest)
4. Triggers ECS service redeployment
---

## License

Apache 2.0
