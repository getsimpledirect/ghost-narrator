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
Pydantic schema models for API requests and responses.

Defines all data transfer objects (DTOs) for the TTS service API.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GenerateRequest(BaseModel):
    """Request payload for TTS synthesis."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description='Text to synthesize. Must be 1-100,000 characters and not whitespace-only.',
    )
    job_id: Optional[str] = Field(
        default=None,
        max_length=200,
        pattern=r'^[a-zA-Z0-9_-]+$',
        description='Custom job ID. Must be alphanumeric with hyphens/underscores, max 200 chars. Auto-generated if omitted.',
    )
    storage_path: Optional[str] = Field(
        default=None,
        description="Custom storage output path. Must not contain '..' or start with '/'. Auto-generated if omitted.",
    )
    site_slug: Optional[str] = Field(
        default='site',
        max_length=100,
        pattern=r'^[a-zA-Z0-9_-]+$',
        description="Site identifier for GCS path generation. Alphanumeric, hyphens, underscores only. Defaults to 'site'.",
    )
    voice_profile: str = Field(
        default='default',
        max_length=100,
        description="Name of voice profile to use for cloning. Defaults to 'default'.",
    )

    @field_validator('text')
    @classmethod
    def validate_text_not_empty(cls, value: str) -> str:
        """Validate text is not whitespace-only."""
        if not value.strip():
            raise ValueError('Text must not be empty or whitespace-only')
        return value

    @field_validator('storage_path')
    @classmethod
    def validate_storage_path(cls, value: Optional[str]) -> Optional[str]:
        """Validate GCS path has no path traversal. Empty string treated as None."""
        if value is not None:
            if not value.strip():
                return None
            if '..' in value or value.startswith('/'):
                raise ValueError("storage_path must not contain '..' or start with '/'")
        return value


class GenerateResponse(BaseModel):
    """Response after submitting a TTS job."""

    job_id: str = Field(..., description='Unique job identifier.')
    status: str = Field(..., description="Initial job status. Always 'queued' for new jobs.")


class StatusResponse(BaseModel):
    """Job status response."""

    model_config = ConfigDict(extra='ignore')

    job_id: str = Field(..., description='Unique job identifier.')
    status: str = Field(
        ...,
        description='Current status: queued, processing, paused, completed, or failed.',
    )
    gcs_uri: Optional[str] = Field(
        default=None,
        description=(
            'Public URL or storage URI of the generated audio file. '
            'Populated when the job completes. Format depends on storage backend: '
            'a `gs://` URI for GCS, an `https://` URL for S3, or a local file path.'
        ),
    )
    error: Optional[str] = Field(default=None, description="Error message when status is 'failed'.")
    created_at: Optional[float] = Field(default=None, description='Unix timestamp of job creation.')
    started_at: Optional[float] = Field(
        default=None, description='Unix timestamp when processing began.'
    )
    completed_at: Optional[float] = Field(default=None, description='Unix timestamp of completion.')
    duration_seconds: Optional[float] = Field(
        default=None, description='Processing duration in seconds.'
    )


class JobListResponse(BaseModel):
    """List of all jobs."""

    total: int = Field(..., ge=0, description='Total job count.')
    jobs: dict[str, dict[str, Any]] = Field(..., description='Map of job_id to job data.')


class HealthResponse(BaseModel):
    """Service health status."""

    model_config = ConfigDict(protected_namespaces=())

    status: str = Field(..., description='Overall status: healthy or degraded.')
    device: str = Field(..., description='Compute device: cpu or cuda.')
    model: str = Field(..., description='TTS model name.')
    voice_sample: bool = Field(..., description='True if voice sample file exists.')
    model_loaded: bool = Field(..., description='True if TTS model is loaded.')
    job_store: str = Field(..., description='Storage backend: redis or memory.')
    jobs_count: int = Field(..., description='Job count, or -1 on error.')
    max_workers: int = Field(..., description='Max concurrent workers.')
    executor_active: bool = Field(..., description='True if executor is running.')
    gcs_client_active: bool = Field(..., description='True if GCS client is connected.')
    reference_audio_present: bool = Field(
        False, description='Voice reference audio exists in voices directory.'
    )
    reference_text_present: bool = Field(
        False, description='Reference text file (reference.txt) exists after voice calibration.'
    )
    tts_engine_ready: bool = Field(False, description='TTSEngine reported ready.')
    hardware_tier: Optional[str] = Field(default=None, description='Detected hardware tier.')
    tts_model: Optional[str] = Field(default=None, description='Selected TTS model name.')
    llm_model: Optional[str] = Field(default=None, description='Selected LLM model name.')


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str = Field(..., description='Error message.')
    error_code: Optional[str] = Field(default=None, description='Machine-readable error code.')


class TTSGenerationConfigUpdate(BaseModel):
    """Partial update for TTS generation parameters. Omitted fields are unchanged."""

    temperature: Optional[float] = Field(
        default=None,
        ge=0.1,
        le=2.0,
        description=(
            'Controls expressiveness and variability of the generated speech (0.1–2.0). '
            'Lower values produce more consistent, neutral delivery. '
            'Higher values add more variation and emotion but may reduce stability.'
        ),
    )
    repetition_penalty: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=1.5,
        description=(
            'Penalises the model for repeating the same sounds or patterns (1.0–1.5). '
            '1.0 means no penalty. Increase slightly if you hear audio artefacts or stuttering.'
        ),
    )
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=200,
        description=(
            'Limits token selection to the top-k most likely candidates at each step (1–200). '
            'Lower values make speech more predictable; higher values allow more variety.'
        ),
    )
    top_p: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            'Nucleus sampling threshold (0.0–1.0). The model samples from the smallest set '
            'of tokens whose cumulative probability exceeds this value. '
            '0.9 is a safe default; lower values tighten the distribution.'
        ),
    )
    temperature_sub_talker: Optional[float] = Field(
        default=None,
        ge=0.1,
        le=2.0,
        description=(
            'Temperature for the acoustic decoder (0.1–2.0). '
            'Controls prosody fine-detail: pitch micro-variation, breath placement, and rhythm. '
            'Analogous to `temperature` but applied at the waveform generation stage.'
        ),
    )
    top_k_sub_talker: Optional[int] = Field(
        default=None,
        ge=1,
        le=200,
        description='Top-k for the acoustic decoder (1–200). See `top_k` for interpretation.',
    )
    do_sample_sub_talker: Optional[bool] = Field(
        default=None,
        description=(
            'Whether the acoustic decoder uses sampling (`true`) or greedy decoding (`false`). '
            'Sampling produces more natural, varied prosody. '
            'Greedy decoding is more deterministic but can sound flat.'
        ),
    )
    max_new_tokens: Optional[int] = Field(
        default=None,
        ge=500,
        le=16000,
        description=(
            'Maximum tokens the model may generate per text chunk (500–16000). '
            'Increase if long sentences are being cut off mid-word. '
            'Decrease to limit memory use on low-VRAM hardware.'
        ),
    )


class TTSGenerationConfigResponse(BaseModel):
    """Current TTS generation config: tier defaults merged with user overrides."""

    tier: str = Field(..., description='Active hardware tier.')
    effective: dict[str, Any] = Field(
        ..., description='Effective values used for synthesis (defaults + overrides).'
    )
    overrides: dict[str, Any] = Field(..., description='User-saved overrides stored in Redis.')
    defaults: dict[str, Any] = Field(..., description='Hardware-tier default values.')
