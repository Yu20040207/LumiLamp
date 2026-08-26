from __future__ import annotations

from array import array
import builtins
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lumilamp.voice.wakeword import SherpaWakeWordDetector, WakeWordConfig


MODEL_DIR = Path("/models/kws")


class FakeStream:
    def __init__(self) -> None:
        self.waveforms: list[tuple[int, list[float]]] = []

    def accept_waveform(self, sample_rate: int, samples: array[float]) -> None:
        self.waveforms.append((sample_rate, list(samples)))


class FakeKeywordSpotter:
    instances: list["FakeKeywordSpotter"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.stream = FakeStream()
        self.ready = False
        self.result = ""
        self.decode_count = 0
        self.reset_count = 0
        self.instances.append(self)

    def create_stream(self) -> FakeStream:
        return self.stream

    def is_ready(self, stream: FakeStream) -> bool:
        self.assert_owns(stream)
        if self.ready:
            self.ready = False
            return True
        return False

    def decode_stream(self, stream: FakeStream) -> None:
        self.assert_owns(stream)
        self.decode_count += 1

    def get_result(self, stream: FakeStream) -> str:
        self.assert_owns(stream)
        return self.result

    def reset_stream(self, stream: FakeStream) -> None:
        self.assert_owns(stream)
        self.result = ""
        self.reset_count += 1

    def assert_owns(self, stream: FakeStream) -> None:
        if stream is not self.stream:
            raise AssertionError("unexpected stream")


def make_detector(
    config: WakeWordConfig | None = None,
) -> tuple[SherpaWakeWordDetector, FakeKeywordSpotter]:
    FakeKeywordSpotter.instances.clear()
    fake_sherpa = SimpleNamespace(KeywordSpotter=FakeKeywordSpotter)
    with (
        patch.dict(sys.modules, {"sherpa_onnx": fake_sherpa}),
        patch.object(Path, "is_dir", return_value=True),
        patch.object(Path, "is_file", return_value=True),
    ):
        detector = SherpaWakeWordDetector(config or WakeWordConfig(MODEL_DIR))
    return detector, FakeKeywordSpotter.instances[-1]


class WakeWordTests(unittest.TestCase):
    def test_defaults_to_confirmed_chinese_phrase(self) -> None:
        config = WakeWordConfig(MODEL_DIR)

        self.assertEqual(config.keyword, "你好露米")
        self.assertEqual(config.threshold, 0.25)
        self.assertEqual(config.score, 1.0)

    def test_rejects_unsupported_keyword_and_invalid_tuning(self) -> None:
        invalid = (
            ({"keyword": "露米"}, "exactly 你好露米"),
            ({"threshold": 0.0}, "threshold"),
            ({"threshold": 1.1}, "threshold"),
            ({"score": 0.0}, "score"),
        )

        for overrides, message in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    WakeWordConfig(MODEL_DIR, **overrides)

    def test_import_does_not_import_sherpa(self) -> None:
        module_name = "lumilamp.voice.wakeword"
        existing = sys.modules.pop(module_name)
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "sherpa_onnx":
                raise AssertionError("module import attempted to import sherpa_onnx")
            return original_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, "__import__", side_effect=guarded_import):
                importlib.import_module(module_name)
        finally:
            sys.modules[module_name] = existing

    def test_rejects_a_missing_explicit_model_file_before_importing_sherpa(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "encoder-epoch-13"):
            SherpaWakeWordDetector(WakeWordConfig(MODEL_DIR))

    def test_constructs_spotter_with_explicit_model_and_keyword_paths(self) -> None:
        config = WakeWordConfig(MODEL_DIR, threshold=0.4, score=1.5)

        _, spotter = make_detector(config)

        self.assertEqual(
            spotter.kwargs,
            {
                "tokens": str(MODEL_DIR / "tokens.txt"),
                "encoder": str(
                    MODEL_DIR
                    / "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx"
                ),
                "decoder": str(
                    MODEL_DIR / "decoder-epoch-13-avg-2-chunk-8-left-64.onnx"
                ),
                "joiner": str(
                    MODEL_DIR
                    / "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx"
                ),
                "keywords_file": str(MODEL_DIR / "keywords_lumilamp.txt"),
                "num_threads": 2,
                "sample_rate": 16000,
                "provider": "cpu",
                "keywords_threshold": 0.4,
                "keywords_score": 1.5,
            },
        )

    def test_normalizes_signed_int16_pcm_and_decodes_ready_frames(self) -> None:
        detector, spotter = make_detector()
        spotter.ready = True

        detected = detector.accept_pcm(array("h", [-32768, 0, 32767]))

        self.assertFalse(detected)
        self.assertEqual(spotter.stream.waveforms[0][0], 16000)
        self.assertEqual(
            spotter.stream.waveforms[0][1],
            [-1.0, 0.0, 32767 / 32768.0],
        )
        self.assertEqual(spotter.decode_count, 1)

    def test_returns_one_event_and_resets_after_detection(self) -> None:
        detector, spotter = make_detector()
        spotter.ready = True
        spotter.result = "你好露米"

        self.assertTrue(detector.accept_pcm(array("h", [1, -1])))
        self.assertEqual(spotter.reset_count, 1)

    def test_reset_clears_the_current_stream(self) -> None:
        detector, spotter = make_detector()

        detector.reset()

        self.assertEqual(spotter.reset_count, 1)

    def test_rejects_pcm_with_the_wrong_array_type(self) -> None:
        detector, _ = make_detector()

        with self.assertRaisesRegex(TypeError, r"array\('h'\)"):
            detector.accept_pcm(array("i", [1]))


if __name__ == "__main__":
    unittest.main()
