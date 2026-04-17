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

Provides functions for splitting text into optimal chunks for
TTS synthesis while maintaining sentence boundaries, and for
determining context-aware pause durations between chunks.
"""

from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

# Default maximum words per chunk (larger chunks for single-shot fallback)
DEFAULT_MAX_CHUNK_WORDS: Final[int] = 400  # Was 200 - aligned with SINGLE_SHOT_MAX_WORDS

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

    # Strip [PAUSE]/[LONG_PAUSE] markers — these are assembly directives extracted
    # by parse_pause_markers(); TTS must never receive them as text to speak.
    text = _PAUSE_MARKER_RE.sub('', text)

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


def split_into_chunks(text: str, max_words: int = DEFAULT_MAX_CHUNK_WORDS) -> list[str]:
    """
    Split narration text into TTS-optimal chunks.

    Strategy:
    - Split on paragraph boundaries first (double newline or sentence groups)
    - Within paragraphs, group sentences into chunks of ~40-60 words
    - Never split mid-sentence
    - For long sentences, prefer splitting at clause boundaries (commas,
      semicolons, em dashes) rather than arbitrary word positions
    - Keep sentence-ending punctuation with its sentence (not the next chunk)
    - Chunks of 40-60 words produce 8-12 second audio segments — optimal for
      Qwen3-TTS voice consistency and natural prosody

    Args:
        text: The input text to split into chunks.
        max_words: Maximum number of words per chunk (default: 200).

    Returns:
        A list of text chunks, each suitable for TTS synthesis.
        Returns an empty list if input is empty/whitespace.
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    # Split into paragraphs
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]

    chunks: list[str] = []

    for para in paragraphs:
        # Split paragraph into sentences using common sentence endings
        # Keep the punctuation with the sentence
        sentences = re.split(r'(?<=[.!?])\s+', para.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk_words: list[str] = []
        current_word_count: int = 0

        for sentence in sentences:
            sentence_words = sentence.split()
            sentence_word_count = len(sentence_words)

            # Skip empty sentences
            if sentence_word_count == 0:
                continue

            # If adding this sentence exceeds max_words and we already have content,
            # flush current chunk and start a new one
            if current_word_count + sentence_word_count > max_words and current_chunk_words:
                chunks.append(' '.join(current_chunk_words))
                current_chunk_words = []
                current_word_count = 0

            # For very long sentences that exceed max_words alone,
            # split at clause boundaries (commas, semicolons) for natural prosody
            if sentence_word_count > max_words:
                # Flush any accumulated chunk first
                if current_chunk_words:
                    chunks.append(' '.join(current_chunk_words))
                    current_chunk_words = []
                    current_word_count = 0

                # Split long sentence at clause boundaries
                clause_chunks = _split_sentence_at_clauses(sentence, max_words)
                for clause in clause_chunks[:-1]:
                    chunks.append(clause)
                # Last clause becomes the start of the next chunk
                last_clause = clause_chunks[-1]
                current_chunk_words = last_clause.split()
                current_word_count = len(current_chunk_words)
                continue

            current_chunk_words.extend(sentence_words)
            current_word_count += sentence_word_count

            # If this single sentence is already at/over the limit, flush immediately
            if current_word_count >= max_words:
                chunks.append(' '.join(current_chunk_words))
                current_chunk_words = []
                current_word_count = 0

        # Flush remaining words at paragraph boundary only if we have enough
        # content to justify a synthesis call. Short paragraphs (section headings,
        # single-word labels) carry over into the next paragraph instead of becoming
        # their own chunk — a 2-word chunk takes nearly as long to synthesize as a
        # 300-word chunk due to model initialization overhead.
        if current_chunk_words and current_word_count >= 15:
            chunks.append(' '.join(current_chunk_words))
            current_chunk_words = []
            current_word_count = 0

    # Flush whatever remains after the last paragraph
    if current_chunk_words:
        chunks.append(' '.join(current_chunk_words))

    # Filter empty chunks
    chunks = [c.strip() for c in chunks if c.strip()]

    if not chunks:
        # All content was filtered — return full text as one chunk and warn
        logger.warning(
            f'Text chunking produced no valid chunks for {len(text)}-char input; '
            'returning as single chunk (may exceed max_words limit)'
        )
        return [text.strip()]
    return chunks


def _split_sentence_at_clauses(sentence: str, max_words: int) -> list[str]:
    """Split a long sentence at clause boundaries (commas, semicolons).

    Prefers splitting after punctuation that indicates a natural breath
    point: commas, semicolons, em dashes, "and", "but", "or", "because".

    Args:
        sentence: A single sentence that exceeds max_words.
        max_words: Maximum words per resulting chunk.

    Returns:
        List of clause-based chunks that together form the original sentence.
    """
    # Split at clause boundaries: comma, semicolon, or conjunction
    # Keep the punctuation with the preceding clause
    parts = re.split(r'(?<=[,;])\s+', sentence)
    if len(parts) == 1:
        # No clause boundaries found — split at "and", "but", "or", "because"
        parts = re.split(
            r'\s+(?=and\s|but\s|or\s|because\s|which\s|that\s|while\s|whereas\s)',
            sentence,
        )
    if len(parts) == 1:
        # Still no good split point — fall back to word-boundary split
        words = sentence.split()
        chunks = []
        for i in range(0, len(words), max_words):
            chunk = ' '.join(words[i : i + max_words])
            # Add period if this chunk doesn't end with punctuation
            if i + max_words < len(words) and chunk[-1] not in '.!?,':
                chunk += ','
            chunks.append(chunk)
        return chunks

    # Group clause parts into chunks of ~max_words
    result: list[str] = []
    current: list[str] = []
    current_words = 0

    for part in parts:
        part_words = len(part.split())
        if current_words + part_words > max_words and current:
            result.append(' '.join(current))
            current = [part]
            current_words = part_words
        else:
            current.append(part)
            current_words += part_words

    if current:
        result.append(' '.join(current))

    return result or [sentence]


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
