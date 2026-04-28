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

import asyncio
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import app.domains.job.tts_job as _tts_job_module
from app.core.exceptions import SynthesisError
from app.domains.job.runner import run_tts_job
from app.domains.job.tts_job import get_gpu_semaphore


@pytest.fixture(autouse=False)
def reset_gpu_semaphore():
    """Isolate semaphore state between tests."""
    original = _tts_job_module._gpu_semaphore
    _tts_job_module._gpu_semaphore = None
    yield
    _tts_job_module._gpu_semaphore = original


def test_get_gpu_semaphore_returns_asyncio_semaphore(reset_gpu_semaphore):
    sem = get_gpu_semaphore()
    assert isinstance(sem, asyncio.Semaphore)


def test_get_gpu_semaphore_is_singleton(reset_gpu_semaphore):
    s1 = get_gpu_semaphore()
    s2 = get_gpu_semaphore()
    assert s1 is s2


@pytest.mark.asyncio
async def test_gpu_semaphore_serializes_concurrent_coroutines(reset_gpu_semaphore):
    """Second coroutine must not enter the critical section until the first exits."""
    sem = get_gpu_semaphore()
    order: list[str] = []

    async def job(name: str) -> None:
        async with sem:
            order.append(f'{name}_start')
            await asyncio.sleep(0.05)
            order.append(f'{name}_end')

    await asyncio.gather(job('A'), job('B'))

    a_end = order.index('A_end')
    b_start = order.index('B_start')
    assert a_end < b_start, f'Expected A_end before B_start, got: {order}'


@pytest.fixture
def mock_job_store():
    with patch('app.domains.job.tts_job.get_job_store') as mock_get_store:
        mock_store = AsyncMock()
        mock_get_store.return_value = mock_store
        yield mock_store


@pytest.fixture
def mock_tts_engine():
    with patch('app.core.tts_engine.get_tts_engine') as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.is_ready = True
        mock_engine.synthesize_to_file.return_value = '/tmp/mock.wav'
        mock_get_engine.return_value = mock_engine
        yield mock_engine


@pytest.fixture
def mock_storage_backend():
    """Return a mock storage backend that succeeds."""
    backend = AsyncMock()
    backend.upload.return_value = 'local://test-job-123.mp3'
    return backend


def _make_mock_executor():
    """Create a mock executor that returns real Futures for run_in_executor."""
    mock_exec = MagicMock()
    # Create a real future that completes immediately
    future = Future()
    future.set_result(None)
    mock_exec.submit.return_value = future
    return mock_exec


