# Plan C: Infrastructure + Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up the full Docker Compose stack (hardware-probe, Ollama, GPU override), update n8n workflows for storage-agnostic audio URIs, rewrite all scripts, and update all documentation.

**Architecture:** A lightweight `hardware-probe` Alpine container writes `tier.env` to a shared Docker volume at startup. Ollama reads it to pull the correct model. Base compose is GPU-free; `docker-compose.gpu.yml` adds device reservations. `start.sh` auto-detects nvidia-smi. n8n callback workflow updated to parse `gs://`, `s3://`, and `local://` URIs.

**Tech Stack:** Docker Compose v2, Bash, n8n workflow JSON, Alpine Linux

**Spec:** `docs/superpowers/specs/2026-04-02-standalone-tts-design.md` — Sections 2, 7, 8

**Dependency:** Plans A and B must be complete before this plan is started.

---

## File Map

```
ghost-narrator/
├── docker-compose.yml                       MODIFY — add ollama, hardware-probe, update defaults
├── docker-compose.gpu.yml                   NEW — GPU device overrides
├── start.sh                                 NEW — auto-detects GPU, runs correct compose
├── .env.example                             MODIFY — all new env vars documented
├── .gitignore                               MODIFY — voices/profiles/*.wav, shared/
├── scripts/
│   ├── hardware-probe.sh                    NEW — detects GPU, writes tier.env
│   ├── ollama-init.sh                       NEW — pulls tier-selected model, pre-warms
│   ├── init.sh                              MODIFY — update Fish Speech refs
│   ├── validate-build.sh                    REWRITE — Qwen3-TTS validation
│   ├── setup-storage.sh                     NEW (renamed from setup-gcp.sh) — GCS + S3 setup
│   ├── backfill-audio.sh                    MODIFY — update model name refs
│   └── backfill-audio.ps1                   MODIFY — update model name refs
├── n8n/
│   ├── SETUP_GUIDE.md                       MODIFY — Ollama refs, storage backend notes
│   └── workflows/
│       ├── ghost-audio-callback.json        MODIFY — audio_uri multi-scheme parsing
│       └── static-content-audio-pipeline.json  MODIFY — storage-backend awareness
├── tts-service/
│   ├── README.md                            REWRITE
│   ├── QUICKSTART.md                        MODIFY
│   ├── run-docker.sh                        MODIFY
│   └── run-docker.ps1                       MODIFY
├── docs/
│   └── ARCHITECTURE.md                      REWRITE
├── README.md                                NEW — project root README
├── NOTICE                                   NEW — Apache 2.0 attribution
├── CHANGELOG.md                             MODIFY
├── CONTRIBUTING.md                          MODIFY — new repo URL
├── CODE_OF_CONDUCT.md                       MODIFY — repo refs
└── SECURITY.md                              MODIFY — repo refs
```

---

## Task 1: hardware-probe.sh

**Files:**
- Create: `scripts/hardware-probe.sh`

- [ ] **Step 1: Create `scripts/hardware-probe.sh`**

```bash
#!/usr/bin/env sh
# hardware-probe.sh — Detects GPU/VRAM and writes tier.env to /shared/
# Runs as a Docker init container (restart: "no") before other services start.

set -e

SHARED_DIR="${SHARED_DIR:-/shared}"
mkdir -p "$SHARED_DIR"

detect_tier() {
    # Check for HARDWARE_TIER override first
    if [ -n "$HARDWARE_TIER" ]; then
        echo "HARDWARE_TIER override: $HARDWARE_TIER" >&2
        echo "$HARDWARE_TIER"
        return
    fi

    # Check for CUDA/GPU via nvidia-smi
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

    # Get VRAM in MiB (first GPU)
    VRAM_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    echo "GPU VRAM: ${VRAM_MIB} MiB" >&2

    if [ "$VRAM_MIB" -lt 9216 ]; then   # < 9 GB
        echo "low_vram"
    elif [ "$VRAM_MIB" -lt 18432 ]; then  # < 18 GB
        echo "mid_vram"
    else
        echo "high_vram"
    fi
}

TIER=$(detect_tier)

case "$TIER" in
    cpu_only)
        TTS_MODEL="Qwen/Qwen3-TTS-0.6B"
        LLM_MODEL="qwen3:1.7b"
        ;;
    low_vram)
        TTS_MODEL="Qwen/Qwen3-TTS-0.6B"
        LLM_MODEL="qwen3:4b-q4"
        ;;
    mid_vram)
        TTS_MODEL="Qwen/Qwen3-TTS-1.7B"
        LLM_MODEL="qwen3:8b-q4"
        ;;
    high_vram)
        TTS_MODEL="Qwen/Qwen3-TTS-1.7B"
        LLM_MODEL="qwen3:8b-q4"
        ;;
    *)
        echo "Unknown tier '$TIER' — defaulting to cpu_only" >&2
        TIER="cpu_only"
        TTS_MODEL="Qwen/Qwen3-TTS-0.6B"
        LLM_MODEL="qwen3:1.7b"
        ;;
esac

cat > "$SHARED_DIR/tier.env" <<EOF
HARDWARE_TIER=${TIER}
SELECTED_TTS_MODEL=${TTS_MODEL}
SELECTED_LLM_MODEL=${LLM_MODEL}
EOF

echo "Wrote $SHARED_DIR/tier.env:" >&2
cat "$SHARED_DIR/tier.env" >&2
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/hardware-probe.sh
```

