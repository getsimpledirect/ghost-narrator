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

"""Quality check and resynthesis logic for TTS audio chunks."""

from __future__ import annotations

import functools
import logging
import math
import os as _os
import re as _re
import threading

import numpy as np
import soundfile as _sf
from pydub import AudioSegment as _AudioSegment


logger = logging.getLogger(__name__)

# Maximum audio duration for WER checking. Transcribing a full single-shot
# 10-minute file on CPU would take ~60s — impractical. WER is most valuable
# for per-segment checking where each segment is 30–120 seconds.
_MAX_WER_DURATION_MS: int = 120_000

# Sentinel object used to mark the ASR pipeline as unavailable after a
# failed load attempt, so subsequent calls skip the load without retrying.
_ASR_UNAVAILABLE = object()
_asr_pipeline = None
_asr_lock = threading.Lock()


def _compute_onset_rate(wav_path: str) -> float:
    """Energy-based onset rate in onsets/second. Uses only numpy + soundfile."""
    try:
        data, sr = _sf.read(wav_path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if len(data) == 0:
            return 0.0
        frame_size = max(1, int(sr * 0.025))
        hop_size = max(1, int(sr * 0.010))
        rms_frames = np.array(
            [
                np.sqrt(np.mean(data[i : i + frame_size] ** 2))
                for i in range(0, len(data) - frame_size + 1, hop_size)
            ]
        )
        if len(rms_frames) < 2:
            return 0.0
        # Count frames where RMS rises > 3 dB (×1.41) above previous frame and > noise floor
        onsets = np.sum((rms_frames[1:] > rms_frames[:-1] * 1.41) & (rms_frames[1:] > 0.01))
        duration_s = len(data) / sr
        return float(onsets) / duration_s if duration_s > 0 else 0.0
    except Exception:
        return 0.0


def _compute_spectral_flatness(wav_path: str) -> float:
    """Spectral flatness (Wiener entropy) of voiced frames. 0 = tonal, 1 = noise."""
    try:
        data, sr = _sf.read(wav_path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if len(data) == 0:
            return 0.0
        n_fft = 512
        hop = 128
        eps = 1e-10
        # Manual short-time magnitude spectrum (no extra deps)
        window = np.hanning(n_fft)
        frames = [
            data[i : i + n_fft] * window
            for i in range(0, len(data) - n_fft, hop)
            if len(data[i : i + n_fft]) == n_fft
        ]
        if not frames:
            return 0.0
        spectra = np.abs(np.fft.rfft(np.stack(frames), axis=1))  # (T, F)
        # Keep only voiced frames (mean magnitude above noise floor)
        voiced_mask = spectra.mean(axis=1) > 0.005
        if not voiced_mask.any():
            return 0.0
        voiced = spectra[voiced_mask]  # (T_voiced, F)
        geo_mean = np.exp(np.mean(np.log(voiced + eps), axis=1))
        arith_mean = np.mean(voiced, axis=1)
        flatness_per_frame = geo_mean / (arith_mean + eps)
        return float(flatness_per_frame.mean())
    except Exception:
        return 0.0


def _estimate_median_f0(wav_path: str) -> float | None:
    """Autocorrelation-based F0 estimate (Hz). Returns None if no voiced frames.

    Uses a stricter voicing threshold (0.5) and octave-down correction to
    avoid the classic autocorrelation octave error: when even harmonics are
    strong, the peak at 2× the true period can exceed the true-period peak,
    causing the estimator to return F0/2 (or 2×F0 depending on direction).
    Returns None if fewer than 10 voiced frames are found.
    """
    try:
        data, sr = _sf.read(wav_path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        frame_size = int(sr * 0.030)
        hop_size = frame_size // 2
        min_lag = max(1, int(sr / 500))
        max_lag = min(len(data) // 2, int(sr / 60))
        if max_lag <= min_lag:
            return None
        f0_values: list[float] = []
        for start in range(0, len(data) - frame_size, hop_size):
            frame = data[start : start + frame_size].astype(np.float64)
            if np.sqrt(np.mean(frame**2)) < 0.01:
                continue  # skip silence
            frame -= frame.mean()
            corr = np.correlate(frame, frame, mode='full')
            corr = corr[len(corr) // 2 :]
            if max_lag >= len(corr):
                continue
            peak_lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
            # Stricter voicing threshold — 0.3 passes noise frames; 0.5 does not.
            if corr[0] <= 0 or corr[peak_lag] <= 0.5 * corr[0]:
                continue
            # Octave-down correction: if the half-period has comparable autocorrelation
            # (within 10%), the true fundamental is an octave lower.
            half_lag = peak_lag // 2
            if half_lag >= min_lag and corr[half_lag] >= 0.9 * corr[peak_lag]:
                peak_lag = half_lag
            f0_values.append(sr / peak_lag)
        # Require at least 10 voiced frames for a reliable median.
        if len(f0_values) < 10:
            return None
        return float(np.median(f0_values))
    except Exception:
        return None


# Seconds of audio per word at 150 WPM (conversational narration)
_SECONDS_PER_WORD: float = 0.40

# F0 deviation threshold in semitones — beyond this, the chunk is a different "speaker".
# Tightened to 2.5 (was 3.0): F0 is a hard identity signal, not a soft metric.
_MAX_F0_DEVIATION_SEMITONES: float = 2.5

# When true, acoustic gate logs failures but always returns pass — shadow/calibration mode.
# Default is 'false' (enforce); set DRY_RUN_GATE=true to observe without rejecting.
_DRY_RUN_GATE: bool = _os.environ.get('DRY_RUN_GATE', 'false').lower() in ('1', 'true', 'yes')


def _gate_result(passed: bool, reason: str) -> tuple[bool, str]:
    """Return gate result, honouring _DRY_RUN_GATE shadow mode."""
    if not passed and _DRY_RUN_GATE:
        logger.info('Acoustic gate [DRY RUN]: would reject — %s', reason)
        return True, ''
    return passed, reason


def _chunk_passes_acoustic_gate(
    wav_path: str,
    word_count: int,
    reference_f0: float | None,
    onset_rate_ceiling: float = 8.0,
    flatness_ceiling: float = 0.18,
) -> tuple[bool, str]:
    """Return (True, '') or (False, reason) based on WAV hallucination signature.

    Hard checks — any one fails the chunk immediately:
    1. Unreadable WAV
    2. Duration < 100ms (empty output)
    3. Duration > 1.6 × expected (hallucination runaway)
    4. Duration < 0.4 × expected (severe truncation)
    5. F0 drift > _MAX_F0_DEVIATION_SEMITONES (speaker identity violation)

    Soft checks — BOTH must trip simultaneously to fail the chunk:
    6. Onset rate > onset_rate_ceiling (8.0 /s)
    7. Spectral flatness > flatness_ceiling (0.18)

    Regional checks — run after soft checks (only reached by chunks that passed 1-7):
    8. Windowed F0 gate: >5% of 3 s windows show >6 st drift from reference_f0.
       Catches garbled regions that whole-chunk median smoothing misses (e.g. 20 s of
       garble inside a 180 s chunk shifts the overall median by ~11%, well under the
       2.5 st hard threshold, but produces >11% bad windows). Skipped when
       reference_f0 is None.
    9. Mid-phrase drop: drops of 0.6-2.0 s where RMS falls below 10% of the
       rolling 2 s local median. Catches mid-sentence amplitude collapses caused by
       Qwen3-TTS emitting near-silent tokens before recovering coherence. Threshold
       scales with chunk duration: max(3, duration_s / 20) — a fixed count rejects
       natural pause density in long chunks.

    When only one soft check trips, an INFO line is logged and the chunk passes.
    Healthy Qwen3-TTS output routinely exceeds one threshold in isolation; the
    co-occurrence pattern is the hallucination signature.

    When _DRY_RUN_GATE is true, all failures are logged but (True, '') is returned.
    """
    # ── Hard checks ──────────────────────────────────────────────────────────

    try:
        from pydub import AudioSegment as _AS

        seg = _AS.from_wav(wav_path)
        duration_ms = len(seg)
    except Exception:
        return _gate_result(False, 'unreadable wav')

    if duration_ms < 100:
        logger.info('Acoustic gate: empty audio (%dms)', duration_ms)
        return _gate_result(False, f'empty audio ({duration_ms}ms)')

    if word_count > 0:
        expected_ms = word_count * _SECONDS_PER_WORD * 1000
        if duration_ms > expected_ms * 1.6:
            logger.info(
                'Acoustic gate: hallucination runaway — %dms for %d words (expected ~%dms)',
                duration_ms,
                word_count,
                int(expected_ms),
            )
            return _gate_result(
                False,
                f'hallucination runaway: {duration_ms}ms for {word_count}w'
                f' (expected ~{int(expected_ms)}ms)',
            )
        if duration_ms < expected_ms * 0.4:
            logger.info(
                'Acoustic gate: severe truncation — %dms for %d words (expected ~%dms)',
                duration_ms,
                word_count,
                int(expected_ms),
            )
            return _gate_result(
                False,
                f'severe truncation: {duration_ms}ms for {word_count}w'
                f' (expected ~{int(expected_ms)}ms)',
            )

    # F0 drift is a hard fail on its own — unambiguous speaker identity violation.
    f0_drift_st: float | None = None
    if reference_f0 is not None and reference_f0 > 0:
        chunk_f0 = _estimate_median_f0(wav_path)
        if chunk_f0 is not None and chunk_f0 > 0:
            f0_drift_st = abs(12 * math.log2(chunk_f0 / reference_f0))
            if f0_drift_st > _MAX_F0_DEVIATION_SEMITONES:
                reason = (
                    f'speaker drift {f0_drift_st:.1f}st'
                    f' (ref={reference_f0:.0f}Hz chunk={chunk_f0:.0f}Hz)'
                )
                logger.info('Acoustic gate: %s', reason)
                return _gate_result(False, reason)

    # ── Soft checks (both must co-occur) ─────────────────────────────────────

    rate = _compute_onset_rate(wav_path)
    flatness = _compute_spectral_flatness(wav_path)

    onset_tripped = rate > onset_rate_ceiling
    flatness_tripped = flatness > flatness_ceiling

    if onset_tripped and flatness_tripped:
        parts = [f'flatness={flatness:.3f}', f'onset_rate={rate:.1f}/s']
        if f0_drift_st is not None:
            parts.append(f'f0_drift={f0_drift_st:.1f}st')
        reason = 'soft-check pattern: ' + ', '.join(parts)
        logger.info('Acoustic gate: %s', reason)
        return _gate_result(False, reason)

    # Single soft-check trip — log for visibility, but pass the chunk.
    if onset_tripped:
        logger.info(
            'Acoustic gate: onset_rate=%.1f/s above %.1f/s — single flag, passing',
            rate,
            onset_rate_ceiling,
        )
    elif flatness_tripped:
        logger.info(
            'Acoustic gate: flatness=%.3f above %.3f — single flag, passing',
            flatness,
            flatness_ceiling,
        )

    # ── Windowed sub-chunk analysis + mid-phrase drop detection ──────────────
    # Runs after the cheaper whole-chunk soft checks. Both analyses share a
    # single soundfile.read() to avoid redundant I/O.
    try:
        data, sr_local = _sf.read(wav_path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)

        # Fix 1: Windowed F0 gate — a 20s garbled region inside a 180s chunk
        # only shifts the overall median by ~11% (well under the 2.5st hard
        # threshold), but produces >5% bad 3s windows — caught here.
        if reference_f0 and reference_f0 > 0:
            window_s = 3.0
            window_samples = int(sr_local * window_s)
            hop_samples = window_samples // 2  # 50% overlap

            n_bad_windows = 0
            total_windows = 0
            for start_idx in range(0, len(data) - window_samples, hop_samples):
                win = data[start_idx : start_idx + window_samples]
                total_windows += 1

                win_rms = float(np.sqrt(np.mean(win**2)))
                if win_rms < 0.02:  # < −34 dBFS — natural pause, skip
                    continue

                frame_size = int(sr_local * 0.030)
                hop_size = frame_size // 2
                min_lag = max(1, int(sr_local / 500))
                max_lag = min(len(win) // 2, int(sr_local / 60))
                win_f0s: list[float] = []
                for frame_start in range(0, len(win) - frame_size, hop_size):
                    frame = win[frame_start : frame_start + frame_size].astype(np.float64)
                    if np.sqrt(np.mean(frame**2)) < 0.01:
                        continue
                    frame -= frame.mean()
                    corr = np.correlate(frame, frame, mode='full')
                    corr = corr[len(corr) // 2 :]
                    if max_lag >= len(corr):
                        continue
                    peak_lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
                    if corr[0] > 0 and corr[peak_lag] > 0.5 * corr[0]:
                        half_lag = peak_lag // 2
                        if half_lag >= min_lag and corr[half_lag] >= 0.9 * corr[peak_lag]:
                            peak_lag = half_lag
                        win_f0s.append(sr_local / peak_lag)

                if len(win_f0s) < 3:
                    continue  # unvoiced window (consonant clusters) — skip

                win_f0_med = float(np.median(win_f0s))
                win_semitones = abs(12 * math.log2(win_f0_med / reference_f0))
                if win_semitones > 6.0:
                    n_bad_windows += 1
                    logger.info(
                        'Windowed gate: bad window at t=%.1fs, F0=%.0fHz (%.1fst from ref)',
                        start_idx / sr_local,
                        win_f0_med,
                        win_semitones,
                    )

            # >5% bad windows (min 3) indicates a genuine regional failure.
            # Qwen3-TTS has occasional 1-2s F0 excursions on phoneme transitions
            # that are inaudible — the 5% floor tolerates those.
            if total_windows > 0 and n_bad_windows > max(2, total_windows * 0.05):
                reason = (
                    f'windowed gate: {n_bad_windows}/{total_windows} 3s windows '
                    f'showed F0 drift >6 semitones'
                )
                logger.info('Acoustic gate: %s', reason)
                return _gate_result(False, reason)

        # Fix 2: Mid-phrase drop detection — catches 0.6-2.0s amplitude
        # collapses mid-sentence when Qwen3-TTS briefly loses coherence and
        # emits near-silent tokens before recovering. The 0.6s lower bound
        # excludes natural punctuation pauses (typically 200-500ms in
        # Qwen3-TTS output), which the previous 0.3s bound over-counted.
        hop_s_rms = 0.05
        rms_frame_len = int(sr_local * hop_s_rms)
        if rms_frame_len > 0:
            rms_per_frame = np.array(
                [
                    float(np.sqrt(np.mean(data[i : i + rms_frame_len] ** 2)))
                    for i in range(0, len(data) - rms_frame_len, rms_frame_len)
                ]
            )

            window_2s_frames = max(1, int(2.0 / hop_s_rms))
            n_drops = 0
            in_drop = False
            drop_start: int = 0
            for i in range(window_2s_frames, len(rms_per_frame)):
                local = rms_per_frame[max(0, i - window_2s_frames) : i + 1]
                local_med = float(np.median(local))
                if local_med < 0.01:
                    in_drop = False
                    continue
                if rms_per_frame[i] < local_med * 0.1:
                    if not in_drop:
                        drop_start = i
                        in_drop = True
                else:
                    if in_drop:
                        drop_dur_s = (i - drop_start) * hop_s_rms
                        if 0.6 <= drop_dur_s <= 2.0:
                            n_drops += 1
                        in_drop = False

            # Threshold scales with chunk duration: ~1 drop per 20s of audio
            # tolerated, with a floor of 3. A fixed count rejects natural pause
            # density in long chunks — a 160s narration segment contains 20+
            # sentence boundaries, some of which register as drops even with
            # the tightened 0.6s minimum.
            duration_s = len(data) / sr_local
            max_tolerated_drops = max(3, int(duration_s / 20))
            if n_drops > max_tolerated_drops:
                reason = (
                    f'mid-phrase drops: {n_drops} drops of 0.6-2.0s found '
                    f'(tolerance {max_tolerated_drops} over {duration_s:.0f}s)'
                )
                logger.info('Acoustic gate: %s', reason)
                return _gate_result(False, reason)

    except Exception as exc:
        logger.debug('Windowed gate check failed (non-fatal): %s', exc)

    return True, ''


def _count_mid_phrase_drops(wav_path: str) -> int:
    """Count 0.6-2.0 s amplitude drops below 10% of rolling 2 s RMS median.

    Exposed for the composite scorer. The acoustic gate inlines the same
    signal with a duration-scaled threshold (max(3, duration_s / 20)) to
    decide pass/fail; the scorer wants the raw count for a continuous score.
    """
    try:
        data, sr_local = _sf.read(wav_path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        hop_s_rms = 0.05
        rms_frame_len = int(sr_local * hop_s_rms)
        if rms_frame_len <= 0 or len(data) < rms_frame_len * 4:
            return 0
        rms_per_frame = np.array(
            [
                float(np.sqrt(np.mean(data[i : i + rms_frame_len] ** 2)))
                for i in range(0, len(data) - rms_frame_len, rms_frame_len)
            ]
        )
        window_2s_frames = max(1, int(2.0 / hop_s_rms))
        n_drops = 0
        in_drop = False
        drop_start: int = 0
        for i in range(window_2s_frames, len(rms_per_frame)):
            local = rms_per_frame[max(0, i - window_2s_frames) : i + 1]
            local_med = float(np.median(local))
            if local_med < 0.01:
                in_drop = False
                continue
            if rms_per_frame[i] < local_med * 0.1:
                if not in_drop:
                    drop_start = i
                    in_drop = True
            else:
                if in_drop:
                    drop_dur_s = (i - drop_start) * hop_s_rms
                    if 0.6 <= drop_dur_s <= 2.0:
                        n_drops += 1
                    in_drop = False
        return n_drops
    except Exception:
        return 0


def _get_asr_pipeline():
    """Lazy-load the Whisper base ASR pipeline (CPU, int8 quantized).

    Uses the transformers library already present in the dependency tree.
    Returns the pipeline on success, or None if the model cannot be loaded
    (no internet, no cached weights, missing dependency). Once marked
    unavailable, subsequent calls return None immediately without retrying.
    """
    global _asr_pipeline
    if _asr_pipeline is not None:
        return None if _asr_pipeline is _ASR_UNAVAILABLE else _asr_pipeline
    with _asr_lock:
        if _asr_pipeline is not None:
            return None if _asr_pipeline is _ASR_UNAVAILABLE else _asr_pipeline
        try:
            from transformers import pipeline as _hf_pipeline

            _asr_pipeline = _hf_pipeline(
                'automatic-speech-recognition',
                model='openai/whisper-base',
                device='cpu',
                generate_kwargs={'language': 'english'},
            )
            logger.info('Whisper base ASR pipeline loaded for WER quality checking')
        except Exception as exc:
            logger.warning('WER quality checking disabled — Whisper ASR unavailable: %s', exc)
            _asr_pipeline = _ASR_UNAVAILABLE
    return None if _asr_pipeline is _ASR_UNAVAILABLE else _asr_pipeline


def _transcribe_wav(wav_path: str) -> str | None:
    """Transcribe a WAV file with Whisper. Returns None if ASR unavailable."""
    pipe = _get_asr_pipeline()
    if pipe is None:
        return None
    try:
        result = pipe(wav_path)
        return result.get('text', '') if isinstance(result, dict) else None
    except Exception as exc:
        logger.debug('ASR transcription failed for %s: %s', wav_path, exc)
        return None


def _normalize_for_wer(text: str) -> str:
    """Lowercase and strip punctuation for fair WER comparison."""
    text = text.lower()
    text = _re.sub(r'[^\w\s]', ' ', text)
    text = _re.sub(r'\s+', ' ', text)
    return text.strip()


def _word_error_rate(reference: str, hypothesis: str) -> float:
    """Compute WER via word-level Levenshtein edit distance."""
    ref = _normalize_for_wer(reference).split()
    hyp = _normalize_for_wer(hypothesis).split()
    if not ref:
        return 0.0
    n, m = len(ref), len(hyp)
    # Single-row DP — O(n*m) time, O(m) space
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        new_dp = [i] + [0] * m
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                new_dp[j] = dp[j - 1]
            else:
                new_dp[j] = 1 + min(dp[j], new_dp[j - 1], dp[j - 1])
        dp = new_dp
    return dp[m] / n


async def _quality_check_and_resynthesize(
    chunk_wav_paths: list[str],
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
    generation_kwargs: dict | None = None,
    wer_threshold: float = 0.10,
    reference_f0: float | None = None,
) -> list[str]:
    """Check each chunk through the acoustic gate; re-synthesize failures.

    Runs checks in order:
    1. _chunk_passes_acoustic_gate — duration ratio, onset rate, spectral flatness, F0
    2. WER via Whisper (optional, skipped if unavailable or chunk > 2 min)

    Raises ChunkExhaustedError if any chunk fails all 3 retry strategies.
    """
    checked_paths = list(chunk_wav_paths)
    resynth_count = 0

    for i, wav_path in enumerate(chunk_wav_paths):
        word_count = len(chunk_texts[i].split()) if i < len(chunk_texts) else 0
        if word_count == 0:
            logger.debug('[%s] Chunk %d: word_count=0, duration-ratio gate disabled', job_id, i)
        try:
            passed_gate, gate_reason = _chunk_passes_acoustic_gate(
                wav_path, word_count, reference_f0
            )
        except Exception as exc:
            logger.debug('[%s] Acoustic gate check for chunk %d skipped: %s', job_id, i, exc)
            passed_gate, gate_reason = True, ''  # fail-open on gate error

        if not passed_gate:
            logger.warning(
                '[%s] Chunk %d failed acoustic gate (%s) — re-synthesizing', job_id, i, gate_reason
            )
            checked_paths[i] = await _resynthesize_with_strategies(
                i,
                wav_path,
                chunk_texts,
                job_id,
                engine,
                loop,
                executor,
                generation_kwargs,
                reference_f0,
            )
            resynth_count += 1
            continue

        # WER check (optional, only for short segments)
        try:
            from pydub import AudioSegment as _AS

            duration_ms = len(_AS.from_wav(wav_path))
            if (
                i < len(chunk_texts)
                and chunk_texts[i].strip()
                and duration_ms <= _MAX_WER_DURATION_MS
            ):
                transcript = await loop.run_in_executor(executor, _transcribe_wav, wav_path)
                if transcript is not None:
                    wer = _word_error_rate(chunk_texts[i], transcript)
                    if wer > wer_threshold:
                        logger.warning(
                            '[%s] Chunk %d WER=%.0f%% (threshold %.0f%%) — re-synthesizing',
                            job_id,
                            i,
                            wer * 100,
                            wer_threshold * 100,
                        )
                        checked_paths[i] = await _resynthesize_with_strategies(
                            i,
                            wav_path,
                            chunk_texts,
                            job_id,
                            engine,
                            loop,
                            executor,
                            generation_kwargs,
                            reference_f0,
                        )
                        resynth_count += 1
        except Exception as exc:
            logger.debug('[%s] WER check for chunk %d skipped: %s', job_id, i, exc)

    if resynth_count > 0:
        logger.info('[%s] Re-synthesized %d/%d chunks', job_id, resynth_count, len(chunk_wav_paths))

    return checked_paths


async def _check_segment_consistency(
    wav_paths: list[str],
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
    generation_kwargs: dict | None = None,
    loudness_tolerance_db: float = 3.0,
    reference_f0: float | None = None,
) -> list[str]:
    """Re-synthesize segments whose loudness deviates > tolerance_db from the median.

    Catches cases where one segment was generated at a systematically different
    volume — a known sampling artifact in autoregressive TTS at segment boundaries
    that is not caught by the per-chunk silence check in _quality_check_and_resynthesize.
    A ±6 dB deviation corresponds to roughly 2× or 0.5× the perceived loudness.
    """
    if len(wav_paths) <= 1:
        return list(wav_paths)

    dbfs_values: list[float] = []
    for wav_path in wav_paths:
        try:
            seg = _AudioSegment.from_wav(wav_path)
            dbfs_values.append(seg.dBFS)
        except Exception:
            dbfs_values.append(float('nan'))

    valid = [v for v in dbfs_values if not math.isnan(v)]
    if len(valid) < 2:
        return list(wav_paths)

    sorted_valid = sorted(valid)
    n = len(sorted_valid)
    median_dbfs = (
        sorted_valid[n // 2]
        if n % 2 == 1
        else (sorted_valid[n // 2 - 1] + sorted_valid[n // 2]) / 2
    )

    checked = list(wav_paths)
    resynth_count = 0
    for i, (wav_path, dbfs) in enumerate(zip(wav_paths, dbfs_values)):
        if math.isnan(dbfs):
            continue
        deviation = abs(dbfs - median_dbfs)
        if deviation > loudness_tolerance_db:
            logger.warning(
                '[%s] Segment %d loudness %.1f dBFS deviates %.1f dB from median %.1f — re-synthesizing',
                job_id,
                i,
                dbfs,
                deviation,
                median_dbfs,
            )
            checked[i] = await _resynthesize_with_strategies(
                i,
                wav_path,
                chunk_texts,
                job_id,
                engine,
                loop,
                executor,
                generation_kwargs,
                reference_f0=reference_f0,
            )
            resynth_count += 1

    if resynth_count > 0:
        logger.info(
            '[%s] Re-synthesized %d/%d segments for loudness consistency',
            job_id,
            resynth_count,
            len(wav_paths),
        )

    return checked


async def _resynthesize_with_strategies(
    chunk_idx: int,
    wav_path: str,
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
    generation_kwargs: dict | None = None,
    reference_f0: float | None = None,
) -> str:
    """Re-synthesize with up to 4 increasingly conservative strategies.

    Strategy 0: raise repetition_penalty to 1.2 (targets repetition-loop hallucinations)
    Strategy 1: split at nearest any-punctuation boundary around midpoint (both directions)
    Strategy 2: quarter the text (halve again), same bidirectional split
    Strategy 3: aggressive text sanitization (strip parentheticals/digits/ALL-CAPS), then retry

    Raises ChunkExhaustedError if all strategies fail the acoustic gate.
    """
    from app.core.exceptions import ChunkExhaustedError, SynthesisError

    if chunk_idx >= len(chunk_texts):
        return wav_path

    original_text = chunk_texts[chunk_idx]

    def _split_at_punctuation(text: str, target_fraction: float = 0.5) -> list[str]:
        """Split text near target_fraction, searching outward for any punctuation."""
        words = text.split()
        if len(words) <= 5:
            return [text]
        pivot = int(len(words) * target_fraction)
        _ANY_PUNCT_ENDS = ('.', ',', ';', ':', '!', '?', '—', '–')
        split_at = pivot  # fallback: split at pivot
        # Search outward from pivot: alternating left/right
        found = False
        for offset in range(0, max(pivot, len(words) - pivot) + 1):
            for candidate in (pivot - offset, pivot + offset):
                if 0 < candidate < len(words):
                    if words[candidate - 1].endswith(_ANY_PUNCT_ENDS):
                        split_at = candidate
                        found = True
                        break
            if found:
                break
        part_a = ' '.join(words[:split_at])
        part_b = ' '.join(words[split_at:])
        return [p for p in (part_a, part_b) if p.strip()]

    def _sanitize_text(text: str) -> str:
        """Strip parentheticals, numeric quantities, and ALL-CAPS tokens."""
        import re as _re

        # Remove content in parentheses
        text = _re.sub(r'\([^)]{0,200}\)', '', text)
        # Replace numeric sequences with spoken approximation
        text = _re.sub(r'\b\d[\d,./]*\b', 'some', text)
        # Remove ALL-CAPS words (often acronyms/jargon that trip the model)
        text = _re.sub(r'\b[A-Z]{3,}\b', '', text)
        # Collapse whitespace
        text = _re.sub(r'\s+', ' ', text).strip()
        return text or text  # return empty-safe

    async def _try_halves(halves: list[str], attempt: int, retry_kw: dict) -> str | None:
        """Synthesize halves, combine, return combined wav_path if gate passes. None otherwise."""
        import tempfile
        from pydub import AudioSegment as _AS

        with tempfile.TemporaryDirectory() as td:
            sub_paths = []
            all_ok = True
            for si, half_text in enumerate(halves):
                sp = f'{td}/half_{si}.wav'
                synth_fn = _make_synth_fn(engine, retry_kw, job_id)
                await loop.run_in_executor(executor, synth_fn, half_text, sp)
                if not _chunk_passes_acoustic_gate(sp, len(half_text.split()), reference_f0)[0]:
                    all_ok = False
                    break
                sub_paths.append(sp)
            if all_ok and len(sub_paths) >= 1:
                combined = _AS.from_wav(sub_paths[0])
                for sp in sub_paths[1:]:
                    combined = combined + _AS.from_wav(sp)
                combined.export(wav_path, format='wav')
                total_wc = sum(len(h.split()) for h in halves)
                if _chunk_passes_acoustic_gate(wav_path, total_wc, reference_f0)[0]:
                    logger.info(
                        '[%s] Chunk %d passed on split strategy %d', job_id, chunk_idx, attempt
                    )
                    return wav_path
        return None

    original_seed = (generation_kwargs or {}).get('seed', 0)

    # Strategy 0: repetition_penalty=1.2 — most conservative change
    retry_kw0 = dict(generation_kwargs or {})
    retry_kw0['repetition_penalty'] = 1.2
    retry_kw0['seed'] = original_seed  # attempt 0: keep seed, only sampling param changes
    try:
        synth_fn = _make_synth_fn(engine, retry_kw0, job_id)
        await loop.run_in_executor(executor, synth_fn, original_text, wav_path)
        if _chunk_passes_acoustic_gate(wav_path, len(original_text.split()), reference_f0)[0]:
            logger.info(
                '[%s] Chunk %d passed on strategy 0 (repetition_penalty)', job_id, chunk_idx
            )
            return wav_path
    except (SynthesisError, RuntimeError, OSError) as exc:
        logger.warning('[%s] Strategy 0 for chunk %d raised: %s', job_id, chunk_idx, exc)

    # Strategy 1: split at midpoint (any punctuation, bidirectional search)
    halves = _split_at_punctuation(original_text, target_fraction=0.5)
    if len(halves) > 1:
        retry_kw1 = dict(generation_kwargs or {})
        retry_kw1['seed'] = (original_seed + 7919) % (2**31)
        try:
            result = await _try_halves(halves, attempt=1, retry_kw=retry_kw1)
            if result is not None:
                return result
        except (SynthesisError, RuntimeError, OSError) as exc:
            logger.warning('[%s] Strategy 1 for chunk %d raised: %s', job_id, chunk_idx, exc)

    # Strategy 2: quarter split (halve each half)
    quarter_texts: list[str] = []
    for half in _split_at_punctuation(original_text, target_fraction=0.5) or [original_text]:
        quarter_texts.extend(_split_at_punctuation(half, target_fraction=0.5))
    quarter_texts = [q for q in quarter_texts if q.strip()]
    if len(quarter_texts) > 1:
        retry_kw2 = dict(generation_kwargs or {})
        retry_kw2['seed'] = (original_seed + 15838) % (2**31)
        try:
            result = await _try_halves(quarter_texts, attempt=2, retry_kw=retry_kw2)
            if result is not None:
                return result
        except (SynthesisError, RuntimeError, OSError) as exc:
            logger.warning('[%s] Strategy 2 for chunk %d raised: %s', job_id, chunk_idx, exc)

    # Strategy 3: aggressive text sanitization
    sanitized = _sanitize_text(original_text)
    if sanitized.strip():
        retry_kw3 = dict(generation_kwargs or {})
        retry_kw3['seed'] = (original_seed + 23757) % (2**31)
        try:
            synth_fn = _make_synth_fn(engine, retry_kw3, job_id)
            await loop.run_in_executor(executor, synth_fn, sanitized, wav_path)
            if _chunk_passes_acoustic_gate(wav_path, len(sanitized.split()), reference_f0)[0]:
                logger.info(
                    '[%s] Chunk %d passed on strategy 3 (sanitized text)', job_id, chunk_idx
                )
                return wav_path
        except (SynthesisError, RuntimeError, OSError) as exc:
            logger.warning('[%s] Strategy 3 for chunk %d raised: %s', job_id, chunk_idx, exc)

    raise ChunkExhaustedError(
        f'Chunk {chunk_idx} failed all 4 synthesis strategies',
        chunk_idx=chunk_idx,
    )


def _make_synth_fn(engine, kwargs: dict, job_id: str = ''):
    """Return a callable that calls engine.synthesize_to_file with given kwargs."""
    return functools.partial(engine.synthesize_to_file, job_id=job_id, generation_kwargs=kwargs)
