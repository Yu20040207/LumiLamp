import asyncio
import inspect
import unittest
from collections.abc import Awaitable, Callable, Iterable

from lumilamp.voice.conversation import ConversationController, ConversationHistory
from lumilamp.voice.state import ConversationState
from lumilamp.voice.streaming_reply import StreamingReplyResult
from lumilamp.voice.voice_loop import (
    IDLE,
    NO_SPEECH,
    SessionEndReason,
    SessionResult,
    VoiceAdapterError,
    VoiceLoop,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TrackingHistory(ConversationHistory):
    def __init__(self) -> None:
        super().__init__()
        self.appended: list[tuple[str, str]] = []
        self.clear_count = 0

    def append_turn(self, user_text: str, assistant_text: str) -> None:
        self.appended.append((user_text, assistant_text))
        super().append_turn(user_text, assistant_text)

    def clear(self) -> None:
        self.clear_count += 1
        super().clear()


class ClosableResource:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class OrderedAsyncCloseResource:
    def __init__(self, events: list[str], label: str) -> None:
        self._events = events
        self._label = label
        self.attempts = 0

    async def aclose(self) -> None:
        self.attempts += 1
        self._events.append(self._label)


class CancellingAsyncCloseResource(OrderedAsyncCloseResource):
    async def aclose(self) -> None:
        await super().aclose()
        raise asyncio.CancelledError


class FailingSyncCloseResource:
    def __init__(self, events: list[str], label: str) -> None:
        self._events = events
        self._label = label
        self.attempts = 0

    def close(self) -> None:
        self.attempts += 1
        self._events.append(self._label)
        raise RuntimeError("sync cleanup failed")


class FlakyAsyncCloseResource(OrderedAsyncCloseResource):
    def __init__(
        self,
        events: list[str],
        label: str,
        failures_before_success: int,
        failure_detail: str = "retryable cleanup detail",
    ) -> None:
        super().__init__(events, label)
        self._failures_remaining = failures_before_success
        self._failure_detail = failure_detail

    async def aclose(self) -> None:
        await super().aclose()
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise RuntimeError(self._failure_detail)


class NonClosableOwnedResource:
    def __init__(self) -> None:
        self.lookup_count = 0

    @property
    def aclose(self) -> None:
        self.lookup_count += 1
        return None

    @property
    def close(self) -> None:
        self.lookup_count += 1
        return None


class BlockingRecognizer:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = 0

    async def __call__(self) -> str:
        self.started.set()
        await asyncio.Event().wait()
        return "unreachable"

    async def aclose(self) -> None:
        self.closed += 1


class FakeAskAdapter:
    def __init__(
        self,
        history: ConversationHistory,
        answers: Iterable[object],
        events: list[str],
        test_case: unittest.TestCase,
    ) -> None:
        self._history = history
        self._answers = iter(answers)
        self._events = events
        self._test_case = test_case

    @property
    def history(self) -> ConversationHistory:
        return self._history

    async def ask(self, text: str) -> str:
        self._events.append("ark")
        value = next(self._answers)
        if isinstance(value, BaseException):
            raise value
        self._test_case.assertIsInstance(value, str)
        self._history.append_turn(text, value)
        return value


class VoiceLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_wake_motion_runs_after_reply_guard_before_recognition(self) -> None:
        clock = FakeClock()
        history = ConversationHistory()
        events: list[str] = []

        async def wake() -> str:
            return "露米"
        async def reply(_: str) -> None:
            events.append("reply")
        async def motion() -> None:
            events.append("motion")
        async def recognize() -> object:
            events.append("recognition")
            return IDLE
        async def delay(_: float) -> None:
            if not events or events[-1] == "reply":
                events.append("guard")
            clock.advance(1.0)

        class NoAsk:
            @property
            def history(self) -> ConversationHistory: return history
            async def ask(self, _: str) -> str: self.fail("not used")

        loop = VoiceLoop(ConversationController(clock, lambda choices: choices[0], timeout_seconds=0.01), wake, reply, recognize, NoAsk(), reply, clock, delay, history=history, wake_motion=motion)
        await loop.run_once()
        self.assertEqual(events[:4], ["reply", "guard", "motion", "recognition"])

    async def test_wake_motion_failure_is_logged_without_detail(self) -> None:
        clock = FakeClock(); history = ConversationHistory(); reports: list[str] = []
        async def wake() -> str: return "露米"
        async def noop(_: str) -> None: return None
        async def motion() -> None:
            error = VoiceAdapterError("serial detail")
            error.motion_stage = "status"
            raise error
        async def recognize() -> object: return IDLE
        async def delay(seconds: float) -> None: clock.advance(seconds or 1.0)
        class NoAsk:
            @property
            def history(self) -> ConversationHistory: return history
            async def ask(self, _: str) -> str: self.fail("not used")
        loop = VoiceLoop(ConversationController(clock, lambda choices: choices[0], timeout_seconds=0.01), wake, noop, recognize, NoAsk(), noop, clock, delay, history=history, wake_motion=motion, report_motion=reports.append)
        await loop.run_once()
        self.assertEqual(reports, ["wake_motion status=error stage=status"])
    async def test_stream_response_appends_history_only_after_complete_reply(self) -> None:
        clock = FakeClock()
        history = TrackingHistory()
        transcripts = iter(("问题", IDLE))

        async def wake() -> str:
            return "露米"

        async def noop(_: str) -> None:
            return None

        async def recognize() -> object:
            return next(transcripts)

        async def respond(text: str) -> StreamingReplyResult:
            clock.advance(2.0)
            return StreamingReplyResult("第一句。第二句。", 2, 1.0, 1.2, clock())

        async def delay(seconds: float) -> None:
            clock.advance(seconds)

        class NoAsk:
            @property
            def history(self) -> ConversationHistory:
                return history

            async def ask(self, _: str) -> str:
                self.fail("stream path must not call non-streaming Ark")

        loop = VoiceLoop(
            ConversationController(clock, lambda choices: choices[0], timeout_seconds=0.05),
            wake,
            noop,
            recognize,
            NoAsk(),
            noop,
            clock,
            delay,
            history=history,
            respond_to_turn=respond,
        )

        await loop.run_once()

        self.assertEqual(history.appended, [("问题", "第一句。第二句。")])

    async def test_stream_response_reports_first_sentence_and_audio_latency(self) -> None:
        clock = FakeClock()
        history = ConversationHistory()
        reports: list[str] = []
        transcripts = iter(("问题", IDLE))

        async def wake() -> str:
            return "露米"

        async def noop(_: str) -> None:
            return None

        async def recognize() -> object:
            value = next(transcripts)
            if value is not IDLE:
                clock.advance(1.0)
            return value

        async def respond(_: str) -> StreamingReplyResult:
            clock.advance(2.0)
            first_sentence_at = clock()
            clock.advance(0.5)
            first_audio_at = clock()
            clock.advance(1.5)
            return StreamingReplyResult("回答。", 1, first_sentence_at, first_audio_at, clock())

        async def delay(seconds: float) -> None:
            clock.advance(seconds)

        class NoAsk:
            @property
            def history(self) -> ConversationHistory:
                return history

            async def ask(self, _: str) -> str:
                self.fail("stream path must not call non-streaming Ark")

        loop = VoiceLoop(
            ConversationController(clock, lambda choices: choices[0], timeout_seconds=0.05),
            wake,
            noop,
            recognize,
            NoAsk(),
            noop,
            clock,
            delay,
            history=history,
            report_latency=reports.append,
            respond_to_turn=respond,
        )

        await loop.run_once()

        self.assertEqual(
            reports,
            [
                "voice_latency status=ok asr=1.00s ark_first_sentence=2.00s "
                "first_audio=2.50s answer_complete=4.00s total=5.00s"
            ],
        )

    async def test_stream_failure_logs_stable_stage_and_played_sentence_count(self) -> None:
        clock = FakeClock()
        history = ConversationHistory()
        reports: list[str] = []
        transcripts = iter(("问题", "再问一次"))

        async def wake() -> str:
            return "露米"

        async def noop(_: str) -> None:
            return None

        async def recognize() -> object:
            clock.advance(1.0)
            return next(transcripts)

        async def respond(_: str) -> StreamingReplyResult:
            clock.advance(2.0)
            error = VoiceAdapterError("redacted")
            error.failure_stage = "ark"
            error.sentences_played = 1
            raise error

        async def delay(seconds: float) -> None:
            clock.advance(seconds)

        class NoAsk:
            @property
            def history(self) -> ConversationHistory:
                return history

            async def ask(self, _: str) -> str:
                self.fail("stream path must not call non-streaming Ark")

        loop = VoiceLoop(
            ConversationController(clock, lambda choices: choices[0]),
            wake,
            noop,
            recognize,
            NoAsk(),
            noop,
            clock,
            delay,
            history=history,
            report_latency=reports.append,
            respond_to_turn=respond,
        )

        await loop.run_once()

        self.assertEqual(
            reports[0],
            "voice_latency status=error failure_stage=ark sentences_played=1 "
            "asr=1.00s ark=2.00s total=3.00s",
        )

    async def test_reports_successful_turn_stage_latencies(self) -> None:
        clock = FakeClock()
        history = ConversationHistory()
        transcripts = iter(("问题", IDLE))
        reports: list[str] = []

        async def listen_for_wake() -> str:
            return "露米"

        async def play(_: str) -> None:
            return None

        async def recognize() -> object:
            value = next(transcripts)
            if value is not IDLE:
                clock.advance(1.2)
            return value

        class TimedAsker:
            @property
            def history(self) -> ConversationHistory:
                return history

            async def ask(self, text: str) -> str:
                clock.advance(7.3)
                history.append_turn(text, "回答")
                return "回答"

        async def speak(_: str) -> None:
            clock.advance(1.1)

        async def delay(seconds: float) -> None:
            clock.advance(seconds)

        loop = VoiceLoop(
            ConversationController(clock, lambda choices: choices[0], timeout_seconds=0.05),
            listen_for_wake,
            play,
            recognize,
            TimedAsker(),
            speak,
            clock,
            delay,
            history=history,
            report_latency=reports.append,
        )

        await loop.run_once()

        self.assertEqual(
            reports,
            ["voice_latency status=ok asr=1.20s ark=7.30s tts_playback=1.10s total=9.60s"],
        )

    async def test_reports_failed_stage_without_exception_detail(self) -> None:
        clock = FakeClock()
        history = ConversationHistory()
        reports: list[str] = []

        async def listen_for_wake() -> str:
            return "露米"

        async def play(_: str) -> None:
            return None

        async def recognize() -> str:
            clock.advance(1.0)
            return "问题"

        class FailingAsker:
            @property
            def history(self) -> ConversationHistory:
                return history

            async def ask(self, _: str) -> str:
                clock.advance(2.0)
                raise VoiceAdapterError("provider-secret")

        async def delay(seconds: float) -> None:
            clock.advance(seconds)

        loop = VoiceLoop(
            ConversationController(clock, lambda choices: choices[0]),
            listen_for_wake,
            play,
            recognize,
            FailingAsker(),
            play,
            clock,
            delay,
            history=history,
            report_latency=reports.append,
        )

        await loop.run_once()

        self.assertEqual(
            reports[0],
            "voice_latency status=error failure_stage=ark asr=1.00s ark=2.00s total=3.00s",
        )
        self.assertNotIn("provider-secret", reports[0])

    async def test_rejects_ask_adapter_bound_to_different_history(self) -> None:
        clock = FakeClock()
        history = ConversationHistory()
        other_history = ConversationHistory()
        asker = FakeAskAdapter(other_history, ["回答"], [], self)

        async def no_argument() -> str:
            return "露米"

        async def one_argument(value: object) -> None:
            return None

        controller = ConversationController(clock, lambda choices: choices[0])

        with self.assertRaisesRegex(ValueError, "history"):
            VoiceLoop(
                controller,
                no_argument,
                one_argument,
                no_argument,
                asker,
                one_argument,
                clock,
                one_argument,
                history=history,
            )

    async def test_history_must_be_explicitly_injected(self) -> None:
        clock = FakeClock()

        async def no_argument() -> str:
            return "露米"

        async def one_argument(text: str) -> None:
            return None

        async def ask(text: str) -> str:
            return "回答"

        controller = ConversationController(clock, lambda choices: choices[0])

        with self.assertRaises(TypeError):
            VoiceLoop(
                controller,
                no_argument,
                one_argument,
                no_argument,
                ask,
                one_argument,
                clock,
                one_argument,
            )

    def make_loop(
        self,
        *,
        wakes: Iterable[str] = ("露米",),
        transcripts: Iterable[object] = (IDLE,),
        ark_answers: Iterable[object] = (),
        events: list[str] | None = None,
        history: ConversationHistory | None = None,
        owned_resources: Iterable[object] = (),
        playback_failure: str | None = None,
        recognizer: Callable[[], Awaitable[object]] | None = None,
        timeout_seconds: float = 0.05,
    ) -> tuple[VoiceLoop, FakeClock]:
        recorded = events if events is not None else []
        wake_values = iter(wakes)
        transcript_values = iter(transcripts)
        session_history = history if history is not None else ConversationHistory()
        clock = FakeClock()
        playback_active = False
        recognize_active = False

        async def listen_for_wake() -> str:
            wake = next(wake_values)
            recorded.append(f"wake:{wake}")
            return wake

        async def play_cached_reply(text: str) -> None:
            nonlocal playback_active
            self.assertFalse(recognize_active)
            playback_active = True
            recorded.append("play_wake")
            try:
                if playback_failure == "wake":
                    raise VoiceAdapterError("speaker path and credentials are secret")
            finally:
                playback_active = False

        async def recognize_turn() -> object:
            nonlocal recognize_active
            self.assertFalse(playback_active)
            recognize_active = True
            recorded.append("asr")
            try:
                value = next(transcript_values)
                if isinstance(value, BaseException):
                    raise value
                return value
            finally:
                recognize_active = False

        async def speak(text: str) -> None:
            nonlocal playback_active
            self.assertFalse(recognize_active)
            playback_active = True
            recorded.append("tts")
            try:
                if playback_failure == "answer":
                    raise VoiceAdapterError("audio device details must not escape")
            finally:
                playback_active = False

        async def delay(seconds: float) -> None:
            recorded.append(f"delay:{seconds:.1f}")
            clock.advance(seconds)

        controller = ConversationController(
            clock, lambda choices: choices[0], timeout_seconds=timeout_seconds
        )
        asker = FakeAskAdapter(session_history, ark_answers, recorded, self)
        return (
            VoiceLoop(
                controller,
                listen_for_wake,
                play_cached_reply,
                recognize_turn if recognizer is None else recognizer,
                asker,
                speak,
                clock,
                delay,
                history=session_history,
                owned_resources=owned_resources,
            ),
            clock,
        )

    async def test_two_turns_then_idle_sleep(self) -> None:
        events: list[str] = []
        history = TrackingHistory()
        loop, _ = self.make_loop(
            transcripts=["你是谁", "今天天气怎么样", IDLE],
            ark_answers=["我是露米。", "今天适合出门。"],
            events=events,
            history=history,
        )

        result = await loop.run_once()

        self.assertEqual(result.turns, 2)
        self.assertEqual(result.reason, "idle_timeout")
        self.assertEqual(
            events,
            [
                "wake:露米",
                "play_wake",
                "delay:0.3",
                "asr",
                "ark",
                "tts",
                "delay:0.3",
                "asr",
                "ark",
                "tts",
                "delay:0.3",
                "asr",
                "delay:0.1",
            ],
        )
        self.assertEqual(
            history.appended,
            [("你是谁", "我是露米。"), ("今天天气怎么样", "今天适合出门。")],
        )
        self.assertEqual(history.messages(), [])
        self.assertEqual(history.clear_count, 1)
        self.assertIs(loop.controller.state, ConversationState.SLEEPING)

    async def test_playback_guards_use_injected_delay_and_prevent_overlap(self) -> None:
        events: list[str] = []
        loop, _ = self.make_loop(
            transcripts=["你好", IDLE], ark_answers=["你好呀"], events=events
        )

        await loop.run_once()

        self.assertEqual(events.count("delay:0.3"), 2)
        self.assertLess(events.index("play_wake"), events.index("asr"))
        self.assertLess(events.index("tts"), events.index("asr", 4))

    async def test_empty_and_no_speech_never_call_ark_or_tts(self) -> None:
        events: list[str] = []
        loop, _ = self.make_loop(
            transcripts=["  ", NO_SPEECH, IDLE],
            timeout_seconds=0.14,
            events=events,
        )

        result = await loop.run_once()

        self.assertEqual(result.reason, SessionEndReason.IDLE_TIMEOUT)
        self.assertEqual(result.turns, 0)
        self.assertEqual(events.count("asr"), 3)
        self.assertNotIn("ark", events)
        self.assertNotIn("tts", events)

    async def test_early_idle_result_continues_until_deadline(self) -> None:
        loop, clock = self.make_loop(timeout_seconds=30.0)
        recognition_times: list[float] = []
        delays: list[float] = []

        async def immediate_idle() -> object:
            if recognition_times and clock.now <= recognition_times[-1]:
                self.fail("immediate IDLE was polled again without positive delay")
            recognition_times.append(clock.now)
            return IDLE

        async def advancing_delay(seconds: float) -> None:
            delays.append(seconds)
            clock.advance(seconds)

        loop.recognize_turn = immediate_idle
        loop.delay = advancing_delay

        result = await loop.run_once()

        self.assertEqual(result.reason, SessionEndReason.IDLE_TIMEOUT)
        self.assertGreater(len(recognition_times), 1)
        self.assertGreater(min(delays[1:]), 0.0)
        self.assertGreaterEqual(clock.now, 30.3)

    async def test_two_consecutive_asr_failures_sleep_and_clear_history(self) -> None:
        history = TrackingHistory()
        loop, _ = self.make_loop(
            transcripts=[VoiceAdapterError("first"), VoiceAdapterError("second")],
            history=history,
        )

        result = await loop.run_once()

        self.assertEqual(result.reason, "two_failures")
        self.assertEqual(result.error_category, "asr")
        self.assertEqual(history.clear_count, 1)
        self.assertIs(loop.controller.state, ConversationState.SLEEPING)

    async def test_two_consecutive_ark_failures_are_recoverable(self) -> None:
        history = TrackingHistory()
        events: list[str] = []
        loop, _ = self.make_loop(
            transcripts=["问题一", "问题二"],
            ark_answers=[VoiceAdapterError("secret one"), VoiceAdapterError("secret two")],
            events=events,
            history=history,
        )

        result = await loop.run_once()

        self.assertEqual(result.reason, "two_failures")
        self.assertEqual(result.error_category, "ark")
        self.assertEqual(events.count("ark"), 2)
        self.assertNotIn("tts", events)
        self.assertNotIn("secret", repr(result))
        self.assertEqual(history.clear_count, 1)

    async def test_successful_turn_resets_consecutive_failure_count(self) -> None:
        loop, _ = self.make_loop(
            transcripts=[
                VoiceAdapterError("first"),
                "恢复了",
                VoiceAdapterError("new first"),
                IDLE,
            ],
            ark_answers=["好的"],
        )

        result = await loop.run_once()

        self.assertEqual(result.reason, "idle_timeout")
        self.assertEqual(result.turns, 1)

    async def test_wake_playback_failure_ends_immediately(self) -> None:
        history = TrackingHistory()
        events: list[str] = []
        loop, _ = self.make_loop(
            transcripts=["must not be read"],
            events=events,
            history=history,
            playback_failure="wake",
        )

        result = await loop.run_once()

        self.assertEqual(result.reason, "playback_error")
        self.assertEqual(result.error_category, "playback")
        self.assertEqual(events, ["wake:露米", "play_wake"])
        self.assertEqual(history.clear_count, 1)
        self.assertIs(loop.controller.state, ConversationState.SLEEPING)

    async def test_answer_playback_failure_ends_without_another_recognition(self) -> None:
        events: list[str] = []
        loop, _ = self.make_loop(
            transcripts=["你好", "must not be read"],
            ark_answers=["你好"],
            events=events,
            playback_failure="answer",
        )

        result = await loop.run_once()

        self.assertEqual(result.reason, "playback_error")
        self.assertEqual(events.count("asr"), 1)
        self.assertNotIn("delay:0.3", events[events.index("tts") + 1 :])

    async def test_cancellation_cleans_session_and_only_owned_resources(self) -> None:
        history = TrackingHistory()
        owned = ClosableResource()
        unrelated = ClosableResource()
        started = asyncio.Event()

        async def recognize_forever() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        loop, _ = self.make_loop(history=history, owned_resources=[owned])
        loop.recognize_turn = recognize_forever
        task = asyncio.create_task(loop.run_once())
        await started.wait()

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(owned.closed, 1)
        self.assertEqual(unrelated.closed, 0)
        self.assertEqual(history.clear_count, 1)
        self.assertIs(loop.controller.state, ConversationState.SLEEPING)

    async def test_cancellation_does_not_close_shared_injected_adapter(self) -> None:
        recognizer = BlockingRecognizer()
        loop, _ = self.make_loop(recognizer=recognizer)
        task = asyncio.create_task(loop.run_once())
        await recognizer.started.wait()

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(recognizer.closed, 0)

    async def test_cleanup_cancellation_has_priority_and_does_not_skip_resources(
        self,
    ) -> None:
        events: list[str] = []
        closes_second = OrderedAsyncCloseResource(events, "second")
        cancels_first = CancellingAsyncCloseResource(events, "first-cancel")
        fails_third = FailingSyncCloseResource(events, "third-error")
        loop, _ = self.make_loop(
            owned_resources=[fails_third, closes_second, cancels_first],
        )

        with self.assertRaises(asyncio.CancelledError):
            await loop._close_owned_resources()

        self.assertEqual(events, ["first-cancel", "second", "third-error"])
        with self.assertRaises(asyncio.CancelledError):
            await loop._close_owned_resources()
        self.assertEqual(cancels_first.attempts, 2)
        self.assertEqual(closes_second.attempts, 1)
        self.assertEqual(fails_third.attempts, 2)

    async def test_partial_cleanup_retries_only_failures_then_becomes_idempotent(
        self,
    ) -> None:
        events: list[str] = []
        closes_third = OrderedAsyncCloseResource(events, "third")
        fails_second = FlakyAsyncCloseResource(
            events,
            "second-error",
            1,
            "second retryable cleanup detail",
        )
        fails_first = FlakyAsyncCloseResource(
            events,
            "first-error",
            1,
            "first retryable cleanup detail",
        )
        loop, _ = self.make_loop(
            owned_resources=[closes_third, fails_second, fails_first]
        )

        with self.assertRaisesRegex(RuntimeError, "first retryable cleanup detail"):
            await loop._close_owned_resources()

        self.assertEqual(events, ["first-error", "second-error", "third"])
        await loop._close_owned_resources()
        await loop._close_owned_resources()
        self.assertEqual(
            events,
            [
                "first-error",
                "second-error",
                "third",
                "first-error",
                "second-error",
            ],
        )
        self.assertEqual(fails_first.attempts, 2)
        self.assertEqual(fails_second.attempts, 2)
        self.assertEqual(closes_third.attempts, 1)

    async def test_non_closable_owned_resource_is_idempotently_complete(self) -> None:
        resource = NonClosableOwnedResource()
        loop, _ = self.make_loop(owned_resources=[resource])

        await loop._close_owned_resources()
        await loop._close_owned_resources()

        self.assertEqual(resource.lookup_count, 2)

    async def test_run_once_body_error_wins_over_cleanup_error_with_type_note(
        self,
    ) -> None:
        events: list[str] = []
        closes_second = OrderedAsyncCloseResource(events, "second")
        fails_first = FailingSyncCloseResource(events, "first-error")
        primary = AssertionError("programming body detail")

        async def fail_recognition() -> str:
            raise primary

        loop, _ = self.make_loop(
            owned_resources=[closes_second, fails_first],
            recognizer=fail_recognition,
        )

        raised: BaseException | None = None
        try:
            await loop.run_once()
        except BaseException as error:
            raised = error
        else:
            self.fail("body failure did not propagate")

        self.assertIs(raised, primary)
        self.assertEqual(
            getattr(raised, "__notes__", []),
            ["owned VoiceLoop resource cleanup also failed: RuntimeError"],
        )
        self.assertEqual(events, ["first-error", "second"])

    async def test_run_once_cancellation_wins_over_cleanup_error_with_type_note(
        self,
    ) -> None:
        events: list[str] = []
        closes_second = OrderedAsyncCloseResource(events, "second")
        fails_first = FailingSyncCloseResource(events, "first-error")
        started = asyncio.Event()

        async def recognize_forever() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        loop, _ = self.make_loop(
            owned_resources=[closes_second, fails_first],
            recognizer=recognize_forever,
        )
        task = asyncio.create_task(loop.run_once())
        await started.wait()

        task.cancel("caller cancellation detail")
        with self.assertRaises(asyncio.CancelledError) as raised:
            await task

        self.assertEqual(raised.exception.args, ("caller cancellation detail",))
        self.assertEqual(
            getattr(raised.exception, "__notes__", []),
            ["owned VoiceLoop resource cleanup also failed: RuntimeError"],
        )
        self.assertEqual(events, ["first-error", "second"])
        with self.assertRaisesRegex(RuntimeError, "sync cleanup failed"):
            await loop._close_owned_resources()
        self.assertEqual(fails_first.attempts, 2)
        self.assertEqual(closes_second.attempts, 1)

    async def test_unexpected_error_clears_history_and_propagates(self) -> None:
        history = TrackingHistory()
        loop, _ = self.make_loop(history=history)

        async def broken_recognizer() -> str:
            raise AssertionError("programming bug")

        loop.recognize_turn = broken_recognizer

        with self.assertRaisesRegex(AssertionError, "programming bug"):
            await loop.run_once()

        self.assertEqual(history.clear_count, 1)
        self.assertIs(loop.controller.state, ConversationState.SLEEPING)

    async def test_only_injected_voice_collaborators_are_used(self) -> None:
        events: list[str] = []
        loop, _ = self.make_loop(transcripts=[IDLE], events=events)

        await loop.run_once()

        self.assertEqual(
            events,
            ["wake:露米", "play_wake", "delay:0.3", "asr", "delay:0.1"],
        )
        collaborators = (
            loop.listen_for_wake,
            loop.play_cached_reply,
            loop.recognize_turn,
            loop.asker.ask,
            loop.speak,
            loop.delay,
        )
        self.assertTrue(all(callable(collaborator) for collaborator in collaborators))
        self.assertTrue(all(inspect.iscoroutinefunction(item) for item in collaborators))

    async def test_run_forever_yields_between_synchronous_sessions(self) -> None:
        loop, _ = self.make_loop()
        sessions = 0
        sibling_ran = asyncio.Event()

        async def instant_session() -> SessionResult:
            nonlocal sessions
            sessions += 1
            if sessions > 1:
                if not sibling_ran.is_set():
                    self.fail("ready sibling task was starved by run_forever")
                raise asyncio.CancelledError
            return SessionResult(0, SessionEndReason.IDLE_TIMEOUT)

        async def non_suspending_delay(seconds: float) -> None:
            return None

        async def ready_sibling() -> None:
            sibling_ran.set()

        loop.run_once = instant_session
        loop.delay = non_suspending_delay
        voice_task = asyncio.create_task(loop.run_forever())
        sibling_task = asyncio.create_task(ready_sibling())

        with self.assertRaises(asyncio.CancelledError):
            await voice_task
        await sibling_task

        self.assertEqual(sessions, 2)
        self.assertTrue(sibling_ran.is_set())

    async def test_run_forever_cancellation_at_yield_cleans_owned_state(self) -> None:
        history = TrackingHistory()
        history.append_turn("问题", "回答")
        owned = ClosableResource()
        loop, _ = self.make_loop(history=history, owned_resources=[owned])
        sessions = 0

        async def instant_session() -> SessionResult:
            nonlocal sessions
            sessions += 1
            if sessions > 1:
                self.fail("run_forever skipped its cancellation yield")
            return SessionResult(1, SessionEndReason.IDLE_TIMEOUT)

        async def cancel_at_yield(seconds: float) -> None:
            raise asyncio.CancelledError

        loop.run_once = instant_session
        loop.delay = cancel_at_yield

        with self.assertRaises(asyncio.CancelledError):
            await loop.run_forever()

        self.assertEqual(history.messages(), [])
        self.assertEqual(owned.closed, 1)


if __name__ == "__main__":
    unittest.main()
