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
set -e

SHARED_DIR="${SHARED_DIR:-/shared}"
mkdir -p "$SHARED_DIR"

detect_tier() {
    if [ -n "$HARDWARE_TIER" ]; then
        echo "HARDWARE_TIER override: $HARDWARE_TIER" >&2
        echo "$HARDWARE_TIER"
        return
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        echo "No nvidia-smi found — CPU_ONLY" >&2
        echo "cpu_only"
        return
    fi
    if ! nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits >/dev/null 2>&1; then
        echo "nvidia-smi present but no GPU detected — CPU_ONLY" >&2
        echo "cpu_only"
        return
    fi
    VRAM_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    if [ -z "$VRAM_MIB" ] || ! [ "$VRAM_MIB" -eq "$VRAM_MIB" ] 2>/dev/null; then
        echo "nvidia-smi returned no VRAM value — defaulting to cpu_only" >&2
        echo "cpu_only"
        return
    fi
    echo "GPU VRAM: ${VRAM_MIB} MiB" >&2
    if [ "$VRAM_MIB" -lt 10240 ]; then
        echo "low_vram"
    elif [ "$VRAM_MIB" -lt 18432 ]; then
        echo "mid_vram"
    else
        echo "high_vram"
    fi
}

TIER=$(detect_tier)
case "$TIER" in
    cpu_only) TTS_MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base"; LLM_MODEL="qwen3:1.7b" ;;
    low_vram) TTS_MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base"; LLM_MODEL="qwen3:4b" ;;
    mid_vram) TTS_MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-Base"; LLM_MODEL="qwen3:8b" ;;
    high_vram) TTS_MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-Base"; LLM_MODEL="qwen3:14b" ;;
    *) echo "Unknown tier '$TIER' — defaulting to cpu_only" >&2; TIER="cpu_only"; TTS_MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base"; LLM_MODEL="qwen3:1.7b" ;;
esac

cat > "$SHARED_DIR/tier.env" <<EOF
HARDWARE_TIER=${TIER}
SELECTED_TTS_MODEL=${TTS_MODEL}
SELECTED_LLM_MODEL=${LLM_MODEL}
EOF

echo "Wrote $SHARED_DIR/tier.env:" >&2
cat "$SHARED_DIR/tier.env" >&2
