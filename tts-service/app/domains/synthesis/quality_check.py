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
    """Autocorrelation-based F0 estimate (Hz). Returns None if no voiced frames."""
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
            if corr[0] > 0 and corr[peak_lag] > 0.3 * corr[0]:
                f0_values.append(sr / peak_lag)
        if not f0_values:
            return None
        return float(np.median(f0_values))
    except Exception:
        return None


# Seconds of audio per word at 150 WPM (conversational narration)
_SECONDS_PER_WORD: float = 0.40

# F0 deviation threshold in semitones — beyond this, the chunk is a different "speaker"
_MAX_F0_DEVIATION_SEMITONES: float = 3.0


def _chunk_passes_acoustic_gate(
    wav_path: str,
    word_count: int,
    reference_f0: float | None,
    onset_rate_ceiling: float = 6.5,
    flatness_ceiling: float = 0.025,
) -> bool:
    """Return False if the WAV exhibits any hallucination signature.

    Checks (any failure → False):
    1. Duration < 100ms → empty output
    2. Duration > 1.6 × expected_from_word_count → hallucinating (ran too long)
    3. Duration < 0.4 × expected_from_word_count → truncated (ran too short)
    4. Onset rate > onset_rate_ceiling → rapid garble
    5. Spectral flatness of voiced frames > flatness_ceiling → noisy garble
    6. |F0_median − reference_f0| > 3 semitones → speaker drift (only if reference given)
    """
    try:
        from pydub import AudioSegment as _AS

        seg = _AS.from_wav(wav_path)
        duration_ms = len(seg)
    except Exception:
        return False  # Unreadable → treat as failed

    # 1. Empty audio
    if duration_ms < 100:
        logger.debug('Acoustic gate: empty audio (%dms)', duration_ms)
        return False

    # 2 & 3. Duration ratio
    if word_count > 0:
        expected_ms = word_count * _SECONDS_PER_WORD * 1000
        if duration_ms > expected_ms * 1.6:
            logger.debug(
                'Acoustic gate: hallucination — %dms audio for %d words (expected ~%dms)',
                duration_ms,
                word_count,
                int(expected_ms),
            )
            return False
        if duration_ms < expected_ms * 0.4:
            logger.debug(
                'Acoustic gate: truncation — %dms audio for %d words (expected ~%dms)',
                duration_ms,
                word_count,
                int(expected_ms),
            )
            return False

    # 4. Onset rate
    rate = _compute_onset_rate(wav_path)
    if rate > onset_rate_ceiling:
        logger.debug('Acoustic gate: onset rate %.1f > %.1f /s', rate, onset_rate_ceiling)
        return False

    # 5. Spectral flatness
    flatness = _compute_spectral_flatness(wav_path)
    if flatness > flatness_ceiling:
        logger.debug('Acoustic gate: spectral flatness %.3f > %.3f', flatness, flatness_ceiling)
        return False

    # 6. Speaker drift
    if reference_f0 is not None and reference_f0 > 0:
        chunk_f0 = _estimate_median_f0(wav_path)
        if chunk_f0 is not None and chunk_f0 > 0:
            semitones = abs(12 * math.log2(chunk_f0 / reference_f0))
            if semitones > _MAX_F0_DEVIATION_SEMITONES:
                logger.debug(
                    'Acoustic gate: speaker drift %.1f st (ref=%.0fHz chunk=%.0fHz)',
                    semitones,
                    reference_f0,
                    chunk_f0,
                )
                return False

    return True


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
            passed_gate = _chunk_passes_acoustic_gate(wav_path, word_count, reference_f0)
        except Exception as exc:
            logger.debug('[%s] Acoustic gate check for chunk %d skipped: %s', job_id, i, exc)
            passed_gate = True  # fail-open on gate error

        if not passed_gate:
            logger.warning('[%s] Chunk %d failed acoustic gate — re-synthesizing', job_id, i)
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
                i, wav_path, chunk_texts, job_id, engine, loop, executor, generation_kwargs
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
    """Re-synthesize with up to 3 increasingly conservative strategies.

    Strategy 0: strip leading punctuation + lower temperature by 30%
    Strategy 1: temperature=0.1, top_p=0.70 (near-greedy decoding)
    Strategy 2: split chunk at mid-sentence boundary (if > 10 words)

    Raises ChunkExhaustedError if all strategies fail acoustic gate.
    """
    from app.core.exceptions import ChunkExhaustedError

    if chunk_idx >= len(chunk_texts):
        return wav_path

    original_text = chunk_texts[chunk_idx]
    word_count = len(original_text.split())

    strategies = [
        # (temperature_scale, top_p_override, split_chunk)
        (0.70, None, False),
        (0.33, 0.70, False),
        (0.33, 0.70, True),
    ]

    for attempt, (temp_scale, top_p_override, do_split) in enumerate(strategies):
        retry_kwargs = dict(generation_kwargs or {})
        orig_temp = retry_kwargs.get('temperature') or 0.3
        retry_kwargs['temperature'] = max(0.05, orig_temp * temp_scale)
        if top_p_override is not None:
            retry_kwargs['top_p'] = top_p_override

        if do_split and word_count > 10:
            # Split at nearest sentence boundary to the midpoint
            words = original_text.split()
            mid = len(words) // 2
            split_at = mid
            for k in range(mid, max(0, mid - 20), -1):
                if words[k].endswith(('.', '!', '?', ';')):
                    split_at = k + 1
                    break
            part_a = ' '.join(words[:split_at])
            part_b = ' '.join(words[split_at:])
            halves = [p for p in (part_a, part_b) if p.strip()]
        else:
            retry_text = (
                original_text.lstrip(
                    '\'""\u2018\u2019\u201c\u201d\u2026\u2013\u2014\u2022\u00b7*#'
                ).strip()
                or original_text
            )
            halves = [retry_text]

        try:
            if len(halves) == 1:
                synth_fn = _make_synth_fn(engine, retry_kwargs, job_id)
                await loop.run_in_executor(executor, synth_fn, halves[0], wav_path)
                wc = len(halves[0].split())
                if _chunk_passes_acoustic_gate(wav_path, wc, reference_f0):
                    logger.info('[%s] Chunk %d passed on strategy %d', job_id, chunk_idx, attempt)
                    return wav_path
            else:
                import tempfile
                from pydub import AudioSegment as _AS

                with tempfile.TemporaryDirectory() as td:
                    sub_paths = []
                    all_ok = True
                    for si, half_text in enumerate(halves):
                        sp = f'{td}/half_{si}.wav'
                        synth_fn = _make_synth_fn(engine, retry_kwargs, job_id)
                        await loop.run_in_executor(executor, synth_fn, half_text, sp)
                        if not _chunk_passes_acoustic_gate(
                            sp, len(half_text.split()), reference_f0
                        ):
                            all_ok = False
                            break
                        sub_paths.append(sp)
                    if all_ok and sub_paths:
                        combined = _AS.from_wav(sub_paths[0])
                        for sp in sub_paths[1:]:
                            combined = combined + _AS.from_wav(sp)
                        combined.export(wav_path, format='wav')
                        wc = sum(len(h.split()) for h in halves)
                        if _chunk_passes_acoustic_gate(wav_path, wc, reference_f0):
                            logger.info('[%s] Chunk %d passed on split strategy', job_id, chunk_idx)
                            return wav_path
        except Exception as exc:
            logger.warning(
                '[%s] Strategy %d for chunk %d raised: %s', job_id, attempt, chunk_idx, exc
            )

    raise ChunkExhaustedError(
        f'Chunk {chunk_idx} failed all {len(strategies)} synthesis strategies',
        chunk_idx=chunk_idx,
    )


def _make_synth_fn(engine, kwargs: dict, job_id: str = ''):
    """Return a callable that calls engine.synthesize_to_file with given kwargs."""
    return functools.partial(engine.synthesize_to_file, job_id=job_id, generation_kwargs=kwargs)
