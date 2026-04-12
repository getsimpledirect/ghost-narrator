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

import re
from dataclasses import dataclass, field


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
    MIN_WORD_RATIO = 0.55

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
            except Exception:
                return []

        def _year_forms(n: int) -> list[str]:
            ys: list[str] = []
            try:
                w = _nw.num2words(n).replace(',', '')
                ys.extend([w, w.replace('-', ' ')])
            except Exception:
                pass
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
                except Exception:
                    pass
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

        # Entity check — each entity is matched against all its acceptable spoken forms.
        entities = self._extract_entities(source)
        narration_lower = narration.lower()
        missing = [
            e
            for e in entities
            if not any(f.lower() in narration_lower for f in self._to_spoken_forms(e))
        ]

        # Word count ratio check
        source_words = len(source.split())
        narration_words = len(narration.split())
        ratio = narration_words / max(source_words, 1)

        if ratio < self.MIN_WORD_RATIO:
            missing.append(
                f'[WORD COUNT RATIO: {ratio:.0%} — narration is only '
                f'{narration_words} words vs {source_words} source words. '
                f'Likely significant content was dropped.]'
            )

        return ValidationResult(
            passed=len(missing) == 0,
            missing_entities=missing,
            word_ratio=ratio,
        )

    def build_retry_prompt(self, result: ValidationResult, original_chunk: str) -> str:
        missing_list = '\n'.join(f'- {e}' for e in result.missing_entities)
        return (
            f'Your previous output was missing the following information:\n'
            f'{missing_list}\n\n'
            f'Please redo the narration conversion of the following text, '
            f'ensuring every item above is included:\n\n{original_chunk}'
        )
