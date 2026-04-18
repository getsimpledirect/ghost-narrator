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
from app.core.exceptions import NarrationError
from app.config import LLM_TIMEOUT, LLM_COMPLETENESS_TIMEOUT, LLM_BASE_URL
from app.domains.narration.prompt import (
    get_system_prompt,
    get_continuity_instruction,
    get_completeness_check_prompt,
)
from app.domains.narration.validator import NarrationValidator

# Matches Qwen3 (and similar reasoning-model) thinking blocks.
# Must be stripped before narration reaches the validator or TTS engine —
# thinking tokens synthesized as speech produce garbled audio noise and
# dramatically inflate generation time.
_THINK_RE = re.compile(
    r'<think(?:ing)?>.*?</think(?:ing)?>',
    re.DOTALL | re.IGNORECASE,
)

# Conservative preamble patterns: short acknowledgment lines the LLM inserts
# before the narration text despite the "no preamble" instruction.
# Also catches meta-commentary framing like "The journey described in the text..."
_LLM_PREAMBLE_RE = re.compile(
    r'^(?:here(?:\'s|\s+is)?|sure,?|okay,?|of\s+course,?|certainly,?|'
    r'absolutely,?|alright,?|got\s+it,?)[^\n]{0,150}\n\n?'
    r'|'
    r'^the\s+(?:journey|story|text|passage|article)\s+described\b.*'
    r'|'
    r'^this\s+(?:passage|article)\s+(?:explores|examines)\b.*'
    r'|'
    r'^in\s+this\s+(?:article|chapter|section)\b.*',
    re.IGNORECASE | re.MULTILINE,
)

# Trailing meta-commentary the LLM sometimes appends after the narration.
_LLM_POSTAMBLE_RE = re.compile(
    r'\n+(?:(?:i\s+hope|let\s+me\s+know|feel\s+free|note\s+that|'
    r'this\s+(?:covers|maintains|preserves|narration|version))'
    r'[^\n]{0,250})$',
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

_validator = NarrationValidator()

# True when the configured LLM endpoint is Ollama.
# Ollama's OpenAI-compatible API accepts a non-standard `think` field that
# prevents Qwen3 from generating <think> blocks entirely.  Other providers
# (OpenAI, Anthropic, etc.) validate the request body strictly and return 400
# on unknown fields, so we must not send it there.
_OLLAMA_ENDPOINT: bool = 'ollama' in LLM_BASE_URL.lower() or ':11434' in LLM_BASE_URL


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


def _strip_llm_artifacts(text: str) -> str:
    """Strip Qwen3 thinking tokens and common LLM preamble/postamble.

    Qwen3 models emit <think>...</think> blocks before their actual response.
    These must be removed before text reaches the narration validator or TTS
    engine — otherwise thinking tokens are synthesized as garbled audio and
    inflate generation time significantly.

    Preamble/postamble stripping is conservative: only unambiguous meta-lines
    are removed to avoid clipping real narration content.
    """
    text = _THINK_RE.sub('', text)
    text = _LLM_PREAMBLE_RE.sub('', text)
    text = _LLM_POSTAMBLE_RE.sub('', text)
    return text.strip()


_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.?!]) +')


