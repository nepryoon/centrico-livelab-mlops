#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=8000}"
: "${ARTIFACT_DIR:=/artifacts}"

mkdir -p "${ARTIFACT_DIR}"

if [[ -n "${ARTIFACT_S3_URI:-}" ]]; then
  echo "[entrypoint] Sync artifacts from ${ARTIFACT_S3_URI} -> ${ARTIFACT_DIR}"
  # non rendiamo fatale un bucket/prefix vuoto: l'app parte comunque
  aws s3 sync "${ARTIFACT_S3_URI}" "${ARTIFACT_DIR}" --only-show-errors || \
    echo "[entrypoint] WARN: S3 sync failed (bucket/prefix empty or permissions)."
else
  echo "[entrypoint] ARTIFACT_S3_URI not set, skipping S3 sync"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
