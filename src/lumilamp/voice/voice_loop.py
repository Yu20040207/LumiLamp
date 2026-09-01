"""Purely injected, half-duplex orchestration for one voice session."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from .conversation import ConversationController, ConversationHistory
from .state import ConversationState
from .streaming_reply import StreamingReplyResult


PLAYBACK_GUARD_SECONDS: Final = 0.3
NO_INPUT_POLL_SECONDS: Final = 0.05
OWNED_RESOURCE_CLEANUP_NOTE: Final = (
    "owned VoiceLoop resource cleanup also failed: "
)


@dataclass(frozen=True, slots=True)
class IdleTimeout:
    """A recognizer result indicating that the listening window expired."""


@dataclass(frozen=True, slots=True)
class NoSpeech:
    """A recognizer result indicating that audio contained no usable speech."""


IDLE: Final = IdleTimeout()
NO_SPEECH: Final = NoSpeech()

RecognitionResult = str | IdleTimeout | NoSpeech
ListenForWake = Callable[[], Awaitable[str]]
PlayCachedReply = Callable[[str], Awaitable[None]]
RecognizeTurn = Callable[[], Awaitable[RecognitionResult]]
Speak = Callable[[str], Awaitable[None]]
WakeMotion = Callable[[], Awaitable[None]]
Clock = Callable[[], float]
Delay = Callable[[float], Awaitable[None]]
ReportLatency = Callable[[str], None]
ReportMotion = Callable[[str], None]
RespondToTurn = Callable[[str], Awaitable[StreamingReplyResult]]


class AskAdapter(Protocol):
    """Ark-like adapter whose session history ownership is observable."""

    @property
    def history(self) -> ConversationHistory: ...

    async def ask(self, text: str) -> str: ...


class VoiceAdapterError(Exception):
    """A documented, operational failure from an injected voice adapter."""


class SessionEndReason(StrEnum):
    IDLE_TIMEOUT = "idle_timeout"
    TWO_FAILURES = "two_failures"
    PLAYBACK_ERROR = "playback_error"


class ErrorCategory(StrEnum):
    ASR = "asr"
    ARK = "ark"
    PLAYBACK = "playback"


@dataclass(frozen=True, slots=True)
class SessionResult:
    turns: int
    reason: SessionEndReason
    error_category: ErrorCategory | None = None


class VoiceLoop:
    """Coordinate injected wake, ASR, answer, and playback adapters serially."""

    def __init__(
        self,
        controller: ConversationController,
        listen_for_wake: ListenForWake,
        play_cached_reply: PlayCachedReply,
        recognize_turn: RecognizeTurn,
        asker: AskAdapter,
        speak: Speak,
        clock: Clock,
        delay: Delay,
        *,
        history: ConversationHistory,
        owned_resources: Iterable[object] = (),
        report_latency: ReportLatency | None = None,
        respond_to_turn: RespondToTurn | None = None,
        wake_motion: WakeMotion | None = None,
        report_motion: ReportMotion | None = None,
    ) -> None:
        self.controller = controller
        self.listen_for_wake = listen_for_wake
        self.play_cached_reply = play_cached_reply
        self.recognize_turn = recognize_turn
        if getattr(asker, "history", None) is not history:
            raise ValueError("ask adapter and voice loop must share the same history")
        self.asker = asker
        self.speak = speak
        self.clock = clock
        self.delay = delay
        self.history = history
        self.report_latency = report_latency
        self.respond_to_turn = respond_to_turn
        self.wake_motion = wake_motion
        self.report_motion = report_motion
        resources = tuple(owned_resources)
        self._owned_resources = tuple(
            resource
            for index, resource in enumerate(resources)
            if all(resource is not earlier for earlier in resources[:index])
        )
        self._closed_owned_resources: list[object] = []
        self._resources_closed = not self._owned_resources

    async def run_forever(self) -> None:
        """Run complete wake-to-sleep sessions until the caller cancels."""
        while True:
            await self.run_once()
            try:
                await self.delay(0.0)
                await asyncio.sleep(0)
            except BaseException as primary_error:
                self._terminate_session()
                await self._close_owned_resources_after(primary_error)
                raise

    async def run_once(self) -> SessionResult:
        """Run one wake-to-sleep session and return its redacted outcome."""
        try:
            return await self._run_session()
        except BaseException as primary_error:
            self._terminate_session()
            await self._close_owned_resources_after(primary_error)
            raise

    async def _run_session(self) -> SessionResult:
        await self.listen_for_wake()
        wake_reply = self.controller.wake()
        try:
            await self.play_cached_reply(wake_reply)
        except VoiceAdapterError:
            return self._finish(
                0, SessionEndReason.PLAYBACK_ERROR, ErrorCategory.PLAYBACK
            )

        self.controller.finish_playback()
        await self._wait_for_playback_guard()

        if self.wake_motion is not None:
            try:
                await self.wake_motion()
            except VoiceAdapterError as error:
                if self.report_motion is not None:
                    stage = getattr(error, "motion_stage", "unknown")
                    self.report_motion(f"wake_motion status=error stage={stage}")
            else:
                if self.report_motion is not None:
                    self.report_motion("wake_motion status=ok")

        turns = 0
        while True:
            turn_started = self.clock()
            self.controller.begin_recognition()
            asr_started = self.clock()
            try:
                recognized = await self.recognize_turn()
            except VoiceAdapterError:
                self._emit_latency(
                    "error",
                    turn_started,
                    failure_stage="asr",
                    asr=self.clock() - asr_started,
                )
                if self.controller.record_failure():
                    return self._finish(
                        turns, SessionEndReason.TWO_FAILURES, ErrorCategory.ASR
                    )
                continue

            if (
                isinstance(recognized, (IdleTimeout, NoSpeech))
                or not recognized.strip()
            ):
                self.controller.finish_recognition_without_input()
                await self.delay(NO_INPUT_POLL_SECONDS)
                if self.controller.expire_if_idle():
                    return self._finish(turns, SessionEndReason.IDLE_TIMEOUT)
                continue

            user_text = recognized.strip()
            self.controller.begin_thinking()
            if self.respond_to_turn is not None:
                asr_elapsed = self.clock() - asr_started
                ark_started = self.clock()
                try:
                    self.controller.begin_speaking()
                    streamed = await self.respond_to_turn(user_text)
                except VoiceAdapterError as error:
                    failure_stage = getattr(error, "failure_stage", "ark")
                    self._emit_latency(
                        "error",
                        turn_started,
                        failure_stage=failure_stage,
                        sentences_played=getattr(error, "sentences_played", None),
                        asr=asr_elapsed,
                        ark=self.clock() - ark_started,
                    )
                    if self.controller.record_failure():
                        return self._finish(
                            turns,
                            SessionEndReason.TWO_FAILURES,
                            (
                                ErrorCategory.PLAYBACK
                                if failure_stage == "tts_playback"
                                else ErrorCategory.ARK
                            ),
                        )
                    continue
                self._emit_latency(
                    "ok",
                    turn_started,
                    asr=asr_elapsed,
                    ark_first_sentence=(
                        streamed.first_sentence_at - ark_started
                        if streamed.first_sentence_at is not None
                        else None
                    ),
                    first_audio=(
                        streamed.first_audio_at - ark_started
                        if streamed.first_audio_at is not None
                        else None
                    ),
                    answer_complete=streamed.completed_at - ark_started,
                )
                self.history.append_turn(user_text, streamed.full_text)
                turns += 1
                self.controller.finish_turn()
                await self._wait_for_playback_guard()
                continue
            asr_elapsed = self.clock() - asr_started
            ark_started = self.clock()
            try:
                answer = await self.asker.ask(user_text)
            except VoiceAdapterError:
                self._emit_latency(
                    "error",
                    turn_started,
                    failure_stage="ark",
                    asr=asr_elapsed,
                    ark=self.clock() - ark_started,
                )
                if self.controller.record_failure():
                    return self._finish(
                        turns, SessionEndReason.TWO_FAILURES, ErrorCategory.ARK
                    )
                continue

            if not isinstance(answer, str) or not answer.strip():
                if self.controller.record_failure():
                    return self._finish(
                        turns, SessionEndReason.TWO_FAILURES, ErrorCategory.ARK
                    )
                continue

            assistant_text = answer.strip()
            self.controller.begin_speaking()
            ark_elapsed = self.clock() - ark_started
            tts_started = self.clock()
            try:
                await self.speak(assistant_text)
            except VoiceAdapterError:
                self._emit_latency(
                    "error",
                    turn_started,
                    failure_stage="tts_playback",
                    asr=asr_elapsed,
                    ark=ark_elapsed,
                    tts_playback=self.clock() - tts_started,
                )
                return self._finish(
                    turns, SessionEndReason.PLAYBACK_ERROR, ErrorCategory.PLAYBACK
                )

            self._emit_latency(
                "ok",
                turn_started,
                asr=asr_elapsed,
                ark=ark_elapsed,
                tts_playback=self.clock() - tts_started,
            )
            turns += 1
            self.controller.finish_turn()
            await self._wait_for_playback_guard()

    async def _wait_for_playback_guard(self) -> None:
        await self.delay(PLAYBACK_GUARD_SECONDS)
        if not self.controller.ready_after_playback():
            raise RuntimeError("injected delay did not satisfy playback guard")

    def _emit_latency(
        self,
        status: str,
        turn_started: float,
        *,
        failure_stage: str | None = None,
        sentences_played: int | None = None,
        asr: float | None = None,
        ark: float | None = None,
        tts_playback: float | None = None,
        ark_first_sentence: float | None = None,
        first_audio: float | None = None,
        answer_complete: float | None = None,
    ) -> None:
        if self.report_latency is None:
            return
        fields = ["voice_latency", f"status={status}"]
        if failure_stage is not None:
            fields.append(f"failure_stage={failure_stage}")
        if sentences_played is not None:
            fields.append(f"sentences_played={sentences_played}")
        for name, elapsed in (
            ("asr", asr),
            ("ark", ark),
            ("tts_playback", tts_playback),
            ("ark_first_sentence", ark_first_sentence),
            ("first_audio", first_audio),
            ("answer_complete", answer_complete),
        ):
            if elapsed is not None:
                fields.append(f"{name}={elapsed:.2f}s")
        fields.append(f"total={self.clock() - turn_started:.2f}s")
        self.report_latency(" ".join(fields))

    def _finish(
        self,
        turns: int,
        reason: SessionEndReason,
        error_category: ErrorCategory | None = None,
    ) -> SessionResult:
        self._terminate_session()
        return SessionResult(turns, reason, error_category)

    def _terminate_session(self) -> None:
        while self.controller.state is not ConversationState.SLEEPING:
            if self.controller.record_failure():
                break
        self.history.clear()

    async def _close_owned_resources_after(
        self, primary_error: BaseException
    ) -> None:
        try:
            await self._close_owned_resources()
        except BaseException as cleanup_error:
            primary_error.add_note(
                f"{OWNED_RESOURCE_CLEANUP_NOTE}{type(cleanup_error).__name__}"
            )

    async def _close_owned_resources(self) -> None:
        if self._resources_closed:
            return
        cancellation: asyncio.CancelledError | None = None
        first_error: BaseException | None = None
        for resource in reversed(self._owned_resources):
            if any(
                resource is closed_resource
                for closed_resource in self._closed_owned_resources
            ):
                continue
            try:
                close = getattr(resource, "aclose", None)
                if close is None:
                    close = getattr(resource, "close", None)
                if close is None or not callable(close):
                    self._closed_owned_resources.append(resource)
                    continue
                result = close()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
            except BaseException as error:
                if first_error is None:
                    first_error = error
            else:
                self._closed_owned_resources.append(resource)

        self._resources_closed = len(self._closed_owned_resources) == len(
            self._owned_resources
        )
        if cancellation is not None:
            raise cancellation
        if first_error is not None:
            raise first_error
