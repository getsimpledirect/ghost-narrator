# tts-service/tests/test_hardware.py
from unittest.mock import patch, MagicMock
import pytest
import os

from app.core.hardware import HardwareTier, EngineConfig, get_engine_config


def test_cpu_only_when_cuda_unavailable():
    with (
        patch('app.core.hardware.torch') as mock_torch,
        patch('app.core.hardware._TORCH_AVAILABLE', True),
    ):
        mock_torch.cuda.is_available.return_value = False
        config = get_engine_config()
    assert config.tier == HardwareTier.CPU_ONLY
    assert config.tts_device == "cpu"
    assert config.tts_model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert config.synthesis_workers == 4
    assert config.llm_model == 'qwen3:1.7b'
    assert config.mp3_bitrate == '192k'
    assert config.sample_rate == 44100
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
    assert config.tts_model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert config.llm_model == "qwen3:4b"
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
    assert config.tts_model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


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
    assert config.tts_model == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert config.llm_model == "qwen3:8b"
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
    assert config.tts_model == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert config.llm_model == "qwen3:14b"
    assert config.synthesis_workers == 2
    assert config.mp3_bitrate == '256k'
    assert config.sample_rate == 48000
    assert config.target_lufs == -14.0


def test_selected_tts_model_env_overrides_tier_config():
    """SELECTED_TTS_MODEL from tier.env (hardware-probe.sh) takes priority over _TIER_CONFIGS."""
    with patch.dict(os.environ, {'HARDWARE_TIER': 'cpu_only', 'SELECTED_TTS_MODEL': 'org/custom-tts-model', 'SELECTED_LLM_MODEL': ''}):
        config = get_engine_config()
    assert config.tts_model == 'org/custom-tts-model'
    assert config.llm_model == 'qwen3:1.7b'  # unchanged — empty env var falls back


def test_selected_llm_model_env_overrides_tier_config():
    """SELECTED_LLM_MODEL from tier.env (hardware-probe.sh) takes priority over _TIER_CONFIGS."""
    with patch.dict(os.environ, {'HARDWARE_TIER': 'cpu_only', 'SELECTED_LLM_MODEL': 'custom-llm:7b', 'SELECTED_TTS_MODEL': ''}):
        config = get_engine_config()
    assert config.llm_model == 'custom-llm:7b'
    assert config.tts_model == 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'  # unchanged


def test_empty_selected_model_env_falls_back_to_tier_config():
    """Empty SELECTED_* env vars must not override — falls back to _TIER_CONFIGS defaults."""
    with patch.dict(os.environ, {'HARDWARE_TIER': 'cpu_only', 'SELECTED_TTS_MODEL': '', 'SELECTED_LLM_MODEL': ''}):
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
