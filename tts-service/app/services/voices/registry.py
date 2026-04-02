"""VoiceRegistry — resolves named voice profiles to filesystem paths."""

from __future__ import annotations
from pathlib import Path


class VoiceRegistry:
    """Manages voice profiles under a voices/ directory.

    Structure:
        voices/default/reference.wav   → profile "default" (preferred)
        voices/reference.wav           → profile "default" (backward-compat fallback)
        voices/profiles/<name>.wav     → named profile "<name>"
    """

    def __init__(self, voices_dir: Path) -> None:
        self._voices_dir = voices_dir
        self._profiles_dir = voices_dir / "profiles"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, profile_name: str) -> Path:
        """Return Path to the WAV file for profile_name. Raises FileNotFoundError if not found."""
        if profile_name == "default":
            new_path = self._voices_dir / "default" / "reference.wav"
            if new_path.exists():
                return new_path
            fallback = self._voices_dir / "reference.wav"
            if fallback.exists():
                return fallback
            raise FileNotFoundError(
                "Voice profile not found: default. "
                "Place a reference.wav in voices/default/ or voices/"
            )
        path = self._profiles_dir / f"{profile_name}.wav"
        if not path.exists():
            raise FileNotFoundError(
                f"Voice profile not found: {profile_name}. Expected at {path}"
            )
        return path

    def profile_path(self, name: str) -> Path:
        """Return the path where a named profile WAV should be stored."""
        return self._profiles_dir / f"{name}.wav"

    def list_profiles(self) -> list[str]:
        """Return list of available profile names including 'default'."""
        profiles = ["default"]
        if self._profiles_dir.exists():
            profiles += [p.stem for p in self._profiles_dir.glob("*.wav")]
        return profiles

    def delete_profile(self, profile_name: str) -> None:
        """Delete a named profile. Raises ValueError if trying to delete 'default'."""
        if profile_name == "default":
            raise ValueError("Cannot delete the default voice profile")
        path = self.resolve(profile_name)
        path.unlink()
