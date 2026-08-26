"""Local sherpa-onnx wake-word detection without audio-device access."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any


SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class WakeWordConfig:
    """Configuration for the one approved local wake phrase."""

    model_dir: Path
    keyword: str = "你好露米"
    threshold: float = 0.25
    score: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.model_dir, Path):
            raise TypeError("model_dir must be a pathlib.Path")
        if self.keyword != "你好露米":
            raise ValueError("keyword must be exactly 你好露米")
        if not math.isfinite(self.threshold) or not 0 < self.threshold <= 1:
            raise ValueError("threshold must be finite and between 0 and 1")
        if not math.isfinite(self.score) or self.score <= 0:
            raise ValueError("score must be finite and greater than 0")


class SherpaWakeWordDetector:
    """Feed in-memory signed 16-bit PCM to a local sherpa keyword spotter."""

    def __init__(self, config: WakeWordConfig) -> None:
        model_dir = config.model_dir
        paths = {
            "encoder": model_dir
            / "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx",
            "decoder": model_dir
            / "decoder-epoch-13-avg-2-chunk-8-left-64.onnx",
            "joiner": model_dir
            / "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx",
            "tokens": model_dir / "tokens.txt",
            "keywords_file": model_dir / "keywords_lumilamp.txt",
        }
        for path in paths.values():
            if not path.is_file():
                raise FileNotFoundError(f"required wake-word model file is missing: {path}")

        import sherpa_onnx

        self._spotter: Any = sherpa_onnx.KeywordSpotter(
            tokens=str(paths["tokens"]),
            encoder=str(paths["encoder"]),
            decoder=str(paths["decoder"]),
            joiner=str(paths["joiner"]),
            keywords_file=str(paths["keywords_file"]),
            num_threads=2,
            sample_rate=SAMPLE_RATE,
            provider="cpu",
            keywords_threshold=config.threshold,
            keywords_score=config.score,
        )
        self._stream: Any = self._spotter.create_stream()

    def accept_pcm(self, samples: array[int]) -> bool:
        """Consume signed int16 PCM without retaining or logging it."""
        if not isinstance(samples, array) or samples.typecode != "h":
            raise TypeError("samples must be array('h') signed int16 PCM")

        normalized = array("f", (sample / 32768.0 for sample in samples))
        self._stream.accept_waveform(SAMPLE_RATE, normalized)

        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            if self._spotter.get_result(self._stream):
                self._spotter.reset_stream(self._stream)
                return True
        return False

    def reset(self) -> None:
        """Clear accumulated recognition state for the current stream."""
        self._spotter.reset_stream(self._stream)
