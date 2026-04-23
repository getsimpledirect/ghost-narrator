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

import os

import pytest

from app.core.exceptions import SynthesisError
from app.domains.synthesis import service


def _fake_synth(text, output_path, job_id, generation_kwargs, voice_path):
    """Write the variant seed into the dummy WAV so we can assert which one won."""
    seed = int((generation_kwargs or {}).get('seed') or 0)
    with open(output_path, 'wb') as f:
        f.write(f'variant-seed-{seed}\n'.encode())
    return output_path


def _fake_scorer_factory(scores_by_seed):
    """Return a compute_composite_score replacement that reads the seed from the file.

    Accepts (and ignores) the ``skip_wer`` keyword so it works for both the
    adaptive per-variant scoring and the winner's final full-WER rescore.
    """

    def _scorer(wav_path, text, reference_f0, *, skip_wer=False):
        with open(wav_path, 'rb') as f:
            body = f.read().decode()
        seed = int(body.strip().split('-')[-1])
        return {'total': scores_by_seed[seed], 'f0': 0.0, 'wer': 0.0, 'drops': 0.0, 'flatness': 0.0}

    return _scorer


def test_best_of_1_calls_single_shot_once(tmp_path, monkeypatch):
    calls: list[tuple] = []

    def _counting_synth(text, output_path, job_id, generation_kwargs, voice_path):
        calls.append((text, output_path))
        return _fake_synth(text, output_path, job_id, generation_kwargs, voice_path)

    monkeypatch.setattr(service, 'synthesize_single_shot', _counting_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(
        scorer,
        'compute_composite_score',
        lambda *_a, **_kw: {'total': 0.1, 'f0': 0.0, 'wer': 0.0, 'drops': 0.0, 'flatness': 0.0},
    )

    out = str(tmp_path / 'seg.wav')
    path, score = service.synthesize_best_of_n(
        text='hello',
        output_path=out,
        n_variants=1,
        reference_f0=None,
        job_id='j',
    )
    assert path == out
    # n_variants=1 path: one synth, one score call. No adaptive loop.
    assert len(calls) == 1
    assert score['total'] == 0.1


def test_early_exit_stops_after_variant_0_when_score_is_low(tmp_path, monkeypatch):
    """With variant 0 scoring below the early-exit threshold, no further synths run."""
    scores_by_seed = {
        0: 0.05,  # variant 0 — well below early_exit=0.08
        7919: 0.5,  # variant 1 — never generated
        15838: 0.9,  # variant 2 — never generated
    }
    call_count = {'n': 0}

    def _counting_synth(text, output_path, job_id, generation_kwargs, voice_path):
        call_count['n'] += 1
        return _fake_synth(text, output_path, job_id, generation_kwargs, voice_path)

    monkeypatch.setattr(service, 'synthesize_single_shot', _counting_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    path, score = service.synthesize_best_of_n(
        text='hi',
        output_path=out,
        n_variants=3,
        reference_f0=None,
    )
    assert path == out
    assert call_count['n'] == 1  # only variant 0 was synthesised
    assert score['total'] == 0.05


def test_good_enough_exit_stops_after_variant_1(tmp_path, monkeypatch):
    """Variant 0 misses early_exit but variant 1 brings best-so-far below good_enough."""
    scores_by_seed = {
        0: 0.30,  # variant 0 — above early_exit and good_enough
        7919: 0.10,  # variant 1 — below good_enough=0.13 → stop
        15838: 0.02,  # variant 2 — never generated
    }
    call_count = {'n': 0}

    def _counting_synth(text, output_path, job_id, generation_kwargs, voice_path):
        call_count['n'] += 1
        return _fake_synth(text, output_path, job_id, generation_kwargs, voice_path)

    monkeypatch.setattr(service, 'synthesize_single_shot', _counting_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    path, score = service.synthesize_best_of_n(
        text='hi',
        output_path=out,
        n_variants=3,
        reference_f0=None,
    )
    assert path == out
    assert call_count['n'] == 2  # stopped after variant 1
    assert score['total'] == 0.10


def test_full_n_when_all_variants_are_marginal(tmp_path, monkeypatch):
    """When every variant is above good_enough, all N are generated and the lowest wins."""
    scores_by_seed = {
        0: 0.40,
        7919: 0.25,  # above good_enough=0.13 → continue
        15838: 0.20,
    }
    call_count = {'n': 0}

    def _counting_synth(text, output_path, job_id, generation_kwargs, voice_path):
        call_count['n'] += 1
        return _fake_synth(text, output_path, job_id, generation_kwargs, voice_path)

    monkeypatch.setattr(service, 'synthesize_single_shot', _counting_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    path, score = service.synthesize_best_of_n(
        text='hi',
        output_path=out,
        n_variants=3,
        reference_f0=None,
    )
    assert path == out
    assert call_count['n'] == 3
    assert score['total'] == 0.20


def test_thresholds_respected_via_env(tmp_path, monkeypatch):
    """BEST_OF_N_EARLY_EXIT env override bumps the exit bar."""
    monkeypatch.setenv('BEST_OF_N_EARLY_EXIT', '0.25')
    scores_by_seed = {0: 0.20, 7919: 0.1, 15838: 0.05}
    call_count = {'n': 0}

    def _counting_synth(text, output_path, job_id, generation_kwargs, voice_path):
        call_count['n'] += 1
        return _fake_synth(text, output_path, job_id, generation_kwargs, voice_path)

    monkeypatch.setattr(service, 'synthesize_single_shot', _counting_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    _, score = service.synthesize_best_of_n(
        text='hi', output_path=out, n_variants=3, reference_f0=None
    )
    assert call_count['n'] == 1  # variant 0 at 0.20 is under the elevated 0.25 bar
    assert score['total'] == 0.20


def test_best_of_3_keeps_lowest_score(tmp_path, monkeypatch):
    # Seeds used: variant 0 → 42, variant 1 → 42 + 7919, variant 2 → 42 + 15838.
    scores_by_seed = {
        42: 0.8,  # variant 0 — worst
        42 + 7919: 0.2,  # variant 1 — best
        42 + 15838: 0.5,  # variant 2 — middle
    }

    monkeypatch.setattr(service, 'synthesize_single_shot', _fake_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    path, score = service.synthesize_best_of_n(
        text='hi',
        output_path=out,
        n_variants=3,
        reference_f0=None,
        job_id='j',
        generation_kwargs={'seed': 42},
    )

    assert path == out
    assert score['total'] == 0.2
    # Kept file should be variant 1 (seed 42 + 7919).
    with open(out, 'rb') as f:
        body = f.read().decode().strip()
    assert body == f'variant-seed-{42 + 7919}'


def test_best_of_n_removes_rejected_variants(tmp_path, monkeypatch):
    scores_by_seed = {0: 0.5, 7919: 0.1, 15838: 0.9}
    monkeypatch.setattr(service, 'synthesize_single_shot', _fake_synth)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    service.synthesize_best_of_n(
        text='hi',
        output_path=out,
        n_variants=3,
        reference_f0=None,
    )

    # Only the kept file should exist in the output directory.
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith('seg_v')]
    assert leftovers == []


def test_best_of_n_all_variants_fail_raises(tmp_path, monkeypatch):
    def _always_fail(*_a, **_kw):
        raise SynthesisError('boom')

    monkeypatch.setattr(service, 'synthesize_single_shot', _always_fail)
    from app.domains.synthesis import scorer

    monkeypatch.setattr(
        scorer,
        'compute_composite_score',
        lambda *_a, **_kw: {'total': 0.1, 'f0': 0.0, 'wer': 0.0, 'drops': 0.0, 'flatness': 0.0},
    )

    out = str(tmp_path / 'seg.wav')
    with pytest.raises(SynthesisError):
        service.synthesize_best_of_n(text='hi', output_path=out, n_variants=3, reference_f0=None)


def test_best_of_n_falls_back_when_some_variants_fail(tmp_path, monkeypatch):
    from app.domains.synthesis import scorer

    call_count = {'n': 0}

    def _flaky(text, output_path, job_id, generation_kwargs, voice_path):
        call_count['n'] += 1
        if call_count['n'] == 2:
            raise SynthesisError('transient failure')
        return _fake_synth(text, output_path, job_id, generation_kwargs, voice_path)

    scores_by_seed = {0: 0.3, 15838: 0.1}
    monkeypatch.setattr(service, 'synthesize_single_shot', _flaky)
    monkeypatch.setattr(scorer, 'compute_composite_score', _fake_scorer_factory(scores_by_seed))

    out = str(tmp_path / 'seg.wav')
    path, score = service.synthesize_best_of_n(
        text='hi', output_path=out, n_variants=3, reference_f0=None
    )
    assert path == out
    # Variant 0 survived with 0.3; variant 1 failed; variant 2 survived with 0.1 and wins.
    assert score['total'] == 0.1
