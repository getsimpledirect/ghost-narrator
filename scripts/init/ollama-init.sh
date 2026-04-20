#!/usr/bin/env sh
# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
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
echo "Hardware tier: $HARDWARE_TIER — LLM: $SELECTED_LLM_MODEL (ctx: ${OLLAMA_NUM_CTX:-default}) — Ollama parallel: ${OLLAMA_NUM_PARALLEL:-1}" >&2

# Export Ollama tunables sourced from tier.env so they are in the environment
# when 'ollama serve' starts. Ollama reads these at process startup only.
# OLLAMA_NUM_CTX pre-allocates the KV cache to match what tts-service will request;
# without it Ollama defaults to 2048 and reloads the model on the first real API call.
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-0}"
export OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-2048}"

ollama serve &
OLLAMA_PID=$!

MAX_WAIT=300
i=0
until ollama list >/dev/null 2>&1; do
    if [ "$i" -ge "$MAX_WAIT" ]; then
        echo "ERROR: Ollama API not ready after ${MAX_WAIT}s" >&2
        exit 1
    fi
    sleep 1
    i=$((i + 1))
done
echo "Ollama API ready" >&2

if ollama show "${SELECTED_LLM_MODEL}" >/dev/null 2>&1; then
    echo "Model $SELECTED_LLM_MODEL already cached — skipping pull" >&2
else
    echo "Pulling $SELECTED_LLM_MODEL..." >&2
    ollama pull "$SELECTED_LLM_MODEL"
fi

echo "Pre-warming ${SELECTED_LLM_MODEL}..." >&2
ollama run "${SELECTED_LLM_MODEL}" "Say: ready" >/dev/null 2>&1 || true
echo "Model ready" >&2

wait "$OLLAMA_PID"