- [ ] **Step 3: Test locally (CPU path)**

```bash
bash scripts/hardware-probe.sh
cat /shared/tier.env
# Expected:
# HARDWARE_TIER=cpu_only
# SELECTED_TTS_MODEL=Qwen/Qwen3-TTS-0.6B
# SELECTED_LLM_MODEL=qwen3:1.7b
```

- [ ] **Step 4: Test with override**

```bash
HARDWARE_TIER=high_vram bash scripts/hardware-probe.sh
cat /shared/tier.env
# Expected: HARDWARE_TIER=high_vram, SELECTED_LLM_MODEL=qwen3:8b-q4
```

- [ ] **Step 5: Commit**

```bash
git add scripts/hardware-probe.sh
git commit -m "feat(infra): hardware-probe.sh — detects GPU tier, writes tier.env"
```

---

## Task 2: ollama-init.sh

**Files:**
- Create: `scripts/ollama-init.sh`

- [ ] **Step 1: Create `scripts/ollama-init.sh`**

```bash
#!/usr/bin/env sh
# ollama-init.sh — Starts Ollama, pulls tier-selected model, pre-warms.
# Runs as the entrypoint for the ollama container.

set -e

SHARED_DIR="${SHARED_DIR:-/shared}"
TIER_ENV="$SHARED_DIR/tier.env"

# Wait for tier.env from hardware-probe (should already exist due to depends_on)
MAX_WAIT=30
i=0
while [ ! -f "$TIER_ENV" ]; do
    if [ "$i" -ge "$MAX_WAIT" ]; then
        echo "ERROR: $TIER_ENV not found after ${MAX_WAIT}s — cannot select model" >&2
        exit 1
    fi
    echo "Waiting for tier.env... ($i/${MAX_WAIT}s)" >&2
    sleep 1
    i=$((i + 1))
done

# Source tier selection
. "$TIER_ENV"
echo "Hardware tier: $HARDWARE_TIER — LLM: $SELECTED_LLM_MODEL" >&2

# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama API to be ready
MAX_WAIT=60
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

# Pull model if not already cached
if ollama list 2>/dev/null | grep -q "^${SELECTED_LLM_MODEL}"; then
    echo "Model $SELECTED_LLM_MODEL already cached — skipping pull" >&2
else
    echo "Pulling $SELECTED_LLM_MODEL (this may take several minutes on first run)..." >&2
    ollama pull "$SELECTED_LLM_MODEL"
fi

# Pre-warm: load model into memory with a short prompt
echo "Pre-warming model $SELECTED_LLM_MODEL..." >&2
ollama run "$SELECTED_LLM_MODEL" "Say: ready" >/dev/null 2>&1 || true
echo "Model ready" >&2

# Keep Ollama running
wait "$OLLAMA_PID"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/ollama-init.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/ollama-init.sh
git commit -m "feat(infra): ollama-init.sh — pulls tier-selected model and pre-warms"
```

---

## Task 3: Update docker-compose.yml

**Files:**
- Modify: `ghost-narrator/docker-compose.yml`

- [ ] **Step 1: Read current `docker-compose.yml` fully before editing**

```bash
cat docker-compose.yml
```

- [ ] **Step 2: Add `hardware-probe` service at the top of `services:`**

```yaml
  # ─── Hardware Probe: Tier Detection (init, runs once) ─────────────────────
  hardware-probe:
    image: alpine:3.19
    container_name: hardware-probe
    restart: "no"
    environment:
      - HARDWARE_TIER=${HARDWARE_TIER:-}
    volumes:
      - ./scripts/hardware-probe.sh:/scripts/hardware-probe.sh:ro
      - tier_data:/shared
    entrypoint: ["/bin/sh", "/scripts/hardware-probe.sh"]
```

- [ ] **Step 3: Add `ollama` service**

```yaml
  # ─── Ollama: Bundled Narration LLM ────────────────────────────────────────
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    environment:
      - SHARED_DIR=/shared
    volumes:
      - ollama_models:/root/.ollama
      - tier_data:/shared:ro
      - ./scripts/ollama-init.sh:/scripts/ollama-init.sh:ro
    entrypoint: ["/bin/sh", "/scripts/ollama-init.sh"]
    networks:
      - pipeline_net
    depends_on:
      hardware-probe:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 600s
    deploy:
      resources:
        limits:
          memory: 12G
        reservations:
          memory: 2G
```