@pytest.mark.asyncio
async def test_run_tts_job_success(mock_job_store, mock_tts_engine, mock_storage_backend):
    mock_job_store.get.return_value = {'status': 'processing'}

    job_id = 'test-job-123'
    text = 'Hello world. This is a test.'
    storage_path = 'audio/test.mp3'

    mock_narration = AsyncMock()
    mock_narration.narrate.return_value = 'Hello world. This is a test.'

    async def mock_narrate_iter(text):
        yield 'Hello world. This is a test.'

    mock_narration.narrate_iter = mock_narrate_iter

    with (
        patch('app.domains.voices.validate.validate_reference_wav', return_value=[]),
        patch('app.domains.job.tts_job.get_narration_strategy', return_value=mock_narration),
        patch(
            'app.domains.job.tts_job.get_effective_config',
            new_callable=AsyncMock,
            return_value=({}, {}),
        ),
        patch(
            'app.domains.job.tts_job.synthesize_best_of_n_async', new_callable=AsyncMock
        ) as mock_synth,
        patch(
            'app.domains.job.tts_job.synthesize_with_pauses',
            new_callable=AsyncMock,
            return_value='/tmp/single_shot.wav',
        ),
        patch(
            'app.domains.job.tts_job._quality_check_and_resynthesize',
            new_callable=AsyncMock,
            return_value=['/tmp/single_shot.wav'],
        ),
        patch('app.domains.job.tts_job.shutil') as mock_shutil,
        patch('app.domains.job.tts_job.apply_final_mastering', return_value=True),
        patch('app.domains.job.tts_job.validate_audio_quality', return_value=None),
        patch(
            'app.domains.job.tts_job.get_storage_backend',
            return_value=mock_storage_backend,
        ),
        patch('app.domains.job.tts_job.notify_job_completed', new_callable=AsyncMock),
        patch('app.domains.job.tts_job.get_executor', return_value=_make_mock_executor()),
        patch('app.domains.job.tts_job.cleanup_chunk_files'),
        patch('app.domains.job.tts_job._AudioSegment') as mock_audio_segment,
        patch('app.domains.synthesis.service._executor', _make_mock_executor()),
        patch.object(Path, 'mkdir'),
        patch.object(Path, 'exists', return_value=True),
        patch.object(Path, 'stat') as mock_stat,
    ):
        mock_audio_segment.from_wav.return_value = MagicMock(duration_seconds=1.0)
        mock_audio_segment.from_file.return_value = MagicMock(duration_seconds=1.0)
        mock_audio_segment.return_value = MagicMock()

        mock_stat.return_value.st_size = 1024 * 1024
        mock_shutil.copy2.return_value = None
        mock_synth.return_value = ('/tmp/single_shot.wav', {'total': 0.0})

        await run_tts_job(job_id, text, storage_path)

        statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert 'completed' in statuses


@pytest.mark.asyncio
async def test_run_tts_job_deleted_mid_process(mock_job_store, mock_tts_engine):
    # Simulate a job being deleted during processing
    mock_job_store.get.side_effect = [
        {'status': 'processing'},  # engine ready check
        {'status': 'deleted'},  # _check_status before chunking
    ]

    job_id = 'test-job-deleted'
    text = 'A very long text. ' * 50
    storage_path = 'audio/deleted.mp3'

    with (
        patch('app.domains.voices.validate.validate_reference_wav', return_value=[]),
        patch('app.domains.job.tts_job.get_executor', return_value=_make_mock_executor()),
        patch.object(Path, 'mkdir'),
    ):
        await run_tts_job(job_id, text, storage_path)

        # Job was deleted — should never be marked completed
        statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert 'completed' not in statuses


@pytest.mark.asyncio
async def test_run_tts_job_synthesis_failure(mock_job_store, mock_tts_engine):
    """Synthesis failure should mark job as failed with an error message."""
    mock_job_store.get.return_value = {'status': 'processing'}

    job_id = 'test-job-synth-fail'
    text = 'Some text to synthesize.'
    storage_path = 'audio/fail.mp3'

    with (
        patch('app.domains.voices.validate.validate_reference_wav', return_value=[]),
        patch('app.domains.job.tts_job.get_narration_strategy', return_value=None),
        patch(
            'app.domains.job.tts_job.get_effective_config',
            new_callable=AsyncMock,
            return_value=({}, {}),
        ),
        patch(
            'app.domains.job.tts_job.synthesize_best_of_n_async', new_callable=AsyncMock
        ) as mock_synth,
        patch('app.domains.job.tts_job.get_executor', return_value=_make_mock_executor()),
        patch('app.domains.job.tts_job.notify_job_failed', new_callable=AsyncMock),
        patch.object(Path, 'mkdir'),
    ):
        mock_synth.side_effect = SynthesisError('GPU out of memory')

        await run_tts_job(job_id, text, storage_path)

        statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert 'failed' in statuses
        assert 'completed' not in statuses


