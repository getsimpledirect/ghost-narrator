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
