"""Pure utterance gating and network packet aggregation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .recorder import LevelConfig, pcm_level


CHUNK_MS = 20
CHUNK_BYTES = 640


@dataclass(frozen=True)
class StreamDecision:
    packets: tuple[bytes, ...]
    finished: bool
    started: bool


class UtterancePacketizer:
    """Convert fixed 20 ms PCM chunks into gated 200 ms packets."""

    def __init__(
        self,
        config: LevelConfig,
        packet_chunks: int = 10,
        pre_roll_chunks: int = 10,
    ) -> None:
        if packet_chunks <= 0:
            raise ValueError("packet_chunks must be positive")
        if not 0 <= pre_roll_chunks <= 10:
            raise ValueError("pre_roll_chunks must be between 0 and 10")
        self._config = config
        self._packet_chunks = packet_chunks
        self._pending: list[bytes] = []
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_chunks)
        self._started = False
        self._finished = False
        self._silent_ms = 0
        self._elapsed_ms = 0

    def push(self, chunk: bytes) -> StreamDecision:
        if len(chunk) != CHUNK_BYTES:
            raise ValueError("PCM chunk must contain exactly 640 bytes")
        if self._finished:
            raise RuntimeError("utterance packetizer is already finished")

        self._elapsed_ms += CHUNK_MS
        level = pcm_level(chunk)
        packets: tuple[bytes, ...] = ()
        if not self._started:
            if level >= self._config.start_threshold:
                self._started = True
                self._pending.extend(self._pre_roll)
                self._pre_roll.clear()
            else:
                self._pre_roll.append(chunk)

        if self._started:
            self._pending.append(chunk)
            if level < self._config.silence_threshold:
                self._silent_ms += CHUNK_MS
            else:
                self._silent_ms = 0
            packet_list: list[bytes] = []
            while len(self._pending) >= self._packet_chunks:
                packet_list.append(b"".join(self._pending[: self._packet_chunks]))
                del self._pending[: self._packet_chunks]
            packets = tuple(packet_list)

        self._finished = (
            self._elapsed_ms >= self._config.max_seconds * 1000
            or self._started
            and self._silent_ms >= self._config.trailing_silence_ms
        )
        if self._finished and not self._started:
            self._pre_roll.clear()
        return StreamDecision(packets, self._finished, self._started)

    def finish(self) -> tuple[bytes, ...]:
        self._pre_roll.clear()
        if not self._pending:
            return ()
        packet = b"".join(self._pending)
        self._pending.clear()
        return (packet,)
