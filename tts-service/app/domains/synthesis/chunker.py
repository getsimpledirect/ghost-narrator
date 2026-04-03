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
Text chunking for TTS synthesis.

Provides functions for splitting text into optimal chunks for
TTS synthesis while maintaining sentence boundaries.
"""

from __future__ import annotations

import logging
import re
from typing import Final, List

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHUNK_WORDS: Final[int] = 200

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


def chunk_text(text: str, max_words: int = DEFAULT_MAX_CHUNK_WORDS) -> List[str]:
    """
    Split narration text into TTS-optimal chunks.

    Strategy:
    - Split on paragraph boundaries first (double newline or sentence groups)
    - Within paragraphs, group sentences into chunks of ~40-60 words
    - Never split mid-sentence
    - For long sentences, prefer splitting at clause boundaries (commas,
      semicolons, em dashes) rather than arbitrary word positions
    - Keep sentence-ending punctuation with its sentence (not the next chunk)

    Args:
        text: The input text to split into chunks.
        max_words: Maximum number of words per chunk (default: 200).

    Returns:
        A list of text chunks, each suitable for TTS synthesis.
        Returns an empty list if input is empty/whitespace.
    """
    if not text or not text.strip():
        return []

    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]

    chunks: List[str] = []

    for para in paragraphs:
        sentences = re.split(r'(?<=[.!?])\s+', para.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk_words: List[str] = []
        current_word_count: int = 0

        for sentence in sentences:
            sentence_words = sentence.split()
            sentence_word_count = len(sentence_words)

            if sentence_word_count == 0:
                continue

            if current_word_count + sentence_word_count > max_words and current_chunk_words:
                chunks.append(' '.join(current_chunk_words))
                current_chunk_words = []
                current_word_count = 0

            if sentence_word_count > max_words:
                if current_chunk_words:
                    chunks.append(' '.join(current_chunk_words))
                    current_chunk_words = []
                    current_word_count = 0

                clause_chunks = _split_sentence_at_clauses(sentence, max_words)
                for clause in clause_chunks[:-1]:
                    chunks.append(clause)
                last_clause = clause_chunks[-1]
                current_chunk_words = last_clause.split()
                current_word_count = len(current_chunk_words)
                continue

            current_chunk_words.extend(sentence_words)
            current_word_count += sentence_word_count

            if current_word_count >= max_words:
                chunks.append(' '.join(current_chunk_words))
                current_chunk_words = []
                current_word_count = 0

        if current_chunk_words:
            chunks.append(' '.join(current_chunk_words))

    chunks = [c.strip() for c in chunks if c.strip()]

    if not chunks:
        logger.warning(
            f'Text chunking produced no valid chunks for {len(text)}-char input; '
            'returning as single chunk (may exceed max_words limit)'
        )
        return [text.strip()]
    return chunks


def _split_sentence_at_clauses(sentence: str, max_words: int) -> List[str]:
    """Split a long sentence at clause boundaries (commas, semicolons)."""
    parts = re.split(r'(?<=[,;])\s+', sentence)
    if len(parts) == 1:
        parts = re.split(
            r'\s+(?=and\s|but\s|or\s|because\s|which\s|that\s|while\s|whereas\s)',
            sentence,
        )
    if len(parts) == 1:
        words = sentence.split()
        chunks = []
        for i in range(0, len(words), max_words):
            chunk = ' '.join(words[i : i + max_words])
            if i + max_words < len(words) and chunk[-1] not in '.!?,':
                chunk += ','
            chunks.append(chunk)
        return chunks

    result: List[str] = []
    current: List[str] = []
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
    - After a sentence ending a paragraph: 700ms
    - After a sentence-ending chunk: 450ms
    - After a mid-sentence break: 250ms

    Args:
        chunk: The current chunk text.
        next_chunk: The next chunk text, or None if this is the last chunk.

    Returns:
        Silence duration in milliseconds.
    """
    if not next_chunk:
        return 0

    chunk_stripped = chunk.strip()

    if chunk_stripped.endswith('.') or chunk_stripped.endswith('!') or chunk_stripped.endswith('?'):
        next_lower = next_chunk.lower().strip()
        if any(next_lower.startswith(t) for t in _TRANSITION_STARTERS):
            return 700
        return 450

    return 250


class TextChunker:
    """Text chunker with configurable settings."""

    def __init__(self, max_words: int = DEFAULT_MAX_CHUNK_WORDS):
        self.max_words = max_words

    def chunk(self, text: str) -> List[str]:
        """Chunk text with configured max_words."""
        return chunk_text(text, self.max_words)

    def __call__(self, text: str) -> List[str]:
        return self.chunk(text)
