"""Concurrent Ark sentence production and strictly ordered sentence playback."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass

from .sentence_segmenter import SentenceSegmenter


SpeakSentence = Callable[[str], Awaitable[None]]
Clock = Callable[[], float]
_DONE = object()


class StreamingReplyError(RuntimeError):
    """A redacted pipeline failure with its stable owning stage."""

    def __init__(self, stage: str, sentences_played: int = 0) -> None:
        super().__init__(stage)
        self.stage = stage
        self.sentences_played = sentences_played


@dataclass(frozen=True, slots=True)
class StreamingReplyResult:
    full_text: str
    sentences_played: int
    first_sentence_at: float | None
    first_audio_at: float | None
    completed_at: float


async def stream_and_play(
    deltas: AsyncIterable[str],
    speak_sentence: SpeakSentence,
    clock: Clock,
    *,
    max_queue_size: int = 3,
) -> StreamingReplyResult:
    """Overlap text receipt with one-at-a-time sentence playback."""
    if isinstance(max_queue_size, bool) or not isinstance(max_queue_size, int):
        raise TypeError("max_queue_size must be an integer")
    if max_queue_size <= 0:
        raise ValueError("max_queue_size must be positive")

    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=max_queue_size)
    segmenter = SentenceSegmenter()
    full_text_parts: list[str] = []
    first_sentence_at: float | None = None

    async def produce() -> None:
        nonlocal first_sentence_at
        try:
            async for delta in deltas:
                if not isinstance(delta, str):
                    raise TypeError("Ark stream delta must be a string")
                full_text_parts.append(delta)
                for sentence in segmenter.push(delta):
                    if first_sentence_at is None:
                        first_sentence_at = clock()
                    await queue.put(sentence)
            for sentence in segmenter.finish():
                if first_sentence_at is None:
                    first_sentence_at = clock()
                await queue.put(sentence)
        except asyncio.CancelledError:
            raise
        except BaseException:
            await queue.put(StreamingReplyError("ark"))
        finally:
            await queue.put(_DONE)

    producer = asyncio.create_task(produce())
    sentences_played = 0
    first_audio_at: float | None = None
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            if isinstance(item, StreamingReplyError):
                raise StreamingReplyError(item.stage, sentences_played)
            if not isinstance(item, str):
                raise StreamingReplyError("ark", sentences_played)
            if first_audio_at is None:
                first_audio_at = clock()
            try:
                await speak_sentence(item)
            except asyncio.CancelledError:
                raise
            except BaseException:
                raise StreamingReplyError("tts_playback", sentences_played) from None
            sentences_played += 1
    except BaseException:
        if not producer.done():
            producer.cancel()
        try:
            await producer
        except asyncio.CancelledError:
            pass
        except BaseException:
            pass
        raise
    await producer
    if not full_text_parts or sentences_played == 0:
        raise StreamingReplyError("ark", sentences_played)
    return StreamingReplyResult(
        full_text="".join(full_text_parts),
        sentences_played=sentences_played,
        first_sentence_at=first_sentence_at,
        first_audio_at=first_audio_at,
        completed_at=clock(),
    )
