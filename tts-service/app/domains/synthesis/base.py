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
Synthesis domain base classes.

Provides abstract interfaces for TTS synthesis pipelines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple


class SynthesisPipeline(ABC):
    """Abstract base class for TTS synthesis pipelines."""

    @abstractmethod
    async def synthesize(self, text: str) -> Tuple[any, int]:
        """
        Synthesize audio from text.

        Args:
            text: Text to synthesize

        Returns:
            Tuple of (audio_data, sample_rate)
        """
        pass

    @abstractmethod
    async def synthesize_chunks(self, chunks: List[str]) -> List[any]:
        """
        Synthesize multiple text chunks.

        Args:
            chunks: List of text chunks

        Returns:
            List of audio arrays
        """
        pass