- [ ] **Step 4: Update `n8n` service — change VLLM vars and add ollama dependency**

```yaml
# In n8n environment, change defaults:
- VLLM_BASE_URL=${LLM_BASE_URL:-http://ollama:11434/v1}
- VLLM_MODEL_NAME=${LLM_MODEL_NAME:-}  # populated from tier.env at runtime

# In n8n depends_on, add:
      ollama:
        condition: service_healthy
```

- [ ] **Step 5: Update `tts-service` — add hardware-probe dependency and new env vars**

```yaml
# In tts-service environment, add:
      - HARDWARE_TIER=${HARDWARE_TIER:-}
      - STORAGE_BACKEND=${STORAGE_BACKEND:-local}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
      - AWS_REGION=${AWS_REGION:-us-east-1}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME:-}
      - S3_AUDIO_PREFIX=${S3_AUDIO_PREFIX:-audio/articles}
      - GCS_SERVICE_ACCOUNT_KEY_PATH=${GCS_SERVICE_ACCOUNT_KEY_PATH:-}
      - LLM_BASE_URL=${LLM_BASE_URL:-http://ollama:11434/v1}
      - LLM_MODEL_NAME=${LLM_MODEL_NAME:-}

# Remove old static DEVICE line (now auto-detected from hardware)

# Add hardware-probe dependency:
    depends_on:
      hardware-probe:
        condition: service_completed_successfully
      redis:
        condition: service_healthy

# Add tier_data volume mount:
      - tier_data:/shared:ro

# Remove hardcoded GPU device section (moves to docker-compose.gpu.yml)
```

- [ ] **Step 6: Add new volumes**

```yaml
volumes:
  redis_data:
  n8n_data:
  tts_output:
  tier_data:       # hardware-probe writes, others read
  ollama_models:   # persistent Ollama model cache
  voices_data:     # voice profiles survive container restarts
```

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): add hardware-probe and ollama services, wire tier_data volume"
```

---

## Task 4: docker-compose.gpu.yml + start.sh

**Files:**
- Create: `docker-compose.gpu.yml`
- Create: `start.sh`

- [ ] **Step 1: Create `docker-compose.gpu.yml`**

```yaml
# docker-compose.gpu.yml — GPU device overrides
# Usage: docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
# Or run ./start.sh which auto-detects and applies this file if GPU present.

services:
  hardware-probe:
    volumes:
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  tts-service:
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

- [ ] **Step 2: Create `start.sh`**

```bash
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
```

- [ ] **Step 3: Make executable and test**

```bash
chmod +x start.sh
./start.sh config  # dry-run — prints merged config without starting
```
Expected: prints merged YAML, no errors

- [ ] **Step 4: Commit**

```bash
git add docker-compose.gpu.yml start.sh
git commit -m "feat(infra): docker-compose.gpu.yml override + start.sh auto-GPU detection"
```

---

## Task 5: Update n8n callback workflow for multi-scheme audio URIs

**Files:**
- Modify: `n8n/workflows/ghost-audio-callback.json`

- [ ] **Step 1: Read the current `parse-callback` node JS code**

```bash
cat n8n/workflows/ghost-audio-callback.json | python -m json.tool | grep -A 5 '"jsCode"'
```

The current code only handles `gs://` URIs and returns `skip: true` for anything else.

- [ ] **Step 2: Replace the `jsCode` in the `parse-callback` node**

Find the node with `"id": "parse-callback"` in `ghost-audio-callback.json`. Replace its `jsCode` string value with:

```javascript
const data = $input.first().json.body || $input.first().json;

if (!data.job_id) {
  return [{ json: { skip: true, reason: 'Callback missing job_id' } }];
}

if (data.status !== 'completed') {
  return [{ json: { skip: true, reason: `Job status is ${data.status}` } }];
}

// Support audio_uri (new) and gcs_uri (backward-compat)
const rawUri = data.audio_uri || data.gcs_uri || '';

if (!rawUri) {
  return [{ json: { skip: true, reason: 'No audio_uri in callback payload' } }];
}

// Resolve to public HTTP URL based on URI scheme
let audioUrl = '';

if (rawUri.startsWith('gs://')) {
  const parts = rawUri.replace('gs://', '').split('/');
  const bucket = parts.shift();
  const objectPath = parts.join('/');
  audioUrl = `https://storage.googleapis.com/${bucket}/${objectPath}`;

} else if (rawUri.startsWith('s3://')) {
  // s3://bucket/prefix/site/job.mp3 → https://bucket.s3.region.amazonaws.com/prefix/...
  const withoutScheme = rawUri.replace('s3://', '');
  const slashIdx = withoutScheme.indexOf('/');
  const bucket = withoutScheme.substring(0, slashIdx);
  const key = withoutScheme.substring(slashIdx + 1);
  const region = $env.AWS_REGION || 'us-east-1';
  audioUrl = `https://${bucket}.s3.${region}.amazonaws.com/${key}`;

} else if (rawUri.startsWith('local://')) {
  // local://job123.mp3 → http://tts-service:8020/tts/download/job123
  const jobFile = rawUri.replace('local://', '');
  const jobId = jobFile.replace('.mp3', '');
  audioUrl = `http://tts-service:8020/tts/download/${jobId}`;

} else {
  return [{ json: { skip: true, reason: `Unknown audio URI scheme: ${rawUri}` } }];
}

