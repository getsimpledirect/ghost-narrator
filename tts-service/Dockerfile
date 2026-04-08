# ─── Stage 1: Compile flash-attn wheel ───────────────────────────────────────
# flash-attn requires nvcc (CUDA compiler) to build from source. The runtime
# image below does not ship nvcc, so we compile the wheel here in the devel
# image and copy only the resulting .whl into the final stage.
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-devel AS flash-builder

# Install the same torch version used at runtime so the wheel is ABI-compatible.
# --no-build-isolation tells the compiler to use the installed torch headers
# rather than fetching a fresh copy in an isolated build env.
RUN pip install --quiet --upgrade pip && \
    pip wheel flash-attn --no-build-isolation --no-deps -w /flash-wheels

# ─── Stage 2: Runtime image ───────────────────────────────────────────────────
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies and curl for uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    sox \
    espeak-ng \
    libsndfile1 \
    git \
    build-essential \
    python3-dev \
    portaudio19-dev \
    libportaudio2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv globally for blazingly fast dependency resolution and installation
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    cp /root/.local/bin/uvx /usr/local/bin/uvx
ENV PATH="/usr/local/bin:$PATH"

WORKDIR /app

# Copy dependency files (both pyproject.toml and requirements.txt for compatibility)
COPY pyproject.toml requirements.txt ./

# Install dependencies using uv (faster than pip)
RUN uv pip install --system --no-cache -r requirements.txt

# Install the flash-attn wheel compiled in the builder stage.
# Installed after the main requirements so uv doesn't try to resolve it from
# PyPI (where it would fail without nvcc).
COPY --from=flash-builder /flash-wheels/flash_attn*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/flash_attn*.whl && \
    rm -f /tmp/flash_attn*.whl

# Verify critical imports work
RUN python -c "import torch, transformers, fastapi, google.cloud.storage, redis, librosa; from qwen_tts import Qwen3TTSModel; import flash_attn" && \
    echo "✓ All critical packages validated"

# Copy application code
COPY app/ ./app/

# Create necessary directories
RUN mkdir -p /app/voices /app/output

# Create non-root user and set ownership
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose the service port
EXPOSE 8020

# Health check with improved error handling
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=5 \
    CMD python -c "\
import urllib.request; \
import urllib.error; \
try: \
    response = urllib.request.urlopen('http://localhost:8020/health', timeout=5); \
    if response.status == 200: \
        exit(0); \
    else: \
        print(f'Health check failed: status {response.status}'); \
        exit(1); \
except urllib.error.URLError as e: \
    print(f'Health check error: {e}'); \
    exit(1); \
except Exception as e: \
    print(f'Health check exception: {e}'); \
    exit(1);" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8020", \
     "--workers", "1", \
     "--timeout-keep-alive", "600", \
     "--log-level", "info"]
