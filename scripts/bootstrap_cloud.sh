#!/usr/bin/env bash
# Prepare a fresh cloud/CI container: start dockerd, pull base images from a mirror,
# fetch wheels for the app image, install python deps, build and start the sandbox.
# On a normal laptop with Docker running, `make install up` is enough.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
  echo "starting dockerd..."
  nohup setsid dockerd >/tmp/dockerd.log 2>&1 </dev/null &
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi

REG="${IMAGE_REGISTRY:-mirror.gcr.io/library}"
for img in postgres:16-alpine redis:7-alpine nginx:1.27-alpine python:3.12-alpine; do
  docker image inspect "$REG/$img" >/dev/null 2>&1 || docker pull -q "$REG/$img"
done

ls sandbox/api/wheels/*.whl >/dev/null 2>&1 || make wheels
python3 -m pip install -q pyyaml pytest 2>&1 | grep -v "root user" || true
python3 -m recovery up
python3 -m pytest -q
