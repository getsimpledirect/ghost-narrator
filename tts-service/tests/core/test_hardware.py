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

# tts-service/tests/test_hardware.py
from unittest.mock import patch, MagicMock
import os

from app.core.hardware import HardwareTier, get_engine_config


def test_cpu_only_when_cuda_unavailable():
    with (
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = False
        config = get_engine_config()
    assert config.tier == HardwareTier.CPU_ONLY
    assert config.tts_device == 'cpu'
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
    assert config.synthesis_workers == 4
    assert config.llm_model == 'qwen3:1.7b'
    assert config.mp3_bitrate == '192k'
    assert config.sample_rate == 48000  # Studio quality for all tiers
    assert config.target_lufs == -16.0


def test_low_vram_when_6gb():
    with (
        patch.dict(os.environ, {'HARDWARE_TIER': ''}, clear=True),
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 6 * 1024**3  # 6 GB
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.LOW_VRAM
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
    assert config.llm_model == 'qwen3:4b'
    assert config.synthesis_workers == 1


def test_low_vram_when_9gb():
    """9 GB is below the 10 GB MID_VRAM threshold."""
    with (
        patch.dict(os.environ, {'HARDWARE_TIER': ''}),
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 9 * 1024**3  # 9 GB
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.LOW_VRAM
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'


def test_mid_vram_when_12gb():
    with (
        patch.dict(os.environ, {'HARDWARE_TIER': ''}),
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 12 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.MID_VRAM
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
    assert config.llm_model == 'qwen3:8b'
    assert config.synthesis_workers == 1


def test_high_vram_when_24gb():
    with (
        patch.dict(os.environ, {'HARDWARE_TIER': ''}),
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 24 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.HIGH_VRAM
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
    assert config.llm_model == 'qwen3:8b'
    assert config.synthesis_workers == 1
    assert config.mp3_bitrate == '320k'
    assert config.sample_rate == 48000
    assert config.target_lufs == -14.0


def test_selected_tts_model_env_overrides_tier_config():
    """SELECTED_TTS_MODEL from tier.env (hardware-probe.sh) takes priority over _TIER_CONFIGS."""
    with patch.dict(
        os.environ,
        {
            'HARDWARE_TIER': 'cpu_only',
            'SELECTED_TTS_MODEL': 'org/custom-tts-model',
            'SELECTED_LLM_MODEL': '',
        },
    ):
        config = get_engine_config()
    assert config.tts_model == 'org/custom-tts-model'
    assert config.llm_model == 'qwen3:1.7b'  # unchanged — empty env var falls back


def test_selected_llm_model_env_overrides_tier_config():
    """SELECTED_LLM_MODEL from tier.env (hardware-probe.sh) takes priority over _TIER_CONFIGS."""
    with patch.dict(
        os.environ,
        {
            'HARDWARE_TIER': 'cpu_only',
            'SELECTED_LLM_MODEL': 'custom-llm:7b',
            'SELECTED_TTS_MODEL': '',
        },
    ):
        config = get_engine_config()
    assert config.llm_model == 'custom-llm:7b'
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'  # unchanged


def test_empty_selected_model_env_falls_back_to_tier_config():
    """Empty SELECTED_* env vars must not override — falls back to _TIER_CONFIGS defaults."""
    with patch.dict(
        os.environ,
        {'HARDWARE_TIER': 'cpu_only', 'SELECTED_TTS_MODEL': '', 'SELECTED_LLM_MODEL': ''},
    ):
        config = get_engine_config()
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
    assert config.llm_model == 'qwen3:1.7b'


def test_env_override_skips_probe():
    with patch.dict(os.environ, {'HARDWARE_TIER': 'mid_vram'}):
        config = get_engine_config()
    assert config.tier == HardwareTier.MID_VRAM  # env wins


def test_invalid_env_override_falls_back_to_probe():
    with (
        patch.dict(os.environ, {'HARDWARE_TIER': 'supercomputer'}),
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = False
        config = get_engine_config()
    assert config.tier == HardwareTier.CPU_ONLY


def test_high_vram_llm_model_is_qwen3_8b():
    """HIGH_VRAM must use qwen3:8b.

    qwen3:14b consumes ~8.5 GB VRAM — combined with the 1.7B TTS model
    (~3.5 GB) it leaves under 13 GB headroom on a 24 GB L4 for KV caches
    and activations. qwen3:8b (~4.5 GB) delivers equivalent narration
    quality for format-conversion tasks at half the VRAM cost.
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.HIGH_VRAM]
    assert cfg.llm_model == 'qwen3:8b', f'Expected qwen3:8b, got {cfg.llm_model!r}'


def test_high_vram_tts_max_new_tokens_is_4000():
    """HIGH_VRAM max_new_tokens must be 4000 for larger 300-word chunks.

    300 words at 130 WPT ≈ 1,684 codec tokens at 12 Hz.
    4000 = 2.4× headroom — sufficient for natural variation,
    prevents runaway loops while supporting larger chunk sizes.
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.HIGH_VRAM]
    assert cfg.tts_max_new_tokens == 4000, f'Expected 4000, got {cfg.tts_max_new_tokens}'


def test_mid_vram_tts_max_new_tokens_is_4500():
    """MID_VRAM max_new_tokens must be 4500 (2× headroom for 400-word segments).

    400 words ≈ 2200 codec tokens at 12 Hz; 3000 left only 35% headroom at 130 wpm,
    causing mid-word clipping. 4500 provides 2× headroom at both speaking rates.
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.MID_VRAM]
    assert cfg.tts_max_new_tokens == 4500, f'Expected 4500, got {cfg.tts_max_new_tokens}'


def test_low_vram_tts_max_new_tokens_is_4500():
    """LOW_VRAM max_new_tokens must be 4500 (2× headroom for 400-word segments).

    400 words ≈ 2200 codec tokens at 12 Hz; 3000 left only 35% headroom at 130 wpm,
    causing mid-word clipping. 4500 provides 2× headroom at both speaking rates.
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.LOW_VRAM]
    assert cfg.tts_max_new_tokens == 4500, f'Expected 4500, got {cfg.tts_max_new_tokens}'


def test_all_tiers_use_temperature_03():
    """All hardware tiers must use tts_temperature=0.3 for consistent pitch across chunks.

    Lower temperature (0.3 vs 0.4) reduces inter-chunk duration variance in the
    autoregressive model, producing more consistent speaking rate and pitch across
    segment boundaries without becoming robotic.
    """
    from app.core.hardware import _TIER_CONFIGS

    for tier, config in _TIER_CONFIGS.items():
        assert config.tts_temperature == 0.3, (
            f'{tier.value}: tts_temperature is {config.tts_temperature}, expected 0.3'
        )
        assert config.tts_temperature_sub_talker == 0.3, (
            f'{tier.value}: tts_temperature_sub_talker is {config.tts_temperature_sub_talker}, expected 0.3'
        )