// Extract postId from job_id
let postId = '';
let siteSlug = '';

if (data.job_id.includes('-pid-')) {
  const parts = data.job_id.split('-pid-');
  siteSlug = parts[0];
  postId = parts[1].split('-')[0];
} else {
  const parts = data.job_id.split('-');
  const postIdIndex = parts.findIndex(part => part.length === 24 && /^[0-9a-fA-F]+$/.test(part));
  if (postIdIndex !== -1) {
    postId = parts[postIdIndex];
    siteSlug = parts.slice(0, postIdIndex).join('-');
  }
}

if (!postId || postId.length !== 24) {
  return [{ json: { skip: true, reason: `Could not extract valid post ID from: ${data.job_id}` } }];
}

return [{
  json: {
    skip: false,
    jobId: data.job_id,
    postId,
    siteSlug,
    audioUrl,
    audioUri: rawUri
  }
}];
```

- [ ] **Step 3: Validate JSON is still valid**

```bash
python -m json.tool n8n/workflows/ghost-audio-callback.json > /dev/null && echo "Valid JSON"
```
Expected: `Valid JSON`

- [ ] **Step 4: Commit**

```bash
git add n8n/workflows/ghost-audio-callback.json
git commit -m "feat(n8n): callback workflow handles gs://, s3://, local:// audio URIs"
```

---

## Task 6: Update static-content workflow for storage awareness

**Files:**
- Modify: `n8n/workflows/static-content-audio-pipeline.json`

- [ ] **Step 1: Read the static-content workflow**

```bash
python -m json.tool n8n/workflows/static-content-audio-pipeline.json | grep -i "gcs_uri\|audio_uri\|storage" | head -20
```

- [ ] **Step 2: Find any hardcoded `gcs_uri` references and replace with `audio_uri`**

The static-content workflow passes job results to the TTS service and may parse the callback. Apply the same `audio_uri` field rename as in Task 5. If the workflow has a code node that checks `data.gcs_uri`, update it to `data.audio_uri || data.gcs_uri`.

- [ ] **Step 3: Validate JSON**

```bash
python -m json.tool n8n/workflows/static-content-audio-pipeline.json > /dev/null && echo "Valid JSON"
```

- [ ] **Step 4: Commit**

```bash
git add n8n/workflows/static-content-audio-pipeline.json
git commit -m "feat(n8n): static-content workflow uses audio_uri field"
```

---

## Task 7: Rewrite validate-build.sh

**Files:**
- Rewrite: `scripts/validate-build.sh`

- [ ] **Step 1: Read current `validate-build.sh` to understand test structure**

```bash
head -80 scripts/validate-build.sh
```

- [ ] **Step 2: Rewrite `validate-build.sh`**

```bash
#!/usr/bin/env bash
# validate-build.sh — Validates the ghost-narrator Docker image is correctly built.
# Tests: Qwen3-TTS imports, new API endpoints, hardware detection, storage factory.
set -euo pipefail

IMAGE="${1:-ghost-tts-service:latest}"
CONTAINER="tts-validate-$$"

cleanup() { docker rm -f "$CONTAINER" 2>/dev/null || true; }
trap cleanup EXIT

echo "=== Validating $IMAGE ==="

# 1. Container starts
echo "[1/6] Container starts..."
docker run -d --name "$CONTAINER" \
    -e HARDWARE_TIER=cpu_only \
    -e STORAGE_BACKEND=local \
    "$IMAGE" uvicorn app.main:app --host 0.0.0.0 --port 8020

sleep 10

# 2. Health endpoint responds
echo "[2/6] Health endpoint..."
docker exec "$CONTAINER" python -c "
import urllib.request, json
res = urllib.request.urlopen('http://localhost:8020/health')
data = json.loads(res.read())
assert 'hardware_tier' in data, f'Missing hardware_tier in health: {data}'
assert data['hardware_tier'] == 'cpu_only', f'Expected cpu_only, got: {data}'
print('  hardware_tier:', data['hardware_tier'])
print('  tts_model:', data.get('tts_model'))
"