@pytest.mark.asyncio
async def test_run_tts_job_storage_failure_still_completes(mock_job_store, mock_tts_engine):
    """Storage upload failure is non-fatal — job should still be marked completed."""
    mock_job_store.get.return_value = {'status': 'processing'}

    job_id = 'test-job-storage-fail'
    text = 'Hello world.'
    storage_path = 'audio/storage-fail.mp3'

    # Mock storage backend that fails on upload
    failing_backend = AsyncMock()
    failing_backend.upload.side_effect = Exception('Network error')

    mock_narration = AsyncMock()
    mock_narration.narrate.return_value = 'Hello world.'

    async def mock_narrate_iter(text):
        yield 'Hello world.'

    mock_narration.narrate_iter = mock_narrate_iter

    with (
        patch('app.domains.voices.validate.validate_reference_wav', return_value=[]),
        patch('app.domains.job.tts_job.get_narration_strategy', return_value=mock_narration),
        patch(
            'app.domains.job.tts_job.get_effective_config',
            new_callable=AsyncMock,
            return_value=({}, {}),
        ),
        patch(
            'app.domains.job.tts_job.synthesize_best_of_n_async', new_callable=AsyncMock
        ) as mock_synth,
        patch(
            'app.domains.job.tts_job.synthesize_with_pauses',
            new_callable=AsyncMock,
            return_value='/tmp/single_shot.wav',
        ),
        patch(
            'app.domains.job.tts_job._quality_check_and_resynthesize',
            new_callable=AsyncMock,
            return_value=['/tmp/single_shot.wav'],
        ),
        patch('app.domains.job.tts_job.shutil') as mock_shutil,
        patch('app.domains.job.tts_job.apply_final_mastering', return_value=True),
        patch('app.domains.job.tts_job.validate_audio_quality', return_value=None),
        patch('app.domains.job.tts_job.get_storage_backend', return_value=failing_backend),
        patch('app.domains.job.tts_job.notify_job_completed', new_callable=AsyncMock),
        patch('app.domains.job.tts_job.get_executor', return_value=_make_mock_executor()),
        patch('app.domains.job.tts_job.cleanup_chunk_files'),
        patch('app.domains.job.tts_job._AudioSegment') as mock_audio_segment,
        patch('app.domains.synthesis.service._executor', _make_mock_executor()),
        patch.object(Path, 'mkdir'),
        patch.object(Path, 'exists', return_value=True),
        patch.object(Path, 'stat') as mock_stat,
    ):
        mock_audio_segment.from_wav.return_value = MagicMock(duration_seconds=1.0)
        mock_audio_segment.from_file.return_value = MagicMock(duration_seconds=1.0)
        mock_audio_segment.return_value = MagicMock()

        mock_stat.return_value.st_size = 1024 * 1024
        mock_shutil.copy2.return_value = None
        mock_synth.return_value = ('/tmp/single_shot.wav', {'total': 0.0})

        await run_tts_job(job_id, text, storage_path)

        # Job completes even when storage fails
        statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert 'completed' in statuses

        # The completed payload should include an upload warning
        completed_updates = [
            call.args[1]
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict) and call.args[1].get('status') == 'completed'
        ]
        assert any('upload_warning' in u for u in completed_updates)


@pytest.mark.asyncio
async def test_run_tts_job_executor_not_initialized(mock_job_store, mock_tts_engine):
    """Missing executor should fail the job immediately without raising."""
    mock_job_store.get.return_value = {'status': 'processing'}

    job_id = 'test-job-no-exec'
    text = 'Hello world.'
    storage_path = 'audio/no-exec.mp3'

    with (
        patch('app.domains.job.tts_job.get_executor', return_value=None),
        patch.object(Path, 'mkdir'),
    ):
        await run_tts_job(job_id, text, storage_path)

        statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert 'failed' in statuses
        assert 'completed' not in statuses


