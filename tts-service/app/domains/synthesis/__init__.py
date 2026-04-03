"""Synthesis domain module — re-exports for convenience."""

from app.domains.synthesis.chunker import (
    TextChunker as TextChunker,
    chunk_text as chunk_text,
    get_pause_ms_after_chunk as get_pause_ms_after_chunk,
)
from app.domains.synthesis.concatenate import (
    concatenate_audio as concatenate_audio,
    concatenate_audio_auto as concatenate_audio_auto,
    concatenate_audio_streaming as concatenate_audio_streaming,
)
from app.domains.synthesis.normalize import (
    normalize_audio as normalize_audio,
    normalize_audio_if_long_enough as normalize_audio_if_long_enough,
)
from app.domains.synthesis.mastering import (
    master_audio as master_audio,
    master_audio_with_fallback as master_audio_with_fallback,
)
from app.domains.synthesis.quality import (
    apply_final_mastering as apply_final_mastering,
    validate_audio_quality as validate_audio_quality,
)

__all__ = [
    'TextChunker',
    'chunk_text',
    'get_pause_ms_after_chunk',
    'concatenate_audio',
    'concatenate_audio_auto',
    'concatenate_audio_streaming',
    'normalize_audio',
    'normalize_audio_if_long_enough',
    'master_audio',
    'master_audio_with_fallback',
    'apply_final_mastering',
    'validate_audio_quality',
]
