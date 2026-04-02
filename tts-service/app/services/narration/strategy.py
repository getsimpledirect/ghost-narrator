"""NarrationStrategy implementations for chunked and single-shot LLM narration."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

from app.core.hardware import HardwareTier
from app.services.narration.prompt import get_system_prompt, get_continuity_instruction
from app.services.narration.validator import NarrationValidator

logger = logging.getLogger(__name__)

_validator = NarrationValidator()


def _split_into_chunks(text: str, chunk_words: int) -> list[str]:
    """Split text at paragraph boundaries, targeting chunk_words per chunk."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > chunk_words and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_words = para_words
        else:
            current.append(para)
            current_words += para_words
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!]) +")


def _tail_sentences(text: str, n: int = 3) -> str:
    """Return last n sentences of text for continuity seeding."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.replace("\n", " ")) if s.strip()]
    return " ".join(sentences[-n:])


async def _call_llm(client, messages: list[dict], model: str, timeout: float = 120.0) -> str:
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        timeout=timeout,
    )
    return response.choices[0].message.content.strip()


class NarrationStrategy(ABC):
    @abstractmethod
    async def narrate(self, text: str) -> str: ...


class ChunkedStrategy(NarrationStrategy):
    def __init__(
        self, llm_client, chunk_words: int, tier: HardwareTier, model: str = ""
    ) -> None:
        self._client = llm_client
        self._chunk_words = chunk_words
        self._tier = tier
        self._model = model
        self._system_prompt = get_system_prompt(tier)

    async def _narrate_chunk(self, chunk: str, previous_tail: str) -> str:
        continuity = get_continuity_instruction(previous_tail)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": chunk + continuity},
        ]
        result = await _call_llm(self._client, messages, self._model)
        validation = _validator.validate(chunk, result)
        if not validation.passed:
            logger.warning(
                "Validation failed for chunk — retrying. Missing: %s",
                validation.missing_entities,
            )
            retry_prompt = _validator.build_retry_prompt(validation, chunk)
            messages.append({"role": "assistant", "content": result})
            messages.append({"role": "user", "content": retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
        return result

    async def narrate(self, text: str) -> str:
        chunks = _split_into_chunks(text, self._chunk_words)
        outputs: list[str] = []
        previous_tail = ""
        for chunk in chunks:
            output = await self._narrate_chunk(chunk, previous_tail)
            outputs.append(output)
            previous_tail = _tail_sentences(output)
        return "\n\n".join(outputs)


class SingleShotStrategy(NarrationStrategy):
    def __init__(
        self,
        llm_client,
        fallback_threshold_words: int,
        fallback_chunk_words: int,
        tier: HardwareTier,
        model: str = "",
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
                "Content (%d words) exceeds threshold — using chunked fallback",
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
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": text},
        ]
        result = await _call_llm(self._client, messages, self._model)
        validation = _validator.validate(text, result)
        if not validation.passed:
            logger.warning(
                "Validation failed — retrying. Missing: %s", validation.missing_entities
            )
            retry_prompt = _validator.build_retry_prompt(validation, text)
            messages.append({"role": "assistant", "content": result})
            messages.append({"role": "user", "content": retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
        return result
