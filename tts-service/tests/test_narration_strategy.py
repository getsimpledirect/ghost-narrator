# tts-service/tests/test_narration_strategy.py
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import types

# Mock qwen_tts before any app imports
_mock = types.ModuleType('qwen_tts')
_mock.QwenTTS = MagicMock
sys.modules.setdefault('qwen_tts', _mock)

import pytest
from app.domains.narration.strategy import ChunkedStrategy, SingleShotStrategy
from app.core.hardware import HardwareTier


def _make_llm_client(response: str) -> AsyncMock:
    """Return a mock LLM client that returns `response` for any request."""
    client = AsyncMock()
    choice = MagicMock()
    choice.message.content = response
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


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
    choice1, choice2 = MagicMock(), MagicMock()
    choice1.message.content = responses[0]
    choice2.message.content = responses[1]
    client.chat.completions.create.side_effect = [
        MagicMock(choices=[choice1]),
        MagicMock(choices=[choice2]),
    ]
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=5,
        tier=HardwareTier.CPU_ONLY,
    )
    # Two 5-word paragraphs → 2 chunks (each paragraph hits the limit)
    source = 'alfa bravo charlie delta echo\n\nfoxtrot golf hotel india juliet'
    result = await strategy.narrate(source)
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
    result = await strategy.narrate(source)
    assert client.chat.completions.create.call_count == 1


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
    result = await strategy.narrate(source)
    # Chunked fallback -> multiple calls
    assert client.chat.completions.create.call_count > 1
