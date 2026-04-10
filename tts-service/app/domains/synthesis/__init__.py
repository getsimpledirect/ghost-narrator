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

"""Synthesis domain module — re-exports for convenience."""

from app.utils.text import (
    split_into_chunks as chunk_text,
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
