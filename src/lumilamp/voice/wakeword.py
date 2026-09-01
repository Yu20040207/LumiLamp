"""Local sherpa-onnx wake-word detection without audio-device access."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any


SAMPLE_RATE = 16_000
WAKE_PHRASES: tuple[str, ...] = ("露米", "你好露米")

MODEL_FILES = {
    "encoder": "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx",
    "decoder": "decoder-epoch-13-avg-2-chunk-8-left-64.onnx",
    "joiner": "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx",
    "tokens": "tokens.txt",
    "keywords_file": "keywords_lumilamp.txt",
}


def validate_model_dir(model_dir: Path) -> dict[str, Path]:
    """Return the local model paths after confirming each required file exists."""
    paths = {name: model_dir / filename for name, filename in MODEL_FILES.items()}
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"required wake-word model file is missing: {path}")
    return paths


@dataclass(frozen=True)
class WakeWordConfig:
    """Configuration for approved local wake phrases."""

    model_dir: Path
    phrases: tuple[str, ...] = WAKE_PHRASES
    threshold: float = 0.25
    score: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.model_dir, Path):
            raise TypeError("model_dir must be a pathlib.Path")
        if not self.phrases:
            raise ValueError("phrases must contain at least one phrase")
        if len(set(self.phrases)) != len(self.phrases):
            raise ValueError("phrases must be unique")
        if any(phrase not in WAKE_PHRASES for phrase in self.phrases):
            raise ValueError("phrases must be supported wake phrases")
        if not math.isfinite(self.threshold) or not 0 < self.threshold <= 1:
            raise ValueError("threshold must be finite and between 0 and 1")
        if not math.isfinite(self.score) or self.score <= 0:
            raise ValueError("score must be finite and greater than 0")


class SherpaWakeWordDetector:
    """Feed in-memory signed 16-bit PCM to a local sherpa keyword spotter."""

    def __init__(self, config: WakeWordConfig) -> None:
        paths = validate_model_dir(config.model_dir)

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
        self._phrases = config.phrases

    def accept_pcm(self, samples: array[int]) -> str | None:
        """Consume signed int16 PCM and return a matched approved phrase, if any."""
        if not isinstance(samples, array) or samples.typecode != "h":
            raise TypeError("samples must be array('h') signed int16 PCM")

        normalized = array("f", (sample / 32768.0 for sample in samples))
        self._stream.accept_waveform(SAMPLE_RATE, normalized)

        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            result = self._spotter.get_result(self._stream)
            if result:
                if result not in self._phrases:
                    raise ValueError(f"unexpected wake-word result: {result}")
                self._spotter.reset_stream(self._stream)
                return result
        return None

    def reset(self) -> None:
        """Clear accumulated recognition state for the current stream."""
        self._spotter.reset_stream(self._stream)