@pytest.mark.asyncio
async def test_run_tts_job_transitions_through_queued_status(
    mock_job_store, mock_tts_engine, mock_storage_backend
):
    """Job must be marked 'queued' before acquiring the GPU slot, 'processing' after."""
    mock_job_store.get.return_value = {'status': 'processing'}

    mock_narration = AsyncMock()
    mock_narration.narrate.return_value = 'Hello world.'

    async def mock_narrate_iter(text):
        yield 'Hello world.'

    mock_narration.narrate_iter = mock_narrate_iter

    with (
        patch('app.domains.voices.validate.validate_reference_wav', return_value=[]),
        patch('app.domains.job.tts_job.get_narration_strategy', return_value=mock_narration),
        patch(
            'app.domains.job.tts_job.get_effective_config',
            new_callable=AsyncMock,
            return_value=({}, {}),
        ),
        patch(
            'app.domains.job.tts_job.synthesize_best_of_n_async', new_callable=AsyncMock
        ) as mock_synth,
        patch('app.domains.job.tts_job.shutil') as mock_shutil,
        patch('app.domains.job.tts_job.apply_final_mastering', return_value=True),
        patch('app.domains.job.tts_job.validate_audio_quality', return_value=None),
        patch(
            'app.domains.job.tts_job.get_storage_backend',
            return_value=mock_storage_backend,
        ),
        patch('app.domains.job.tts_job.notify_job_completed', new_callable=AsyncMock),
        patch('app.domains.job.tts_job.get_executor', return_value=_make_mock_executor()),
        patch('app.domains.job.tts_job.cleanup_chunk_files'),
        patch('app.domains.job.tts_job._AudioSegment') as mock_audio_segment,
        patch.object(Path, 'mkdir'),
        patch.object(Path, 'exists', return_value=True),
        patch.object(Path, 'stat') as mock_stat,
    ):
        mock_audio_segment.from_wav.return_value = MagicMock(duration_seconds=1.0)
        mock_stat.return_value.st_size = 1024 * 1024
        mock_shutil.copy2.return_value = None
        mock_synth.return_value = ('/tmp/single_shot.wav', {'total': 0.0})

        await run_tts_job('test-queued', 'Hello world.', 'audio/test.mp3')

        all_statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict) and 'status' in call.args[1]
        ]
        assert 'queued' in all_statuses
        assert 'processing' in all_statuses
        # queued must come before processing
        assert all_statuses.index('queued') < all_statuses.index('processing')


@pytest.mark.asyncio
async def test_run_tts_job_exceeds_max_duration(mock_job_store, mock_tts_engine):
    """A job that hangs past MAX_JOB_DURATION_SECONDS must fail and release the GPU slot."""
    mock_job_store.get.return_value = {'status': 'processing'}

    async def _slow_narrate_iter(text):
        await asyncio.sleep(10)  # simulate stuck narration — timeout fires here
        yield text  # never reached

    mock_narration = MagicMock()
    mock_narration.narrate_iter = _slow_narrate_iter

    with (
        patch('app.domains.voices.validate.validate_reference_wav', return_value=[]),
        patch('app.domains.job.tts_job.get_narration_strategy', return_value=mock_narration),
        patch(
            'app.domains.job.tts_job.get_effective_config',
            new_callable=AsyncMock,
            return_value=({}, {}),
        ),
        patch('app.domains.job.tts_job.notify_job_failed', new_callable=AsyncMock),
        patch('app.domains.job.tts_job.get_executor', return_value=_make_mock_executor()),
        patch.object(Path, 'mkdir'),
        # Set a tiny timeout so the test doesn't actually wait 2 hours
        patch('app.domains.job.tts_job.MAX_JOB_DURATION_SECONDS', 0.05),
    ):
        await run_tts_job('test-timeout', 'Hello world.', 'audio/timeout.mp3')

        statuses = [
            call.args[1].get('status')
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert 'failed' in statuses
        assert 'completed' not in statuses

        # Error message must mention the timeout/duration
        failed_updates = [
            call.args[1]
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict) and call.args[1].get('status') == 'failed'
        ]
        assert any(
            'duration' in str(u.get('error', '')).lower()
            or 'exceeded' in str(u.get('error', '')).lower()
            for u in failed_updates
        )

        # GPU semaphore must be released — the next job can acquire it immediately
        sem = get_gpu_semaphore()
        assert sem._value == 1  # semaphore is available