# 3. Qwen3-TTS imports
echo "[3/6] Qwen3-TTS imports..."
docker exec "$CONTAINER" python -c "
from app.core.tts_engine import get_tts_engine
engine = get_tts_engine()
print('  TTSEngine created:', type(engine).__name__)
"

# 4. Hardware detection
echo "[4/6] Hardware detection..."
docker exec "$CONTAINER" python -c "
from app.core.hardware import ENGINE_CONFIG
print('  Tier:', ENGINE_CONFIG.tier.value)
print('  TTS model:', ENGINE_CONFIG.tts_model)
print('  LLM model:', ENGINE_CONFIG.llm_model)
"

# 5. Storage backend factory
echo "[5/6] Storage backend..."
docker exec -e STORAGE_BACKEND=local "$CONTAINER" python -c "
from app.services.storage import get_storage_backend
b = get_storage_backend()
print('  Backend:', type(b).__name__)
"

# 6. Voices endpoint
echo "[6/6] Voices endpoint..."
docker exec "$CONTAINER" python -c "
import urllib.request, json
res = urllib.request.urlopen('http://localhost:8020/voices')
data = json.loads(res.read())
assert 'profiles' in data, f'Missing profiles in voices response: {data}'
print('  Profiles:', data['profiles'])
"

echo ""
echo "=== All validation checks passed ==="
```

- [ ] **Step 3: Make executable**

```bash
chmod +x scripts/validate-build.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/validate-build.sh
git commit -m "chore(scripts): rewrite validate-build.sh for Qwen3-TTS and new endpoints"
```

---

## Task 8: setup-storage.sh (renamed from setup-gcp.sh)

**Files:**
- Create: `scripts/setup-storage.sh` (replaces `scripts/setup-gcp.sh`)
- Delete: `scripts/setup-gcp.sh`

- [ ] **Step 1: Create `scripts/setup-storage.sh`**

```bash
#!/usr/bin/env bash
# setup-storage.sh — Helper for configuring cloud storage backends.
# Usage: bash scripts/setup-storage.sh [gcs|s3]
set -euo pipefail

BACKEND="${1:-}"

usage() {
    echo "Usage: $0 [gcs|s3]"
    echo "  gcs  — Create GCS bucket and service account"
    echo "  s3   — Create AWS S3 bucket and IAM policy"
    exit 1
}

setup_gcs() {
    echo "=== GCS Setup ==="
    command -v gcloud >/dev/null 2>&1 || { echo "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"; exit 1; }

    read -r -p "GCS bucket name: " BUCKET_NAME
    read -r -p "GCP project ID: " PROJECT_ID
    read -r -p "Service account name [ghost-narrator-tts]: " SA_NAME
    SA_NAME="${SA_NAME:-ghost-narrator-tts}"

    gcloud storage buckets create "gs://$BUCKET_NAME" --project="$PROJECT_ID" --uniform-bucket-level-access
    gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT_ID" \
        --description="Ghost Narrator TTS audio uploads" --display-name="Ghost Narrator TTS"
    SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
    gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
        --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectAdmin"
    KEY_FILE="${SA_NAME}-key.json"
    gcloud iam service-accounts keys create "$KEY_FILE" --iam-account="$SA_EMAIL"

    echo ""
    echo "=== Add to .env ==="
    echo "STORAGE_BACKEND=gcs"
    echo "GCS_BUCKET_NAME=$BUCKET_NAME"
    echo "GCS_SERVICE_ACCOUNT_KEY_PATH=/run/secrets/${KEY_FILE}  # or mount path"
}

setup_s3() {
    echo "=== AWS S3 Setup ==="
    command -v aws >/dev/null 2>&1 || { echo "AWS CLI not found. Install: https://aws.amazon.com/cli/"; exit 1; }

    read -r -p "S3 bucket name: " BUCKET_NAME
    read -r -p "AWS region [us-east-1]: " REGION
    REGION="${REGION:-us-east-1}"
    read -r -p "IAM username for TTS uploads [ghost-narrator-tts]: " IAM_USER
    IAM_USER="${IAM_USER:-ghost-narrator-tts}"

    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
        $([ "$REGION" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=$REGION")

    # Block public access
    aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
        --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

    # Create IAM user + policy
    aws iam create-user --user-name "$IAM_USER"
    POLICY_ARN=$(aws iam create-policy --policy-name "${IAM_USER}-s3-policy" \
        --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\",\"s3:GetObject\",\"s3:DeleteObject\"],\"Resource\":\"arn:aws:s3:::${BUCKET_NAME}/*\"}]}" \
        --query Policy.Arn --output text)
    aws iam attach-user-policy --user-name "$IAM_USER" --policy-arn "$POLICY_ARN"
    KEYS=$(aws iam create-access-key --user-name "$IAM_USER" --query AccessKey --output json)

    echo ""
    echo "=== Add to .env ==="
    echo "STORAGE_BACKEND=s3"
    echo "S3_BUCKET_NAME=$BUCKET_NAME"
    echo "AWS_REGION=$REGION"
    echo "AWS_ACCESS_KEY_ID=$(echo "$KEYS" | python -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")"
    echo "AWS_SECRET_ACCESS_KEY=$(echo "$KEYS" | python -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")"
}