def _tail_sentences(text: str, n: int = 3) -> str:
    """Return last n sentences of text for continuity seeding."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.replace('\n', ' ')) if s.strip()]
    return ' '.join(sentences[-n:])


async def _call_llm(client, messages: list[dict], model: str, timeout: float = None) -> str:
    """Call LLM with configurable timeout, using config defaults if not specified."""
    if timeout is None:
        timeout = LLM_TIMEOUT

    # On Ollama endpoints: disable thinking blocks via two mechanisms:
    #   1. think: False in extra_body — API-level flag (Ollama >= 0.6.x)
    #   2. /no_think prepended to each user message — model-level instruction that
    #      works on ALL Ollama versions since qwen3 was trained to respect it.
    #
    # Why both? Older Ollama container images silently ignore think: False. When
    # thinking is not suppressed, qwen3:8b may generate 5000-8000 thinking tokens
    # before the narration text. Those tokens count against max_tokens=8192 and can
    # leave as few as 59 tokens for the actual narration — producing the CRITICAL 7%
    # word-ratio failures seen in production. Stripping <think> blocks fixes the
    # output text but the token budget is already spent.
    #
    # Also set num_ctx=8192 explicitly: Ollama defaults to 2048, which silently
    # truncates long chunks and produces summarization-style output.
    kwargs: dict = {}
    effective_messages = messages
    if _OLLAMA_ENDPOINT:
        # Prepend /no_think to every user turn so thinking is suppressed regardless
        # of Ollama version. Skip turns that already carry the instruction (retries).
        effective_messages = [
            (
                {**msg, 'content': '/no_think\n' + msg['content']}
                if msg.get('role') == 'user' and not msg['content'].startswith('/no_think')
                else msg
            )
            for msg in messages
        ]
        kwargs['extra_body'] = {'think': False, 'options': {'num_ctx': 8192}}

    # max_tokens: set high enough to never truncate narration output. Ollama caps
    # the actual output at min(max_tokens, num_ctx - prompt_tokens), so this only
    # matters if thinking is disabled and input is small.
    max_tokens = 8192

    response = await client.chat.completions.create(
        model=model,
        messages=effective_messages,
        temperature=0.3,
        max_tokens=max_tokens,
        timeout=timeout,
        **kwargs,
    )
    if not response.choices:
        raise NarrationError('LLM returned empty response with no choices')
    return _strip_llm_artifacts(response.choices[0].message.content)


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
        self._base_system_prompt = get_system_prompt(tier)

    async def _narrate_chunk(
        self,
        chunk: str,
        chunk_index: int,
        total_chunks: int,
        previous_output_tail: str,
        previous_source_tail: str = '',
        system_prompt: str = '',
    ) -> str:
        effective_prompt = system_prompt or self._base_system_prompt
        word_count = len(chunk.split())
        # Explicit word-count target prevents qwen3:8b from under-generating.
        # Without this, the model sometimes outputs a brief summary (7-45% of source
        # length) despite the system prompt's "match source length" instruction.
        position_ctx = (
            f'\n[SECTION {chunk_index + 1} of {total_chunks} | '
            f'SOURCE: ~{word_count} words → your narration must be approximately {word_count} words]'
        )
        continuity = get_continuity_instruction(previous_output_tail, previous_source_tail)
        messages = [
            {'role': 'system', 'content': effective_prompt},
            {'role': 'user', 'content': chunk + position_ctx + continuity},
        ]
        # Use retry wrapper for network resilience
        result = await _call_llm_with_retry(self._client, messages, self._model)
        validation = _validator.validate(chunk, result)
        retry_count = 0
        max_retries = 2  # Allow initial attempt + 2 retries = 3 total attempts
        while not validation.passed and retry_count < max_retries:
            logger.warning(
                'Validation failed for chunk — retrying (%d/%d). Missing: %s',
                retry_count + 1,
                max_retries,
                validation.missing_entities,
            )
            retry_prompt = _validator.build_retry_prompt(validation, chunk)
            messages.append({'role': 'assistant', 'content': result})
            messages.append({'role': 'user', 'content': retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
            # Validate the retry result
            validation = _validator.validate(chunk, result)
            retry_count += 1

        if not validation.passed:
            logger.error(
                'Validation failed for chunk after %d retries. Missing: %s',
                retry_count,
                validation.missing_entities,
            )
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
                    {'role': 'system', 'content': self._base_system_prompt},
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
        from app.utils.normalize import extract_section_map, normalize_for_narration

        # Extract H2/H3 section titles BEFORE normalize strips HTML tags
        section_map = extract_section_map(text)
        text = normalize_for_narration(text)

        # Build system prompt with section context (deterministic, no extra LLM call)
        system_prompt = get_system_prompt(self._tier, section_map=section_map)

        chunks = _split_into_chunks(text, self._chunk_words, overlap_paragraphs=0)
        total_chunks = len(chunks)
        outputs: list[str] = []
        previous_output_tail = ''
        previous_source_tail = ''
        for i, chunk in enumerate(chunks):
            output = await self._narrate_chunk(
                chunk,
                i,
                total_chunks,
                previous_output_tail,
                previous_source_tail,
                system_prompt=system_prompt,
            )
            outputs.append(output)
            previous_output_tail = _tail_sentences(output)
            previous_source_tail = _tail_sentences(chunk)

        full_narration = '\n\n'.join(outputs)

        # Layer 4: LLM completeness check — HIGH_VRAM only, small articles only.
        # The check sends source + narration to the LLM in one call. With num_ctx=8192
        # and the system prompt consuming ~200 tokens, the combined budget for source
        # and narration is ~4000 words each. Skip for larger content to avoid silent
        # truncation that produces garbage JSON and triggers unnecessary re-narration.
        if self._tier == HardwareTier.HIGH_VRAM:
            _combined_words = len(text.split()) + len(full_narration.split())
            if _combined_words <= 4000:
                logger.info('Running LLM completeness check (HIGH_VRAM)...')
                full_narration = await self._llm_completeness_check(text, full_narration)
            else:
                logger.info(
                    'Skipping LLM completeness check — combined word count %d exceeds '
                    '4000-word context budget',
                    _combined_words,
                )

        return full_narration

    async def narrate_iter(self, text: str) -> AsyncIterator[str]:
        from app.utils.normalize import extract_section_map, normalize_for_narration

        section_map = extract_section_map(text)
        text = normalize_for_narration(text)

        system_prompt = get_system_prompt(self._tier, section_map=section_map)

        chunks = _split_into_chunks(text, self._chunk_words, overlap_paragraphs=0)
        total_chunks = len(chunks)
        previous_output_tail = ''
        previous_source_tail = ''
        for i, chunk in enumerate(chunks):
            output = await self._narrate_chunk(
                chunk,
                i,
                total_chunks,
                previous_output_tail,
                previous_source_tail,
                system_prompt=system_prompt,
            )
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
        self._base_system_prompt = get_system_prompt(tier)

    async def narrate(self, text: str) -> str:
        from app.utils.normalize import extract_section_map, normalize_for_narration

        section_map = extract_section_map(text)
        text = normalize_for_narration(text)

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

        system_prompt = get_system_prompt(self._tier, section_map=section_map)
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': text},
        ]
        result = await _call_llm_with_retry(self._client, messages, self._model)
        validation = _validator.validate(text, result)
        retry_count = 0
        max_retries = 2  # Allow initial attempt + 2 retries = 3 total attempts
        while not validation.passed and retry_count < max_retries:
            logger.warning(
                'Validation failed — retrying (%d/%d). Missing: %s',
                retry_count + 1,
                max_retries,
                validation.missing_entities,
            )
            retry_prompt = _validator.build_retry_prompt(validation, text)
            messages.append({'role': 'assistant', 'content': result})
            messages.append({'role': 'user', 'content': retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
            # Validate the retry result
            validation = _validator.validate(text, result)
            retry_count += 1

        if not validation.passed:
            logger.error(
                'Validation failed after %d retries. Missing: %s',
                retry_count,
                validation.missing_entities,
            )
        return result
