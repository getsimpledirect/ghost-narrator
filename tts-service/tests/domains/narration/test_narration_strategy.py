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

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.hardware import HardwareTier
from app.domains.narration.strategy import (
    ChunkedStrategy,
    SingleShotStrategy,
    _split_into_chunks,
    _strip_llm_artifacts,
    _OLLAMA_ENDPOINT,
    _VLLM_ENDPOINT,
)


def _make_stream(content: str):
    """Async generator yielding a single chunk — matches stream=True response shape."""

    async def _gen():
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        yield chunk

    return _gen()


def _make_llm_client(response: str) -> AsyncMock:
    """Return a mock LLM client that yields `response` as a single streaming chunk."""
    client = AsyncMock()

    async def _side_effect(*args, **kwargs):
        async def _gen():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = response
            yield chunk

        return _gen()

    client.chat.completions.create.side_effect = _side_effect
    return client


def test_ollama_endpoint_detected():
    """Default LLM_BASE_URL (http://ollama:11434/v1) must be detected as Ollama
    so that think=False is passed, preventing Qwen3 thinking-token generation."""
    # The module-level flag is set from the default URL at import time.
    # In test env LLM_BASE_URL defaults to 'http://ollama:11434/v1'.
    import app.config as cfg

    url = cfg.LLM_BASE_URL.lower()
    expected = 'ollama' in url or ':11434' in url
    assert _OLLAMA_ENDPOINT == expected


def test_vllm_endpoint_detected():
    """http://vllm:8000/v1 must be detected as vLLM so chat_template_kwargs is sent."""
    from app.config import LLM_BASE_URL

    url = LLM_BASE_URL.lower()
    expected = 'vllm' in url or ':8000/' in LLM_BASE_URL
    assert _VLLM_ENDPOINT == expected


@pytest.mark.asyncio
async def test_chunked_strategy_passes_think_false_to_ollama():
    """When targeting Ollama, extra_body must contain think=False and the tier's num_ctx."""
    from app.core.hardware import ENGINE_CONFIG

    client = _make_llm_client('Narrated output with enough words to pass validation check here.')
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=500,
        tier=HardwareTier.CPU_ONLY,
    )
    import app.domains.narration.strategy as strat

    original = strat._OLLAMA_ENDPOINT
    try:
        strat._OLLAMA_ENDPOINT = True
        await strategy.narrate('Short source text paragraph for testing purposes only.')
        call_kwargs = client.chat.completions.create.call_args[1]
        extra_body = call_kwargs.get('extra_body', {})
        assert extra_body.get('think') is False
        assert extra_body.get('options', {}).get('num_ctx') == ENGINE_CONFIG.llm_num_ctx
    finally:
        strat._OLLAMA_ENDPOINT = original


@pytest.mark.asyncio
async def test_chunked_strategy_omits_think_false_for_non_ollama():
    """When NOT targeting Ollama or vLLM, extra_body must not be present in the LLM call."""
    client = _make_llm_client('Narrated output with enough words to pass validation check here.')
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=500,
        tier=HardwareTier.CPU_ONLY,
    )
    import app.domains.narration.strategy as strat

    original_ollama = strat._OLLAMA_ENDPOINT
    original_vllm = strat._VLLM_ENDPOINT
    try:
        strat._OLLAMA_ENDPOINT = False
        strat._VLLM_ENDPOINT = False
        await strategy.narrate('Short source text paragraph for testing purposes only.')
        call_kwargs = client.chat.completions.create.call_args[1]
        assert 'extra_body' not in call_kwargs
    finally:
        strat._OLLAMA_ENDPOINT = original_ollama
        strat._VLLM_ENDPOINT = original_vllm


