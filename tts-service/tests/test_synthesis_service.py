import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.exceptions import SynthesisError
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
        chunks, total_words = prepare_text_for_synthesis(text, max_chunk_words=200)
        assert len(chunks) >= 1
        assert total_words > 0
        assert isinstance(chunks, list)
        assert all(isinstance(c, str) for c in chunks)

    def test_cleanup_chunk_files(self, tmp_path):
        job_dir = tmp_path / 'test-cleanup'
        job_dir.mkdir()
        chunk_file = job_dir / 'chunk_0000.wav'
        chunk_file.write_bytes(b'fake-audio-data')
        assert chunk_file.exists()
        cleanup_chunk_files(job_dir, 'test-job-3')
        assert not job_dir.exists()
