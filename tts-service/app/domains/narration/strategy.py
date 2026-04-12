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

"""NarrationStrategy implementations for chunked and single-shot LLM narration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.core.hardware import HardwareTier
from app.core.retry import retry_with_backoff
from app.config import LLM_TIMEOUT, LLM_COMPLETENESS_TIMEOUT
from app.domains.narration.prompt import (
    get_system_prompt,
    get_continuity_instruction,
    get_completeness_check_prompt,
)
from app.domains.narration.validator import NarrationValidator

logger = logging.getLogger(__name__)

_validator = NarrationValidator()


def _split_into_chunks(text: str, chunk_words: int, overlap_paragraphs: int = 1) -> list[str]:
    """Split text at paragraph boundaries with optional overlap.

    Args:
        text: Full text to split.
        chunk_words: Target words per chunk.
        overlap_paragraphs: Number of paragraphs to repeat at chunk boundaries
            so the LLM has context from the previous chunk's end.

    Returns:
        List of text chunks with overlapping paragraphs at boundaries.
    """
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paragraphs) <= 1:
        return [text]

    raw_chunks: list[list[str]] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > chunk_words and current:
            raw_chunks.append(current)
            current = [para]
            current_words = para_words
        else:
            current.append(para)
            current_words += para_words
    if current:
        raw_chunks.append(current)

    if len(raw_chunks) <= 1:
        return ['\n\n'.join(raw_chunks[0])] if raw_chunks else [text]

    # Add overlap: prepend last N paragraphs from previous chunk
    chunks: list[str] = []
    for i, chunk_paras in enumerate(raw_chunks):
        if i > 0 and overlap_paragraphs > 0:
            overlap = raw_chunks[i - 1][-overlap_paragraphs:]
            chunk_paras = overlap + chunk_paras
        chunks.append('\n\n'.join(chunk_paras))

    return chunks


_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.?!]) +')


def _tail_sentences(text: str, n: int = 3) -> str:
    """Return last n sentences of text for continuity seeding."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.replace('\n', ' ')) if s.strip()]
    return ' '.join(sentences[-n:])


async def _call_llm(client, messages: list[dict], model: str, timeout: float = None) -> str:
    """Call LLM with configurable timeout, using config defaults if not specified."""
    if timeout is None:
        timeout = LLM_TIMEOUT

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        timeout=timeout,
    )
    return response.choices[0].message.content.strip()


# Retry wrapper for LLM calls - handles transient failures.
# TimeoutError is excluded: if Ollama can't respond within LLM_TIMEOUT, retrying
# with the same timeout burns 3× the wait. Let it fail fast and surface the error.
@retry_with_backoff(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    exceptions=(Exception,),
    exclude=(asyncio.TimeoutError,),
)
async def _call_llm_with_retry(
    client, messages: list[dict], model: str, timeout: float = None
) -> str:
    """Call LLM with retry on transient failures. TimeoutError is not retried."""
    return await _call_llm(client, messages, model, timeout)


class NarrationStrategy(ABC):
    @abstractmethod
    async def narrate(self, text: str) -> str: ...

    async def narrate_iter(self, text: str) -> AsyncIterator[str]:
        """Yield narrated chunks as they complete (for pipelining with TTS).

        Default implementation: narrate everything, then yield as one chunk.
        ChunkedStrategy overrides this to yield each chunk as it's ready.
        """
        yield await self.narrate(text)


