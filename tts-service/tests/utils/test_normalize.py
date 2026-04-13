from app.utils.normalize import normalize_for_narration, extract_section_map


def test_strips_html_tags():
    result = normalize_for_narration('<p>Hello <strong>world</strong>.</p>')
    assert '<' not in result
    assert 'Hello world.' in result


def test_unescapes_html_entities():
    result = normalize_for_narration('Revenue &amp; profit grew 12%.')
    assert '&amp;' not in result
    assert 'Revenue & profit' in result


def test_expands_eg_abbreviation():
    result = normalize_for_narration('Some things, e.g. apples, are good.')
    assert 'e.g.' not in result
    assert 'for example' in result


def test_expands_ie_abbreviation():
    result = normalize_for_narration('The result, i.e. failure, was clear.')
    assert 'i.e.' not in result
    assert 'that is' in result


def test_expands_etc_abbreviation():
    result = normalize_for_narration('Fruits, vegetables, etc. are healthy.')
    assert 'etc.' not in result
    assert 'and so on' in result


def test_expands_dollar_billion():
    result = normalize_for_narration('Revenue hit $1.2B this year.')
    assert '$1.2B' not in result
    assert '1.2 billion dollars' in result


def test_expands_dollar_million():
    result = normalize_for_narration('The deal was worth $450M.')
    assert '$450M' not in result
    assert '450 million dollars' in result


def test_expands_iso_date():
    result = normalize_for_narration('Announced on 2026-04-13.')
    assert '2026-04-13' not in result
    assert 'April 13, 2026' in result


def test_passes_clean_text_unchanged():
    text = 'The company grew steadily over the past year.'
    assert normalize_for_narration(text) == text


def test_normalizes_whitespace():
    result = normalize_for_narration('Hello   world\n\n\n\nbye')
    assert '   ' not in result
    assert result.count('\n\n') <= 1


# Acronym registry tests
def test_acronym_ceo_expanded():
    result = normalize_for_narration('The CEO announced layoffs.')
    assert 'C-E-O' in result
    assert 'CEO' not in result


def test_acronym_api_expanded():
    result = normalize_for_narration('The new API is live.')
    assert 'A-P-I' in result


def test_acronym_saas_expanded():
    result = normalize_for_narration('It is a SaaS company.')
    assert 'SaaS' not in result
    assert 'Saas' in result or 'software as a service' in result.lower()


def test_acronym_b2b_expanded():
    result = normalize_for_narration('They are a B2B startup.')
    assert 'B2B' not in result
    assert 'B-to-B' in result


def test_acronym_not_partial_match():
    """Acronym expansion must not match partial words — 'APEX' should not expand 'A-P-I'."""
    result = normalize_for_narration('APEX is a product name.')
    assert 'A-P-I' not in result


# Section map tests
def test_extract_section_map_h2_headers():
    html = '<h2>Introduction</h2><p>Text</p><h2>The VC Math</h2><p>More text.</p>'
    result = extract_section_map(html)
    assert 'Introduction' in result
    assert 'The VC Math' in result


def test_extract_section_map_h3_headers():
    html = '<h3>Market Size</h3><p>Details.</p><h3>Competitive Moat</h3>'
    result = extract_section_map(html)
    assert 'Market Size' in result
    assert 'Competitive Moat' in result


def test_extract_section_map_no_headers_returns_empty():
    html = '<p>Just a paragraph. No headers here.</p>'
    result = extract_section_map(html)
    assert result == ''


def test_extract_section_map_strips_tags_from_header():
    html = '<h2><strong>Revenue</strong> Growth</h2>'
    result = extract_section_map(html)
    assert 'Revenue Growth' in result
    assert '<strong>' not in result


def test_extract_section_map_markdown_headers():
    md = '## Introduction\nText\n### The VC Math\nMore text.'
    result = extract_section_map(md)
    assert 'Introduction' in result
    assert 'The VC Math' in result


def test_normalize_strips_markdown_syntax():
    md = '---\ntitle: "Test"\n---\n# Header\nThis is **bold** and *italic* with a [link](http://example.com).'
    result = normalize_for_narration(md)
    assert '---' not in result
    assert 'title: "Test"' not in result
    assert '#' not in result
    assert '**' not in result
    assert '*' not in result
    assert 'http://example.com' not in result
    assert 'This is bold and italic with a link.' in result
