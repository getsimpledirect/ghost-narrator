from app.utils.text import parse_pause_markers, clean_text_for_tts, PAUSE_MS, LONG_PAUSE_MS


def test_parse_no_markers():
    result = parse_pause_markers('Hello world.')
    assert result == [('Hello world.', 0)]


def test_parse_single_pause():
    result = parse_pause_markers('First sentence. [PAUSE] Second sentence.')
    assert len(result) == 2
    assert result[0] == ('First sentence.', PAUSE_MS)
    assert result[1] == ('Second sentence.', 0)


def test_parse_long_pause():
    result = parse_pause_markers('Para one. [LONG_PAUSE] Para two.')
    assert result[0][1] == LONG_PAUSE_MS
    assert result[1][1] == 0


def test_parse_mixed_markers():
    result = parse_pause_markers('A. [PAUSE] B. [LONG_PAUSE] C.')
    assert len(result) == 3
    assert result[0] == ('A.', PAUSE_MS)
    assert result[1] == ('B.', LONG_PAUSE_MS)
    assert result[2] == ('C.', 0)


def test_parse_case_insensitive():
    result = parse_pause_markers('Text. [pause] More text.')
    assert len(result) == 2
    assert result[0][1] == PAUSE_MS


def test_clean_text_strips_pause_markers():
    text = 'Hello world. [PAUSE] Goodbye.'
    cleaned = clean_text_for_tts(text)
    assert '[PAUSE]' not in cleaned
    assert '[LONG_PAUSE]' not in cleaned
    assert 'Hello world.' in cleaned
    assert 'Goodbye.' in cleaned
