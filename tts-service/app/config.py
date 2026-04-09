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

"""
Application configuration module.

Centralizes all environment variables and application settings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final


def _get_engine_config():
    """Lazy accessor for ENGINE_CONFIG to avoid import-time hardware probing."""
    from app.core.hardware import ENGINE_CONFIG

    return ENGINE_CONFIG


# Voice and TTS settings
VOICE_SAMPLE_PATH: Final[str] = os.environ.get(
    'VOICE_SAMPLE_PATH', '/app/voices/default/reference.wav'
)
# Optional transcription of the reference audio.
# When set, Qwen3-TTS uses ICL mode (reference audio + text) for higher-fidelity cloning.
# When empty (default), x-vector-only mode is used — no transcription required.
VOICE_SAMPLE_REF_TEXT: Final[str] = os.environ.get('VOICE_SAMPLE_REF_TEXT', '')
TTS_LANGUAGE: Final[str] = os.environ.get('TTS_LANGUAGE', '').strip() or 'auto'

# Hardware tier (read from ENGINE_CONFIG — set at startup)
HARDWARE_TIER: Final[str] = _get_engine_config().tier.value
SELECTED_TTS_MODEL: Final[str] = _get_engine_config().tts_model
SELECTED_LLM_MODEL: Final[str] = _get_engine_config().llm_model

# Override DEVICE from engine config (replaces static env var)
DEVICE: Final[str] = _get_engine_config().tts_device

# Narration LLM endpoint (bundled Ollama default; override for any OpenAI-compatible API)
LLM_BASE_URL: Final[str] = os.environ.get('LLM_BASE_URL', 'http://ollama:11434/v1')
LLM_MODEL_NAME: Final[str] = (
    os.environ.get('LLM_MODEL_NAME', '').strip() or _get_engine_config().llm_model
)

# Storage backend
STORAGE_BACKEND: Final[str] = os.environ.get('STORAGE_BACKEND', 'local').lower()

# S3 settings (used when STORAGE_BACKEND=s3)
AWS_ACCESS_KEY_ID: Final[str] = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY: Final[str] = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_REGION: Final[str] = os.environ.get('AWS_REGION', 'us-east-1')
S3_BUCKET_NAME: Final[str] = os.environ.get('S3_BUCKET_NAME', '')
S3_AUDIO_PREFIX: Final[str] = os.environ.get('S3_AUDIO_PREFIX', 'audio/articles')

# GCS service account key (optional — leave blank for ADC)
GCS_SERVICE_ACCOUNT_KEY_PATH: Final[str] = os.environ.get('GCS_SERVICE_ACCOUNT_KEY_PATH', '')

# GCS bucket settings (used when STORAGE_BACKEND=gcs)
GCS_BUCKET_NAME: Final[str] = os.environ.get('GCS_BUCKET_NAME', '')
GCS_AUDIO_PREFIX: Final[str] = os.environ.get('GCS_AUDIO_PREFIX', 'audio/articles')

_ec = _get_engine_config()

# Audio quality (from ENGINE_CONFIG — overridable via env)
MP3_BITRATE: Final[str] = os.environ.get('MP3_BITRATE', _ec.mp3_bitrate)
AUDIO_SAMPLE_RATE: Final[int] = int(os.environ.get('AUDIO_SAMPLE_RATE', str(_ec.sample_rate)))
TARGET_LUFS: Final[float] = float(os.environ.get('TARGET_LUFS', str(_ec.target_lufs)))

# TTS chunk words (from ENGINE_CONFIG)
try:
    MAX_CHUNK_WORDS: Final[int] = max(
        10,
        min(
            int(os.environ.get('MAX_CHUNK_WORDS', str(_ec.tts_chunk_words))),
            1000,
        ),
    )
except ValueError:
    MAX_CHUNK_WORDS: Final[int] = _ec.tts_chunk_words

# Webhook settings
N8N_CALLBACK_URL: Final[str] = os.environ.get('N8N_CALLBACK_URL', '')

# Worker and concurrency settings
try:
    MAX_WORKERS: Final[int] = max(1, min(int(os.environ.get('MAX_WORKERS', '4')), 32))
except ValueError:
    MAX_WORKERS: Final[int] = 4

# Redis settings
REDIS_URL: Final[str] = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
try:
    REDIS_JOB_TTL: Final[int] = max(60, min(int(os.environ.get('REDIS_JOB_TTL', '86400')), 604800))
except ValueError:
    REDIS_JOB_TTL: Final[int] = 86400

# Output directory
OUTPUT_DIR: Final[Path] = Path(os.environ.get('OUTPUT_DIR', '/app/output'))
try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError) as exc:
    import logging

    logging.getLogger(__name__).warning(
        'Could not create OUTPUT_DIR %s: %s. Will attempt at runtime.', OUTPUT_DIR, exc
    )

# Validation constants
MAX_TEXT_LENGTH: Final[int] = 100_000
VALID_JOB_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r'^[a-zA-Z0-9_-]{1,200}$')
MAX_JOB_ID_LENGTH: Final[int] = 200

# TTS timeout settings
try:
    SEMANTIC_TOKEN_TIMEOUT: Final[int] = max(
        60, int(os.environ.get('SEMANTIC_TOKEN_TIMEOUT', '360'))
    )
except ValueError:
    SEMANTIC_TOKEN_TIMEOUT: Final[int] = 360
try:
    AUDIO_DECODE_TIMEOUT: Final[int] = max(30, int(os.environ.get('AUDIO_DECODE_TIMEOUT', '180')))
except ValueError:
    AUDIO_DECODE_TIMEOUT: Final[int] = 180

# Audio settings (MP3_BITRATE already set from ENGINE_CONFIG above)
STREAMING_THRESHOLD_MS: Final[int] = 600_000

# HTTP client settings
HTTP_TIMEOUT: Final[float] = 10.0
HTTP_CONNECT_TIMEOUT: Final[float] = 5.0
MAX_KEEPALIVE_CONNECTIONS: Final[int] = 5
MAX_CONNECTIONS: Final[int] = 10

# Retry settings
MAX_RETRIES: Final[int] = 3

# API authentication
TTS_API_KEY: Final[str] = os.environ.get('TTS_API_KEY', '')
LLM_API_KEY: Final[str] = os.environ.get('LLM_API_KEY', 'ollama')
try:
    TRUSTED_PROXY_COUNT: Final[int] = max(0, int(os.environ.get('TRUSTED_PROXY_COUNT', '0')))
except ValueError:
    TRUSTED_PROXY_COUNT: Final[int] = 0

# LLM timeouts (seconds) - configurable for different model performance
try:
    LLM_TIMEOUT: Final[float] = max(30, float(os.environ.get('LLM_TIMEOUT', '120')))
except ValueError:
    LLM_TIMEOUT: Final[float] = 120.0

try:
    LLM_COMPLETENESS_TIMEOUT: Final[float] = max(
        30, float(os.environ.get('LLM_COMPLETENESS_TIMEOUT', '180'))
    )
except ValueError:
    LLM_COMPLETENESS_TIMEOUT: Final[float] = 180.0

# GCS upload settings
GCS_UPLOAD_TIMEOUT: Final[int] = 300

# Logging configuration
LOG_FORMAT: Final[str] = os.environ.get('LOG_FORMAT', '').lower()  # '', 'json', or 'console'
LOG_LEVEL: Final[str] = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Server external IP (for local storage URLs)
SERVER_EXTERNAL_IP: Final[str] = os.environ.get('SERVER_EXTERNAL_IP', 'localhost')


def get_llm_client():
    """Return async OpenAI-compatible client pointed at Ollama (or override URL)."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def validate_config() -> None:
    """Validate required configuration at startup. Raises RuntimeError on any failure.

    Call this from the lifespan before model loading — fail fast rather than
    discovering misconfiguration when a code path is first exercised.
    """
    import logging

    logger = logging.getLogger(__name__)
    errors: list[str] = []

    valid_backends = {'local', 'gcs', 's3'}
    if STORAGE_BACKEND not in valid_backends:
        errors.append(
            f"STORAGE_BACKEND='{STORAGE_BACKEND}' is not valid. Must be one of: {valid_backends}"
        )

    if STORAGE_BACKEND == 'gcs' and not GCS_BUCKET_NAME:
        errors.append('GCS_BUCKET_NAME must be set when STORAGE_BACKEND=gcs')

    if STORAGE_BACKEND == 's3' and not S3_BUCKET_NAME:
        errors.append('S3_BUCKET_NAME must be set when STORAGE_BACKEND=s3')

    if N8N_CALLBACK_URL and not N8N_CALLBACK_URL.startswith(('http://', 'https://')):
        errors.append(f"N8N_CALLBACK_URL='{N8N_CALLBACK_URL}' must start with http:// or https://")

    # TTS_API_KEY is required - service should not start without it
    if not TTS_API_KEY:
        errors.append('TTS_API_KEY must be set. Generate one with: openssl rand -hex 32')

    if errors:
        raise RuntimeError(
            'Configuration errors — fix these before starting the service:\n'
            + '\n'.join(f'  - {e}' for e in errors)
        )

    # Create OUTPUT_DIR now that config is validated
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as exc:
        logger.warning(
            'Could not create OUTPUT_DIR %s: %s. Will attempt at runtime.', OUTPUT_DIR, exc
        )
