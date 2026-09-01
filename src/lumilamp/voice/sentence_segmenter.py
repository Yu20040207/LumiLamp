"""Pure incremental segmentation for naturally spoken Chinese short sentences."""

from __future__ import annotations


TERMINATORS = frozenset("。！？；")
FALLBACK_BOUNDARIES = frozenset("，、")


class SentenceSegmenter:
    """Buffer text deltas until a natural or bounded sentence is available."""

    def __init__(self, max_chars: int = 30) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int):
            raise TypeError("max_chars must be an integer")
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars
        self._buffer = ""

    def push(self, delta: str) -> list[str]:
        """Append one text fragment and return every newly complete sentence."""
        if not isinstance(delta, str):
            raise TypeError("delta must be a string")
        if not delta.strip():
            return []
        self._buffer += delta
        return self._drain_complete()

    def finish(self) -> list[str]:
        """Return an unfinished final sentence once, if it contains text."""
        residual = self._buffer.strip()
        self._buffer = ""
        return [residual] if residual else []

    def _drain_complete(self) -> list[str]:
        sentences: list[str] = []
        while self._buffer:
            terminator_index = next(
                (
                    index
                    for index, character in enumerate(self._buffer)
                    if character in TERMINATORS
                ),
                None,
            )
            if terminator_index is not None:
                sentences.append(self._take(terminator_index + 1))
                continue
            if len(self._buffer) < self._max_chars:
                break
            boundary_index = max(
                (
                    index
                    for index, character in enumerate(
                        self._buffer[: self._max_chars]
                    )
                    if character in FALLBACK_BOUNDARIES
                ),
                default=-1,
            )
            sentences.append(
                self._take(boundary_index + 1 if boundary_index >= 0 else self._max_chars)
            )
        return sentences

    def _take(self, end: int) -> str:
        sentence = self._buffer[:end].strip()
        self._buffer = self._buffer[end:]
        return sentence
