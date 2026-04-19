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
# hardware-probe.sh — Detects GPU/VRAM and writes tier.env to /shared/
#
# Outputs to /shared/tier.env:
#   HARDWARE_TIER          — cpu_only | low_vram | mid_vram | high_vram
#   SELECTED_TTS_MODEL     — HuggingFace model ID for Qwen3-TTS
#   SELECTED_LLM_MODEL     — Ollama model tag for narration LLM
#   SELECTED_LLM_NUM_CTX   — LLM context window size (tokens); used by tts-service
#   OLLAMA_NUM_CTX         — same value; exported before ollama serve for KV pre-allocation
#   OLLAMA_NUM_PARALLEL    — concurrent Ollama request slots (computed from VRAM)
#   OLLAMA_FLASH_ATTENTION — 1 on GPU tiers (Ampere+ supports flash attention)
set -e

SHARED_DIR="${SHARED_DIR:-/shared}"
mkdir -p "$SHARED_DIR"

# ── Detect VRAM ───────────────────────────────────────────────────────────────
VRAM_MIB=0
if [ -n "$HARDWARE_TIER" ]; then
    echo "HARDWARE_TIER override: $HARDWARE_TIER" >&2
    TIER="$HARDWARE_TIER"
elif ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "No nvidia-smi found — CPU_ONLY" >&2
    TIER="cpu_only"
else
    _VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
            | head -1 | tr -d ' ')
    if [ -z "$_VRAM" ] || ! [ "$_VRAM" -eq "$_VRAM" ] 2>/dev/null; then
        echo "nvidia-smi returned no VRAM value — defaulting to cpu_only" >&2
        TIER="cpu_only"
    else
        VRAM_MIB="$_VRAM"
        echo "GPU VRAM: ${VRAM_MIB} MiB" >&2
        if [ "$VRAM_MIB" -lt 10240 ]; then
            TIER="low_vram"
        elif [ "$VRAM_MIB" -lt 18432 ]; then
            TIER="mid_vram"
        else
            TIER="high_vram"
        fi
    fi
fi

# ── Model and VRAM budget constants per tier ─────────────────────────────────
# LLM_SIZE_MIB  — approximate VRAM for the LLM model weights (Q4_K_M quant)
# TTS_SIZE_MIB  — approximate VRAM for the TTS model weights
# KV_PER_SLOT   — KV cache per Ollama parallel slot at the tier's context window (fp16)
# SAFETY_MIB    — reserved for CUDA context, activations, and OS overhead
case "$TIER" in
    cpu_only)
        TTS_MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        LLM_MODEL="qwen3.5:2b"
        LLM_NUM_CTX=4096
        LLM_SIZE_MIB=1700; TTS_SIZE_MIB=2400; KV_PER_SLOT=200; SAFETY_MIB=512
        OLLAMA_FA=0
        ;;
    low_vram)
        TTS_MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        LLM_MODEL="qwen3.5:4b"
        LLM_NUM_CTX=4096
        LLM_SIZE_MIB=3400; TTS_SIZE_MIB=2400; KV_PER_SLOT=350; SAFETY_MIB=1024
        OLLAMA_FA=1
        ;;
    mid_vram)
        TTS_MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
        LLM_NUM_CTX=8192
        OLLAMA_FA=1
        # qwen3.5:9b (6.6GB) + TTS 1.7B (3.4GB) = 10GB minimum — fits ≥13GB GPUs only.
        # Fall back to qwen3.5:4b (3.4GB) for 10-12GB GPUs to avoid OOM.
        if [ "$VRAM_MIB" -ge 13312 ]; then
            LLM_MODEL="qwen3.5:9b"
            LLM_SIZE_MIB=6600; TTS_SIZE_MIB=3400; KV_PER_SLOT=500; SAFETY_MIB=2048
        else
            LLM_MODEL="qwen3.5:4b"
            LLM_SIZE_MIB=3400; TTS_SIZE_MIB=3400; KV_PER_SLOT=600; SAFETY_MIB=2048
        fi
        ;;
    high_vram)
        TTS_MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
        LLM_MODEL="qwen3.5:9b"
        LLM_NUM_CTX=65536
        # qwen3.5:9b Q4_K_M ≈ 6600 MiB; 64K ctx KV grows on 15 attn layers → ~2000 MiB/slot
        # (15 layers × 2 × 65536 tokens × 4 heads × 128 head_dim × fp16 = ~1920 MiB)
        LLM_SIZE_MIB=6600; TTS_SIZE_MIB=3400; KV_PER_SLOT=2000; SAFETY_MIB=2048
        OLLAMA_FA=1
        ;;
    *)
        echo "Unknown HARDWARE_TIER='$HARDWARE_TIER' — defaulting to cpu_only" >&2
        TIER="cpu_only"
        TTS_MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        LLM_MODEL="qwen3.5:2b"
        LLM_NUM_CTX=4096
        LLM_SIZE_MIB=1700; TTS_SIZE_MIB=2400; KV_PER_SLOT=200; SAFETY_MIB=512
        OLLAMA_FA=0
        ;;
