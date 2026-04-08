#!/usr/bin/env bash
# install.sh — Ghost Narrator one-command installer.
# Handles: .env setup, storage backend config, voice directory, Docker images.
set -euo pipefail

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

echo ""
info "Edit .env to configure your setup. Required fields:"
echo "  - SERVER_EXTERNAL_IP: Your server's public IP"
echo "  - GHOST_SITE1_URL / GHOST_KEY_SITE1: Ghost CMS credentials"
echo "  - N8N_USER (must be a valid email) / N8N_PASSWORD / N8N_ENCRYPTION_KEY: n8n auth"
echo ""
info "Optional fields:"
echo "  - VOICE_SAMPLE_REF_TEXT: Transcription of your reference audio (enables higher-quality ICL cloning)"
echo "    Leave blank to use x-vector-only mode (no transcription needed — recommended default)"
echo ""

# Interactive .env editing (optional)
read -r -p "Configure .env now? [y/N] " CONFIGURE_ENV
if [[ "$CONFIGURE_ENV" =~ ^[Yy]$ ]]; then
    # Server IP
    read -r -p "Server external IP (for webhook URLs): " SERVER_IP
    if [ -n "$SERVER_IP" ]; then
        sed -i.bak "s/SERVER_EXTERNAL_IP=.*/SERVER_EXTERNAL_IP=${SERVER_IP}/" .env
    fi

    # Ghost credentials
    read -r -p "Ghost site URL (e.g. https://mysite.com): " GHOST_URL
    if [ -n "$GHOST_URL" ]; then
        sed -i.bak "s|GHOST_SITE1_URL=.*|GHOST_SITE1_URL=${GHOST_URL}|" .env
    fi
    read -r -p "Ghost Content API key: " GHOST_KEY
    if [ -n "$GHOST_KEY" ]; then
        sed -i.bak "s/GHOST_KEY_SITE1=.*/GHOST_KEY_SITE1=${GHOST_KEY}/" .env
    fi

    # n8n auth
    read -r -p "n8n owner email [admin@localhost]: " N8N_USER
    N8N_USER="${N8N_USER:-admin@localhost}"
    sed -i.bak "s/N8N_USER=.*/N8N_USER=${N8N_USER}/" .env

    read -r -s -p "n8n admin password: " N8N_PASS
    echo ""
    if [ -n "$N8N_PASS" ]; then
        sed -i.bak "s/N8N_PASSWORD=.*/N8N_PASSWORD=${N8N_PASS}/" .env
    fi

    # Generate encryption key if placeholder or empty
    if grep -qE "N8N_ENCRYPTION_KEY=(changeme|your-encryption-key-here|)$" .env 2>/dev/null; then
        ENC_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n')
        sed -i.bak "s/N8N_ENCRYPTION_KEY=.*/N8N_ENCRYPTION_KEY=${ENC_KEY}/" .env
        ok "Generated N8N_ENCRYPTION_KEY"
    fi

    rm -f .env.bak
    ok ".env configured"
fi

# ─── Storage Backend ───────────────────────────────────────────────────────────
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

        sed -i.bak "s/STORAGE_BACKEND=.*/STORAGE_BACKEND=gcs/" .env
        sed -i.bak "s/GCS_BUCKET_NAME=.*/GCS_BUCKET_NAME=${GCS_BUCKET}/" .env
        sed -i.bak "s|GCS_SERVICE_ACCOUNT_KEY_PATH=.*|GCS_SERVICE_ACCOUNT_KEY_PATH=/app/secrets/${SA_NAME}-key.json|" .env
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
        read -r -p "AWS region [us-east-1]: " S3_REGION
        S3_REGION="${S3_REGION:-us-east-1}"

        info "Creating S3 bucket..."
        aws s3api create-bucket --bucket "${S3_BUCKET}" --region "${S3_REGION}" \
            $([ "${S3_REGION}" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=${S3_REGION}") 2>/dev/null || warn "Bucket may already exist"

        aws s3api put-public-access-block --bucket "${S3_BUCKET}" \
            --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

        sed -i.bak "s/STORAGE_BACKEND=.*/STORAGE_BACKEND=s3/" .env
        sed -i.bak "s/S3_BUCKET_NAME=.*/S3_BUCKET_NAME=${S3_BUCKET}/" .env
        sed -i.bak "s/AWS_REGION=.*/AWS_REGION=${S3_REGION}/" .env
        rm -f .env.bak

        warn "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env manually"
        ok "S3 configured"
        ;;
    *)
        err "Unknown storage backend: ${STORAGE_CHOICE}"
        exit 1
        ;;
esac

# ─── Voice Sample ──────────────────────────────────────────────────────────────
echo ""
info "Voice sample setup"
mkdir -p tts-service/voices/default

if [ -f tts-service/voices/default/reference.wav ]; then
    ok "Voice sample already exists at tts-service/voices/default/reference.wav"
elif [ -f tts-service/voices/reference.wav ]; then
    info "Found legacy voice sample — copying to new location"
    cp tts-service/voices/reference.wav tts-service/voices/default/reference.wav
    ok "Voice sample moved to tts-service/voices/default/reference.wav"
else
    warn "No voice sample found!"
    echo "  Place a WAV file (5-120 seconds, 16kHz+) at:"
    echo "  tts-service/voices/default/reference.wav"
    echo ""
    read -r -p "Path to voice sample (or skip): " VOICE_PATH
    if [ -n "$VOICE_PATH" ] && [ -f "$VOICE_PATH" ]; then
        cp "$VOICE_PATH" tts-service/voices/default/reference.wav
        ok "Voice sample copied"
    else
        warn "Skipping — add voice sample before starting"
    fi
fi

# ─── GPU Detection ───────────────────────────────────────────────────────
echo ""
info "Detecting GPU..."
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    GPU_DETECTED=true
    ok "NVIDIA GPU detected — GPU compose override will be used"
else
    GPU_DETECTED=false
    info "No NVIDIA GPU detected — running in CPU mode"
    echo "  (If you have a GPU, ensure nvidia-smi is available)"
fi

# Activate GPU overlay via docker-compose.override.yml symlink.
# Docker Compose v2 automatically merges override.yml — this is more reliable
# than COMPOSE_FILE in .env, which Compose v2 ignores for file selection.
if [ "$GPU_DETECTED" = true ]; then
    ln -sf docker-compose.gpu.yml docker-compose.override.yml
    ok "Created docker-compose.override.yml → docker-compose.gpu.yml"
else
    rm -f docker-compose.override.yml
    ok "No GPU — skipped docker-compose.override.yml (CPU mode)"
fi

# ─── Pull Docker Images ───────────────────────────────────────────────────────
echo ""
info "Pulling Docker images (this may take a few minutes on first run)..."
docker compose pull redis n8n ollama 2>/dev/null || warn "Some images failed to pull — will retry on start"

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
