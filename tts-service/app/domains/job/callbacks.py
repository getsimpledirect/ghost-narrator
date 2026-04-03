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
Job callback notifications for webhook events.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def notify_job_started(job_id: str, callback_url: Optional[str] = None):
    """Notify that job has started."""
    if callback_url:
        # TODO: Implement webhook notification
        pass


async def notify_job_completed(job_id: str, audio_url: str, callback_url: Optional[str] = None):
    """Notify that job completed successfully."""
    if callback_url:
        # TODO: Implement webhook with audio URL
        pass


async def notify_job_failed(job_id: str, error: str, callback_url: Optional[str] = None):
    """Notify that job failed."""
    if callback_url:
        # TODO: Implement webhook with error
        pass