case "$BACKEND" in
    gcs) setup_gcs ;;
    s3)  setup_s3 ;;
    *)   usage ;;
esac
```

- [ ] **Step 2: Delete old script, make new one executable**

```bash
git rm scripts/setup-gcp.sh
chmod +x scripts/setup-storage.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/setup-storage.sh
git commit -m "feat(scripts): setup-storage.sh with GCS and S3 setup (replaces setup-gcp.sh)"
```

---

## Task 9: .env.example + .gitignore updates

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Update `.env.example`**

Add all new sections. Keep all existing entries. Add after existing blocks:

```env
# ─── Hardware Detection ────────────────────────────────────────────────────────
# Override auto-detection. Leave blank for automatic. Values: cpu_only, low_vram, mid_vram, high_vram
HARDWARE_TIER=

# ─── Narration LLM ─────────────────────────────────────────────────────────────
# Default: bundled Ollama (http://ollama:11434/v1)
# Override to use external vLLM: http://host.docker.internal:8001/v1
LLM_BASE_URL=http://ollama:11434/v1

# Override model name (default: auto-selected from hardware tier)
LLM_MODEL_NAME=

# ─── Storage Backend ───────────────────────────────────────────────────────────
# Options: local (default), gcs, s3
STORAGE_BACKEND=local

# Local storage — files saved to tts_output Docker volume
# No additional config needed for local

# GCS (if STORAGE_BACKEND=gcs)
# GCS_BUCKET_NAME=your-gcs-bucket
# GCS_AUDIO_PREFIX=audio/articles
# GCS_SERVICE_ACCOUNT_KEY_PATH=   # leave blank to use Application Default Credentials on GCE

# AWS S3 (if STORAGE_BACKEND=s3)
# AWS_ACCESS_KEY_ID=your-access-key-id
# AWS_SECRET_ACCESS_KEY=your-secret-access-key
# AWS_REGION=us-east-1
# S3_BUCKET_NAME=your-s3-bucket
# S3_AUDIO_PREFIX=audio/articles

