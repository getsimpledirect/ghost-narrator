"""Root conftest — session-wide setup that must run before any app import.

pytest_configure() fires before test collection begins, which means before
any test module is imported. This is the correct place to patch sys.modules
for unavailable native packages (qwen_tts requires the actual TTS model
weights and is not importable in a test environment).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def pytest_configure(config: object) -> None:
    """Stub out qwen_tts so app modules can be imported without model weights."""
    if 'qwen_tts' not in sys.modules:
        _mock = types.ModuleType('qwen_tts')
        _mock.Qwen3TTSModel = MagicMock  # type: ignore[attr-defined]
        sys.modules['qwen_tts'] = _mock
