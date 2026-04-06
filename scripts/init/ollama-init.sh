#!/usr/bin/env sh
# ollama-init.sh — Starts Ollama, pulls tier-selected model, pre-warms.
set -e

SHARED_DIR="${SHARED_DIR:-/shared}"
TIER_ENV="$SHARED_DIR/tier.env"

MAX_WAIT=30
i=0
while [ ! -f "$TIER_ENV" ]; do
    if [ "$i" -ge "$MAX_WAIT" ]; then
        echo "ERROR: $TIER_ENV not found after ${MAX_WAIT}s" >&2
        exit 1
    fi
    echo "Waiting for tier.env... ($i/${MAX_WAIT}s)" >&2
    sleep 1
    i=$((i + 1))
done

. "$TIER_ENV"
echo "Hardware tier: $HARDWARE_TIER — LLM: $SELECTED_LLM_MODEL" >&2

ollama serve &
OLLAMA_PID=$!

MAX_WAIT=300
i=0
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    if [ "$i" -ge "$MAX_WAIT" ]; then
        echo "ERROR: Ollama API not ready after ${MAX_WAIT}s" >&2
        exit 1
    fi
    sleep 1
    i=$((i + 1))
done
echo "Ollama API ready" >&2

if ollama list 2>/dev/null | grep -q "^${SELECTED_LLM_MODEL}"; then
    echo "Model $SELECTED_LLM_MODEL already cached — skipping pull" >&2
else
    echo "Pulling $SELECTED_LLM_MODEL..." >&2
    ollama pull "$SELECTED_LLM_MODEL"
fi

echo "Pre-warming model $SELECTED_LLM_MODEL..." >&2
ollama run "$SELECTED_LLM_MODEL" "Say: ready" >/dev/null 2>&1 || true
echo "Model ready" >&2

wait "$OLLAMA_PID"
