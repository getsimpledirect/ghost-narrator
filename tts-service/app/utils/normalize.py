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
"""Pre-LLM text normalization for narration quality.

Deterministic transforms applied to raw article text before it reaches
the LLM narration pipeline. No ML inference — pure regex and lookup tables.
"""

from __future__ import annotations

import html
import re
from typing import Final

# HTML tag stripper (used in normalize_for_narration and extract_section_map)
_HTML_TAG_RE: Final = re.compile(r'<[^>]+>')

# H2/H3 header extractor — used to build section map before HTML is stripped
_SECTION_HEADER_RE: Final = re.compile(r'<h[23][^>]*>(.*?)</h[23]>', re.IGNORECASE | re.DOTALL)

# Markdown H2/H3 header extractor
_MD_SECTION_HEADER_RE: Final = re.compile(r'^(?:##|###)\s+(.+)$', re.MULTILINE)

# Markdown frontmatter stripper
_MD_FRONTMATTER_RE: Final = re.compile(r'^---\s*\n.*?\n---\s*\n', re.DOTALL)

# Markdown syntax strippers
_MD_IMAGE_RE: Final = re.compile(r'!\[[^\]]*\]\([^)]+\)')
_MD_BOLD_ITALIC_RE: Final = re.compile(r'(\*\*|__|\*|_)(.*?)\1')
_MD_LINK_RE: Final = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_MD_HEADER_RE: Final = re.compile(r'^#+\s+', re.MULTILINE)
_MD_BLOCKQUOTE_RE: Final = re.compile(r'^>\s+', re.MULTILINE)

# Dollar amounts with SI abbreviations: $1.2B, $450M, $3T, $200K
_DOLLAR_ABBREV_RE: Final = re.compile(r'\$(\d+(?:\.\d+)?)(B|M|T|K)\b', re.IGNORECASE)

# ISO 8601 dates: 2026-04-13
_ISO_DATE_RE: Final = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')

_MONTHS: Final = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]

# Abbreviation expansions — prevent TTS reading "e.g." as "e g" etc.
_ABBREVIATIONS: Final[dict[str, str]] = {
    'e.g.': 'for example',
    'i.e.': 'that is',
    'etc.': 'and so on',
    'vs.': 'versus',
    'approx.': 'approximately',
    'dept.': 'department',
    'govt.': 'government',
    'est.': 'established',
}

_SUFFIX_MAP: Final[dict[str, str]] = {
    'B': 'billion',
    'M': 'million',
    'T': 'trillion',
    'K': 'thousand',
}

_ABBREV_RE: Final = re.compile('(' + '|'.join(re.escape(k) for k in _ABBREVIATIONS) + r')(?=\s|$)')

# Acronym registry: maps exact-match whole-word tokens to TTS-friendly forms.
# Spelled-out acronyms use hyphens so TTS reads each letter individually.
# Pronounceable acronyms (NASA, NATO) are left as-is — TTS handles them correctly.
_ACRONYM_REGISTRY: Final[dict[str, str]] = {
    # Titles / C-suite
    'CEO': 'C-E-O',
    'CTO': 'C-T-O',
    'CFO': 'C-F-O',
    'COO': 'C-O-O',
    'CMO': 'C-M-O',
    'CPO': 'C-P-O',
    # Tech
    'API': 'A-P-I',
    'SDK': 'S-D-K',
    'SaaS': 'software as a service',
    'PaaS': 'platform as a service',
    'IaaS': 'infrastructure as a service',
    'LLM': 'L-L-M',
    'UI': 'U-I',
    'UX': 'U-X',
    # Finance / business
    'IPO': 'I-P-O',
    'ARR': 'A-R-R',
    'MRR': 'M-R-R',
    'GMV': 'G-M-V',
    'TAM': 'T-A-M',
    'SAM': 'S-A-M',
    'B2B': 'B-to-B',
    'B2C': 'B-to-C',
    'VC': 'V-C',
    'PE': 'P-E',
}

