from abc import ABC, abstractmethod
from typing import List, Dict, Any


class NarrationStrategy(ABC):
    """Abstract base class for narration strategies."""

    @abstractmethod
    def narrate(self, text: str, context: Dict[str, Any]) -> str:
        """
        Transform raw article text into podcast-style narration.

        Args:
            text: Raw article text
            context: Additional context (title, excerpt, etc.)

        Returns:
            Narrated text ready for TTS
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for identification."""
        pass
