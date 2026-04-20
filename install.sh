#!/usr/bin/env bash
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
# install.sh — Ghost Narrator one-command installer.
# Handles: .env setup, storage backend config, voice directory, Docker images.
set -euo pipefail

if [ ! -f .env.example ]; then
    echo "ERROR: .env.example not found. Run this script from the ghost-narrator directory." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Set or update a KEY=VALUE line in .env (adds if absent, replaces if present).
_set_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" .env 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${val}|" .env && rm -f .env.bak
    else
        echo "${key}=${val}" >> .env
    fi
}

# ─── Preflight ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Ghost Narrator — Installer${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""

# Check Docker
if ! command -v docker &>/dev/null; then
    err "Docker is not installed. Install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi
if ! docker compose version &>/dev/null 2>&1; then
    err "Docker Compose v2 is required. Update Docker Desktop or install the compose plugin."
    exit 1
fi
ok "Docker and Docker Compose found"

# ─── .env Setup ────────────────────────────────────────────────────────────────
if [ -f .env ]; then
    warn ".env already exists — skipping creation"
    info "Delete .env and re-run install.sh to start fresh"
else
    cp .env.example .env
    ok "Created .env from .env.example"
fi

# ─── GPU Detection ────────────────────────────────────────────────────────────
# Run before the configure prompt so the tier override question has context.
echo ""
info "Detecting GPU..."
GPU_DETECTED=false
VLLM_TIER=false

if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    _VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
            | head -1 | tr -d ' ')
    if [ -n "$_VRAM" ] && [ "$_VRAM" -eq "$_VRAM" ] 2>/dev/null && [ "$_VRAM" -gt 0 ]; then
        GPU_DETECTED=true
        if [ "$_VRAM" -ge 12288 ]; then
            VLLM_TIER=true
            ok "NVIDIA GPU detected (${_VRAM} MiB VRAM) — mid/high_vram tier, vLLM backend"
        else
            ok "NVIDIA GPU detected (${_VRAM} MiB VRAM) — low_vram tier, Ollama backend"
            info "GPU accelerates TTS synthesis; Ollama handles the narration LLM"
        fi
    else
        info "nvidia-smi found but returned no VRAM value — falling back to CPU mode"
    fi
else
    info "No NVIDIA GPU detected — running in CPU mode"
    echo "  (If you have a GPU, ensure nvidia-smi is available)"
fi

# GPU overlay: applied for any GPU machine — provides the CUDA base image for
# hardware-probe (nvidia-smi needs driver userspace libs present in the container)
# and NVIDIA device reservations for tts-service (CUDA TTS synthesis). The vllm
# service inside the overlay only starts when COMPOSE_PROFILES=gpu.
if [ "$GPU_DETECTED" = true ]; then
    ln -sf docker-compose.gpu.yml docker-compose.override.yml
    ok "Created docker-compose.override.yml → docker-compose.gpu.yml"
else
    rm -f docker-compose.override.yml
    ok "No GPU — skipped docker-compose.override.yml (CPU mode)"
fi

# ─── LLM Backend Selection ────────────────────────────────────────────────────
# mid_vram / high_vram (VRAM ≥ 12 GB): vLLM — no per-request timeout, 3-5× faster.
# cpu_only / low_vram  (no GPU or < 12 GB VRAM): Ollama — GGUF Q4_K_M quantization.
if [ "$VLLM_TIER" = true ]; then
    _set_env "COMPOSE_PROFILES" "gpu"
    _set_env "LLM_BASE_URL" "http://vllm:8000/v1"
    ok "vLLM backend selected (COMPOSE_PROFILES=gpu)"
    info "First start downloads the HuggingFace model — allow 10-20 min"
else
    _set_env "COMPOSE_PROFILES" "cpu"
    _set_env "LLM_BASE_URL" "http://ollama:11434/v1"
    ok "Ollama backend selected (COMPOSE_PROFILES=cpu)"
