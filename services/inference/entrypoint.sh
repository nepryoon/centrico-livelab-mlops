#!/bin/sh
set -eu

: "${PORT:=8000}"
: "${ARTIFACT_DIR:=/artifacts}"

echo "[entrypoint] Starting inference container"
echo "[entrypoint] ARTIFACT_DIR=${ARTIFACT_DIR}"
echo "[entrypoint] ARTIFACT_S3_URI=${ARTIFACT_S3_URI:-<not set>}"

mkdir -p "${ARTIFACT_DIR}"

if [ -n "${ARTIFACT_S3_URI:-}" ]; then
  echo "[entrypoint] Syncing artifacts from S3..."
  aws s3 sync "${ARTIFACT_S3_URI}" "${ARTIFACT_DIR}" --only-show-errors || {
    echo "[entrypoint] WARN: aws s3 sync failed (container will still start)"
  }
else
  echo "[entrypoint] ARTIFACT_S3_URI not set: skipping S3 sync"
fi

echo "[entrypoint] Launching Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
