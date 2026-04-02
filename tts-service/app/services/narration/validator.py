"""NarrationValidator — entity-level completeness check for narration output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    passed: bool
    missing_entities: list[str] = field(default_factory=list)


class NarrationValidator:
    """Verifies that key entities from source appear in narration output.

    Extracts: numbers/percentages, quoted strings, dollar amounts.
    Fast regex matching — no LLM calls.
    """

    _NUMBER_RE = re.compile(
        r"\b\d+(?:\.\d+)?%|\$[\d,.]+|\b\d+(?:\.\d+)?\s*(?:billion|million|trillion|thousand)\b",
        re.IGNORECASE,
    )
    _QUOTE_RE = re.compile(r'"([^"]{4,})"')

    def _extract_entities(self, text: str) -> list[str]:
        entities = []
        entities.extend(self._NUMBER_RE.findall(text))
        entities.extend(self._QUOTE_RE.findall(text))
        return [e.strip() for e in entities if e.strip()]

    def validate(self, source: str, narration: str) -> ValidationResult:
        if not source.strip():
            return ValidationResult(passed=True)
        entities = self._extract_entities(source)
        narration_lower = narration.lower()
        missing = [e for e in entities if e.lower() not in narration_lower]
        return ValidationResult(passed=len(missing) == 0, missing_entities=missing)

    def build_retry_prompt(self, result: ValidationResult, original_chunk: str) -> str:
        missing_list = "\n".join(f"- {e}" for e in result.missing_entities)
        return (
            f"Your previous output was missing the following information:\n"
            f"{missing_list}\n\n"
            f"Please redo the narration conversion of the following text, "
            f"ensuring every item above is included:\n\n{original_chunk}"
        )