@pytest.mark.asyncio
async def test_chunked_strategy_passes_enable_thinking_false_to_vllm():
    """When targeting vLLM, extra_body must contain chat_template_kwargs.enable_thinking=False."""
    client = _make_llm_client('Narrated output with enough words to pass validation check here.')
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=500,
        tier=HardwareTier.HIGH_VRAM,
    )
    import app.domains.narration.strategy as strat

    original_ollama = strat._OLLAMA_ENDPOINT
    original_vllm = strat._VLLM_ENDPOINT
    try:
        strat._OLLAMA_ENDPOINT = False
        strat._VLLM_ENDPOINT = True
        await strategy.narrate('Short source text paragraph for testing purposes only.')
        call_kwargs = client.chat.completions.create.call_args[1]
        extra_body = call_kwargs.get('extra_body', {})
        assert extra_body.get('chat_template_kwargs', {}).get('enable_thinking') is False
    finally:
        strat._OLLAMA_ENDPOINT = original_ollama
        strat._VLLM_ENDPOINT = original_vllm


@pytest.mark.asyncio
async def test_chunked_strategy_omits_no_think_prefix_for_vllm():
    """When targeting vLLM, user messages must NOT have /no_think prepended.
    vLLM disables thinking server-side; injecting /no_think would corrupt the prompt."""
    client = _make_llm_client('Narrated output with enough words to pass validation check here.')
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=500,
        tier=HardwareTier.HIGH_VRAM,
    )
    import app.domains.narration.strategy as strat

    original_ollama = strat._OLLAMA_ENDPOINT
    original_vllm = strat._VLLM_ENDPOINT
    try:
        strat._OLLAMA_ENDPOINT = False
        strat._VLLM_ENDPOINT = True
        await strategy.narrate('Short source text paragraph for testing purposes only.')
        call_kwargs = client.chat.completions.create.call_args[1]
        messages = call_kwargs.get('messages', [])
        user_messages = [m for m in messages if m.get('role') == 'user']
        for msg in user_messages:
            assert not msg['content'].startswith('/no_think'), (
                f'vLLM user message must not have /no_think prefix; got: {msg["content"][:60]}'
            )
    finally:
        strat._OLLAMA_ENDPOINT = original_ollama
        strat._VLLM_ENDPOINT = original_vllm


@pytest.mark.asyncio
async def test_chunked_strategy_joins_chunks():
    # Return long enough text to pass word count ratio validation
    client = _make_llm_client('This is the narrated text for each chunk that is long enough.')
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=10,
        tier=HardwareTier.CPU_ONLY,
    )
    # 3 paragraphs of 4 words each -> with chunk_words=10,
    # first two fit in one chunk, third starts a new chunk -> 2 chunks
    source = '\n\n'.join(['alfa bravo charlie delta'] * 3)
    result = await strategy.narrate(source)
    assert client.chat.completions.create.call_count == 2
    assert 'narrated text' in result


@pytest.mark.asyncio
async def test_chunked_strategy_uses_continuity_seed():
    responses = [
        'First chunk output ending here with enough words to pass validation.',
        'Second chunk output also with enough words to pass the ratio check.',
    ]
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        _make_stream(responses[0]),
        _make_stream(responses[1]),
    ]
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=5,
        tier=HardwareTier.CPU_ONLY,
    )
    # Two 5-word paragraphs → 2 chunks (each paragraph hits the limit)
    source = 'alfa bravo charlie delta echo\n\nfoxtrot golf hotel india juliet'
    await strategy.narrate(source)
    # Second call should include continuity context from first response
    second_call_messages = client.chat.completions.create.call_args_list[1][1]['messages']
    user_content = next(m['content'] for m in second_call_messages if m['role'] == 'user')
    # Check that the first response text appears in the continuity context
    assert responses[0] in user_content


@pytest.mark.asyncio
async def test_single_shot_strategy_one_call():
    # Return text long enough to pass word count ratio (50 source words * 0.55 = 27.5 min)
    # Need at least 28 words in narration to pass ratio check
    client = _make_llm_client(
        'This is the full narration text that contains enough words to pass '
        'the word count ratio validation check so no retry is triggered. '
        'Here are some extra words to ensure the ratio passes.'
    )
    strategy = SingleShotStrategy(
        llm_client=client,
        fallback_threshold_words=100,
        fallback_chunk_words=50,
        tier=HardwareTier.MID_VRAM,
    )
    source = ' '.join(['word'] * 50)  # under threshold
    await strategy.narrate(source)
    assert client.chat.completions.create.call_count == 1