# ─── Audio Quality Override ─────────────────────────────────────────────────────
# Leave blank to use tier defaults (recommended)
# MP3_BITRATE=192k        # HIGH_VRAM default: 256k
# AUDIO_SAMPLE_RATE=44100 # HIGH_VRAM default: 48000
# TARGET_LUFS=-16.0       # HIGH_VRAM default: -14.0
```

Update existing vLLM section comment:
```env
# ─── vLLM / LLM Configuration ─────────────────────────────────────────────────
# External vLLM endpoint — only needed if overriding the bundled Ollama LLM
# VLLM_BASE_URL=http://host.docker.internal:8001/v1
# VLLM_MODEL_NAME=Qwen/Qwen3-14B-AWQ
```

- [ ] **Step 2: Update `.gitignore`**

Add:
```
# Voice profiles (may contain sensitive voice data)
tts-service/voices/profiles/*.wav
tts-service/voices/default/reference.wav

# Hardware probe output
shared/
```

- [ ] **Step 3: Commit**

```bash
git add .env.example .gitignore
git commit -m "chore(config): update .env.example with all new vars, .gitignore voice files"
```

---

## Task 10: Minor file updates

**Files:**
- Modify: `scripts/init.sh`
- Modify: `scripts/backfill-audio.sh`
- Modify: `scripts/backfill-audio.ps1`
- Modify: `tts-service/run-docker.sh`
- Modify: `tts-service/run-docker.ps1`
- Modify: `CONTRIBUTING.md`
- Modify: `CODE_OF_CONDUCT.md`
- Modify: `SECURITY.md`
- Modify: `CHANGELOG.md`
- Modify: `tts-service/app/__init__.py`
- Modify: `tts-service/app/main.py`

- [ ] **Step 1: `scripts/init.sh` — replace Fish Speech references**

```bash
grep -n "fish\|Fish\|fishspeech\|fish-speech" scripts/init.sh
```
For each match: replace "Fish Speech" → "Qwen3-TTS", remove any fish-speech model download commands, replace with a note that TTS models are loaded by the `tts-service` container via Hugging Face Hub on first run.

- [ ] **Step 2: `scripts/backfill-audio.sh` and `.ps1` — update model references**

```bash
grep -n "fish\|Fish\|vLLM\|vllm\|14B\|14b" scripts/backfill-audio.sh
```
Replace any Fish Speech or vLLM-specific model name references in comments/echo statements. The actual logic (hitting n8n webhook) does not change.

- [ ] **Step 3: `tts-service/run-docker.sh` and `.ps1` — update messages**

Replace "Fish Speech" in echo/print statements with "Qwen3-TTS". Replace any Fish Speech model download steps. The `docker run` command itself stays the same (same image name, same ports).

- [ ] **Step 4: Update repo URLs in community files**

```bash
# CONTRIBUTING.md — replace old repo URL
sed -i 's|workos-mvp/ghost-narrator|getsimpledirect/ghost-narrator|g' CONTRIBUTING.md

# CODE_OF_CONDUCT.md — same
sed -i 's|workos-mvp/ghost-narrator|getsimpledirect/ghost-narrator|g' CODE_OF_CONDUCT.md

# SECURITY.md — same
sed -i 's|workos-mvp/ghost-narrator|getsimpledirect/ghost-narrator|g' SECURITY.md
```

- [ ] **Step 5: Update `CHANGELOG.md`**

Add at the top:
```markdown
## [2.0.0] — 2026-04-02

### Added
- Hardware auto-detection: CPU_ONLY / LOW_VRAM / MID_VRAM / HIGH_VRAM tiers
- Qwen3-TTS engine (replaces Fish Speech v1.5)
- Bundled Ollama LLM service (replaces external vLLM dependency)
- Tiered narration pipeline: ChunkedStrategy + SingleShotStrategy
- NarrationValidator: entity-level information preservation check
- Voice profiles: named profiles, runtime upload, backward-compatible default
- Storage backends: local (default), GCS, AWS S3
- Tiered audio quality: 192kbps/44.1kHz standard, 256kbps/48kHz on HIGH_VRAM
- docker-compose.gpu.yml overlay + start.sh auto GPU detection

### Changed
- Callback payload: `gcs_uri` → `audio_uri` (gcs_uri kept for backward compat)
- `VLLM_BASE_URL` default now points to bundled Ollama at `http://ollama:11434/v1`
- `scripts/setup-gcp.sh` renamed to `scripts/setup-storage.sh`

### Removed
- Fish Speech v1.5 dependency
- External vLLM requirement (now optional override)
```

- [ ] **Step 6: Update `tts-service/app/__init__.py` docstring**

```python
"""
Ghost Narrator TTS Service — Qwen3-TTS voice cloning with hardware-tiered model selection.
"""
```

- [ ] **Step 7: Commit all minor updates**

```bash
git add scripts/init.sh scripts/backfill-audio.sh scripts/backfill-audio.ps1 \
    tts-service/run-docker.sh tts-service/run-docker.ps1 \
    CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md \
    tts-service/app/__init__.py
git commit -m "chore: update repo references, model names, and changelogs"
```

---

## Task 11: README.md + NOTICE

**Files:**
- Create: `README.md`
- Create: `NOTICE`

- [ ] **Step 1: Create `README.md`**

```markdown
# Ghost Narrator

> Automated studio-quality audio narration for Ghost CMS — powered by Qwen3-TTS voice cloning.

Ghost Narrator converts your Ghost articles into podcast-quality MP3 audio automatically when you publish. Drop in a voice reference file and every post gets a narrated audio version — embedded directly in the article.

## Features

- **Zero-config hardware detection** — auto-selects the right Qwen3-TTS model for your machine
- **Voice cloning** — natural voice cloning from a 5-second reference audio sample
- **Information-preserving narration** — LLM rewrites articles to spoken format without losing facts
- **Flexible storage** — local folder, Google Cloud Storage, or AWS S3
- **Ghost CMS integration** — webhook-driven, embeds an HTML5 audio player in published posts
- **Static content support** — narrate books, series pages, or any plain text via API

## Hardware Tiers

| Tier | VRAM | TTS Model | Output Quality |
|---|---|---|---|
| CPU only | None | Qwen3-TTS-0.6B | 192kbps, 44.1kHz |
| Low (4–8 GB) | 4–8 GB | Qwen3-TTS-0.6B | 192kbps, 44.1kHz |
| Mid (10–16 GB) | 10–16 GB | Qwen3-TTS-1.7B | 192kbps, 44.1kHz |
| High (20+ GB) | 20+ GB | Qwen3-TTS-1.7B | 256kbps, 48kHz, −14 LUFS |

## Quick Start

```bash
cp .env.example .env
# Edit .env — set Ghost API keys, storage backend, server IP
# Place voice reference: tts-service/voices/default/reference.wav
./start.sh up -d
```

Open `http://YOUR_IP:5678` and import the three n8n workflows from `n8n/workflows/`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full setup.

## Storage

```env
STORAGE_BACKEND=local   # default — no cloud setup needed
STORAGE_BACKEND=gcs     # Google Cloud Storage
STORAGE_BACKEND=s3      # AWS S3
```

Run `bash scripts/setup-storage.sh gcs` or `bash scripts/setup-storage.sh s3` for guided setup.

## License

Project code: [MIT License](LICENSE)
Qwen3-TTS models: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)
```

- [ ] **Step 2: Create `NOTICE`**

```
Ghost Narrator
Copyright (c) 2026 Ayush Naik

This project uses the following third-party components:

Qwen3-TTS (Qwen/Qwen3-TTS-0.6B, Qwen/Qwen3-TTS-1.7B)
  Copyright (c) Alibaba Cloud
  Licensed under the Apache License, Version 2.0
  https://huggingface.co/Qwen/Qwen3-TTS-1.7B

Qwen3 Language Models (qwen3:1.7b, qwen3:4b, qwen3:8b)
  Copyright (c) Alibaba Cloud
  Licensed under the Apache License, Version 2.0
  https://huggingface.co/Qwen

PyTorch
  Copyright (c) Facebook, Inc.
  BSD 3-Clause License
  https://github.com/pytorch/pytorch

See LICENSE for the full MIT license text for this project's original code.
```

- [ ] **Step 3: Commit**

```bash
git add README.md NOTICE
git commit -m "docs: add root README.md and NOTICE with Apache 2.0 model attribution"
```

---

## Task 12: Rewrite docs/ARCHITECTURE.md + tts-service/README.md

**Files:**
- Rewrite: `docs/ARCHITECTURE.md`
- Rewrite: `tts-service/README.md`
- Modify: `tts-service/QUICKSTART.md`
- Modify: `n8n/SETUP_GUIDE.md`

- [ ] **Step 1: Rewrite `docs/ARCHITECTURE.md`**

Update every Fish Speech reference to Qwen3-TTS. Update every vLLM reference to Ollama. Add new sections:
- Hardware Tier Detection (reference `app/core/hardware.py`, tier matrix)
- Narration Pipeline (ChunkedStrategy vs SingleShotStrategy, NarrationValidator)
- Storage Backends (local/gcs/s3, StorageBackend ABC)
- Voice Profiles (VoiceRegistry, upload API)
- Service Startup Sequence (hardware-probe → ollama → tts-service → n8n)

Update the VRAM Budget section with the new four-tier table.

- [ ] **Step 2: Rewrite `tts-service/README.md`**

Replace "Fish Speech v1.5" throughout. Update:
- Python version: 3.9-3.11 → 3.12
- Build information: model size references (was 4GB Fish Speech → Qwen3-TTS model sizes by tier)
- Runtime resources: update VRAM estimates per tier table
- Quick Start: reference `start.sh` instead of `docker compose up`

- [ ] **Step 3: Update `tts-service/QUICKSTART.md`**

Replace "Step 1: Add Your Voice Sample" path from `voices/reference.wav` → `voices/default/reference.wav` (keep backward compat note). Update start command to `./start.sh up -d`.

- [ ] **Step 4: Update `n8n/SETUP_GUIDE.md`**

Replace "vLLM (Qwen3-14B)" references with "bundled Ollama LLM (auto-selected model)". Add note: "To use an external vLLM, set `LLM_BASE_URL` in `.env`." Update GCS-only storage references to mention all three backends.

- [ ] **Step 5: Commit**

```bash
git add docs/ARCHITECTURE.md tts-service/README.md tts-service/QUICKSTART.md n8n/SETUP_GUIDE.md
git commit -m "docs: rewrite ARCHITECTURE.md and tts-service/README.md for Qwen3-TTS stack"
```

---

## Task 13: Final end-to-end smoke test

- [ ] **Step 1: Build the tts-service image**

```bash
cd tts-service
docker build -t ghost-tts-service:latest .
```
Expected: build completes, no errors

- [ ] **Step 2: Run validate-build.sh**

```bash
cd ..
bash scripts/validate-build.sh ghost-tts-service:latest
```
Expected: `=== All validation checks passed ===`

- [ ] **Step 3: Start full stack with start.sh**

```bash
./start.sh up -d
./start.sh ps
```
Expected: all 5 services running (hardware-probe exits 0, others up)

- [ ] **Step 4: Check Ollama pulled the correct model**

```bash
docker logs ollama 2>&1 | tail -20
# Expected: "Model ready" at the end
docker exec ollama ollama list
# Expected: shows the tier-selected model
```

- [ ] **Step 5: Verify health endpoint includes tier info**

```bash
curl -s http://localhost:8020/health | python -m json.tool | grep -E "hardware_tier|tts_model|llm_model"
```
Expected: all three fields present

- [ ] **Step 6: Final commit**

```bash
git add .
git status  # review — should only be any remaining unstaged changes
git commit -m "chore(plan-c): Plan C complete — full infrastructure, n8n, docs"
```