esac

# Allow environment overrides for model selection (install.sh may set these)
TTS_MODEL="${SELECTED_TTS_MODEL:-$TTS_MODEL}"
LLM_MODEL="${SELECTED_LLM_MODEL:-$LLM_MODEL}"
LLM_NUM_CTX="${SELECTED_LLM_NUM_CTX:-$LLM_NUM_CTX}"

# ── Compute OLLAMA_NUM_PARALLEL from actual free VRAM ─────────────────────────
# Formula: floor((vram_mib - llm_size - tts_size - safety) / kv_per_slot)
# Capped at 4: reflects realistic concurrent job submission, not raw headroom.
# Ollama pre-allocates ALL slots at startup — setting it too high wastes VRAM.
#
# Worked examples (KV_PER_SLOT reflects context window for each tier):
#   24 GB L4,  high_vram  qwen3.5:9b 64K ctx: (24576 - 6600 - 3400 - 2048) / 2000 = 6  → capped 4
#   16 GB GPU, mid_vram   qwen3.5:9b  8K ctx: (16384 - 6600 - 3400 - 2048) /  500 = 8  → capped 4
#   12 GB GPU, mid_vram   qwen3.5:4b  8K ctx: (12288 - 3400 - 3400 - 2048) /  600 = 5  → capped 4
#    8 GB GPU, low_vram   qwen3.5:4b  4K ctx: ( 8192 - 3400 - 2400 - 1024) /  350 = 3  → 3
if [ "$TIER" = "cpu_only" ] || [ "$VRAM_MIB" -le 0 ]; then
    OLLAMA_PARALLEL=1
else
    AVAIL=$((VRAM_MIB - LLM_SIZE_MIB - TTS_SIZE_MIB - SAFETY_MIB))
    if [ "$AVAIL" -le 0 ]; then
        OLLAMA_PARALLEL=1
    else
        OLLAMA_PARALLEL=$((AVAIL / KV_PER_SLOT))
        [ "$OLLAMA_PARALLEL" -lt 1 ] && OLLAMA_PARALLEL=1
        [ "$OLLAMA_PARALLEL" -gt 4 ] && OLLAMA_PARALLEL=4
    fi
    echo "Ollama parallelism: ${OLLAMA_PARALLEL} (${AVAIL} MiB free / ${KV_PER_SLOT} MiB per slot)" >&2
fi

# ── Write tier.env ─────────────────────────────────────────────────────────────
cat > "$SHARED_DIR/tier.env" <<EOF
HARDWARE_TIER=${TIER}
SELECTED_TTS_MODEL=${TTS_MODEL}
SELECTED_LLM_MODEL=${LLM_MODEL}
SELECTED_LLM_NUM_CTX=${LLM_NUM_CTX}
OLLAMA_NUM_CTX=${LLM_NUM_CTX}
OLLAMA_NUM_PARALLEL=${OLLAMA_PARALLEL}
OLLAMA_FLASH_ATTENTION=${OLLAMA_FA}
EOF

echo "Wrote $SHARED_DIR/tier.env:" >&2
cat "$SHARED_DIR/tier.env" >&2
