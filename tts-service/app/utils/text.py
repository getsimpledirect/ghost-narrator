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
Text processing utilities for TTS service.

Provides functions for cleaning and segmenting text for TTS synthesis,
and for determining context-aware pause durations between audio segments.
"""

from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

# Pause durations injected by LLM markers during narration
PAUSE_MS: Final[int] = (
    500  # [PAUSE] — sentence/minor topic boundary (slightly longer for natural speech)
)
LONG_PAUSE_MS: Final[int] = 1000  # [LONG_PAUSE] — paragraph/major topic boundary (more pronounced)

_PAUSE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r'\[(LONG_PAUSE|PAUSE)\]', re.IGNORECASE)

# ─── TTS Text Preprocessing ───────────────────────────────────────────────────

# Common abbreviations that trip up TTS models when not expanded
_ABBREVIATIONS: Final[dict[str, str]] = {
    'Dr.': 'Doctor',
    'Mr.': 'Mister',
    'Mrs.': 'Missus',
    'Ms.': 'Miss',
    'Prof.': 'Professor',
    'Sr.': 'Senior',
    'Jr.': 'Junior',
    'St.': 'Saint',
    'vs.': 'versus',
    'etc.': 'et cetera',
    'e.g.': 'for example',
    'i.e.': 'that is',
    'approx.': 'approximately',
    'dept.': 'department',
    'govt.': 'government',
    'Inc.': 'Incorporated',
    'Corp.': 'Corporation',
    'Ltd.': 'Limited',
    'Co.': 'Company',
}

# Safety-net: strip any <think>...</think> blocks that survived the narration layer.
# Primary stripping happens in strategy._strip_llm_artifacts; this catches any
# path that bypasses narration (raw-text fallback) or future model changes.
_THINK_RE: Final[re.Pattern[str]] = re.compile(
    r'<think(?:ing)?>.*?</think(?:ing)?>',
    re.DOTALL | re.IGNORECASE,
)
# Regex for remaining markdown artifacts
_MARKDOWN_RE: Final[re.Pattern[str]] = re.compile(r'[#*_~>`]+')
# Multiple consecutive punctuation (e.g., "...", "!!", "??")
_MULTI_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r'([.!?]){3,}')
# Stray brackets or parentheses with empty content
_EMPTY_BRACKETS_RE: Final[re.Pattern[str]] = re.compile(r'\(\s*\)|\[\s*\]|\{\s*\}')
# URLs that the LLM didn't fully remove
_URL_RE: Final[re.Pattern[str]] = re.compile(r'https?://\S+')
# Smart quotes and special characters
_SPECIAL_CHARS: Final[dict[str, str]] = {
    '\u2018': "'",  # left single quote
    '\u2019': "'",  # right single quote
    '\u201c': '"',  # left double quote
    '\u201d': '"',  # right double quote
    '\u2014': ', ',  # em dash → comma pause (space prevents run-on after replacement)
    '\u2013': ', ',  # en dash → comma pause
    '\u2026': '.',  # ellipsis
    '\u00a0': ' ',  # non-breaking space
    '\u200b': '',  # zero-width space
    '\u2060': '',  # word joiner
    # Arrows — common in blog posts for "X → Y" transitions
    '\u2192': ' to ',  # →
    '\u2190': ' from ',  # ←
    '\u2194': ' to and from ',  # ↔
    '\u21d2': ' leads to ',  # ⇒
    # Bullet symbols that survive normalize_for_narration
    '\u2022': '',  # •
    '\u25e6': '',  # ◦
    '\u2023': '',  # ‣
    '\u25b8': '',  # ▸
    # Math / comparison
    '\u00b1': ' plus or minus ',  # ±
    '\u00d7': ' times ',  # ×
    '\u00f7': ' divided by ',  # ÷
    '\u2248': ' approximately ',  # ≈
    '\u2264': ' less than or equal to ',  # ≤
    '\u2265': ' greater than or equal to ',  # ≥
    '\u2260': ' not equal to ',  # ≠
    # Degree symbol — temperature and angles
    '\u00b0': ' degrees ',  # °
    # Currency symbols beyond $
    '\u20ac': ' euros ',  # €
    '\u00a3': ' pounds ',  # £
    '\u00a5': ' yen ',  # ¥
    '\u20b9': ' rupees ',  # ₹
    # Trademark / legal — strip silently
    '\u2122': '',  # ™
    '\u00ae': '',  # ®
    '\u00a9': '',  # ©
    # Fractions
    '\u00bd': ' one half ',  # ½
    '\u00bc': ' one quarter ',  # ¼
    '\u00be': ' three quarters ',  # ¾
    # Superscripts — common in metrics (m², CO₂)
    '\u00b2': ' squared ',  # ²
    '\u00b3': ' cubed ',  # ³
    # Section / paragraph marks
    '\u00a7': ' section ',  # §
    '\u00b6': '',  # ¶
}


def clean_text_for_tts(text: str) -> str:
    """Clean narration text for optimal TTS synthesis.

    Catches artifacts the LLM narration may have missed:
    - Stray markdown characters
    - Smart quotes and special Unicode
    - Unexpanded abbreviations
    - Remaining URLs
    - Multiple consecutive punctuation
    - Empty brackets
    - Excessive whitespace

    Args:
        text: Narration text from LLM.

    Returns:
        Cleaned text ready for TTS chunking.
    """
    # Strip thinking tokens before any other processing — otherwise tag fragments
    # survive the markdown pass and get synthesized as garbled speech
    text = _THINK_RE.sub('', text)

    # Convert pause markers to punctuation the TTS model naturally pauses on.
    # [LONG_PAUSE] → paragraph break (longest natural pause in spoken delivery).
    # [PAUSE]      → comma (reliable short-beat cue; '...' would be collapsed to '.'
    #                by the _MULTI_PUNCT_RE normalizer that runs below).
    # LONG_PAUSE first so its pattern isn't consumed by the PAUSE replacement.
    text = re.sub(r'\s*\[LONG_PAUSE\]\s*', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\[PAUSE\]\s*', ', ', text, flags=re.IGNORECASE)

    # Replace smart quotes and special characters
    for char, replacement in _SPECIAL_CHARS.items():
        text = text.replace(char, replacement)

    # Strip remaining markdown artifacts
    text = _MARKDOWN_RE.sub('', text)

    # Remove URLs (LLM should have converted to spoken form)
    text = _URL_RE.sub('', text)

    # Expand abbreviations (word-boundary safe)
    for abbr, expansion in _ABBREVIATIONS.items():
        text = re.sub(re.escape(abbr) + r'\b', expansion, text)

    # Normalize ellipsis and repeated punctuation
    text = _MULTI_PUNCT_RE.sub(r'\1', text)

    # Remove empty brackets
    text = _EMPTY_BRACKETS_RE.sub('', text)

    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def parse_pause_markers(text: str) -> list[tuple[str, int]]:
    """Split text at [PAUSE]/[LONG_PAUSE] markers into (segment, pause_after_ms) pairs.

    Each tuple is (text_to_synthesize, ms_of_silence_to_insert_after).
    The last segment always has pause_after_ms=0 (no trailing silence).

    Example:
        'Hello. [PAUSE] World. [LONG_PAUSE] Goodbye.'
        → [('Hello.', 450), ('World.', 750), ('Goodbye.', 0)]

    Args:
        text: Narration text that may contain [PAUSE] or [LONG_PAUSE] markers.

    Returns:
        List of (text_segment, pause_ms) pairs. At least one element.
    """
    parts = _PAUSE_MARKER_RE.split(text)
    # split returns: [text, marker_name, text, marker_name, text, ...]
    # e.g. 'A [PAUSE] B [LONG_PAUSE] C' → ['A ', 'PAUSE', ' B ', 'LONG_PAUSE', ' C']
    segments: list[tuple[str, int]] = []
    i = 0
    while i < len(parts):
        segment_text = parts[i].strip()
        # Next element (if exists) is the captured group — the marker name
        if i + 1 < len(parts):
            marker_name = parts[i + 1].upper()
            pause_ms = LONG_PAUSE_MS if marker_name == 'LONG_PAUSE' else PAUSE_MS
            if segment_text:
                segments.append((segment_text, pause_ms))
            i += 2
        else:
            if segment_text:
                segments.append((segment_text, 0))
            i += 1

    return segments if segments else [(text.strip() or text, 0)]


# Transition words that suggest a new topic/paragraph boundary.
# Only genuine topic-transition openers — not common sentence starters like
# "the", "for", "so", "if", "this" which match nearly every sentence.
_TRANSITION_STARTERS: Final[tuple[str, ...]] = (
    'now,',
    'however',
    'meanwhile',
    'turning to',
    'on the other hand',
    'in other news',
    'speaking of',
    'that said',
    'moving on',
    'in contrast',
    'furthermore',
    'moreover',
    'additionally',
    'but despite',
    'yet despite',
    'looking ahead',
    'in summary',
    'to summarize',
    'finally,',
    'lastly,',
    'in other words',
    'put another way',
)


def split_into_large_segments(text: str, target_words: int) -> list[str]:
    """Group paragraphs into large segments of ~target_words for segment synthesis.

    Accumulates paragraphs until the target word count is reached. A paragraph
    boundary is only used as a split point when the accumulated words would exceed
    target_words — preserving long-range prosody within each synthesized segment.

    Args:
        text: Full narration text.
        target_words: Desired words per segment (e.g. SINGLE_SHOT_SEGMENT_WORDS=3000).

    Returns:
        List of large text segments, each close to target_words in length.
    """
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
    segments: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > target_words and current:
            segments.append('\n\n'.join(current))
            current = [para]
            current_words = para_words
        else:
            current.append(para)
            current_words += para_words

    if current:
        segments.append('\n\n'.join(current))

    # Merge trailing segments shorter than 40 words into the preceding segment.
    # Qwen3-TTS produces codec artifacts (clicks, truncated phonemes) on very
    # short inputs — a single paragraph at the end becomes a standalone synthesis
    # call that clips mid-decode because there are too few tokens to close cleanly.
    _MIN_SEGMENT_WORDS = 40
    if len(segments) >= 2 and len(segments[-1].split()) < _MIN_SEGMENT_WORDS:
        segments[-2] = segments[-2] + '\n\n' + segments[-1]
        segments.pop()

    return segments if segments else [text]


def get_pause_ms_after_chunk(chunk: str, next_chunk: str | None) -> int:
    """
    Determine appropriate silence gap after this chunk.

    Returns milliseconds of silence to insert between audio chunks.
    - After a sentence ending a paragraph (next chunk starts a new topic): 700ms
    - After a sentence-ending chunk: 450ms
    - After a mid-sentence break: 250ms

    Args:
        chunk: The current chunk text.
        next_chunk: The next chunk text, or None if this is the last chunk.

    Returns:
        Silence duration in milliseconds.
    """
    if not next_chunk:
        return 0  # No trailing silence at end

    chunk_stripped = chunk.strip()

    # Paragraph-level break: current ends with sentence-final punctuation
    if chunk_stripped.endswith('.') or chunk_stripped.endswith('!') or chunk_stripped.endswith('?'):
        # Check if next chunk seems to be a new thought (starts with transition words)
        next_lower = next_chunk.lower().strip()
        if any(next_lower.startswith(t) for t in _TRANSITION_STARTERS):
            return 700  # Paragraph/topic boundary
        return 450  # Normal sentence boundary

    return 250  # Mid-thought break


# ─── Quote Detection for Multi-Voice ──────────────────────────────────────────

# Regex to detect quoted speech (double quotes, single quotes, or backticks)
_QUOTE_RE: Final[re.Pattern[str]] = re.compile(r'["\u201c\u201d](.+?)["\u201d]')


def has_quoted_speech(text: str) -> bool:
    """Check if text contains quoted speech for multi-voice synthesis."""
    return bool(_QUOTE_RE.search(text))


def split_at_quotes(text: str) -> list[tuple[str, bool]]:
    """Split text into segments, marking which are quoted speech.

    Returns:
        List of (text_segment, is_quote) tuples.
        is_quote=True means this segment should use a shifted voice.
    """
    segments: list[tuple[str, bool]] = []
    last_end = 0

    for match in _QUOTE_RE.finditer(text):
        # Add non-quoted text before this match
        before = text[last_end : match.start()].strip()
        if before:
            segments.append((before, False))
        # Add the quoted text (without the quote marks)
        quoted = match.group(1).strip()
        if quoted:
            segments.append((quoted, True))
        last_end = match.end()

    # Add remaining non-quoted text
    remaining = text[last_end:].strip()
    if remaining:
        segments.append((remaining, False))

    return segments if segments else [(text, False)]
