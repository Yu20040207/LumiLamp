import unittest

from lumilamp.voice.sentence_segmenter import SentenceSegmenter


class SentenceSegmenterTests(unittest.TestCase):
    def test_emits_complete_chinese_sentences_across_frames(self) -> None:
        segmenter = SentenceSegmenter()

        self.assertEqual(segmenter.push("我是露"), [])
        self.assertEqual(
            segmenter.push("米。很高兴见到你！"),
            ["我是露米。", "很高兴见到你！"],
        )

    def test_prefers_latest_comma_before_long_sentence_limit(self) -> None:
        segmenter = SentenceSegmenter(max_chars=8)

        self.assertEqual(segmenter.push("前四个字，后面继续说话"), ["前四个字，"])

    def test_hard_splits_long_text_without_punctuation(self) -> None:
        segmenter = SentenceSegmenter(max_chars=4)

        self.assertEqual(segmenter.push("一二三四五"), ["一二三四"])
        self.assertEqual(segmenter.finish(), ["五"])

    def test_finish_emits_residual_only_once(self) -> None:
        segmenter = SentenceSegmenter()
        segmenter.push("还没有句号")

        self.assertEqual(segmenter.finish(), ["还没有句号"])
        self.assertEqual(segmenter.finish(), [])

    def test_ignores_blank_delta_and_rejects_non_string_delta(self) -> None:
        segmenter = SentenceSegmenter()

        self.assertEqual(segmenter.push(" \t"), [])
        with self.assertRaises(TypeError):
            segmenter.push(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
