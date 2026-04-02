#!/usr/bin/env sh
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
    echo "GPU VRAM: ${VRAM_MIB} MiB" >&2
    if [ "$VRAM_MIB" -lt 9216 ]; then
        echo "low_vram"
    elif [ "$VRAM_MIB" -lt 18432 ]; then
        echo "mid_vram"
    else
        echo "high_vram"
    fi
}

TIER=$(detect_tier)
case "$TIER" in
    cpu_only) TTS_MODEL="Qwen/Qwen3-TTS-0.6B"; LLM_MODEL="qwen3:1.7b" ;;
    low_vram) TTS_MODEL="Qwen/Qwen3-TTS-0.6B"; LLM_MODEL="qwen3:4b-q4" ;;
    mid_vram) TTS_MODEL="Qwen/Qwen3-TTS-1.7B"; LLM_MODEL="qwen3:8b-q4" ;;
    high_vram) TTS_MODEL="Qwen/Qwen3-TTS-1.7B"; LLM_MODEL="qwen3:8b-q4" ;;
    *) echo "Unknown tier '$TIER' — defaulting to cpu_only" >&2; TIER="cpu_only"; TTS_MODEL="Qwen/Qwen3-TTS-0.6B"; LLM_MODEL="qwen3:1.7b" ;;
esac

cat > "$SHARED_DIR/tier.env" <<EOF
HARDWARE_TIER=${TIER}
SELECTED_TTS_MODEL=${TTS_MODEL}
SELECTED_LLM_MODEL=${LLM_MODEL}
EOF

echo "Wrote $SHARED_DIR/tier.env:" >&2
cat "$SHARED_DIR/tier.env" >&2
