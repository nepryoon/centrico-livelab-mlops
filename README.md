# Centrico LiveLab — MLOps + LLMOps Factory

This repo is an end-to-end, production-minded MLOps pipeline:
Airflow ingestion → training → CI quality gates → staging/prod deploy → Prometheus monitoring → alert → retrain.

## Local quickstart (Step 1)
```bash
docker compose -f docker-compose.local.yml up --build