# Pre-compiled acronym pattern: matches whole-word occurrences only.
_ACRONYM_RE: Final = re.compile(r'\b(' + '|'.join(re.escape(k) for k in _ACRONYM_REGISTRY) + r')\b')

_MULTI_SPACE_RE: Final = re.compile(r'[ \t]+')
_MULTI_NEWLINE_RE: Final = re.compile(r'\n{3,}')

# ── Content pre-filter patterns ───────────────────────────────────────────────
# Strip non-narrable blocks BEFORE they reach the LLM narration pipeline.
# These patterns match content that is meaningful visually but nonsensical
# when spoken aloud: code, tables, CTA boilerplate, Ghost CMS card elements.

# Fenced code blocks: ```...``` (possibly with language tag)
_FENCED_CODE_RE: Final = re.compile(r'```[\s\S]*?```', re.DOTALL)

# Inline code: `...`
_INLINE_CODE_RE: Final = re.compile(r'`[^`\n]+`')

# HTML block-level elements that are never narrated: pre, code, table, figure,
# script, style, noscript, and Ghost CMS kg-card variants.
_HTML_NON_NARRABLE_RE: Final = re.compile(
    r'<(?:pre|code|table|figure|script|style|noscript|iframe|svg)[^>]*>[\s\S]*?'
    r'</(?:pre|code|table|figure|script|style|noscript|iframe|svg)>',
    re.IGNORECASE | re.DOTALL,
)

# Markdown table rows: lines that start and end with | (including header separator)
_MD_TABLE_ROW_RE: Final = re.compile(r'^\|.*\|[ \t]*$', re.MULTILINE)
_MD_TABLE_SEP_RE: Final = re.compile(r'^\|[-| :]+\|[ \t]*$', re.MULTILINE)

# Footnote reference markers: [^1] or [1] at end of sentence
_FOOTNOTE_MARKER_RE: Final = re.compile(r'\[\^?\d+\]')

# Call-to-action boilerplate common in Ghost posts — single-line patterns
# matched at start of line so mid-sentence uses of these words are unaffected.
_CTA_LINE_RE: Final = re.compile(
    r'^[ \t]*(?:subscribe|follow us|share this|sign up|get notified|'
    r'join our newsletter|click here|read more|learn more|see more|'
    r'view all|newsletter|unsubscribe)[^\n]{0,120}$',
    re.IGNORECASE | re.MULTILINE,
)


def filter_non_narrable_content(text: str) -> str:
    """Strip content that is visual/interactive but nonsensical when narrated.

    Applied before normalize_for_narration so the LLM receives only prose.
    Removes: fenced code blocks, HTML pre/code/table/figure/script elements,
    markdown tables, footnote markers, and common CTA boilerplate lines.

    Args:
        text: Raw article text (HTML or Markdown, not yet normalized).

    Returns:
        Text with non-narrable blocks removed.
    """
    # HTML non-narrable block elements (pre/code/table/figure/etc.)
    text = _HTML_NON_NARRABLE_RE.sub('', text)

    # Fenced code blocks before markdown stripping removes the backticks
    text = _FENCED_CODE_RE.sub('', text)

    # Inline code (single backtick)
    text = _INLINE_CODE_RE.sub('', text)

    # Markdown table rows (separator lines and data rows)
    text = _MD_TABLE_SEP_RE.sub('', text)
    text = _MD_TABLE_ROW_RE.sub('', text)

    # Footnote markers
    text = _FOOTNOTE_MARKER_RE.sub('', text)

    # CTA boilerplate lines
    text = _CTA_LINE_RE.sub('', text)

    # Re-collapse whitespace introduced by the removals
    text = _MULTI_NEWLINE_RE.sub('\n\n', text)
    return text.strip()


