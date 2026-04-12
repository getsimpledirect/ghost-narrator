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

from app.domains.narration.validator import NarrationValidator


def test_passes_when_number_present():
    v = NarrationValidator()
    result = v.validate(
        source='Revenue grew 47% to $2.3 billion in Q3',
        narration='Revenue grew 47% to $2.3 billion in the third quarter',
    )
    assert result.passed
    assert result.missing_entities == []


def test_spoken_form_dollar_amount_passes_validation():
    """Dollar amounts spelled out per narration prompt must not fail validation.

    The prompt says: '$1.2 billion' → 'one point two billion dollars'.
    The old _NUMBER_RE check flagged this as missing on every finance chunk.
    """
    v = NarrationValidator()
    result = v.validate(
        source='Revenue reached $2.3 billion, up 47% year over year',
        narration=(
            'Revenue reached two point three billion dollars, up forty-seven percent year over year'
        ),
    )
    assert result.passed
    assert result.missing_entities == []


def test_spoken_form_quarter_passes_validation():
    """Quarter references spelled out per narration prompt must pass."""
    v = NarrationValidator()
    result = v.validate(
        source='In Q3 2024 the company reported record sales',
        narration='In the third quarter of twenty-twenty-four the company reported record sales',
    )
    assert result.passed
    assert result.missing_entities == []


def test_fails_when_proper_noun_dropped():
    """Company and person names must still be caught when missing."""
    v = NarrationValidator()
    result = v.validate(
        source='OpenAI secured a major investment from Sequoia Capital and Microsoft',
        narration='A startup secured a major investment from several investors',
    )
    assert not result.passed
    assert any(
        entity in result.missing_entities for entity in ('OpenAI', 'Sequoia Capital', 'Microsoft')
    )


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


def test_fails_when_number_completely_dropped():
    """A number absent in all spoken forms must still fail validation.

    '47%' → acceptable forms include 'forty-seven percent', '47%', etc.
    If the narration contains none of them the entity is genuinely missing.
    """
    v = NarrationValidator()
    result = v.validate(
        source='Revenue grew 47% this quarter',
        narration='Revenue grew this quarter',
    )
    assert not result.passed
    assert any('47' in e for e in result.missing_entities)


def test_build_retry_prompt_contains_missing():
    v = NarrationValidator()
    result = v.validate(source='Revenue grew 47%', narration='Revenue grew')
    prompt = v.build_retry_prompt(result, original_chunk='Revenue grew 47%')
    assert '47%' in prompt
    assert 'missing' in prompt.lower()
