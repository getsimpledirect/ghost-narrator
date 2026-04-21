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


class TestIsSpeakableText:
    def test_normal_prose_passes(self):
        from app.utils.text import is_speakable_text

        assert is_speakable_text('The revenue model failed to account for churn rates.') is True

    def test_url_fails(self):
        from app.utils.text import is_speakable_text

        assert is_speakable_text('Visit https://github.com/foo/bar for more info.') is False

    def test_markdown_code_fence_fails(self):
        from app.utils.text import is_speakable_text

        assert is_speakable_text('```python\ndef foo(): return 42\n```') is False

    def test_high_non_alpha_ratio_fails(self):
        from app.utils.text import is_speakable_text

        assert is_speakable_text('>>> 12345 != None && x == True || y >= 0;') is False

    def test_empty_string_fails(self):
        from app.utils.text import is_speakable_text

        assert is_speakable_text('   ') is False

    def test_snake_case_identifier_fails(self):
        from app.utils.text import is_speakable_text

        assert (
            is_speakable_text('Call get_voice_clone_prompt() to initialise the embedding.') is False
        )

    def test_camel_case_word_allowed_in_prose(self):
        from app.utils.text import is_speakable_text

        # CamelCase proper nouns should not fail — only snake_case identifiers
        assert is_speakable_text('OpenAI released a new model called ChatGPT.') is True
