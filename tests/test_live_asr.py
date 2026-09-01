import asyncio
import gzip
import json
import struct
import unittest
from unittest.mock import AsyncMock, patch

from lumilamp.voice.config import AsrConfig
from lumilamp.voice.live_asr import recognize_microphone, terminate_owned_process
from lumilamp.voice.recorder import LevelConfig


def server_result_frame(text: str, flags: int, sequence: int) -> bytes:
    body = json.dumps({"result": {"text": text}}).encode()
    return (
        bytes((0x11, 0x90 | flags, 0x10, 0x00))
        + struct.pack(">i", sequence)
        + struct.pack(">I", len(body))
        + body
    )


class FakeStdout:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.read_count = 0

    async def readexactly(self, size: int) -> bytes:
        try:
            chunk = next(self._chunks)
        except StopIteration:
            raise asyncio.IncompleteReadError(b"", size) from None
        if len(chunk) != size:
            raise AssertionError(f"expected read size {size}, got {len(chunk)}")
        self.read_count += 1
        return chunk


class BlockingStdout:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def readexactly(self, size: int) -> bytes:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class SpeechThenFailureStdout:
    def __init__(self, speech: bytes, receiver_failed: asyncio.Event) -> None:
        self._speech = speech
        self._receiver_failed = receiver_failed
        self._read_count = 0

    async def readexactly(self, size: int) -> bytes:
        self._read_count += 1
        if self._read_count == 1:
            return self._speech
        await self._receiver_failed.wait()
        raise ValueError("body failed")


class SpeechThenBlockingStdout:
    def __init__(self, speech: bytes, receiver_failed: asyncio.Event) -> None:
        self._speech = speech
        self._receiver_failed = receiver_failed
        self._read_count = 0
        self.body_blocked = asyncio.Event()

    async def readexactly(self, size: int) -> bytes:
        self._read_count += 1
        if self._read_count == 1:
            return self._speech
        await self._receiver_failed.wait()
        self.body_blocked.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FakeProcess:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = FakeStdout(chunks)
        self.stderr = FakeStdout([])
        self.returncode = None
        self.terminated = False
        self.waited = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    async def wait(self) -> int:
        self.waited = True
        return self.returncode or 0


class CleanupProcess:
    def __init__(
        self,
        waits: list[str],
        *,
        returncode: int | None = None,
        term_lookup: bool = False,
        kill_lookup: bool = False,
    ) -> None:
        self.returncode = returncode
        self._waits = iter(waits)
        self._term_lookup = term_lookup
        self._kill_lookup = kill_lookup
        self.terminate_count = 0
        self.kill_count = 0
        self.wait_count = 0
        self.wait_started = asyncio.Event()

    def terminate(self) -> None:
        self.terminate_count += 1
        if self._term_lookup:
            raise ProcessLookupError

    def kill(self) -> None:
        self.kill_count += 1
        if self._kill_lookup:
            raise ProcessLookupError

    async def wait(self) -> int:
        self.wait_count += 1
        behavior = next(self._waits)
        self.wait_started.set()
        if behavior == "hang":
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        if self.returncode is None:
            self.returncode = -9 if self.kill_count else -15
        return self.returncode


class NonCooperativeCleanupProcess:
    """A process whose wait coroutine deliberately ignores cancellation."""

    def __init__(self) -> None:
        self.returncode = None
        self.terminate_count = 0
        self.kill_count = 0
        self.release = asyncio.Event()
        self.waiter_tasks: list[asyncio.Task[int]] = []

    def terminate(self) -> None:
        self.terminate_count += 1

    def kill(self) -> None:
        self.kill_count += 1

    async def wait(self) -> int:
        task = asyncio.current_task()
        if task is None:
            raise AssertionError("process.wait must run in a task")
        self.waiter_tasks.append(task)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await self.release.wait()
        raise RuntimeError("late process waiter failure")


class OwnedProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_already_exited_process_is_reaped_without_signal(self) -> None:
        process = CleanupProcess(["return"], returncode=0)

        await terminate_owned_process(process, term_timeout=0.01, kill_timeout=0.01)

        self.assertEqual(process.terminate_count, 0)
        self.assertEqual(process.kill_count, 0)
        self.assertEqual(process.wait_count, 1)

    async def test_term_success_is_bounded_and_never_kills(self) -> None:
        process = CleanupProcess(["return"])

        await terminate_owned_process(process, term_timeout=0.01, kill_timeout=0.01)

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 0)
        self.assertEqual(process.wait_count, 1)

    async def test_term_timeout_kills_only_child_and_reaps_with_bound(self) -> None:
        process = CleanupProcess(["hang", "return"])

        await asyncio.wait_for(
            terminate_owned_process(process, term_timeout=0.001, kill_timeout=0.01),
            timeout=0.1,
        )

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 1)
        self.assertEqual(process.wait_count, 2)

    async def test_kill_timeout_fails_in_finite_time(self) -> None:
        process = CleanupProcess(["hang", "hang"])

        with self.assertRaisesRegex(RuntimeError, "owned audio process did not exit"):
            await asyncio.wait_for(
                terminate_owned_process(
                    process,
                    term_timeout=0.001,
                    kill_timeout=0.001,
                ),
                timeout=0.1,
            )

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 1)
        self.assertEqual(process.wait_count, 2)
        self.assertIsNone(process.returncode)

    async def test_non_cooperative_wait_is_hard_bounded_and_late_error_retrieved(
        self,
    ) -> None:
        process = NonCooperativeCleanupProcess()
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda unused_loop, context: contexts.append(context))
        cleanup = asyncio.create_task(
            terminate_owned_process(process, term_timeout=0.001, kill_timeout=0.001)
        )
        try:
            done, _ = await asyncio.wait({cleanup}, timeout=0.05)
            bounded = cleanup in done
            if bounded:
                with self.assertRaisesRegex(
                    RuntimeError, "owned audio process did not exit"
                ):
                    cleanup.result()
            else:
                process.release.set()
                try:
                    await cleanup
                except RuntimeError:
                    pass
                self.fail("owned process cleanup exceeded its wall-clock bound")

            self.assertEqual(process.terminate_count, 1)
            self.assertEqual(process.kill_count, 1)
            self.assertEqual(len(process.waiter_tasks), 2)

            process.release.set()
            for _ in range(10):
                await asyncio.sleep(0)
                if all(task.done() for task in process.waiter_tasks):
                    break
            self.assertTrue(all(task.done() for task in process.waiter_tasks))
            await asyncio.sleep(0)
            self.assertTrue(
                all(
                    not getattr(task, "_log_traceback", True)
                    for task in process.waiter_tasks
                )
            )
            self.assertEqual(contexts, [])
        finally:
            process.release.set()
            loop.set_exception_handler(previous_handler)

    async def test_process_lookup_races_still_use_bounded_waits(self) -> None:
        process = CleanupProcess(
            ["hang", "return"], term_lookup=True, kill_lookup=True
        )

        await asyncio.wait_for(
            terminate_owned_process(process, term_timeout=0.001, kill_timeout=0.01),
            timeout=0.1,
        )

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 1)
        self.assertEqual(process.wait_count, 2)

    async def test_cancellation_waits_for_bounded_stop_then_propagates(self) -> None:
        process = CleanupProcess(["hang", "return"])
        cleanup = asyncio.create_task(
            terminate_owned_process(process, term_timeout=0.01, kill_timeout=0.01)
        )
        await process.wait_started.wait()

        cancellation = asyncio.CancelledError("caller cancelled")
        cleanup.cancel(cancellation.args[0])
        with self.assertRaises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(cleanup, timeout=0.1)

        self.assertEqual(raised.exception.args, cancellation.args)
        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 1)
        self.assertEqual(process.wait_count, 2)
        self.assertEqual(process.returncode, -9)

    async def test_cancellation_stays_primary_when_child_cannot_be_reaped(self) -> None:
        process = CleanupProcess(["hang", "hang"])
        cleanup = asyncio.create_task(
            terminate_owned_process(process, term_timeout=0.001, kill_timeout=0.001)
        )
        await process.wait_started.wait()

        cleanup.cancel("caller cancelled")
        with self.assertRaises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(cleanup, timeout=0.1)

        self.assertEqual(raised.exception.args, ("caller cancelled",))
        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 1)
        self.assertEqual(process.wait_count, 2)
        self.assertIsNone(process.returncode)
        self.assertTrue(
            any("cleanup also failed" in note for note in raised.exception.__notes__)
        )


class FakeSocket:
    def __init__(self, responses: list[bytes]) -> None:
        self._responses = iter(responses)
        self.sent: list[bytes] = []

    async def send(self, frame: bytes) -> None:
        self.sent.append(frame)

    async def recv(self) -> bytes:
        try:
            return next(self._responses)
        except StopIteration:
            await asyncio.Future()
            raise AssertionError("unreachable")


class FakeConnection:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket
        self.exited = False

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *args: object) -> None:
        self.exited = True


class LiveAsrTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = AsrConfig("app", "private-token", "volc.seedasr.sauc.duration")
        self.levels = LevelConfig(0.02, 0.01, trailing_silence_ms=800, max_seconds=10)
        self.speech = struct.pack("<" + "h" * 320, *(2000,) * 320)
        self.silence = bytes(640)

    async def test_streams_microphone_and_returns_final_text(self) -> None:
        process = FakeProcess([self.speech] + [self.silence] * 40)
        socket = FakeSocket(
            [
                bytes((0x11, 0x10, 0x00, 0x00)),
                server_result_frame("你好", 0x01, 2),
                server_result_frame("你好露米", 0x03, -3),
            ]
        )
        connection = FakeConnection(socket)
        partials: list[str] = []

        with (
            patch(
                "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                return_value=process,
            ) as create_process,
            patch("lumilamp.voice.live_asr._open_websocket", return_value=connection),
            patch(
                "lumilamp.voice.live_asr.terminate_owned_process",
                new=AsyncMock(),
            ) as cleanup,
        ):
            result = await recognize_microphone(
                self.config,
                "plughw:CARD=Device,DEV=0",
                self.levels,
                partials.append,
            )

        self.assertEqual(result, "你好露米")
        self.assertEqual(partials, ["你好"])
        self.assertTrue(connection.exited)
        self.assertFalse(process.terminated)
        self.assertFalse(process.waited)
        cleanup.assert_awaited_once_with(process)
        create_process.assert_awaited_once_with(
            "arecord",
            "-D",
            "plughw:CARD=Device,DEV=0",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.assertGreaterEqual(len(socket.sent), 2)
        self.assertEqual(struct.unpack(">i", socket.sent[-1][4:8])[0] < 0, True)

    async def test_waits_for_local_speech_before_opening_websocket(self) -> None:
        quiet_chunks = [
            struct.pack("<" + "h" * 320, *(index,) * 320) for index in range(12)
        ]
        process = FakeProcess(quiet_chunks + [self.speech] + [self.silence] * 40)
        socket = FakeSocket(
            [
                bytes((0x11, 0x10, 0x00, 0x00)),
                server_result_frame("延迟说话", 0x03, -2),
            ]
        )
        connection = FakeConnection(socket)

        def open_after_speech(headers):
            self.assertEqual(process.stdout.read_count, 13)
            self.assertEqual(socket.sent, [])
            return connection

        with (
            patch(
                "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                return_value=process,
            ),
            patch(
                "lumilamp.voice.live_asr._open_websocket",
                side_effect=open_after_speech,
            ),
        ):
            result = await recognize_microphone(
                self.config,
                "plughw:CARD=Device,DEV=0",
                self.levels,
                lambda text: None,
            )

        self.assertEqual(result, "延迟说话")
        self.assertEqual(gzip.decompress(socket.sent[1][12:]), b"".join(quiet_chunks[-10:]))
        self.assertEqual(len(gzip.decompress(socket.sent[1][12:])), 10 * 640)

    async def test_cleans_up_recorder_when_server_returns_no_final_text(self) -> None:
        process = FakeProcess([self.speech] + [self.silence] * 40)
        socket = FakeSocket(
            [bytes((0x11, 0x10, 0x00, 0x00)), server_result_frame("临时", 0x03, -2)]
        )
        connection = FakeConnection(socket)

        with (
            patch(
                "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                return_value=process,
            ),
            patch("lumilamp.voice.live_asr._open_websocket", return_value=connection),
        ):
            result = await recognize_microphone(
                self.config,
                "plughw:CARD=Device,DEV=0",
                self.levels,
                lambda text: None,
            )

        self.assertEqual(result, "临时")
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    async def test_cleanup_failure_propagates_when_recognition_succeeded(self) -> None:
        process = FakeProcess([self.speech] + [self.silence] * 40)
        socket = FakeSocket(
            [
                bytes((0x11, 0x10, 0x00, 0x00)),
                server_result_frame("完成", 0x03, -2),
            ]
        )

        with (
            patch(
                "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                return_value=process,
            ),
            patch(
                "lumilamp.voice.live_asr._open_websocket",
                return_value=FakeConnection(socket),
            ),
            patch(
                "lumilamp.voice.live_asr.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                await recognize_microphone(
                    self.config,
                    "plughw:CARD=Device,DEV=0",
                    self.levels,
                    lambda text: None,
                )

    async def test_primary_failure_wins_and_records_cleanup_failure(self) -> None:
        process = FakeProcess([])

        with (
            patch(
                "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                return_value=process,
            ),
            patch(
                "lumilamp.voice.live_asr.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ) as cleanup,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "microphone audio stream ended unexpectedly"
            ) as raised:
                await recognize_microphone(
                    self.config,
                    "plughw:CARD=Device,DEV=0",
                    self.levels,
                    lambda text: None,
                )

        cleanup.assert_awaited_once_with(process)
        self.assertTrue(
            any("cleanup also failed" in note for note in raised.exception.__notes__)
        )

    async def test_primary_cancellation_wins_after_cleanup_attempt(self) -> None:
        process = FakeProcess([])
        blocking = BlockingStdout()
        process.stdout = blocking

        with (
            patch(
                "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                return_value=process,
            ),
            patch(
                "lumilamp.voice.live_asr.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ) as cleanup,
        ):
            recognition = asyncio.create_task(
                recognize_microphone(
                    self.config,
                    "plughw:CARD=Device,DEV=0",
                    self.levels,
                    lambda text: None,
                )
            )
            await blocking.started.wait()
            recognition.cancel("caller cancelled")
            with self.assertRaises(asyncio.CancelledError) as raised:
                await recognition

        self.assertEqual(raised.exception.args, ("caller cancelled",))
        cleanup.assert_awaited_once_with(process)
        self.assertTrue(
            any("cleanup also failed" in note for note in raised.exception.__notes__)
        )

    async def test_done_receiver_exception_is_retrieved_but_body_error_wins(
        self,
    ) -> None:
        receiver_failed = asyncio.Event()
        process = FakeProcess([])
        process.stdout = SpeechThenFailureStdout(self.speech, receiver_failed)
        socket = FakeSocket([bytes((0x11, 0x10, 0x00, 0x00))])
        contexts: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        async def fail_receiver(*args: object) -> str:
            receiver_failed.set()
            raise RuntimeError("receiver failed")

        loop.set_exception_handler(lambda unused_loop, context: contexts.append(context))
        try:
            with (
                patch(
                    "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                    return_value=process,
                ),
                patch(
                    "lumilamp.voice.live_asr._open_websocket",
                    return_value=FakeConnection(socket),
                ),
                patch(
                    "lumilamp.voice.live_asr._receive_final",
                    side_effect=fail_receiver,
                ),
                patch(
                    "lumilamp.voice.live_asr.terminate_owned_process",
                    new=AsyncMock(),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "body failed") as raised:
                    await recognize_microphone(
                        self.config,
                        "plughw:CARD=Device,DEV=0",
                        self.levels,
                        lambda text: None,
                    )
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        self.assertTrue(
            any(
                "receiver" in note and "RuntimeError" in note
                for note in raised.exception.__notes__
            )
        )
        self.assertEqual(contexts, [])

    async def test_receiver_exception_propagates_when_it_is_the_primary_failure(
        self,
    ) -> None:
        process = FakeProcess([self.speech] + [self.silence] * 40)
        socket = FakeSocket([bytes((0x11, 0x10, 0x00, 0x00))])
        contexts: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        async def fail_receiver(*args: object) -> str:
            raise RuntimeError("receiver failed")

        loop.set_exception_handler(lambda unused_loop, context: contexts.append(context))
        try:
            with (
                patch(
                    "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                    return_value=process,
                ),
                patch(
                    "lumilamp.voice.live_asr._open_websocket",
                    return_value=FakeConnection(socket),
                ),
                patch(
                    "lumilamp.voice.live_asr._receive_final",
                    side_effect=fail_receiver,
                ),
                patch(
                    "lumilamp.voice.live_asr.terminate_owned_process",
                    new=AsyncMock(),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "receiver failed"):
                    await recognize_microphone(
                        self.config,
                        "plughw:CARD=Device,DEV=0",
                        self.levels,
                        lambda text: None,
                    )
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        self.assertEqual(contexts, [])

    async def test_cancellation_wins_over_done_receiver_exception(self) -> None:
        receiver_failed = asyncio.Event()
        process = FakeProcess([])
        stdout = SpeechThenBlockingStdout(self.speech, receiver_failed)
        process.stdout = stdout
        socket = FakeSocket([bytes((0x11, 0x10, 0x00, 0x00))])
        contexts: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        async def fail_receiver(*args: object) -> str:
            receiver_failed.set()
            raise RuntimeError("receiver failed")

        loop.set_exception_handler(lambda unused_loop, context: contexts.append(context))
        try:
            with (
                patch(
                    "lumilamp.voice.live_asr.asyncio.create_subprocess_exec",
                    return_value=process,
                ),
                patch(
                    "lumilamp.voice.live_asr._open_websocket",
                    return_value=FakeConnection(socket),
                ),
                patch(
                    "lumilamp.voice.live_asr._receive_final",
                    side_effect=fail_receiver,
                ),
                patch(
                    "lumilamp.voice.live_asr.terminate_owned_process",
                    new=AsyncMock(),
                ),
            ):
                recognition = asyncio.create_task(
                    recognize_microphone(
                        self.config,
                        "plughw:CARD=Device,DEV=0",
                        self.levels,
                        lambda text: None,
                    )
                )
                await stdout.body_blocked.wait()
                recognition.cancel("caller cancelled")
                with self.assertRaises(asyncio.CancelledError) as raised:
                    await recognition
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        self.assertEqual(raised.exception.args, ("caller cancelled",))
        self.assertTrue(
            any(
                "receiver" in note and "RuntimeError" in note
                for note in raised.exception.__notes__
            )
        )
        self.assertEqual(contexts, [])


if __name__ == "__main__":
    unittest.main()
