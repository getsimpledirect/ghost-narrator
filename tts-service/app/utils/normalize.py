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

# Markdown horizontal rules: ---, ***, ___ on their own line (article section dividers)
# Applied in normalize_for_narration AFTER frontmatter stripping so frontmatter
# delimiters are removed as a block first, not as individual HR lines.
_MD_HR_RE: Final = re.compile(r'^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$', re.MULTILINE)

# Dollar amounts with SI abbreviations: $1.2B, $450M, $3T, $200K
_DOLLAR_ABBREV_RE: Final = re.compile(r'\$(\d+(?:\.\d+)?)(B|M|T|K)\b', re.IGNORECASE)

# Plain dollar amounts: $500, $29.99, $1,200 — not followed by B/M/T/K (already handled above)
_PLAIN_DOLLAR_RE: Final = re.compile(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)(?![BMTKbmtk\d])')

# Slash-unit price suffixes: /month, /year, /user, /seat → "per month" etc.
_PER_UNIT_RE: Final = re.compile(
    r'/(?:month|year|user|seat|day|week|quarter|hour)\b',
    re.IGNORECASE,
)

# Multiplier patterns: 10x, 3x, 2.5x → "10 times", "3 times"
# \b before ensures we don't match inside words; (?![a-zA-Z]) after prevents "Xbox" matches
_MULTIPLIER_RE: Final = re.compile(r'\b(\d+(?:\.\d+)?)x\b(?![a-zA-Z0-9])', re.IGNORECASE)

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
    'ROI': 'R-O-I',
    'EBITDA': 'E-B-I-T-D-A',
    'NPS': 'N-P-S',
    'KPI': 'K-P-I',
    'OKR': 'O-K-R',
    'YoY': 'year over year',
    'QoQ': 'quarter over quarter',
    # HR is kept as H-R to avoid confusion with "hours" abbreviation
    'HR': 'H-R',
    'VP': 'V-P',
    'P&L': 'profit and loss',
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

# Emoji-prefixed bullet lines: common in Ghost pricing/feature tables
# (📬 Basic Package — $29/month, 💎 Pro Plan, etc.)
_EMOJI_BULLET_LINE_RE: Final = re.compile(
    r'^[ \t]*[\U0001F300-\U0001FAFF\u2600-\u27BF\u2700-\u27BF].*$',
    re.MULTILINE,
)

# Plain bullet symbol lines: • item, ◦ sub-item, ▸ item
_SYMBOL_BULLET_LINE_RE: Final = re.compile(
    r'^[ \t]*[•◦‣▸▪▫]\s+.+$',
    re.MULTILINE,
)

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

# Ghost CMS kg-card divs (bookmarks, images, galleries, videos, embeds) —
# strip entire block because they inject URLs, file paths, and metadata that
# break narration. Applied in a loop in filter_non_narrable_content to handle
# nested cards (e.g. a gallery card containing image cards).
_KG_CARD_RE: Final = re.compile(
    r'<div[^>]+\bkg-card\b[^>]*>[\s\S]*?</div>',
    re.IGNORECASE | re.DOTALL,
)

# Percentages: 12.5% → "12.5 percent"
_PERCENT_RE: Final = re.compile(r'\b(\d+(?:\.\d+)?)%')

# Ordinal numbers: 1st→first … 20th→twentieth; strip suffix for higher numbers
# so "21st" becomes "21" which TTS reads as "twenty-one" (close enough).
_ORDINAL_WORDS: Final[dict[int, str]] = {
    1: 'first',
    2: 'second',
    3: 'third',
    4: 'fourth',
    5: 'fifth',
    6: 'sixth',
    7: 'seventh',
    8: 'eighth',
    9: 'ninth',
    10: 'tenth',
    11: 'eleventh',
    12: 'twelfth',
    13: 'thirteenth',
    14: 'fourteenth',
    15: 'fifteenth',
    16: 'sixteenth',
    17: 'seventeenth',
    18: 'eighteenth',
    19: 'nineteenth',
    20: 'twentieth',
}
_ORDINAL_RE: Final = re.compile(r'\b(\d+)(st|nd|rd|th)\b', re.IGNORECASE)

# 24/7 → "twenty-four seven"
_24_7_RE: Final = re.compile(r'\b24/7\b')

# URLs and email addresses — stripped before LLM so "https://..." strings
# don't appear verbatim in narration (TTS would read them letter by letter).
_URL_RE: Final = re.compile(r'https?://[^\s<>"\']+|www\.[^\s<>"\']+', re.IGNORECASE)
_EMAIL_RE: Final = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')


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

    # Ghost CMS kg-card divs — strip iteratively to handle nested cards
    prev = None
    while prev != text:
        prev = text
        text = _KG_CARD_RE.sub('', text)

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

    # Emoji-prefixed bullet lines (pricing tables, feature lists with emoji icons)
    text = _EMOJI_BULLET_LINE_RE.sub('', text)

    # Plain bullet symbol lines
    text = _SYMBOL_BULLET_LINE_RE.sub('', text)

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

    # Strip Markdown frontmatter first — must precede HR stripping so the
    # frontmatter delimiters (---) are removed as a block, not as HR lines.
    text = _MD_FRONTMATTER_RE.sub('', text)

    # Strip Markdown horizontal rules (article section dividers: ---, ***, ___)
    text = _MD_HR_RE.sub('', text)

    # Strip Markdown images completely
    text = _MD_IMAGE_RE.sub('', text)

    # Strip Markdown links: [text](url) -> text
    text = _MD_LINK_RE.sub(r'\1', text)

    # Strip bare URLs and email addresses after Markdown link/image removal.
    # Placed here so the full Markdown syntax is removed first — otherwise
    # stripping the URL inside ![alt](url) leaves ![alt]() which the image
    # regex cannot match (it requires a non-empty href).
    text = _URL_RE.sub('', text)
    text = _EMAIL_RE.sub('', text)

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

    # Expand plain dollar amounts: $500 → 500 dollars, $29.99 → 29.99 dollars
    text = _PLAIN_DOLLAR_RE.sub(lambda m: f'{m.group(1)} dollars', text)

    # Expand slash-unit price suffixes: /month → per month
    text = _PER_UNIT_RE.sub(lambda m: ' per ' + m.group(0)[1:].lower(), text)

    # Expand multipliers: 10x → 10 times
    text = _MULTIPLIER_RE.sub(lambda m: f'{m.group(1)} times', text)

    # Expand percentages: 12.5% → "12.5 percent"
    text = _PERCENT_RE.sub(lambda m: f'{m.group(1)} percent', text)

    # Expand ordinal numbers: 1st → first, 21st → 21 (TTS reads as "twenty-one")
    text = _ORDINAL_RE.sub(lambda m: _ORDINAL_WORDS.get(int(m.group(1)), m.group(1)), text)

    # Expand 24/7 → twenty-four seven
    text = _24_7_RE.sub('twenty-four seven', text)

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