fi

# ─── Voice sample: migrate legacy path unconditionally ────────────────────────
mkdir -p tts-service/voices/default
if [ ! -f tts-service/voices/default/reference.wav ] && [ -f tts-service/voices/reference.wav ]; then
    cp tts-service/voices/reference.wav tts-service/voices/default/reference.wav
    ok "Voice sample moved from legacy location to tts-service/voices/default/reference.wav"
fi

# ─── Configure .env ───────────────────────────────────────────────────────────
echo ""
read -r -p "Configure .env now? [y/N] " CONFIGURE_ENV
if [[ "$CONFIGURE_ENV" =~ ^[Yy]$ ]]; then

    # ── Credentials ──────────────────────────────────────────────────────────
    read -r -p "Server external IP (for webhook URLs): " SERVER_IP
    if [ -n "$SERVER_IP" ]; then
        sed -i.bak "s/SERVER_EXTERNAL_IP=.*/SERVER_EXTERNAL_IP=${SERVER_IP}/" .env
    fi

    read -r -p "Timezone [UTC]: " TIMEZONE_VAL
    TIMEZONE_VAL="${TIMEZONE_VAL:-UTC}"
    sed -i.bak "s|TIMEZONE=.*|TIMEZONE=${TIMEZONE_VAL}|" .env

    # Ghost site 1
    read -r -p "Ghost site URL (e.g. https://mysite.com): " GHOST_URL
    if [ -n "$GHOST_URL" ]; then
        sed -i.bak "s|GHOST_SITE1_URL=.*|GHOST_SITE1_URL=${GHOST_URL}|" .env
    fi
    read -r -p "Ghost Content API key: " GHOST_KEY
    if [ -n "$GHOST_KEY" ]; then
        sed -i.bak "s/GHOST_KEY_SITE1=.*/GHOST_KEY_SITE1=${GHOST_KEY}/" .env
    fi
    read -r -p "Ghost Admin API key (for embedding audio player): " GHOST_ADMIN_KEY
    if [ -n "$GHOST_ADMIN_KEY" ]; then
        sed -i.bak "s/GHOST_SITE1_ADMIN_API_KEY=.*/GHOST_SITE1_ADMIN_API_KEY=${GHOST_ADMIN_KEY}/" .env
    fi

    # Ghost site 2 (optional)
    read -r -p "Configure a second Ghost site? [y/N] " SECOND_SITE
    if [[ "$SECOND_SITE" =~ ^[Yy]$ ]]; then
        read -r -p "Ghost site 2 URL: " GHOST_URL2
        if [ -n "$GHOST_URL2" ]; then
            sed -i.bak "s|GHOST_SITE2_URL=.*|GHOST_SITE2_URL=${GHOST_URL2}|" .env
        fi
        read -r -p "Ghost site 2 Content API key: " GHOST_KEY2
        if [ -n "$GHOST_KEY2" ]; then
            sed -i.bak "s/GHOST_KEY_SITE2=.*/GHOST_KEY_SITE2=${GHOST_KEY2}/" .env
        fi
        read -r -p "Ghost site 2 Admin API key: " GHOST_ADMIN_KEY2
        if [ -n "$GHOST_ADMIN_KEY2" ]; then
            sed -i.bak "s/GHOST_SITE2_ADMIN_API_KEY=.*/GHOST_SITE2_ADMIN_API_KEY=${GHOST_ADMIN_KEY2}/" .env
        fi
        ok "Ghost site 2 configured"
    fi

    # n8n auth
    read -r -p "n8n owner email [admin@localhost]: " N8N_USER
    N8N_USER="${N8N_USER:-admin@localhost}"
    sed -i.bak "s/N8N_USER=.*/N8N_USER=${N8N_USER}/" .env

    read -r -s -p "n8n admin password: " N8N_PASS
    echo ""
    if [ -n "$N8N_PASS" ]; then
        tmpfile=$(mktemp)
        grep -v '^N8N_PASSWORD=' .env > "$tmpfile"
        printf '%s=%s\n' N8N_PASSWORD "$N8N_PASS" >> "$tmpfile"
        mv "$tmpfile" .env
    fi

    # Auto-generate secrets if missing
    if grep -qE "N8N_ENCRYPTION_KEY=(changeme|your-encryption-key-here|)$" .env 2>/dev/null; then
        ENC_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n')
        tmpfile=$(mktemp)
        grep -v '^N8N_ENCRYPTION_KEY=' .env > "$tmpfile"
        echo "N8N_ENCRYPTION_KEY=${ENC_KEY}" >> "$tmpfile"
        mv "$tmpfile" .env
        ok "Generated N8N_ENCRYPTION_KEY"
    fi
    if [ -z "$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2)" ]; then
        REDIS_PASS=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -d '=\n/')
        tmpfile=$(mktemp)
        grep -v '^REDIS_PASSWORD=' .env > "$tmpfile"
        echo "REDIS_PASSWORD=${REDIS_PASS}" >> "$tmpfile"
        mv "$tmpfile" .env
        info "Generated REDIS_PASSWORD"
    fi
    if [ -z "$(grep '^N8N_GHOST_WEBHOOK_SECRET=' .env | cut -d= -f2)" ]; then
        WEBHOOK_SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -d '=\n/')
        tmpfile=$(mktemp)
        grep -v '^N8N_GHOST_WEBHOOK_SECRET=' .env > "$tmpfile"
        echo "N8N_GHOST_WEBHOOK_SECRET=${WEBHOOK_SECRET}" >> "$tmpfile"
        mv "$tmpfile" .env
        info "Generated N8N_GHOST_WEBHOOK_SECRET — set this same value in Ghost's webhook settings"
    fi
    if [ -z "$(grep '^TTS_API_KEY=' .env | cut -d= -f2)" ]; then
        TTS_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -d '=\n/')
        tmpfile=$(mktemp)
        grep -v '^TTS_API_KEY=' .env > "$tmpfile"
        echo "TTS_API_KEY=${TTS_KEY}" >> "$tmpfile"
        mv "$tmpfile" .env
        info "Generated TTS_API_KEY"
    fi

    # ── Hardware tier override ────────────────────────────────────────────────
    echo ""
    info "Hardware tier: auto-detected above (recommended)"
    echo "  Override only if auto-detection is wrong: cpu_only | low_vram | mid_vram | high_vram"
    read -r -p "Hardware tier override (leave blank to keep auto-detected): " HW_TIER
    if [ -n "$HW_TIER" ]; then
        sed -i.bak "s/HARDWARE_TIER=.*/HARDWARE_TIER=${HW_TIER}/" .env
        ok "Hardware tier set to ${HW_TIER}"
    fi

    # ── Storage Backend ───────────────────────────────────────────────────────
    echo ""
    info "Storage backend — where audio files are saved:"
    echo "  local  — Docker volume (no cloud setup needed) [default]"
    echo "  gcs    — Google Cloud Storage"
    echo "  s3     — AWS S3"
    echo ""
    read -r -p "Storage backend [local]: " STORAGE_CHOICE
    STORAGE_CHOICE="${STORAGE_CHOICE:-local}"

    case "$STORAGE_CHOICE" in
        local)
            ok "Using local storage (Docker volume tts_output)"
            ;;
        gcs)
            info "GCS Setup"
            if ! command -v gcloud &>/dev/null; then
                err "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
                exit 1
            fi
            read -r -p "GCS bucket name: " GCS_BUCKET
            read -r -p "GCS audio prefix [audio/articles]: " GCS_PREFIX
            GCS_PREFIX="${GCS_PREFIX:-audio/articles}"
            read -r -p "GCP project ID: " GCS_PROJECT
            read -r -p "Service account name [ghost-narrator-tts]: " SA_NAME
            SA_NAME="${SA_NAME:-ghost-narrator-tts}"

            info "Creating GCS bucket..."
            gcloud storage buckets create "gs://${GCS_BUCKET}" --project="${GCS_PROJECT}" --uniform-bucket-level-access 2>/dev/null || warn "Bucket may already exist"

            info "Creating service account..."
            gcloud iam service-accounts create "${SA_NAME}" --project="${GCS_PROJECT}" \
                --description="Ghost Narrator TTS audio uploads" 2>/dev/null || warn "Service account may already exist"

            SA_EMAIL="${SA_NAME}@${GCS_PROJECT}.iam.gserviceaccount.com"
            gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
                --member="serviceAccount:${SA_EMAIL}" --role="roles/storage.objectAdmin"

            KEY_FILE="${SCRIPT_DIR}/secrets/${SA_NAME}-key.json"
            mkdir -p "${SCRIPT_DIR}/secrets"
            gcloud iam service-accounts keys create "${KEY_FILE}" --iam-account="${SA_EMAIL}"
            chmod 644 "${KEY_FILE}"

            sed -i.bak "s/STORAGE_BACKEND=.*/STORAGE_BACKEND=gcs/" .env
            sed -i.bak -E "s|^#?[[:space:]]*GCS_BUCKET_NAME=.*|GCS_BUCKET_NAME=${GCS_BUCKET}|" .env
            sed -i.bak -E "s|^#?[[:space:]]*GCS_AUDIO_PREFIX=.*|GCS_AUDIO_PREFIX=${GCS_PREFIX}|" .env
            sed -i.bak -E "s|^#?[[:space:]]*GCS_SERVICE_ACCOUNT_KEY_PATH=.*|GCS_SERVICE_ACCOUNT_KEY_PATH=/app/secrets/${SA_NAME}-key.json|" .env
            rm -f .env.bak
            ok "GCS configured — key saved to secrets/"
            ;;
        s3)
            info "AWS S3 Setup"
            if ! command -v aws &>/dev/null; then
                err "AWS CLI not found. Install: https://aws.amazon.com/cli/"
                exit 1
            fi
            read -r -p "S3 bucket name: " S3_BUCKET
            read -r -p "S3 audio prefix [audio/articles]: " S3_PREFIX
            S3_PREFIX="${S3_PREFIX:-audio/articles}"
            read -r -p "AWS region [us-east-1]: " S3_REGION
            S3_REGION="${S3_REGION:-us-east-1}"
            read -r -p "AWS Access Key ID: " AWS_KEY_ID
            read -r -s -p "AWS Secret Access Key: " AWS_SECRET
            echo ""

            info "Creating S3 bucket..."
            aws s3api create-bucket --bucket "${S3_BUCKET}" --region "${S3_REGION}" \
                $([ "${S3_REGION}" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=${S3_REGION}") 2>/dev/null || warn "Bucket may already exist"

            aws s3api put-public-access-block --bucket "${S3_BUCKET}" \
                --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

            sed -i.bak "s/STORAGE_BACKEND=.*/STORAGE_BACKEND=s3/" .env
            sed -i.bak -E "s|^#?[[:space:]]*S3_BUCKET_NAME=.*|S3_BUCKET_NAME=${S3_BUCKET}|" .env
            sed -i.bak -E "s|^#?[[:space:]]*S3_AUDIO_PREFIX=.*|S3_AUDIO_PREFIX=${S3_PREFIX}|" .env
            sed -i.bak -E "s|^#?[[:space:]]*AWS_REGION=.*|AWS_REGION=${S3_REGION}|" .env
            if [ -n "$AWS_KEY_ID" ]; then
                sed -i.bak -E "s|^#?[[:space:]]*AWS_ACCESS_KEY_ID=.*|AWS_ACCESS_KEY_ID=${AWS_KEY_ID}|" .env
            fi
            if [ -n "$AWS_SECRET" ]; then
                sed -i.bak -E "s|^#?[[:space:]]*AWS_SECRET_ACCESS_KEY=.*|AWS_SECRET_ACCESS_KEY=${AWS_SECRET}|" .env
            fi
            rm -f .env.bak
            ok "S3 configured"
            ;;
        *)
            err "Unknown storage backend: ${STORAGE_CHOICE}"
            exit 1
            ;;
    esac

    # ── Voice Sample ──────────────────────────────────────────────────────────
    echo ""
    info "Voice sample setup"
    if [ -f tts-service/voices/default/reference.wav ]; then
        ok "Voice sample already exists at tts-service/voices/default/reference.wav"
    else
        warn "No voice sample found!"
        echo "  Place a WAV file (5-120 seconds, 16kHz+) at:"
        echo "  tts-service/voices/default/reference.wav"
        echo ""
        read -r -p "Path to voice sample (or skip): " VOICE_PATH
        if [ -n "$VOICE_PATH" ] && [ -f "$VOICE_PATH" ]; then
            cp "$VOICE_PATH" tts-service/voices/default/reference.wav
            if file tts-service/voices/default/reference.wav 2>/dev/null | grep -q -i "wave\|audio"; then
                ok "Voice sample copied and validated"
            else
                warn "File may not be a valid WAV audio — proceeding anyway"
            fi
        else
            warn "Skipping — add voice sample before starting"
        fi
    fi

    # ── Voice Reference Text ──────────────────────────────────────────────────
    echo ""
    info "Voice reference text (optional)"
    echo "  The exact transcript of your reference.wav enables ICL (in-context learning)"
    echo "  mode for higher-quality voice cloning."
    echo "  Leave blank to use x-vector-only mode — no transcript needed (recommended default)."
    echo ""
    read -r -p "Paste the transcript of your voice sample, or press Enter to skip: " REF_TEXT
    if [ -n "$REF_TEXT" ]; then
        awk -v val="VOICE_SAMPLE_REF_TEXT=${REF_TEXT}" \
            '/^VOICE_SAMPLE_REF_TEXT=/{print val; next} {print}' .env > .env.tmp && mv .env.tmp .env
        ok "Voice reference text saved"
    else
        info "Using x-vector-only mode (no transcript)"
    fi

    rm -f .env.bak
    ok ".env configured"
else
    # Not configuring — warn about anything that will block startup
    if [ ! -f tts-service/voices/default/reference.wav ]; then
        warn "No voice sample found — add tts-service/voices/default/reference.wav before starting"
    fi
fi

# ─── Pull Docker Images ───────────────────────────────────────────────────────
echo ""
info "Pulling Docker images (this may take a few minutes on first run)..."
docker compose pull redis n8n 2>/dev/null || warn "Some images failed to pull — will retry on start"
if [ "$VLLM_TIER" = true ]; then
    docker compose --profile gpu pull vllm 2>/dev/null || warn "vLLM image pull failed — will retry on start"
else
    docker compose --profile cpu pull ollama 2>/dev/null || warn "Ollama image pull failed — will retry on start"
fi

info "Building TTS service image..."
docker compose build tts-service 2>/dev/null || warn "Build failed — check Dockerfile"

# ─── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Start the stack:"
echo -e "    ${BLUE}docker compose up -d${NC}"
echo ""
echo "  View logs:"
echo -e "    ${BLUE}docker compose logs -f${NC}"
echo ""
echo "  Open n8n dashboard:"
SERVER_IP=$(grep SERVER_EXTERNAL_IP .env 2>/dev/null | cut -d= -f2 || echo "YOUR_SERVER_IP")
echo -e "    ${BLUE}http://${SERVER_IP}:5678${NC}"
echo ""
echo "  Import n8n workflows from: n8n/workflows/"
echo ""
