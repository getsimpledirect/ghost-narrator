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
    assert config.llm_model == 'qwen3.5:2b'
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
    assert config.llm_model == 'qwen3.5:4b'
    assert config.synthesis_workers == 1


def test_low_vram_when_9gb():
    """9 GB is below the 12 GB MID_VRAM threshold."""
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


def test_low_vram_when_11gb():
    """11 GB is below the 12 GB MID_VRAM threshold — new boundary after raising from 10 GB."""
    with (
        patch.dict(os.environ, {'HARDWARE_TIER': ''}),
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 11 * 1024**3  # 11 GB
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
    assert (
        config.llm_model == 'Qwen/Qwen3.5-4B'
    )  # vLLM fp8; hardware-probe.sh writes HuggingFace ID
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
    assert config.llm_model == 'Qwen/Qwen3.5-9B'  # vLLM fp8; HuggingFace ID
    assert config.llm_num_ctx == 65536
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
    assert config.llm_model == 'qwen3.5:2b'  # unchanged — empty env var falls back


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
    assert config.llm_model == 'qwen3.5:2b'


def test_selected_llm_num_ctx_env_overrides_tier_config():
    """SELECTED_LLM_NUM_CTX overrides llm_num_ctx from _TIER_CONFIGS."""
    with patch.dict(
        os.environ,
        {'HARDWARE_TIER': 'high_vram', 'SELECTED_LLM_NUM_CTX': '32768'},
    ):
        config = get_engine_config()
    assert config.llm_num_ctx == 32768


def test_empty_selected_llm_num_ctx_falls_back_to_tier_config():
    """Empty SELECTED_LLM_NUM_CTX must not override — falls back to _TIER_CONFIGS default."""
    with patch.dict(os.environ, {'HARDWARE_TIER': 'high_vram', 'SELECTED_LLM_NUM_CTX': ''}):
        config = get_engine_config()
    assert config.llm_num_ctx == 65536


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


def test_high_vram_llm_model_is_qwen3_5_9b():
    """HIGH_VRAM must use Qwen/Qwen3.5-9B (HuggingFace ID) with 64K context window.

    vLLM fp8: Qwen3.5-9B ≈ 9.7 GB weights + fp8 KV ≈ 4.8 GB at 65K tokens = 14.5 GB;
    leaves ~3.5 GB headroom on 24 GB L4 alongside TTS (~5.1 GB runtime).
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.HIGH_VRAM]
    assert cfg.llm_model == 'Qwen/Qwen3.5-9B', f'Expected Qwen/Qwen3.5-9B, got {cfg.llm_model!r}'
    assert cfg.llm_num_ctx == 65536, f'Expected 65536, got {cfg.llm_num_ctx}'


def test_high_vram_tts_max_new_tokens_is_7000():
    """HIGH_VRAM max_new_tokens must be 7000 for dynamic 400-word segments.

    Empirical noise ceiling for Qwen3-TTS-1.7B is 400 words (reduced from 650
    to limit per-segment autoregressive drift on long generation runs).
    400 words × 5.54 codec tokens/word = 2,216 tokens; 7000 = 3.16× headroom.
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.HIGH_VRAM]
    assert cfg.tts_max_new_tokens == 7000, f'Expected 7000, got {cfg.tts_max_new_tokens}'


def test_mid_vram_tts_max_new_tokens_is_7000():
    """MID_VRAM max_new_tokens must be 7000 (3.16× headroom for 400-word segments).

    MID_VRAM uses the same 1.7B model with the same 400-word noise ceiling.
    7000 gives comfortable headroom at 400 words (2,216 tokens).
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.MID_VRAM]
    assert cfg.tts_max_new_tokens == 7000, f'Expected 7000, got {cfg.tts_max_new_tokens}'


def test_low_vram_tts_max_new_tokens_is_4500():
    """LOW_VRAM max_new_tokens stays 4500 — 0.6B model has 300-word noise ceiling.

    300 words × 5.54 = 1,662 codec tokens; 4500 = 2.7× headroom. No change needed.
    """
    from app.core.hardware import _TIER_CONFIGS

    cfg = _TIER_CONFIGS[HardwareTier.LOW_VRAM]
    assert cfg.tts_max_new_tokens == 4500, f'Expected 4500, got {cfg.tts_max_new_tokens}'


# ── get_studio_segment_words tests ─────────────────────────────────────────────


def test_get_studio_segment_words_returns_tier_default():
    """Without an env override, returns the active tier's studio_segment_words."""
    import app.core.hardware as _hw

    env = {k: v for k, v in os.environ.items() if k != 'SINGLE_SHOT_SEGMENT_WORDS'}
    with patch.dict(os.environ, env, clear=True):
        assert _hw.get_studio_segment_words() == _hw.ENGINE_CONFIG.studio_segment_words


def test_get_studio_segment_words_env_override():
    """SINGLE_SHOT_SEGMENT_WORDS env var wins over the tier default."""
    import app.core.hardware as _hw

    with patch.dict(os.environ, {'SINGLE_SHOT_SEGMENT_WORDS': '75'}):
        assert _hw.get_studio_segment_words() == 75


def test_get_studio_segment_words_env_clamped():
    """Env values outside [30, 300] are clamped — short destroys prosody, long defeats design."""
    import app.core.hardware as _hw

    with patch.dict(os.environ, {'SINGLE_SHOT_SEGMENT_WORDS': '500'}):
        assert _hw.get_studio_segment_words() == 300
    with patch.dict(os.environ, {'SINGLE_SHOT_SEGMENT_WORDS': '10'}):
        assert _hw.get_studio_segment_words() == 30


def test_get_studio_segment_words_ignores_non_digit_env():
    """Non-digit env values fall back to the tier default rather than raising."""
    import app.core.hardware as _hw

    with patch.dict(os.environ, {'SINGLE_SHOT_SEGMENT_WORDS': 'auto'}):
        assert _hw.get_studio_segment_words() == _hw.ENGINE_CONFIG.studio_segment_words


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