class ChunkedStrategy(NarrationStrategy):
    def __init__(self, llm_client, chunk_words: int, tier: HardwareTier, model: str = '') -> None:
        self._client = llm_client
        self._chunk_words = chunk_words
        self._tier = tier
        self._model = model
        self._system_prompt = get_system_prompt(tier)

    async def _narrate_chunk(
        self, chunk: str, previous_output_tail: str, previous_source_tail: str = ''
    ) -> str:
        continuity = get_continuity_instruction(previous_output_tail, previous_source_tail)
        messages = [
            {'role': 'system', 'content': self._system_prompt},
            {'role': 'user', 'content': chunk + continuity},
        ]
        # Use retry wrapper for network resilience
        result = await _call_llm_with_retry(self._client, messages, self._model)
        validation = _validator.validate(chunk, result)
        if not validation.passed:
            logger.warning(
                'Validation failed for chunk — retrying. Missing: %s',
                validation.missing_entities,
            )
            retry_prompt = _validator.build_retry_prompt(validation, chunk)
            messages.append({'role': 'assistant', 'content': result})
            messages.append({'role': 'user', 'content': retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
        return result

    async def _llm_completeness_check(self, source: str, narration: str) -> str:
        """Run LLM-based completeness verification (HIGH_VRAM only).

        Returns narration with corrections if issues found, or original narration.
        """
        messages = get_completeness_check_prompt(source, narration)
        try:
            # Use longer timeout for completeness check (more complex LLM task)
            raw = await _call_llm(
                self._client, messages, self._model, timeout=LLM_COMPLETENESS_TIMEOUT
            )
            # Parse JSON array from response
            raw = raw.strip()
            if raw.startswith('```'):
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
            missing = json.loads(raw)
            if isinstance(missing, list) and missing:
                logger.warning(
                    'LLM completeness check found %d issues: %s',
                    len(missing),
                    missing[:3],
                )
                # Re-narrate with explicit missing items
                fix_messages = [
                    {'role': 'system', 'content': self._system_prompt},
                    {
                        'role': 'user',
                        'content': (
                            'Your previous narration was missing these items:\n'
                            + '\n'.join(f'- {item}' for item in missing)
                            + f'\n\nRewrite the narration for this source, '
                            f'ensuring all items above are included:\n\n{source}'
                        ),
                    },
                ]
                return await _call_llm(self._client, fix_messages, self._model)
        except json.JSONDecodeError as exc:
            logger.debug('LLM completeness check returned invalid JSON: %s', exc)
        except Exception as exc:
            logger.warning('LLM completeness check failed: %s', exc)
        return narration

    async def narrate(self, text: str) -> str:
        chunks = _split_into_chunks(text, self._chunk_words)
        outputs: list[str] = []
        previous_output_tail = ''
        previous_source_tail = ''
        for chunk in chunks:
            output = await self._narrate_chunk(chunk, previous_output_tail, previous_source_tail)
            outputs.append(output)
            previous_output_tail = _tail_sentences(output)
            previous_source_tail = _tail_sentences(chunk)

        full_narration = '\n\n'.join(outputs)

        # Layer 4: LLM completeness check — HIGH_VRAM only
        if self._tier == HardwareTier.HIGH_VRAM:
            logger.info('Running LLM completeness check (HIGH_VRAM)...')
            full_narration = await self._llm_completeness_check(text, full_narration)

        return full_narration

    async def narrate_iter(self, text: str) -> AsyncIterator[str]:
        """Yield each narrated chunk as it completes for pipelining with TTS.

        Note: LLM completeness check is skipped in iter mode since chunks
        are consumed immediately by TTS. Full narrate() should be used when
        completeness checking is needed.
        """
        chunks = _split_into_chunks(text, self._chunk_words)
        previous_output_tail = ''
        previous_source_tail = ''
        for chunk in chunks:
            output = await self._narrate_chunk(chunk, previous_output_tail, previous_source_tail)
            previous_output_tail = _tail_sentences(output)
            previous_source_tail = _tail_sentences(chunk)
            yield output


class SingleShotStrategy(NarrationStrategy):
    def __init__(
        self,
        llm_client,
        fallback_threshold_words: int,
        fallback_chunk_words: int,
        tier: HardwareTier,
        model: str = '',
    ) -> None:
        self._client = llm_client
        self._fallback_threshold = fallback_threshold_words
        self._fallback_chunk_words = fallback_chunk_words
        self._tier = tier
        self._model = model
        self._system_prompt = get_system_prompt(tier)

    async def narrate(self, text: str) -> str:
        word_count = len(text.split())
        if word_count > self._fallback_threshold:
            logger.info(
                'Content (%d words) exceeds threshold — using chunked fallback',
                word_count,
            )
            fallback = ChunkedStrategy(
                llm_client=self._client,
                chunk_words=self._fallback_chunk_words,
                tier=self._tier,
                model=self._model,
            )
            return await fallback.narrate(text)
        messages = [
            {'role': 'system', 'content': self._system_prompt},
            {'role': 'user', 'content': text},
        ]
        result = await _call_llm_with_retry(self._client, messages, self._model)
        validation = _validator.validate(text, result)
        if not validation.passed:
            logger.warning('Validation failed — retrying. Missing: %s', validation.missing_entities)
            retry_prompt = _validator.build_retry_prompt(validation, text)
            messages.append({'role': 'assistant', 'content': result})
            messages.append({'role': 'user', 'content': retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
        return result
