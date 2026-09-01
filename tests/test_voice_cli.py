import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from websockets.exceptions import ConnectionClosed, InvalidHandshake, WebSocketException

from lumilamp.voice.config import AsrConfig, VoiceConfig
from lumilamp.voice.conversation import ConversationHistory
from lumilamp.voice.devices import AlsaDevice, AudioDeviceNotFoundError
from lumilamp.voice.voice_cli import (
    ArkAskAdapter,
    ArkStreamAdapter,
    CachedReplyPlaybackAdapter,
    CliBindings,
    LiveAsrAdapter,
    LoopAdapters,
    StartupValidationError,
    StreamingTurnAdapter,
    StreamingTurnError,
    TtsPlaybackAdapter,
    WakeListenAdapter,
    WakeMotionAdapter,
    build_voice_loop,
    main,
)
from lumilamp.voice.voice_loop import VoiceAdapterError
from lumilamp.voice.wake_cache import WakeReplyCache


def make_config(root: Path) -> VoiceConfig:
    return VoiceConfig(
        asr=AsrConfig("app", "asr-secret", "asr-resource"),
        tts_api_key="tts-secret",
        tts_resource_id="tts-resource",
        ark_api_key="ark-secret",
        ark_model_id="ark-model",
        kws_model_dir=root / "models",
        wake_cache_dir=root / "cache",
    )


class NoIoTracker:
    def __init__(self) -> None:
        self.microphone_opened = False
        self.network_opened = False
        self.speaker_opened = False
        self.imported: list[str] = []

    def open_microphone(self) -> None:
        self.microphone_opened = True

    def open_network(self) -> None:
        self.network_opened = True

    def open_speaker(self) -> None:
        self.speaker_opened = True


class OneChunkStdout:
    async def readexactly(self, size: int) -> bytes:
        return bytes(size)


class BlockingWakeStdout:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def readexactly(self, size: int) -> bytes:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FakeWakeProcess:
    def __init__(self) -> None:
        self.stdout = OneChunkStdout()
        self.returncode: int | None = None
        self.terminate_count = 0
        self.kill_count = 0
        self.wait_count = 0

    def terminate(self) -> None:
        self.terminate_count += 1
        self.returncode = -15

    def kill(self) -> None:
        self.kill_count += 1
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_count += 1
        return self.returncode or 0


