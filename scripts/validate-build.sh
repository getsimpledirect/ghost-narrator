#!/usr/bin/env bash
# validate-build.sh — Validates the ghost-narrator Docker image.
set -euo pipefail

IMAGE="${1:-ghost-tts-service:latest}"
CONTAINER="tts-validate-$$"

cleanup() { docker rm -f "$CONTAINER" 2>/dev/null || true; }
trap cleanup EXIT

echo "=== Validating $IMAGE ==="

echo "[1/6] Container starts..."
docker run -d --name "$CONTAINER" \
    -e HARDWARE_TIER=cpu_only \
    -e STORAGE_BACKEND=local \
    "$IMAGE" uvicorn app.main:app --host 0.0.0.0 --port 8020
sleep 10

echo "[2/6] Health endpoint..."
docker exec "$CONTAINER" python -c "
import urllib.request, json
res = urllib.request.urlopen('http://localhost:8020/health')
data = json.loads(res.read())
assert 'hardware_tier' in data, f'Missing hardware_tier: {data}'
print('  hardware_tier:', data['hardware_tier'])
print('  tts_model:', data.get('tts_model'))
"

echo "[3/6] Qwen3-TTS imports..."
docker exec "$CONTAINER" python -c "
from app.core.tts_engine import get_tts_engine
engine = get_tts_engine()
print('  TTSEngine created:', type(engine).__name__)
"

echo "[4/6] Hardware detection..."
docker exec "$CONTAINER" python -c "
from app.core.hardware import ENGINE_CONFIG
print('  Tier:', ENGINE_CONFIG.tier.value)
print('  TTS model:', ENGINE_CONFIG.tts_model)
print('  LLM model:', ENGINE_CONFIG.llm_model)
"

echo "[5/6] Storage backend..."
docker exec -e STORAGE_BACKEND=local "$CONTAINER" python -c "
from app.services.storage import get_storage_backend
b = get_storage_backend()
print('  Backend:', type(b).__name__)
"

echo "[6/6] Voices endpoint..."
docker exec "$CONTAINER" python -c "
import urllib.request, json
res = urllib.request.urlopen('http://localhost:8020/voices')
data = json.loads(res.read())
assert 'profiles' in data
print('  Profiles:', data['profiles'])
"

echo ""
echo "=== All validation checks passed ==="
