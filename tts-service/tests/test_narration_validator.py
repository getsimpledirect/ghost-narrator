# tts-service/tests/test_narration_validator.py
import sys
import types

import pytest

# Mock qwen_tts so the import chain through app.domains doesn't crash
_mock = types.ModuleType('qwen_tts')
_mock.QwenTTS = type('QwenTTS', (), {})
sys.modules.setdefault('qwen_tts', _mock)

from app.domains.narration.validator import NarrationValidator, ValidationResult


def test_passes_when_number_present():
    v = NarrationValidator()
    result = v.validate(
        source='Revenue grew 47% to $2.3 billion in Q3',
        narration='Revenue grew 47% to $2.3 billion in the third quarter',
    )
    assert result.passed
    assert result.missing_entities == []


def test_fails_when_number_missing():
    v = NarrationValidator()
    result = v.validate(
        source='Revenue grew 47% to $2.3 billion',
        narration='Revenue grew significantly this year',
    )
    assert not result.passed
    assert '47%' in result.missing_entities


def test_fails_when_quoted_string_missing():
    v = NarrationValidator()
    result = v.validate(
        source='CEO said "we are on track"',
        narration='The CEO made a statement about progress',
    )
    assert not result.passed
    assert 'we are on track' in result.missing_entities


def test_case_insensitive_match():
    v = NarrationValidator()
    result = v.validate(source='The GDP grew by 3.2%', narration='the gdp grew by 3.2%')
    assert result.passed


def test_passes_on_empty_source():
    v = NarrationValidator()
    result = v.validate(source='', narration='some narration')
    assert result.passed


def test_build_retry_prompt_contains_missing():
    v = NarrationValidator()
    result = v.validate(source='Revenue grew 47%', narration='Revenue grew')
    prompt = v.build_retry_prompt(result, original_chunk='Revenue grew 47%')
    assert '47%' in prompt
    assert 'missing' in prompt.lower()
