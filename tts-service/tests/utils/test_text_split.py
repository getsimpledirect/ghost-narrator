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

"""Tests for split_into_large_segments cascading splitter."""

from app.utils.text import split_into_large_segments


def _words(n: int, word: str = 'word') -> str:
    return ' '.join([word] * n)


def _para(n: int) -> str:
    return _words(n)


def _paras(*counts: int) -> str:
    return '\n\n'.join(_para(c) for c in counts)


class TestStage1ParagraphSplit:
    """Stage 1: paragraphs fit within target — no sentence splitting needed."""

    def test_single_short_text_returned_as_one_segment(self):
        text = _paras(100)
        segs = split_into_large_segments(text, target_words=650)
        assert len(segs) == 1
        assert len(segs[0].split()) == 100

    def test_two_paras_fitting_combined(self):
        text = _paras(300, 300)
        segs = split_into_large_segments(text, target_words=650)
        assert len(segs) == 1
        assert len(segs[0].split()) == 600

    def test_three_paras_split_across_segments(self):
        # 400 + 400 + 400 = 1200 words; each pair 800 > 650, so each para is its own segment
        text = _paras(400, 400, 400)
        segs = split_into_large_segments(text, target_words=650)
        assert len(segs) == 3
        for seg in segs:
            assert len(seg.split()) <= int(650 * 1.3)

    def test_empty_string_returns_single_segment(self):
        segs = split_into_large_segments('', target_words=650)
        assert len(segs) == 1

    def test_all_segments_within_hard_cap(self):
        # Many paragraphs of mixed size — none should exceed 1.3× target
        counts = [200, 150, 350, 100, 600, 50, 400, 300]
        text = _paras(*counts)
        segs = split_into_large_segments(text, target_words=650)
        cap = int(650 * 1.3)
        for seg in segs:
            assert len(seg.split()) <= cap, f'Segment exceeded cap: {len(seg.split())} > {cap}'


class TestStage2SentenceSplit:
    """Stage 2: paragraph exceeds target — split at sentence boundaries."""

    def _sentence_para(self, n_sentences: int, words_per_sentence: int) -> str:
        # Capitalise first word of each sentence so the regex lookahead triggers.
        cap_sentence = 'Word ' + _words(words_per_sentence - 1) + '.'
        sentences = [cap_sentence] * n_sentences
        return ' '.join(sentences)

    def test_oversized_paragraph_split_into_multiple_sub_paras(self):
        # Each sentence is 80 words; 10 sentences = 800-word paragraph > 650×1.1=715
        para = self._sentence_para(10, 80)
        assert len(para.split()) > int(650 * 1.1)
        segs = split_into_large_segments(para, target_words=650)
        assert len(segs) >= 2
        cap = int(650 * 1.3)
        for seg in segs:
            assert len(seg.split()) <= cap

    def test_sentence_split_preserves_all_words(self):
        para = self._sentence_para(8, 100)
        total = len(para.split())
        segs = split_into_large_segments(para, target_words=650)
        reconstructed = ' '.join(seg.replace('\n\n', ' ') for seg in segs)
        assert len(reconstructed.split()) == total


class TestStage2RegexMissesBoundaries:
    """Regression: regex catches some boundaries but misses others.

    The sentence boundary regex requires `[.!?]` + whitespace + `[A-Z"“]`.
    It misses boundaries when the next sentence starts with a digit, a
    lowercase letter, or punctuation. Production failure mode: a
    4770-word LLM-rewritten paragraph where 4 early boundaries matched
    and the trailing 4631 words contained periods only before
    digits/lowercase, leaving a single 4631-word "sentence" that blew
    TTS VRAM. Stage 3's emergency word-count fallback didn't fire
    because len(sentences) > 1.
    """

    def test_partial_regex_matches_still_respect_hard_cap(self):
        # 4 early sentences regex catches (uppercase next-word), then a
        # long tail of clauses ending in `.` followed by digits or
        # lowercase — regex sees the entire tail as one "sentence".
        early = ' '.join('Word ' + _words(39) + '.' for _ in range(4))
        # 'by 2026.' (digit follows period) and 'and so on.' (lowercase
        # follows period) — neither matches [A-Z"“] lookahead.
        tail_clauses = ['by 2026.', 'and so on.', '50 percent gone.'] * 100
        para = early + ' ' + ' '.join(tail_clauses)
        segs = split_into_large_segments(para, target_words=60)
        cap = int(60 * 1.3)
        for seg in segs:
            wc = len(seg.split())
            assert wc <= cap, f'segment with {wc} words exceeds cap {cap}'

    def test_partial_regex_matches_preserve_all_words(self):
        early = ' '.join('Word ' + _words(39) + '.' for _ in range(4))
        tail_clauses = ['by 2026.', 'and so on.'] * 50
        para = early + ' ' + ' '.join(tail_clauses)
        total = len(para.split())
        segs = split_into_large_segments(para, target_words=60)
        reconstructed = sum(len(seg.replace('\n\n', ' ').split()) for seg in segs)
        assert reconstructed == total


class TestStage3EmergencyWordCountSplit:
    """Stage 3: paragraph has no sentence boundaries — word-count emergency split."""

    def test_no_sentence_boundary_falls_back_to_word_split(self):
        # 1000-word paragraph with no punctuation at all.
        para = _words(1000, 'monotone')
        segs = split_into_large_segments(para, target_words=650)
        cap = int(650 * 1.3)
        for seg in segs:
            assert len(seg.split()) <= cap

    def test_emergency_split_preserves_all_words(self):
        para = _words(900, 'monotone')
        total = len(para.split())
        segs = split_into_large_segments(para, target_words=650)
        reconstructed_words = sum(len(s.split()) for s in segs)
        assert reconstructed_words == total


class TestTrailingShortSegmentMerge:
    """Short trailing segment should be merged into the preceding one."""

    def test_trailing_short_segment_merged(self):
        # Two large segments + tiny tail
        text = _paras(600, 600, 20)
        segs = split_into_large_segments(text, target_words=650)
        # The 20-word tail must be merged — no segment should have ≤ 20 words
        # (except if there's only one segment total)
        if len(segs) > 1:
            assert len(segs[-1].split()) >= 40

    def test_no_merge_when_last_segment_is_large_enough(self):
        text = _paras(400, 400, 200)
        segs = split_into_large_segments(text, target_words=650)
        # Last segment has 200 words — above the 40-word merge threshold
        if len(segs) > 1:
            assert len(segs[-1].split()) >= 40


class TestRealWorldNarrationStructure:
    """Integration: simulate narration text with varying paragraph sizes."""

    def test_long_narration_all_segments_within_cap(self):
        import random

        random.seed(42)
        paras = []
        for _ in range(30):
            size = random.choice([50, 100, 200, 400, 700, 1000])
            paras.append(_words(size))
        text = '\n\n'.join(paras)
        segs = split_into_large_segments(text, target_words=650)
        cap = int(650 * 1.3)
        for i, seg in enumerate(segs):
            wc = len(seg.split())
            assert wc <= cap, f'Segment {i} has {wc} words, exceeds cap {cap}'

    def test_single_giant_paragraph_no_sentences(self):
        # Worst case: entire book chapter as one unbroken paragraph
        para = _words(5000)
        segs = split_into_large_segments(para, target_words=650)
        cap = int(650 * 1.3)
        assert len(segs) > 1
        for seg in segs:
            assert len(seg.split()) <= cap