class VoiceCliTests(unittest.TestCase):
    def test_default_device_resolver_passes_proc_root_for_both_usb_ids(self) -> None:
        resolved: list[tuple[str, Path]] = []

        def fake_discover(usb_id: str, proc_root: Path) -> AlsaDevice:
            resolved.append((usb_id, proc_root))
            return AlsaDevice("Card", "plughw:Card")

        with patch(
            "lumilamp.voice.voice_cli.discover_alsa_device",
            side_effect=fake_discover,
        ):
            resolver = CliBindings().resolve_device
            resolver("08bb:2902")
            resolver("1b3f:2008")

        self.assertEqual(
            resolved,
            [
                ("08bb:2902", Path("/proc/asound")),
                ("1b3f:2008", Path("/proc/asound")),
            ],
        )

    def test_dry_run_validates_without_constructing_runtime_or_opening_io(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_config(root)
            tracker = NoIoTracker()
            validated: list[str] = []

            def load_config(path: Path) -> VoiceConfig:
                self.assertEqual(path, root / ".env.voice")
                validated.append("config")
                return config

            def validate_models(path: Path) -> object:
                self.assertEqual(path, config.kws_model_dir)
                validated.append("models")
                return object()

            def validate_cache(candidate: VoiceConfig) -> None:
                self.assertIs(candidate, config)
                validated.append("cache")

            def resolve(usb_id: str) -> AlsaDevice:
                validated.append(f"device:{usb_id}")
                return AlsaDevice(usb_id.replace(":", "_"), f"plughw:{usb_id}")

            def import_dependency(name: str) -> object:
                tracker.imported.append(name)
                return object()

            def construct_runtime(*args: object, **kwargs: object) -> object:
                tracker.open_microphone()
                tracker.open_network()
                tracker.open_speaker()
                self.fail("dry-run constructed the operational runtime")

            bindings = CliBindings(
                load_config=load_config,
                validate_models=validate_models,
                validate_cache=validate_cache,
                resolve_device=resolve,
                import_dependency=import_dependency,
                construct_runtime=construct_runtime,
            )

            result = main(
                ["--config", str(root / ".env.voice"), "--dry-run"],
                adapters=bindings,
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            validated,
            [
                "config",
                "models",
                "cache",
                "device:08bb:2902",
                "device:1b3f:2008",
            ],
        )
        self.assertEqual(tracker.imported, ["sherpa_onnx", "websockets"])
        self.assertFalse(tracker.microphone_opened)
        self.assertFalse(tracker.network_opened)
        self.assertFalse(tracker.speaker_opened)

    def test_missing_setup_is_concise_and_does_not_print_credentials(self) -> None:
        root = Path("/ignored")
        config = make_config(root)
        cases = (
            CliBindings(
                load_config=lambda path: (_ for _ in ()).throw(
                    FileNotFoundError("ark-secret")
                )
            ),
            CliBindings(
                load_config=lambda path: config,
                validate_models=lambda path: (_ for _ in ()).throw(
                    ValueError("tts-secret")
                ),
            ),
            CliBindings(
                load_config=lambda path: config,
                validate_models=lambda path: object(),
                validate_cache=lambda candidate: None,
                resolve_device=lambda usb_id: (_ for _ in ()).throw(
                    AudioDeviceNotFoundError("asr-secret")
                ),
            ),
            CliBindings(
                load_config=lambda path: config,
                validate_models=lambda path: object(),
                validate_cache=lambda candidate: None,
                resolve_device=lambda usb_id: AlsaDevice("Card", "plughw:Card"),
                import_dependency=lambda name: (_ for _ in ()).throw(
                    ModuleNotFoundError("ark-secret")
                ),
            ),
        )
        for bindings in cases:
            with self.subTest(bindings=bindings):
                stderr = io.StringIO()

                with patch("sys.stderr", stderr):
                    result = main(["--config", "missing", "--dry-run"], adapters=bindings)

                self.assertEqual(result, 1)
                message = stderr.getvalue()
                self.assertIn("voice setup failed", message)
                self.assertNotIn("ark-secret", message)
                self.assertNotIn("tts-secret", message)
                self.assertNotIn("asr-secret", message)
                self.assertLessEqual(len(message.splitlines()), 1)

    def test_programming_error_during_validation_propagates(self) -> None:
        bindings = CliBindings(
            load_config=lambda path: (_ for _ in ()).throw(AssertionError("bug"))
        )

        with self.assertRaisesRegex(AssertionError, "bug"):
            main(["--dry-run"], adapters=bindings)

    def test_expected_runtime_initialization_failure_is_redacted(self) -> None:
        config = make_config(Path("/ignored"))
        bindings = CliBindings(
            load_config=lambda path: config,
            validate_models=lambda path: object(),
            validate_cache=lambda candidate: None,
            resolve_device=lambda usb_id: AlsaDevice("Card", "plughw:Card"),
            import_dependency=lambda name: object(),
            construct_runtime=lambda startup, history: (_ for _ in ()).throw(
                RuntimeError("ark-secret")
            ),
        )
        stderr = io.StringIO()

        with patch("sys.stderr", stderr):
            result = main([], adapters=bindings)

        self.assertEqual(result, 1)
        self.assertIn("voice setup failed", stderr.getvalue())
        self.assertNotIn("ark-secret", stderr.getvalue())

    def test_build_voice_loop_shares_ark_history_and_actual_clock(self) -> None:
        history = ConversationHistory()
        adapter = ArkAskAdapter(make_config(Path("/ignored")), history)
        clock = lambda: 10.0

        async def no_argument() -> str:
            return "露米"

        async def one_argument(value: object) -> None:
            return None

        loop = build_voice_loop(
            history=history,
            asker=adapter,
            adapters=LoopAdapters(
                listen_for_wake=no_argument,
                play_cached_reply=one_argument,
                recognize_turn=no_argument,
                speak=one_argument,
                clock=clock,
                delay=one_argument,
                choose=lambda choices: choices[0],
            ),
        )

        self.assertIs(loop.history, adapter.history)
        self.assertIs(loop.clock, clock)
        self.assertIs(loop.controller._clock, clock)
        self.assertIs(loop.delay, one_argument)

    def test_build_voice_loop_passes_optional_wake_motion(self) -> None:
        history = ConversationHistory()
        adapter = ArkAskAdapter(make_config(Path("/ignored")), history)

        async def wake() -> str: return "露米"
        async def no_arg() -> None: return None
        async def one_arg(_: object) -> None: return None

        loop = build_voice_loop(
            history=history,
            asker=adapter,
            adapters=LoopAdapters(
                listen_for_wake=wake,
                play_cached_reply=one_arg,
                recognize_turn=wake,
                speak=one_arg,
                wake_motion=no_arg,
            ),
        )

        self.assertIs(loop.wake_motion, no_arg)

    def test_startup_validation_error_redacts_cause(self) -> None:
        error = StartupValidationError("wake cache is invalid")
        self.assertEqual(str(error), "wake cache is invalid")


class ArkAskAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_to_thread_and_real_ask_function_is_only_append_owner(self) -> None:
        config = make_config(Path("/ignored"))
        history = ConversationHistory()
        calls: list[tuple[object, ...]] = []

        def fake_ask(
            actual_config: VoiceConfig,
            actual_history: ConversationHistory,
            text: str,
        ) -> str:
            calls.append((actual_config, actual_history, text))
            actual_history.append_turn(text, "回答")
            return "回答"

        async def run_in_thread(function, *args):
            self.assertIs(function, fake_ask)
            return function(*args)

        adapter = ArkAskAdapter(config, history)
        with (
            patch("lumilamp.voice.voice_cli.ask_ark", fake_ask),
            patch("lumilamp.voice.voice_cli.asyncio.to_thread", run_in_thread),
        ):
            answer = await adapter.ask("问题")

        self.assertEqual(answer, "回答")
        self.assertEqual(calls, [(config, history, "问题")])
        self.assertEqual(
            history.messages(),
            [
                {"role": "user", "content": "问题"},
                {"role": "assistant", "content": "回答"},
            ],
        )


class WakeMotionAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_servo_error_without_exposing_detail(self) -> None:
        class FailingClient:
            def wake_nod(self) -> None:
                raise RuntimeError("serial hardware detail")

        adapter = WakeMotionAdapter(FailingClient())
        with self.assertRaisesRegex(VoiceAdapterError, "wake motion failed") as raised:
            await adapter()
        self.assertNotIn("serial hardware detail", str(raised.exception))


class ArkStreamAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_fragments_without_appending_history(self) -> None:
        history = ConversationHistory()

        def fake_stream(*_):
            return iter(("第一句", "。"))

        adapter = ArkStreamAdapter(make_config(Path("/ignored")), history, stream_ark=fake_stream)

        self.assertEqual([part async for part in adapter.stream("问题")], ["第一句", "。"])
        self.assertEqual(history.messages(), [])


class StreamingTurnAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_interruption_keeps_played_sentence_then_plays_one_local_error(self) -> None:
        class InterruptedArk:
            async def stream(self, _: str):
                yield "已经播放。"
                raise RuntimeError("transport disconnected")

        played: list[str] = []

        async def speak(text: str) -> None:
            played.append(text)

        async def play_error() -> None:
            played.append("网络好像断开了")

        adapter = StreamingTurnAdapter(
            InterruptedArk(),
            speak,
            play_network_error=play_error,
        )

        with self.assertRaises(StreamingTurnError) as raised:
            await adapter("问题")

        self.assertEqual(raised.exception.failure_stage, "ark")
        self.assertEqual(raised.exception.sentences_played, 1)
        self.assertEqual(played, ["已经播放。", "网络好像断开了"])

    async def test_converts_expected_ark_failure_only(self) -> None:
        adapter = ArkAskAdapter(make_config(Path("/ignored")), ConversationHistory())

        async def fail_in_thread(function, *args):
            raise RuntimeError("provider unavailable")

        with patch("lumilamp.voice.voice_cli.asyncio.to_thread", fail_in_thread):
            with self.assertRaises(VoiceAdapterError):
                await adapter.ask("问题")

    async def test_maps_malformed_ark_provider_response_after_input_validation(self) -> None:
        adapter = ArkAskAdapter(make_config(Path("/ignored")), ConversationHistory())

        async def fail_in_thread(function, *args):
            raise ValueError("Ark response is malformed")

        with patch("lumilamp.voice.voice_cli.asyncio.to_thread", fail_in_thread):
            with self.assertRaises(VoiceAdapterError):
                await adapter.ask("问题")

    async def test_blank_ark_input_is_a_contract_error(self) -> None:
        adapter = ArkAskAdapter(make_config(Path("/ignored")), ConversationHistory())

        with self.assertRaises(ValueError):
            await adapter.ask("  ")

    async def test_does_not_swallow_cancellation_or_programming_errors(self) -> None:
        adapter = ArkAskAdapter(make_config(Path("/ignored")), ConversationHistory())
        for error in (asyncio.CancelledError(), TypeError("bug"), AssertionError("bug")):
            with self.subTest(error=type(error).__name__):
                async def fail_in_thread(function, *args, error=error):
                    raise error

                with patch("lumilamp.voice.voice_cli.asyncio.to_thread", fail_in_thread):
                    with self.assertRaises(type(error)):
                        await adapter.ask("问题")


class LiveAsrAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_documented_websocket_transport_failures(self) -> None:
        adapter = LiveAsrAdapter(make_config(Path("/ignored")), "plughw:Mic")
        failures = (
            WebSocketException("transport failed"),
            ConnectionClosed(None, None),
            InvalidHandshake("handshake failed"),
        )

        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch(
                    "lumilamp.voice.voice_cli.recognize_microphone",
                    new=AsyncMock(side_effect=failure),
                ):
                    with self.assertRaises(VoiceAdapterError):
                        await adapter()

    async def test_asr_cancellation_propagates(self) -> None:
        adapter = LiveAsrAdapter(make_config(Path("/ignored")), "plughw:Mic")
        with patch(
            "lumilamp.voice.voice_cli.recognize_microphone",
            new=AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await adapter()


class WakeListenAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_kws_result_value_error_propagates(self) -> None:
        process = FakeWakeProcess()

        class ContractFailingDetector:
            def reset(self) -> None:
                pass

            def accept_pcm(self, samples) -> str | None:
                raise ValueError("unexpected wake-word result")

        adapter = WakeListenAdapter("plughw:Mic", ContractFailingDetector())
        with patch(
            "lumilamp.voice.voice_cli.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            with self.assertRaisesRegex(ValueError, "unexpected wake-word result"):
                await adapter()

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.wait_count, 1)

    async def test_owned_arecord_delegates_to_shared_bounded_cleanup(self) -> None:
        process = FakeWakeProcess()
        adapter = WakeListenAdapter("plughw:Mic", object())
        adapter._process = process

        with patch(
            "lumilamp.voice.voice_cli.terminate_owned_process",
            new=AsyncMock(),
            create=True,
        ) as cleanup:
            await adapter.aclose()

        cleanup.assert_awaited_once_with(process)
        self.assertIsNone(adapter._process)

    async def test_failed_shared_cleanup_retains_owned_handle_for_retry(self) -> None:
        process = FakeWakeProcess()
        adapter = WakeListenAdapter("plughw:Mic", object())
        adapter._process = process

        with patch(
            "lumilamp.voice.voice_cli.terminate_owned_process",
            new=AsyncMock(side_effect=RuntimeError("owned audio process did not exit")),
            create=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "did not exit"):
                await adapter.aclose()

        self.assertIs(adapter._process, process)

    async def test_cleanup_cancellation_after_reap_clears_handle(self) -> None:
        process = FakeWakeProcess()
        adapter = WakeListenAdapter("plughw:Mic", object())
        adapter._process = process

        async def cancel_after_reap(owned_process) -> None:
            owned_process.returncode = -9
            raise asyncio.CancelledError("caller cancelled")

        with patch(
            "lumilamp.voice.voice_cli.terminate_owned_process",
            new=AsyncMock(side_effect=cancel_after_reap),
            create=True,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await adapter.aclose()

        self.assertIsNone(adapter._process)

    async def test_cleanup_cancellation_before_reap_retains_handle(self) -> None:
        process = FakeWakeProcess()
        adapter = WakeListenAdapter("plughw:Mic", object())
        adapter._process = process

        with patch(
            "lumilamp.voice.voice_cli.terminate_owned_process",
            new=AsyncMock(side_effect=asyncio.CancelledError("caller cancelled")),
            create=True,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await adapter.aclose()

        self.assertIs(adapter._process, process)

    async def test_body_adapter_error_wins_over_cleanup_failure(self) -> None:
        process = FakeWakeProcess()

        class OperationallyFailingDetector:
            def reset(self) -> None:
                pass

            def accept_pcm(self, samples) -> str | None:
                raise RuntimeError("detector unavailable")

        adapter = WakeListenAdapter("plughw:Mic", OperationallyFailingDetector())
        with (
            patch(
                "lumilamp.voice.voice_cli.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "lumilamp.voice.voice_cli.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ),
        ):
            with self.assertRaises(VoiceAdapterError) as raised:
                await adapter()

        self.assertTrue(
            any(
                "cleanup" in note and "RuntimeError" in note
                for note in raised.exception.__notes__
            )
        )

    async def test_body_contract_error_wins_over_cleanup_failure(self) -> None:
        process = FakeWakeProcess()

        class ContractFailingDetector:
            def reset(self) -> None:
                pass

            def accept_pcm(self, samples) -> str | None:
                raise ValueError("unexpected wake-word result")

        adapter = WakeListenAdapter("plughw:Mic", ContractFailingDetector())
        with (
            patch(
                "lumilamp.voice.voice_cli.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "lumilamp.voice.voice_cli.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError, "unexpected wake-word result"
            ) as raised:
                await adapter()

        self.assertTrue(
            any(
                "cleanup" in note and "RuntimeError" in note
                for note in raised.exception.__notes__
            )
        )

    async def test_body_cancellation_wins_over_cleanup_failure(self) -> None:
        process = FakeWakeProcess()
        stdout = BlockingWakeStdout()
        process.stdout = stdout

        class WaitingDetector:
            def reset(self) -> None:
                pass

        adapter = WakeListenAdapter("plughw:Mic", WaitingDetector())
        with (
            patch(
                "lumilamp.voice.voice_cli.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "lumilamp.voice.voice_cli.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ),
        ):
            listening = asyncio.create_task(adapter())
            await stdout.started.wait()
            listening.cancel("caller cancelled")
            with self.assertRaises(asyncio.CancelledError) as raised:
                await listening

        self.assertEqual(raised.exception.args, ("caller cancelled",))
        self.assertTrue(
            any(
                "cleanup" in note and "RuntimeError" in note
                for note in raised.exception.__notes__
            )
        )

    async def test_cleanup_failure_propagates_after_successful_wake(self) -> None:
        process = FakeWakeProcess()

        class SuccessfulDetector:
            def reset(self) -> None:
                pass

            def accept_pcm(self, samples) -> str | None:
                return "你好露米"

        adapter = WakeListenAdapter("plughw:Mic", SuccessfulDetector())
        with (
            patch(
                "lumilamp.voice.voice_cli.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "lumilamp.voice.voice_cli.terminate_owned_process",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                await adapter()

    async def test_wake_body_primary_survives_two_cleanup_failures_and_retries(
        self,
    ) -> None:
        process = FakeWakeProcess()
        history = ConversationHistory()
        successful_close_attempts = 0

        class OperationallyFailingDetector:
            def reset(self) -> None:
                pass

            def accept_pcm(self, samples) -> str | None:
                raise RuntimeError("detector provider detail")

        class SuccessfulOwnedResource:
            async def aclose(inner_self) -> None:
                nonlocal successful_close_attempts
                successful_close_attempts += 1

        async def unused_no_argument() -> str:
            raise AssertionError("wake failure should end the session")

        async def unused_one_argument(value: object) -> None:
            raise AssertionError("wake failure should end the session")

        wake = WakeListenAdapter("plughw:Mic", OperationallyFailingDetector())
        loop = build_voice_loop(
            history=history,
            asker=ArkAskAdapter(make_config(Path("/ignored")), history),
            adapters=LoopAdapters(
                listen_for_wake=wake,
                play_cached_reply=unused_one_argument,
                recognize_turn=unused_no_argument,
                speak=unused_one_argument,
                clock=lambda: 0.0,
                delay=unused_one_argument,
                choose=lambda choices: choices[0],
                owned_resources=(SuccessfulOwnedResource(), wake),
            ),
        )

        cleanup = AsyncMock(
            side_effect=(
                RuntimeError("first cleanup detail"),
                RuntimeError("second cleanup detail"),
                None,
            )
        )
        with (
            patch(
                "lumilamp.voice.voice_cli.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "lumilamp.voice.voice_cli.terminate_owned_process",
                new=cleanup,
            ),
        ):
            raised: BaseException | None = None
            try:
                await loop.run_once()
            except BaseException as error:
                raised = error
            else:
                self.fail("wake body failure did not propagate")

            self.assertIsInstance(raised, VoiceAdapterError)
            self.assertEqual(str(raised), "wake-word listening failed")
            self.assertEqual(
                raised.__notes__,
                [
                    "owned wake recorder cleanup also failed: RuntimeError",
                    "owned VoiceLoop resource cleanup also failed: RuntimeError",
                ],
            )
            self.assertNotIn("second cleanup detail", repr(raised.__notes__))
            self.assertIs(wake._process, process)
            self.assertEqual(successful_close_attempts, 1)

            await loop._close_owned_resources()
            await loop._close_owned_resources()

        self.assertEqual(cleanup.await_count, 3)
        self.assertIsNone(wake._process)
        self.assertEqual(successful_close_attempts, 1)


class PlaybackAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_reply_uses_configured_conversation_volume(self) -> None:
        cache = WakeReplyCache(Path("/cache"))
        adapter = CachedReplyPlaybackAdapter(
            cache,
            AlsaDevice("Speaker", "plughw:speaker"),
        )

        with (
            patch("lumilamp.voice.voice_cli.set_usb_speaker_volume") as volume,
            patch("lumilamp.voice.voice_cli.play_wav"),
            patch("lumilamp.voice.voice_cli.asyncio.to_thread", side_effect=lambda function, *args: function(*args)),
        ):
            await adapter("我在呀")

        volume.assert_called_once_with("Speaker", 80)

    async def test_unsupported_cached_reply_is_a_contract_error(self) -> None:
        cache = WakeReplyCache(Path("/ignored"))
        adapter = CachedReplyPlaybackAdapter(
            cache,
            AlsaDevice("Speaker", "plughw:speaker"),
        )

        with (
            patch(
                "lumilamp.voice.voice_cli.set_usb_speaker_volume",
                side_effect=AssertionError("contract error reached amixer"),
            ),
            patch(
                "lumilamp.voice.voice_cli.play_wav",
                side_effect=AssertionError("contract error reached aplay"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "unsupported wake reply"):
                await adapter("not-a-wake-reply")

    async def test_blank_tts_text_is_a_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            config.wake_cache_dir.mkdir()

            def reject_blank(*args) -> None:
                raise ValueError("TTS text must not be empty")

            async def run_in_thread(function, *args):
                return function(*args)

            adapter = TtsPlaybackAdapter(
                config,
                AlsaDevice("Speaker", "plughw:speaker"),
                speak_answer=reject_blank,
            )
            with patch("lumilamp.voice.voice_cli.asyncio.to_thread", run_in_thread):
                with self.assertRaisesRegex(ValueError, "TTS text must not be empty"):
                    await adapter("  ")

    async def test_maps_tts_provider_failure_after_input_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            config.wake_cache_dir.mkdir()

            def provider_failure(*args) -> None:
                raise ValueError("Doubao TTS response chunk is malformed")

            async def run_in_thread(function, *args):
                return function(*args)

            adapter = TtsPlaybackAdapter(
                config,
                AlsaDevice("Speaker", "plughw:speaker"),
                speak_answer=provider_failure,
            )
            with patch("lumilamp.voice.voice_cli.asyncio.to_thread", run_in_thread):
                with self.assertRaises(VoiceAdapterError):
                    await adapter("回答")

    async def test_answer_wav_uses_configured_cache_and_cleans_only_owned_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_config(root)
            config.wake_cache_dir.mkdir()
            user_file = config.wake_cache_dir / "answer.wav"
            user_file.write_text("mine", encoding="utf-8")
            observed_paths: list[Path] = []

            def fake_speak(
                actual_config: VoiceConfig,
                text: str,
                output_path: Path,
                card_id: str,
                device: str,
            ) -> None:
                self.assertIs(actual_config, config)
                self.assertEqual((text, card_id, device), ("回答", "Speaker", "plughw:speaker"))
                self.assertEqual(output_path.parent, config.wake_cache_dir)
                observed_paths.append(output_path)
                output_path.write_bytes(b"wav")

            async def run_in_thread(function, *args):
                return function(*args)

            adapter = TtsPlaybackAdapter(
                config,
                AlsaDevice("Speaker", "plughw:speaker"),
                speak_answer=fake_speak,
            )
            with patch("lumilamp.voice.voice_cli.asyncio.to_thread", run_in_thread):
                await adapter("回答")

            self.assertEqual(user_file.read_text(encoding="utf-8"), "mine")
            self.assertEqual(len(observed_paths), 1)
            self.assertFalse(observed_paths[0].exists())
            self.assertNotEqual(observed_paths[0], user_file)

    async def test_programming_error_from_playback_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            config.wake_cache_dir.mkdir()
            adapter = TtsPlaybackAdapter(
                config,
                AlsaDevice("Speaker", "plughw:speaker"),
                speak_answer=lambda *args: (_ for _ in ()).throw(TypeError("bug")),
            )

            async def run_in_thread(function, *args):
                return function(*args)

            with patch("lumilamp.voice.voice_cli.asyncio.to_thread", run_in_thread):
                with self.assertRaisesRegex(TypeError, "bug"):
                    await adapter("回答")


if __name__ == "__main__":
    unittest.main()
