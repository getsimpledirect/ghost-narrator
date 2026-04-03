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
Job runner for TTS job orchestration.

This module provides the main entry point for executing TTS jobs,
orchestrating the complete pipeline from narration through synthesis,
concatenation, mastering, and storage.
"""

# The actual job implementation is in app/domains/job/tts_job.py
# This module provides the main entry point for backward compatibility

from app.domains.job.tts_job import run_tts_job as _run_tts_job

__all__ = ['run_tts_job']


async def run_tts_job(
    job_id: str,
    text: str,
    gcs_object_path: str,
    site_slug: str = 'site',
) -> None:
    """
    Execute the complete TTS pipeline.

    This is a delegation wrapper that forwards to the underlying
    implementation in app.domains.job.tts_job.

    Args:
        job_id: Unique identifier for tracking and file storage.
        text: The raw article text content to be narrated and synthesized.
        gcs_object_path: The target destination path in the GCS bucket.
        site_slug: Site identifier for storage path organization.

    Raises:
        JobDeletedError: If the job is removed by a user during processing.
        RuntimeError: For fatal pipeline initialization or processing failures.
    """
    await _run_tts_job(job_id, text, gcs_object_path, site_slug)
