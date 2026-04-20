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
# vllm-init.sh — Sources tier.env and starts vLLM OpenAI-compatible server.
#
# GPU memory utilization is computed from VRAM_MIB (written by hardware-probe.sh)
# to leave headroom for the TTS model that shares the same GPU.
# Formula: (VRAM_MIB - 3584) / VRAM_MIB, clamped [0.60, 0.90].
# Example: 24 GB L4 → (24576 - 3584) / 24576 ≈ 0.85
#          10 GB GPU → (10240 - 3584) / 10240 ≈ 0.65
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

# ── Compute GPU memory utilization ────────────────────────────────────────────
# Reserve ~3.5 GB for TTS model (Qwen3-TTS-1.7B fp16) + CUDA context overhead.
# If VRAM_MIB is 0 (HARDWARE_TIER override without GPU probe), use 0.70 default.
TTS_RESERVE_MIB=3584
if [ -n "${VRAM_MIB:-}" ] && [ "${VRAM_MIB:-0}" -gt 4096 ]; then
    GPU_UTIL=$(awk "BEGIN {
        x = (${VRAM_MIB} - ${TTS_RESERVE_MIB}) / ${VRAM_MIB};
        if (x < 0.60) x = 0.60;
        if (x > 0.90) x = 0.90;
        printf \"%.2f\", x
    }")
else
    GPU_UTIL="0.70"
fi

echo "vLLM: tier=${HARDWARE_TIER} model=${SELECTED_LLM_MODEL} max-model-len=${SELECTED_LLM_NUM_CTX:-8192} quantization=${VLLM_QUANTIZATION:-none} gpu-util=${GPU_UTIL}" >&2

# ── Build argument list ────────────────────────────────────────────────────────
# --reasoning-parser qwen3 covers both Qwen3 and Qwen3.5 — the parser name is
#   shared across the Qwen3 family; there is no separate qwen3.5 variant.
# --default-chat-template-kwargs disables thinking server-wide so <think> tokens
#   are never generated; per-request extra_body reinforces this.
# --quantization is added only when VLLM_QUANTIZATION is set
#   (fp8 for GPU tiers; empty for CPU/low-VRAM tiers that run Ollama instead).
set -- \
    --model "${SELECTED_LLM_MODEL}" \
    --max-model-len "${SELECTED_LLM_NUM_CTX:-8192}" \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    --gpu-memory-utilization "${GPU_UTIL}" \
    --max-num-seqs 4 \
    --host 0.0.0.0 \
    --port 8000

if [ -n "${VLLM_QUANTIZATION:-}" ]; then
    set -- "$@" --quantization "${VLLM_QUANTIZATION}"
fi

echo "Starting: python3 -m vllm.entrypoints.openai.api_server $*" >&2
exec python3 -m vllm.entrypoints.openai.api_server "$@"
