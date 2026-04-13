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
from pathlib import Path
from unittest.mock import patch
from app.domains.synthesis.service import (
    synthesize_chunks_sequential,
    synthesize_chunks_parallel,
    prepare_text_for_synthesis,
    cleanup_chunk_files,
    initialize_executor,
    shutdown_executor,
)


class TestSynthesisService:
    @pytest.fixture(autouse=True)
    def setup_executor(self):
        initialize_executor(max_workers=2)
        yield
        shutdown_executor(wait=True, cancel_futures=True)

    @pytest.mark.asyncio
    async def test_synthesize_chunks_sequential(self):
        job_dir = Path('/tmp/test-job')
        with patch('app.domains.synthesis.service.synthesize_chunk') as mock_synth:
            mock_synth.side_effect = lambda text, path, job_id, generation_kwargs=None: path
            result = await synthesize_chunks_sequential(
                chunks=['Hello world.', 'Second sentence.'],
                job_dir=job_dir,
                job_id='test-job-1',
            )
            assert len(result) == 2
            assert mock_synth.call_count == 2

    @pytest.mark.asyncio
    async def test_synthesize_chunks_parallel(self):
        job_dir = Path('/tmp/test-job-parallel')
        with patch('app.domains.synthesis.service.synthesize_chunk') as mock_synth:
            mock_synth.side_effect = lambda text, path, job_id, generation_kwargs=None: path
            result = await synthesize_chunks_parallel(
                chunks=['Chunk one.', 'Chunk two.', 'Chunk three.'],
                job_dir=job_dir,
                job_id='test-job-2',
            )
            assert len(result) == 3
            assert mock_synth.call_count == 3

    def test_prepare_text_for_synthesis(self):
        text = (
            'This is the first sentence. This is the second sentence. This is the third sentence.'
        )
        chunks, total_words, pauses = prepare_text_for_synthesis(text, max_chunk_words=200)
        assert len(chunks) >= 1
        assert total_words > 0
        assert isinstance(chunks, list)
        assert all(isinstance(c, str) for c in chunks)


def test_prepare_text_returns_pause_durations():
    """prepare_text_for_synthesis must return a 3-tuple with pause durations."""
    from app.domains.synthesis.service import prepare_text_for_synthesis
    from app.utils.text import PAUSE_MS, LONG_PAUSE_MS

    text = 'First sentence here. [PAUSE] Second sentence here. [LONG_PAUSE] Third sentence.'
    chunks, total_words, pauses = prepare_text_for_synthesis(text, max_chunk_words=50)

    assert isinstance(chunks, list)
    assert isinstance(pauses, list)
    assert len(pauses) == len(chunks)
    # The last segment's last chunk gets 0 (no trailing pause)
    assert pauses[-1] == 0
    # At least one chunk should have PAUSE_MS or LONG_PAUSE_MS
    assert PAUSE_MS in pauses or LONG_PAUSE_MS in pauses


def test_prepare_text_no_markers_returns_zero_pauses():
    """Without pause markers, all pause durations are 0 (use heuristic)."""
    from app.domains.synthesis.service import prepare_text_for_synthesis

    text = 'Plain text with no pause markers whatsoever.'
    chunks, total_words, pauses = prepare_text_for_synthesis(text, max_chunk_words=50)

    assert all(p == 0 for p in pauses)

    def test_cleanup_chunk_files(self, tmp_path):
        job_dir = tmp_path / 'test-cleanup'
        job_dir.mkdir()
        chunk_file = job_dir / 'chunk_0000.wav'
        chunk_file.write_bytes(b'fake-audio-data')
        assert chunk_file.exists()
        cleanup_chunk_files(job_dir, 'test-job-3')
        assert not job_dir.exists()
