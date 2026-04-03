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
from typing import Optional
from datetime import datetime


class JobState(str, Enum):
    """Job state enumeration."""

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
