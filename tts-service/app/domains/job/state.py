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
Job state management for TTS job processing.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Final, Optional
from datetime import datetime


# Terminal status strings actually written by the codebase. The JobState enum
# below is unused dead code (the writes use raw strings 'queued', 'processing',
# 'paused', etc., which don't match the enum's 'pending'/'running'). The
# orphan reaper and any future state-aware code should reference this set.
#
# 'deleted' is transient in normal operation: DELETE /tts/{id} sets the status
# to 'deleted' as a signal, kills any active synthesis, then calls
# job_store.delete() to remove the record entirely (tts.py:439 then :471).
# Included here because there is a small crash window where the record could
# persist with status='deleted' if the service dies between those two calls;
# treating it as terminal lets Redis TTL clean it up rather than the reaper
# fighting the user's deletion intent by marking it 'failed'.
TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {
        'completed',
        'failed',
        'cancelled',
        'deleted',
    }
)

# Maximum times a queued job will be auto-resumed by the orphan reaper before
# being marked failed. Prevents poison-pill inputs from creating a crash loop
# where the reaper keeps resuming a job that immediately crashes the worker.
MAX_RESUME_ATTEMPTS: Final[int] = 3


class JobState(str, Enum):
    """Job state enumeration.

    NOTE: Currently unused — the codebase writes raw status strings to Redis
    that don't match these enum values (production uses 'queued', 'processing',
    'paused' which aren't here). Kept for reference / potential future
    refactor. Source of truth for terminal-state identification is
    `TERMINAL_STATES` above.
    """

    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass
class JobStatus:
    """Job status information."""

    job_id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    progress: float = 0.0
    error: Optional[str] = None

    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)