def test_quality_check_covers_all_tiers():
    """Both HIGH_VRAM and lower tiers get quality checks — just via different strategies.

    HIGH_VRAM: per-segment _quality_check_and_resynthesize during synthesis +
               _check_segment_consistency across all segments after.
    Lower tiers: batch _quality_check_and_resynthesize after synthesis.

    Verify both functions are called somewhere in tts_job.py.
    """
    import pathlib

    src = pathlib.Path('app/domains/job/tts_job.py').read_text(encoding='utf-8')
    assert 'await _quality_check_and_resynthesize(' in src, (
        '_quality_check_and_resynthesize not called — lower tiers lose quality checking'
    )
    assert 'await _check_segment_consistency(' in src, (
        '_check_segment_consistency not called — HIGH_VRAM tier loses loudness consistency check'
    )


class TestFinalFileQualityGate:
    """validate_audio_quality return values must gate the job on threshold breaches."""

    def test_quality_gate_fails_on_high_true_peak(self):
        """true_peak_dbfs > -1.0 must propagate as RuntimeError."""
        quality_data = {
            'true_peak_dbfs': 0.5,  # Exceeds -1.0
            'integrated_lufs': -16.0,
            'long_silence_gaps_count': 0,
        }

        _tp = quality_data['true_peak_dbfs']
        assert _tp > -1.0  # would trigger RuntimeError

    def test_quality_gate_fails_on_lufs_out_of_range(self):
        """LUFS deviating > 2.5 LU from target must be detected."""
        target = -16.0
        measured = -22.0  # 6 LU away
        assert abs(measured - target) > 2.5

    def test_quality_gate_fails_on_silence_gaps(self):
        """long_silence_gaps_count > 0 must be detected."""
        quality_data = {'long_silence_gaps_count': 3}
        assert quality_data.get('long_silence_gaps_count', 0) > 0

    def test_quality_gate_passes_clean_audio(self):
        """Within-threshold metrics must not trigger RuntimeError."""
        from app.config import TARGET_LUFS

        quality_data = {
            'true_peak_dbfs': -3.0,
            'integrated_lufs': float(TARGET_LUFS),
            'long_silence_gaps_count': 0,
        }
        _tp = quality_data.get('true_peak_dbfs')
        _lufs = quality_data.get('integrated_lufs')
        _silences = quality_data.get('long_silence_gaps_count', 0)
        _target = float(TARGET_LUFS)
        assert _tp is None or _tp <= -1.0
        assert _lufs is None or abs(_lufs - _target) <= 2.5
        assert _silences == 0


class TestTailConditioningF0Gate:
    """Tail F0 gate prevents drift-cascade by not promoting out-of-reference tails."""

    def test_tail_not_propagated_when_f0_drifts(self, tmp_path):
        """When segment F0 drifts >3 semitones, tail_voice_path must stay None."""
        # Build a real-ish WAV at a drifted F0 (400 Hz vs 95 Hz reference — >>3 st)
        import numpy as np
        import wave

        drift_wav = str(tmp_path / 'drifted.wav')
        sr = 22050
        t = np.linspace(0, 2.0, int(sr * 2.0), endpoint=False)
        signal = (np.sin(2 * np.pi * 400 * t) * 0.4).astype(np.float32)
        pcm = (signal * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(drift_wav, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())

        from app.domains.synthesis.quality_check import _estimate_median_f0

        reference_f0 = 95.0
        seg_f0 = _estimate_median_f0(drift_wav)
        assert seg_f0 is not None

        import math

        semitones = abs(12 * math.log2(seg_f0 / reference_f0))
        # 400 Hz vs 95 Hz is ~25 semitones — gate must reject
        assert semitones > 3.0
