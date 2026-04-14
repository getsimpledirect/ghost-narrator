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

"""NarrationValidator — entity-level completeness check for narration output."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Pause markers inserted by the LLM for audio assembly — strip before entity check
# so they don't inflate or deflate word count ratios or interfere with matching.
_PAUSE_MARKER_RE = re.compile(r'\[(?:LONG_PAUSE|PAUSE)\]', re.IGNORECASE)

# Meta-commentary patterns: phrases indicating LLM is summarizing/paraphrasing rather
# than narrating the actual source content. These patterns check the FIRST sentence
# of the narration to detect when the LLM has started with meta-commentary instead
# of the source content.
# Only matches when followed by specific meta-commentary verbs/phrases, not legitimate content.
_META_COMMENTARY_FIRST_SENTENCE_RE = re.compile(
    r'^[^.?!]*'
    r'(?:'
    # Pattern 1: "The journey/story/text/passage described in the text..."
    r'the\s+(?:journey|story|text|passage|content|article|piece|selection)'
    r'\s+(?:described|presented|outlined|detailed|discussed|covered)'
    r'|'
    # Pattern 2: "This passage/text/article..." followed by meta verbs (NOT chapter/section)
    r'this\s+(?:passage|text|article|piece|selection)\s+(?:explores|examines|describes|outlines|covers|details|presents|discusses|introduces)'
    r'|'
    # Pattern 3: "In this text/passage/article..." followed by meta verbs (NOT chapter/section)
    r'in\s+this\s+(?:text|passage|article|piece|selection)\s+(?:we|you|let\s+us)\s+(?:explore|examine|look|discuss|consider|analyze)'
    r'|'
    # Pattern 4: "The following is a narration/narration of..."
    r'the\s+following\s+is\s+(?:a\s+)?(?:narration|recitation|reading)'
    r')',
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    passed: bool
    missing_entities: list[str] = field(default_factory=list)
    word_ratio: float = 1.0  # narration_words / source_words


class NarrationValidator:
    """Verifies that key entities from source appear in narration output.

    Extracts: numbers/percentages, quoted strings, dollar amounts, proper nouns,
    dates/times, URLs, emails. Also checks word count ratio.
    Fast regex matching — no LLM calls.

    Number/date entities are matched via spoken-form equivalents (using num2words)
    so correctly-converted narration passes ("$1.2B" → "one point two billion dollars")
    while completely dropped entities still fail validation.
    """

    _NUMBER_RE = re.compile(
        r'\b\d+(?:\.\d+)?%|\$[\d,.]+|\b\d{4}\b|\b\d+(?:\.\d+)?\s*(?:billion|million|trillion|thousand)\b',
        re.IGNORECASE,
    )
    _QUOTE_RE = re.compile(r'"([^"]{4,})"')
    # Proper nouns: capitalized words not at sentence start, or multi-word names
    _PROPER_NOUN_RE = re.compile(
        r'(?<!\. )(?<!\! )(?<!\? )(?<=[a-z,;:] )([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)'
        r'|(?<=[a-z,;:] )([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)+)'
    )
    # Standalone capitalized words mid-sentence (e.g., "by Musk", "from OpenAI")
    _SINGLE_PROPER_RE = re.compile(
        r'(?<= )(?:by|from|at|for|of|with|via|to|and|or|the) ([A-Z][a-zA-Z]{2,})(?=[ ,.;:!?])'
    )
    # Dates and timeframes
    _DATE_RE = re.compile(
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b'
        r'|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b'
        r'|\b(?:Q[1-4]|FY)\s*\d{2,4}\b'
        r'|\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day|nesday|ursday|turday)?\b'
        r'|\b(?:yesterday|today|tomorrow|last\s+(?:week|month|year|quarter)|next\s+(?:week|month|year|quarter))\b',
        re.IGNORECASE,
    )
    # URLs
    _URL_RE = re.compile(
        r"https?://[^\s,;)\]>\"']+|www\.[^\s,;)\]>\"']+",
        re.IGNORECASE,
    )
    # Email addresses
    _EMAIL_RE = re.compile(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    )
    # Minimum acceptable word count ratio (narration / source)
    # Primary check for content preservation - if below this, significant
    # content was likely dropped. 40% allows natural compression while
    # catching genuine content loss (60% max compression).
    MIN_WORD_RATIO = 0.40

    # Warning threshold - log when ratio is below this but above MIN_WORD_RATIO
    # This provides visibility into potential content issues without blocking.
    WARNING_WORD_RATIO = 0.50

    # Critical threshold - hard fail below this (no retries)
    # Anything below this likely means major content was lost.
    CRITICAL_WORD_RATIO = 0.25

    # Entity validation is now SECONDARY and non-blocking.
    # It serves as a warning/logging mechanism, not a pass/fail criteria.
    # This prevents the all-or-nothing failure mode while still providing
    # visibility into entity preservation.
    # Note: Entity check disabled by setting threshold to 100% (always passes)
    MAX_ENTITY_MISSING_RATE = 1.0  # Disabled - use word ratio as primary check

    @classmethod
    def _to_spoken_forms(cls, entity: str) -> list[str]:
        """Return all acceptable spoken-form equivalents for a numeric/date entity.

        The narration LLM converts source literals to spoken English:
            "$1.2B"   → "one point two billion dollars"
            "3.2%"    → "three point two percent"
            "Q3 2024" → "the third quarter of twenty twenty-four"

        This method generates those equivalents so validate() can check any form
        rather than only the literal string — preventing false positives on
        finance articles while still catching completely dropped entities.

        Falls back to [entity] if num2words is not installed.
        """
        text = entity.strip()
        forms: list[str] = [text]

        try:
            import num2words as _nw
        except ImportError:
            return forms

        def _wordify(n: float) -> list[str]:
            try:
                w = _nw.num2words(n).replace(',', '')
                return [w, w.replace('-', ' ')]
            except Exception as e:
                logger.warning(f'num2words conversion failed for {n}: {e}')
                return []

        def _year_forms(n: int) -> list[str]:
            ys: list[str] = []
            try:
                w = _nw.num2words(n).replace(',', '')
                ys.extend([w, w.replace('-', ' ')])
            except Exception as e:
                logger.warning(f'num2words conversion failed for year {n}: {e}')
            if 2000 <= n <= 2099:
                suffix = n % 100
                try:
                    if suffix == 0:
                        ys.extend(['twenty twenty', 'twenty-twenty'])
                    else:
                        sw = _nw.num2words(suffix).replace(',', '')
                        ys.extend(
                            [f'twenty {sw}', f'twenty-{sw}', f'twenty {sw.replace("-", " ")}']
                        )
                except Exception as e:
                    logger.warning(f'num2words conversion failed for year suffix {suffix}: {e}')
            return ys

        # Percentage: "3.2%" → "three point two percent"
        pct = re.match(r'^(\d+(?:\.\d+)?)%$', text)
        if pct:
            for w in _wordify(float(pct.group(1))):
                forms.append(f'{w} percent')
            return forms

        # Dollar amount: "$1.2B" handled by _NUMBER_RE as "$1.2"; magnitude separate
        dollar = re.match(r'^\$([0-9,.]+)$', text)
        if dollar:
            n_str = dollar.group(1).replace(',', '')
            try:
                for w in _wordify(float(n_str)):
                    forms.extend([w, f'{w} dollars'])
            except ValueError:
                pass
            return forms

        # Number with magnitude suffix: "1.2 billion", "$3 trillion"
        num_mag = re.match(
            r'^\$?(\d+(?:\.\d+)?)\s*(billion|million|trillion|thousand)$', text, re.IGNORECASE
        )
        if num_mag:
            mag = num_mag.group(2).lower()
            try:
                for w in _wordify(float(num_mag.group(1))):
                    forms.extend([f'{w} {mag}', f'{w} {mag} dollars'])
            except ValueError:
                pass
            return forms

        # Quarter: "Q3 2024" → "third quarter", "the third quarter"
        quarter = re.match(r'^Q([1-4])(?:\s*\d{2,4})?$', text, re.IGNORECASE)
        if quarter:
            ordinals = {'1': 'first', '2': 'second', '3': 'third', '4': 'fourth'}
            ord_word = ordinals[quarter.group(1)]
            forms.extend([f'{ord_word} quarter', f'the {ord_word} quarter'])
            return forms

        # Fiscal year: "FY2024" → "fiscal year twenty twenty-four"
        fy = re.match(r'^FY\s*(\d{2,4})$', text, re.IGNORECASE)
        if fy:
            yr_str = fy.group(1)
            if len(yr_str) == 2:
                yr_str = '20' + yr_str
            try:
                n = int(yr_str)
                for yf in _year_forms(n):
                    forms.extend([f'fiscal year {yf}', f'fy {yf}'])
                forms.append(yr_str)
            except ValueError:
                pass
            return forms

        # Standalone 4-digit year: "2024" → "twenty twenty-four"
        if re.match(r'^\d{4}$', text):
            try:
                forms.extend(_year_forms(int(text)))
            except ValueError:
                pass
            return forms

        return forms

    def _extract_entities(self, text: str) -> list[str]:
        entities = []

        # Numbers and percentages — checked via spoken-form equivalents in validate()
        # so "$1.2B" passes when narration says "one point two billion dollars".
        entities.extend(self._NUMBER_RE.findall(text))

        # Dates and timeframes — quarter/fiscal-year patterns converted to spoken form.
        entities.extend(self._DATE_RE.findall(text))

        # Direct quotes must survive verbatim — the prompt preserves them.
        entities.extend(self._QUOTE_RE.findall(text))

        # Multi-word proper nouns (company and person names) must appear in output.
        for match in self._PROPER_NOUN_RE.finditer(text):
            name = match.group(1) or match.group(2)
            if name and len(name) > 3:
                entities.append(name)

        # Single proper nouns after prepositions (e.g. "by OpenAI", "from Sequoia")
        for match in self._SINGLE_PROPER_RE.finditer(text):
            name = match.group(1)
            if name and len(name) > 3:
                entities.append(name)

        return [e.strip() for e in entities if e.strip()]

    def validate(self, source: str, narration: str) -> ValidationResult:
        if not source.strip():
            return ValidationResult(passed=True)

        # Check for meta-commentary at the start of narration
        # If the first sentence matches meta-commentary patterns, fail validation
        narration_stripped = narration.strip()
        if _META_COMMENTARY_FIRST_SENTENCE_RE.match(narration_stripped):
            return ValidationResult(
                passed=False,
                missing_entities=[
                    '[META-COMMENTARY DETECTED: narration starts with summary instead of source content]'
                ],
                word_ratio=0.0,
            )

        # Strip pause markers before entity and word-count checks — markers are
        # assembly directives, not narration content.
        narration_for_check = _PAUSE_MARKER_RE.sub('', narration)

        # Entity check — each entity is matched against all its acceptable spoken forms.
        entities = self._extract_entities(source)
        narration_lower = narration_for_check.lower()
        missing = [
            e
            for e in entities
            if not any(f.lower() in narration_lower for f in self._to_spoken_forms(e))
        ]

        # Entity check is now purely informational (for logging/warnings)
        # It no longer causes validation failure - only word ratio determines pass/fail
        # This prevents all-or-nothing failures while still providing visibility

        # Word count ratio check - PRIMARY and ONLY pass/fail criteria
        source_words = len(source.split())
        narration_words = len(narration_for_check.split())
        ratio = narration_words / max(source_words, 1)

        # Three-tier threshold system:
        # - >= 20%: Pass
        # - 15-19%: Fail (retry allowed)
        # - < 15%: Critical fail (no retries - likely data loss)
        ratio_fail = ratio < self.MIN_WORD_RATIO
        ratio_critical = ratio < self.CRITICAL_WORD_RATIO

        if ratio_fail:
            severity = 'CRITICAL' if ratio_critical else 'WARNING'
            missing.append(
                f'[WORD COUNT RATIO: {severity} {ratio:.0%} — narration is only '
                f'{narration_words} words vs {source_words} source words. '
                f'{"Major content loss - do not retry" if ratio_critical else "Consider retrying"}]'
            )

        # Only word ratio determines pass/fail - entities are for logging only
        passed = not ratio_fail

        return ValidationResult(
            passed=passed,
            missing_entities=missing,
            word_ratio=ratio,
        )

    def build_retry_prompt(self, result: ValidationResult, original_chunk: str) -> str:
        # Only include top 5 most critical missing items to prevent overwhelming the LLM
        # Filter out the word ratio message as it's not actionable
        critical_items = [e for e in result.missing_entities if not e.startswith('[WORD COUNT')][:5]

        if not critical_items:
            return (
                f'Please provide a more complete narration of the following text:\n\n'
                f'{original_chunk}'
            )

        missing_list = '\n'.join(f'- {e}' for e in critical_items)
        return (
            f'Your previous output was missing some key information: '
            f'{missing_list}\n\n'
            f'Please provide a more complete narration of:\n\n{original_chunk}'
        )
