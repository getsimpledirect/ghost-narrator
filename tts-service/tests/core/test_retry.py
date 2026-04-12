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

"""Tests for retry_with_backoff decorator."""

from __future__ import annotations

import asyncio

import pytest

from app.core.retry import retry_with_backoff


@pytest.mark.asyncio
async def test_retry_succeeds_on_first_attempt():
    calls = []

    @retry_with_backoff(max_attempts=3, base_delay=0)
    async def fn():
        calls.append(1)
        return 'ok'

    result = await fn()
    assert result == 'ok'
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_retries_on_transient_error():
    calls = []

    @retry_with_backoff(max_attempts=3, base_delay=0)
    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError('transient')
        return 'ok'

    result = await fn()
    assert result == 'ok'
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retry_raises_after_exhausting_attempts():
    @retry_with_backoff(max_attempts=2, base_delay=0)
    async def fn():
        raise RuntimeError('always fails')

    with pytest.raises(RuntimeError, match='always fails'):
        await fn()


@pytest.mark.asyncio
async def test_retry_exclude_does_not_retry_excluded_exception():
    """TimeoutError (or any excluded type) must not be retried — fail immediately."""
    calls = []

    @retry_with_backoff(
        max_attempts=3,
        base_delay=0,
        exceptions=(Exception,),
        exclude=(asyncio.TimeoutError,),
    )
    async def fn():
        calls.append(1)
        raise asyncio.TimeoutError('timed out')

    with pytest.raises(asyncio.TimeoutError):
        await fn()

    # Must have been called exactly once — no retries
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_exclude_still_retries_non_excluded_exception():
    """Non-excluded exceptions are still retried even when exclude is set."""
    calls = []

    @retry_with_backoff(
        max_attempts=3,
        base_delay=0,
        exceptions=(Exception,),
        exclude=(asyncio.TimeoutError,),
    )
    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError('transient')
        return 'recovered'

    result = await fn()
    assert result == 'recovered'
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retry_empty_exclude_tuple_retries_all():
    """An empty exclude tuple is a no-op — all exceptions matching `exceptions` are retried."""
    calls = []

    @retry_with_backoff(max_attempts=2, base_delay=0, exceptions=(Exception,), exclude=())
    async def fn():
        calls.append(1)
        raise ValueError('always')

    with pytest.raises(ValueError):
        await fn()

    assert len(calls) == 2
