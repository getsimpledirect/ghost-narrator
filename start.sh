#!/usr/bin/env bash
# start.sh — Auto-detects GPU and runs the correct Docker Compose configuration.
set -euo pipefail

COMPOSE_BASE="docker-compose.yml"
COMPOSE_GPU="docker-compose.gpu.yml"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "GPU detected — using GPU compose override"
    exec docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_GPU" "$@"
else
    echo "No GPU detected — running in CPU mode"
    exec docker compose -f "$COMPOSE_BASE" "$@"
fi
