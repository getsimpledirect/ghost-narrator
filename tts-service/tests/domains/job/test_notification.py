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

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.domains.job.notification import (
    notify_job_completed,
    notify_job_failed,
    notify_n8n,
    callback_circuit_breaker,
)
from app.core.circuit_breaker import CircuitBreakerOpenError


class TestNotification:
    @pytest.mark.asyncio
    async def test_notify_job_completed_success(self):
        with patch('app.domains.job.notification.N8N_CALLBACK_URL', 'http://example.com/webhook'):
            with patch('app.domains.job.notification._httpx_client', MagicMock()):
                with patch(
                    'app.domains.job.notification.send_callback_with_circuit_breaker',
                    new_callable=AsyncMock,
                    return_value=True,
                ) as mock_send:
                    result = await notify_job_completed('job-123', gcs_uri='local://test.mp3')
                    assert result is True
                    mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_job_completed_no_callback_url(self):
        with patch('app.domains.job.notification.N8N_CALLBACK_URL', None):
            with patch('app.domains.job.notification._httpx_client', None):
                result = await notify_job_completed('job-123')
                assert result is True

    @pytest.mark.asyncio
    async def test_notify_job_failed_error(self):
        with patch('app.domains.job.notification.N8N_CALLBACK_URL', 'http://example.com/webhook'):
            with patch('app.domains.job.notification._httpx_client', MagicMock()):
                with patch(
                    'app.domains.job.notification.send_callback_with_circuit_breaker',
                    new_callable=AsyncMock,
                    side_effect=ConnectionError('Connection refused'),
                ):
                    result = await notify_job_failed('job-123', error='Something went wrong')
                    assert result is False

    @pytest.mark.asyncio
    async def test_notify_n8n_circuit_breaker_open(self):
        with patch('app.domains.job.notification.N8N_CALLBACK_URL', 'http://example.com/webhook'):
            with patch('app.domains.job.notification._httpx_client', MagicMock()):
                with patch.object(
                    callback_circuit_breaker,
                    'call',
                    side_effect=CircuitBreakerOpenError('Circuit n8n_callback is open'),
                ):
                    result = await notify_n8n('job-123', status='completed')
                    assert result is False
