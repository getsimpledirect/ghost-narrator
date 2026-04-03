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
Service modules for TTS service.

Contains business logic services for job storage, synthesis,
audio processing, storage, and notifications.
"""

# Re-export everything from domains for backward compatibility

# Narration
from app.domains.narration.base import NarrationStrategy
from app.domains.narration.strategy import ChunkedStrategy, SingleShotStrategy
from app.domains.narration.validator import NarrationValidator
from app.domains.narration.prompt import (
    get_system_prompt,
    get_continuity_instruction,
    get_completeness_check_prompt,
)

# Storage
from app.domains.storage import (
    StorageBackend,
    LocalStorageBackend,
    GCSStorageBackend,
    S3StorageBackend,
    get_storage_backend,
)

# Job
from app.domains.job.runner import run_tts_job
from app.domains.job.state import JobState, JobStatus

# Synthesis
from app.domains.synthesis.base import SynthesisPipeline
from app.domains.synthesis.chunker import chunk_text, TextChunker
from app.domains.synthesis.concatenate import concatenate_audio
from app.domains.synthesis.normalize import normalize_audio
from app.domains.synthesis.mastering import master_audio

# Also re-export existing services (keeping original exports)
from app.services.audio import (
    apply_final_mastering,
    concatenate_wavs,
    concatenate_wavs_auto,
    concatenate_wavs_streaming,
    get_audio_duration,
    get_file_size_mb,
    normalize_chunk_to_target_lufs,
    validate_audio_quality,
)
from app.services.job_store import (
    JobStore,
    get_job_store,
    initialize_job_store,
)
from app.services.notification import (
    close_http_client,
    get_http_client,
    initialize_http_client,
    is_notification_enabled,
    notify_job_completed,
    notify_job_failed,
    notify_n8n,
)
from app.services.storage import (
    get_gcs_client,
    upload_to_gcs,
    is_gcs_enabled,
    build_gcs_path,
    get_public_url,
    initialize_gcs_client,
    cleanup_gcs_client,
)
from app.services.synthesis import (
    cleanup_chunk_files,
    get_executor,
    initialize_executor,
    prepare_text_for_synthesis,
    shutdown_executor,
    synthesize_chunk,
    synthesize_chunks_auto,
    synthesize_chunks_parallel,
    synthesize_chunks_sequential,
)

__all__ = [
    # Narration
    'NarrationStrategy',
    'ChunkedStrategy',
    'SingleShotStrategy',
    'NarrationValidator',
    'get_system_prompt',
    'get_continuity_instruction',
    'get_completeness_check_prompt',
    # Storage (domain)
    'StorageBackend',
    'LocalStorageBackend',
    'GCSStorageBackend',
    'S3StorageBackend',
    'get_storage_backend',
    # Job
    'run_tts_job',
    'JobState',
    'JobStatus',
    # Synthesis (domain)
    'SynthesisPipeline',
    'chunk_text',
    'TextChunker',
    'concatenate_audio',
    'normalize_audio',
    'master_audio',
    # Audio processing
    'apply_final_mastering',
    'concatenate_wavs',
    'concatenate_wavs_auto',
    'concatenate_wavs_streaming',
    'get_audio_duration',
    'get_file_size_mb',
    'normalize_chunk_to_target_lufs',
    'validate_audio_quality',
    # Job store
    'JobStore',
    'get_job_store',
    'initialize_job_store',
    # Notifications
    'close_http_client',
    'get_http_client',
    'initialize_http_client',
    'is_notification_enabled',
    'notify_job_completed',
    'notify_job_failed',
    'notify_n8n',
    # Storage (service)
    'get_gcs_client',
    'upload_to_gcs',
    'is_gcs_enabled',
    'build_gcs_path',
    'get_public_url',
    'initialize_gcs_client',
    'cleanup_gcs_client',
    # Synthesis (service)
    'cleanup_chunk_files',
    'get_executor',
    'initialize_executor',
    'prepare_text_for_synthesis',
    'shutdown_executor',
    'synthesize_chunk',
    'synthesize_chunks_auto',
    'synthesize_chunks_parallel',
    'synthesize_chunks_sequential',
]