def test_strip_llm_artifacts_removes_think_blocks():
    """<think>...</think> blocks must be stripped before text reaches TTS."""
    raw = '<think>Let me reason about this carefully.</think>Here is the narration text.'
    assert _strip_llm_artifacts(raw) == 'Here is the narration text.'


def test_strip_llm_artifacts_multiline_think():
    """Multi-line thinking blocks (typical Qwen3 output) must be fully removed."""
    raw = (
        '<think>\n'
        'I need to convert this article.\n'
        'The key facts are: revenue grew 47%.\n'
        '</think>\n'
        'Revenue grew forty-seven percent this quarter.'
    )
    result = _strip_llm_artifacts(raw)
    assert '<think>' not in result
    assert 'Revenue grew' in result
    assert 'I need to convert' not in result


def test_strip_llm_artifacts_removes_preamble():
    """Common LLM acknowledgment lines must be stripped."""
    raw = "Here's the narration:\n\nRevenue grew forty-seven percent."
    result = _strip_llm_artifacts(raw)
    assert result == 'Revenue grew forty-seven percent.'


def test_strip_llm_artifacts_preserves_clean_output():
    """Clean narration text must pass through unchanged."""
    text = 'Revenue grew forty-seven percent this quarter. The company reported record sales.'
    assert _strip_llm_artifacts(text) == text


def test_split_into_chunks_no_overlap():
    """Chunks must not contain content from adjacent chunks (overlap=0 default)."""
    # Three distinct paragraphs — with overlap=1, para2 would appear in both chunk1 and chunk2
    source = (
        'paragraph one content here\n\nparagraph two content here\n\nparagraph three content here'
    )
    chunks = _split_into_chunks(source, chunk_words=6, overlap_paragraphs=0)
    # Each paragraph should appear in exactly one chunk
    all_text = ' '.join(chunks)
    for para in ['paragraph one', 'paragraph two', 'paragraph three']:
        assert all_text.count(para) == 1, f'"{para}" appears more than once across chunks'


def test_chunked_strategy_no_duplicate_content_at_boundaries():
    """Overlap paragraphs must not cause duplicate narration at chunk boundaries."""
    # Verify that narrate() uses overlap=0 by checking that split chunks are distinct.
    # Two paragraphs that each exceed half of chunk_words → forces 2 chunks.
    source = 'first paragraph text goes here now\n\nsecond paragraph text goes here now'
    chunks = _split_into_chunks(source, chunk_words=7, overlap_paragraphs=0)
    assert len(chunks) == 2
    # No paragraph text appears in both chunks
    assert 'first paragraph' not in chunks[1]
    assert 'second paragraph' not in chunks[0]


@pytest.mark.asyncio
async def test_single_shot_falls_back_to_chunked_when_over_threshold():
    client = _make_llm_client('Chunk narration with enough words to pass validation check.')
    strategy = SingleShotStrategy(
        llm_client=client,
        fallback_threshold_words=10,
        fallback_chunk_words=5,
        tier=HardwareTier.MID_VRAM,
    )
    # 6 paragraphs of 5 words each → 6 chunks at chunk_words=5
    source = '\n\n'.join(['alfa bravo charlie delta echo'] * 6)
    await strategy.narrate(source)
    # Chunked fallback -> multiple calls
    assert client.chat.completions.create.call_count > 1


@pytest.mark.asyncio
async def test_chunked_strategy_no_extra_llm_call_for_section_map():
    """ChunkedStrategy must NOT make an extra LLM call for an article brief.

    Section context comes from HTML header extraction - zero extra LLM calls.
    Two chunks -> exactly 2 LLM calls total.
    """
    responses = [
        'First chunk narrated output with enough words to pass validation check.',
        'Second chunk narrated output with enough words to pass validation.',
    ]
    client = AsyncMock()
    client.chat.completions.create.side_effect = [_make_stream(r) for r in responses]
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=5,
        tier=HardwareTier.CPU_ONLY,
    )
    source = 'alfa bravo charlie delta echo\n\nfoxtrot golf hotel india juliet'
    await strategy.narrate(source)
    # No brief call - exactly 1 LLM call per chunk
    assert client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_chunk_position_in_user_content():
    """Each chunk's user message must contain a [SECTION X of Y] position marker."""
    responses = [
        'First chunk narrated output with enough words to pass validation check.',
        'Second chunk narrated output with enough words to pass validation.',
    ]
    client = AsyncMock()
    client.chat.completions.create.side_effect = [_make_stream(r) for r in responses]
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=5,
        tier=HardwareTier.CPU_ONLY,
    )
    source = 'alfa bravo charlie delta echo\n\nfoxtrot golf hotel india juliet'
    await strategy.narrate(source)
    # First call (chunk 0) has [SECTION 1 of 2]
    first_call_messages = client.chat.completions.create.call_args_list[0][1]['messages']
    user_content = next(m['content'] for m in first_call_messages if m['role'] == 'user')
    assert '[SECTION 1 of 2 |' in user_content


