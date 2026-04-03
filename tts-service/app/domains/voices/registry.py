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

"""
Voice management domain.

Manages voice profiles under a voices/ directory.
"""

from __future__ import annotations
import re
from pathlib import Path


class VoiceRegistry:
    """Manages voice profiles under a voices/ directory.

    Structure:
        voices/default/reference.wav   → profile "default" (preferred)
        voices/reference.wav           → profile "default" (backward-compat fallback)
        voices/profiles/<name>.wav     → named profile "<name>"
    """

    _VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

    def __init__(self, voices_dir: Path) -> None:
        self._voices_dir = voices_dir
        self._profiles_dir = voices_dir / 'profiles'
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    def _validate_name(self, name: str) -> None:
        """Validate that a profile name is alphanumeric (hyphens/underscores allowed)."""
        if not self._VALID_NAME_PATTERN.match(name):
            raise ValueError('Profile name must be alphanumeric (hyphens/underscores allowed)')

    def resolve(self, profile_name: str) -> Path:
        """Return Path to the WAV file for profile_name. Raises FileNotFoundError if not found."""
        if profile_name == 'default':
            new_path = self._voices_dir / 'default' / 'reference.wav'
            if new_path.exists():
                return new_path
            fallback = self._voices_dir / 'reference.wav'
            if fallback.exists():
                return fallback
            raise FileNotFoundError(
                'Voice profile not found: default. '
                'Place a reference.wav in voices/default/ or voices/'
            )
        self._validate_name(profile_name)
        path = self._profiles_dir / f'{profile_name}.wav'
        if not path.exists():
            raise FileNotFoundError(f'Voice profile not found: {profile_name}. Expected at {path}')
        return path

    def profile_path(self, name: str) -> Path:
        """Return the path where a named profile WAV should be stored."""
        self._validate_name(name)
        return self._profiles_dir / f'{name}.wav'

    def list_profiles(self) -> list[str]:
        """Return list of available profile names including 'default'."""
        profiles = ['default']
        if self._profiles_dir.exists():
            profiles += [p.stem for p in self._profiles_dir.glob('*.wav')]
        return profiles

    def delete_profile(self, profile_name: str) -> None:
        """Delete a named profile. Raises ValueError if trying to delete 'default'."""
        if profile_name == 'default':
            raise ValueError('Cannot delete the default voice profile')
        self._validate_name(profile_name)
        path = self.resolve(profile_name)
        path.unlink(missing_ok=True)