def extract_section_map(html_text: str) -> str:
    """Extract H2/H3 section headers from HTML or Markdown to build a compact section map.

    Called BEFORE normalize_for_narration strips HTML tags, so this receives
    the raw HTML/Markdown. Returns empty string if no headers found.

    Example:
        '<h2>Introduction</h2><h2>The VC Math</h2>'
        → 'Sections: Introduction | The VC Math'

    Args:
        html_text: Raw HTML or Markdown article text.

    Returns:
        Section map string, or empty string if no H2/H3 headers present.
    """
    headers = [
        _HTML_TAG_RE.sub('', m.group(1)).strip()
        for m in _SECTION_HEADER_RE.finditer(html_text)
        if _HTML_TAG_RE.sub('', m.group(1)).strip()
    ]

    # Also look for Markdown headers if no HTML headers found
    if not headers:
        headers = [
            m.group(1).strip()
            for m in _MD_SECTION_HEADER_RE.finditer(html_text)
            if m.group(1).strip()
        ]

    if not headers:
        return ''
    return 'Sections: ' + ' | '.join(headers)


def normalize_for_narration(text: str) -> str:
    """Normalize raw article text before the LLM narration pipeline.

    Applies deterministic, fast transforms only:
    - Filter non-narrable blocks (code, tables, Ghost kg-cards, CTAs)
    - Strip HTML tags and unescape HTML entities
    - Expand $NB/$NM/$NT/$NK abbreviations to spoken form
    - Convert ISO 8601 dates to natural form (April 13, 2026)
    - Expand common written abbreviations (e.g. → for example)
    - Expand tech/business acronyms to TTS-friendly hyphenated form
    - Normalize whitespace

    Args:
        text: Raw article text (may contain HTML, abbreviations, etc.)

    Returns:
        Cleaned text suitable for LLM narration.
    """
    # Strip non-narrable content before any other processing so code blocks,
    # tables, and CTAs don't inflate token count or confuse the LLM
    text = filter_non_narrable_content(text)

    # Strip Markdown frontmatter
    text = _MD_FRONTMATTER_RE.sub('', text)

    # Strip Markdown images completely
    text = _MD_IMAGE_RE.sub('', text)

    # Strip Markdown links: [text](url) -> text
    text = _MD_LINK_RE.sub(r'\1', text)

    # Strip Markdown bold/italic: **text** -> text
    text = _MD_BOLD_ITALIC_RE.sub(r'\2', text)

    # Strip Markdown headers: ## Header -> Header
    text = _MD_HEADER_RE.sub('', text)

    # Strip Markdown blockquotes: > text -> text
    text = _MD_BLOCKQUOTE_RE.sub('', text)

    # Strip HTML tags (replace block-level tags with space, inline tags with empty)
    text = _HTML_TAG_RE.sub('', text)
    # Unescape HTML entities (&amp; → &, &lt; → <, &nbsp; → space, etc.)
    text = html.unescape(text)

    # Expand dollar + SI suffix: $1.2B → 1.2 billion dollars
    def _expand_dollar(m: re.Match) -> str:
        num = m.group(1)
        suffix = _SUFFIX_MAP[m.group(2).upper()]
        return f'{num} {suffix} dollars'

    text = _DOLLAR_ABBREV_RE.sub(_expand_dollar, text)

    # Convert ISO dates: 2026-04-13 → April 13, 2026
    def _expand_date(m: re.Match) -> str:
        year, month_idx, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        month_name = _MONTHS[month_idx - 1] if 1 <= month_idx <= 12 else str(month_idx)
        return f'{month_name} {day}, {year}'

    text = _ISO_DATE_RE.sub(_expand_date, text)

    # Expand written abbreviations (word-boundary safe)
    text = _ABBREV_RE.sub(lambda m: _ABBREVIATIONS[m.group(1)], text)

    # Expand tech/business acronyms to TTS-friendly forms
    text = _ACRONYM_RE.sub(lambda m: _ACRONYM_REGISTRY[m.group(1)], text)

    # Normalize whitespace
    text = _MULTI_SPACE_RE.sub(' ', text)
    text = _MULTI_NEWLINE_RE.sub('\n\n', text)

    return text.strip()