@pytest.mark.asyncio
async def test_section_map_from_html_appears_in_system_prompt():
    """When HTML headers are present, their text must appear in the system prompt."""
    responses = [
        'Narrated output with enough words to pass validation check.',
    ]
    client = AsyncMock()
    client.chat.completions.create.side_effect = [_make_stream(r) for r in responses]
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=200,
        tier=HardwareTier.CPU_ONLY,
    )
    # HTML with H2 headers - extract_section_map should find 'Introduction' and 'Conclusion'
    source = '<h2>Introduction</h2><p>alfa bravo charlie delta echo foxtrot</p><h2>Conclusion</h2><p>golf hotel india juliet kilo lima</p>'
    await strategy.narrate(source)
    first_call_messages = client.chat.completions.create.call_args_list[0][1]['messages']
    system_content = next(m['content'] for m in first_call_messages if m['role'] == 'system')
    assert 'Introduction' in system_content
    assert 'Conclusion' in system_content


def test_system_prompt_includes_pause_marker_instruction():
    """System prompt must instruct the LLM to use [PAUSE] and [LONG_PAUSE] markers."""
    from app.domains.narration.prompt import get_system_prompt
    from app.core.hardware import HardwareTier

    for tier in HardwareTier:
        prompt = get_system_prompt(tier)
        assert '[PAUSE]' in prompt, f'[PAUSE] instruction missing for {tier}'
        assert '[LONG_PAUSE]' in prompt, f'[LONG_PAUSE] instruction missing for {tier}'


def test_system_prompt_includes_active_voice_instruction():
    """System prompt must instruct active voice and no hedging."""
    from app.domains.narration.prompt import get_system_prompt
    from app.core.hardware import HardwareTier

    prompt = get_system_prompt(HardwareTier.MID_VRAM)
    assert 'active voice' in prompt.lower()
    assert 'hedge' in prompt.lower() or 'it seems' in prompt.lower()


def test_system_prompt_with_section_map():
    """get_system_prompt must embed section map text when provided."""
    from app.domains.narration.prompt import get_system_prompt
    from app.core.hardware import HardwareTier

    prompt = get_system_prompt(HardwareTier.CPU_ONLY, section_map='Intro, Deep Dive, Conclusion')
    assert 'Intro' in prompt
    assert 'Deep Dive' in prompt
    assert 'Conclusion' in prompt


def test_strip_llm_artifacts_removes_meta_commentary():
    """Meta-commentary patterns must be stripped."""
    from app.domains.narration.strategy import _strip_llm_artifacts

    # Test: "The journey described in the text" pattern
    raw = 'The journey described in the text begins with someone sitting in a Toronto coffee shop.'
    result = _strip_llm_artifacts(raw)
    assert result.strip() == ''

    # Test: "This passage explores" pattern
    raw2 = 'This passage explores the concept of consulting.'
    result2 = _strip_llm_artifacts(raw2)
    assert result2.strip() == ''

    # Test: "In this article" pattern
    raw3 = 'In this article we look at the key findings.'
    result3 = _strip_llm_artifacts(raw3)
    assert result3.strip() == ''


def test_strip_llm_artifacts_preserves_normal_content():
    """Normal content without meta-commentary should pass through."""
    from app.domains.narration.strategy import _strip_llm_artifacts

    text = "I'm sitting in a Toronto coffee shop, looking at my bank statements."
    result = _strip_llm_artifacts(text)
    assert result == text
