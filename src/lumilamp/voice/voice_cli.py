"""Executable assembly for the real, half-duplex LumiLamp voice loop."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import random
import subprocess
import sys
import tempfile
import time
from array import array
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lumilamp.hardware.esp32_servo import Esp32ServoClient, Esp32ServoError

from .ark import ask_ark, stream_ark
from .audio_output import (
    CONVERSATION_VOLUME_PERCENT,
    play_wav,
    set_usb_speaker_volume,
    speak as speak_answer,
)
from .config import VoiceConfig, load_voice_config
from .conversation import ConversationController, ConversationHistory
from .devices import (
    DEFAULT_MICROPHONE_USB_ID,
    AlsaDevice,
    AudioDeviceNotFoundError,
    discover_alsa_device,
)
from .live_asr import recognize_microphone, terminate_owned_process
from .recorder import LevelConfig
from .streaming_audio import CHUNK_BYTES
from .streaming_reply import StreamingReplyError, StreamingReplyResult, stream_and_play
from .voice_loop import (
    NO_SPEECH,
    AskAdapter,
    Clock,
    Delay,
    ListenForWake,
    PlayCachedReply,
    RecognitionResult,
    RecognizeTurn,
    Speak,
    VoiceAdapterError,
    VoiceLoop,
)
from .wake_cache import NETWORK_ERROR_REPLY, WakeReplyCache
from .wakeword import SherpaWakeWordDetector, WakeWordConfig, validate_model_dir


SPEAKER_USB_ID = "1b3f:2008"
DEPENDENCIES = ("sherpa_onnx", "websockets")


class StartupValidationError(RuntimeError):
    """A redacted, user-actionable startup validation failure."""


class ArkAskAdapter:
    """Run the blocking Ark client without taking history ownership from it."""

    def __init__(self, config: VoiceConfig, history: ConversationHistory) -> None:
        self._config = config
        self._history = history

    @property
    def history(self) -> ConversationHistory:
        return self._history

    async def ask(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("Ark text must be a string")
        if not text.strip():
            raise ValueError("Ark text must not be blank")
        if not self._config.ark_api_key.strip():
            raise ValueError("Ark API key is not configured")
        if not self._config.ark_model_id.strip():
            raise ValueError("Ark model ID must not be empty")
        try:
            return await asyncio.to_thread(
                ask_ark, self._config, self._history, text
            )
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            raise VoiceAdapterError("Ark request failed") from error


class WakeMotionAdapter:
    """Run the bounded ESP32 wake gesture without exposing serial details."""

    def __init__(self, client: Esp32ServoClient) -> None:
        self._client = client

    async def __call__(self) -> None:
        try:
            await asyncio.to_thread(self._client.wake_nod)
        except (Esp32ServoError, OSError, RuntimeError, TimeoutError) as error:
            mapped = VoiceAdapterError("wake motion failed")
            mapped.motion_stage = error.stage if isinstance(error, Esp32ServoError) else "transport"
            raise mapped from error


_STREAM_DONE = object()


def _next_stream_fragment(iterator: Iterator[str]) -> str | object:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_DONE


class ArkStreamAdapter:
    """Expose the blocking standard-library Ark stream as an async iterator."""

    def __init__(
        self,
        config: VoiceConfig,
        history: ConversationHistory,
        *,
        stream_ark: Callable[[VoiceConfig, ConversationHistory, str], Iterator[str]] = stream_ark,
    ) -> None:
        self._config = config
        self._history = history
        self._stream_ark = stream_ark
        self._iterator: Iterator[str] | None = None

    @property
    def history(self) -> ConversationHistory:
        return self._history

    async def stream(self, text: str) -> AsyncIterator[str]:
        if not isinstance(text, str):
            raise TypeError("Ark text must be a string")
        if not text.strip():
            raise ValueError("Ark text must not be blank")
        try:
            iterator = await asyncio.to_thread(
                self._stream_ark, self._config, self._history, text
            )
            self._iterator = iterator
            while True:
                fragment = await asyncio.to_thread(_next_stream_fragment, iterator)
                if fragment is _STREAM_DONE:
                    break
                yield fragment
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            raise VoiceAdapterError("Ark stream failed") from error
        finally:
            if self._iterator is not None:
                close = getattr(self._iterator, "close", None)
                if callable(close):
                    await asyncio.to_thread(close)
                self._iterator = None

    async def aclose(self) -> None:
        if self._iterator is not None:
            close = getattr(self._iterator, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
            self._iterator = None


class WakeListenAdapter:
    """Own one arecord child while sleeping and feed only in-memory PCM to KWS."""

    def __init__(self, device: str, detector: SherpaWakeWordDetector) -> None:
        self._device = device
        self._detector = detector
        self._process: Any | None = None

    async def __call__(self) -> str:
        process: Any | None = None
        primary_error: BaseException | None = None
        try:
            self._detector.reset()
            process = await asyncio.create_subprocess_exec(
                "arecord",
                "-D",
                self._device,
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
            self._process = process
            if process.stdout is None:
                raise RuntimeError("wake recorder did not provide PCM output")
            while True:
                try:
                    chunk = await process.stdout.readexactly(CHUNK_BYTES)
                except asyncio.IncompleteReadError as error:
                    raise RuntimeError("wake recorder stopped unexpectedly") from error
                samples = array("h")
                samples.frombytes(chunk)
                if sys.byteorder != "little":
                    samples.byteswap()
                phrase = self._detector.accept_pcm(samples)
                if phrase is not None:
                    return phrase
        except (OSError, RuntimeError, TimeoutError) as error:
            primary_error = VoiceAdapterError("wake-word listening failed")
            raise primary_error from error
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if process is not None:
                try:
                    await self._stop_owned(process)
                except BaseException as cleanup_error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(
                        "owned wake recorder cleanup also failed: "
                        f"{type(cleanup_error).__name__}"
                    )

    async def aclose(self) -> None:
        process = self._process
        if process is not None:
            await self._stop_owned(process)

    async def _stop_owned(self, process: Any) -> None:
        try:
            await terminate_owned_process(process)
        except asyncio.CancelledError:
            if process.returncode is not None and self._process is process:
                self._process = None
            raise
        else:
            if self._process is process:
                self._process = None


class LiveAsrAdapter:
    """Map documented ASR provider/transport failures to the loop boundary."""

    def __init__(self, config: VoiceConfig, device: str) -> None:
        self._config = config
        self._device = device
        self._levels = LevelConfig(
            start_threshold=0.02,
            silence_threshold=0.018,
            trailing_silence_ms=800,
            max_seconds=10,
        )

    async def __call__(self) -> RecognitionResult:
        from websockets.exceptions import WebSocketException

        try:
            return await recognize_microphone(
                self._config.asr,
                self._device,
                self._levels,
                lambda partial: None,
            )
        except RuntimeError as error:
            if str(error) == "no speech detected within 10 seconds":
                return NO_SPEECH
            raise VoiceAdapterError("ASR request failed") from error
        except WebSocketException as error:
            raise VoiceAdapterError("ASR request failed") from error
        except (OSError, TimeoutError, ValueError, subprocess.SubprocessError) as error:
            raise VoiceAdapterError("ASR request failed") from error


class CachedReplyPlaybackAdapter:
    """Play an already validated wake reply through the selected speaker."""

    def __init__(self, cache: WakeReplyCache, speaker: AlsaDevice) -> None:
        self._cache = cache
        self._speaker = speaker

    async def __call__(self, text: str) -> None:
        path = self._cache.path_for(text)
        try:
            await asyncio.to_thread(self._play, path)
        except (OSError, subprocess.SubprocessError) as error:
            raise VoiceAdapterError("wake reply playback failed") from error

    def _play(self, path: Path) -> None:
        set_usb_speaker_volume(
            self._speaker.card_id, CONVERSATION_VOLUME_PERCENT
        )
        play_wav(self._speaker.device, path)


class TtsPlaybackAdapter:
    """Synthesize and play one answer using a uniquely owned cache WAV."""

    def __init__(
        self,
        config: VoiceConfig,
        speaker: AlsaDevice,
        *,
        speak_answer: Callable[[VoiceConfig, str, Path, str, str], None] = speak_answer,
    ) -> None:
        self._config = config
        self._speaker = speaker
        self._speak_answer = speak_answer

    async def __call__(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("TTS text must be a string")
        if not text.strip():
            raise ValueError("TTS text must not be empty")
        if not self._config.tts_api_key.strip():
            raise ValueError("TTS API key is not configured")
        if not self._config.tts_resource_id.strip():
            raise ValueError("TTS resource ID is not configured")
        try:
            await asyncio.to_thread(self._speak_owned_wav, text)
        except (
            OSError,
            RuntimeError,
            TimeoutError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            raise VoiceAdapterError("answer synthesis or playback failed") from error

    def _speak_owned_wav(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(
            prefix=".lumilamp-answer-",
            suffix=".wav",
            dir=self._config.wake_cache_dir,
            delete=False,
        ) as temporary:
            output_path = Path(temporary.name)
        try:
            self._speak_answer(
                self._config,
                text,
                output_path,
                self._speaker.card_id,
                self._speaker.device,
            )
        finally:
            output_path.unlink(missing_ok=True)


class StreamingTurnAdapter:
    """Join an Ark delta stream to serial short-sentence TTS playback."""

    def __init__(
        self,
        ark: ArkStreamAdapter,
        tts: TtsPlaybackAdapter,
        *,
        clock: Clock = time.monotonic,
        play_network_error: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._ark = ark
        self._tts = tts
        self._clock = clock
        self._play_network_error = play_network_error

    async def __call__(self, text: str) -> StreamingReplyResult:
        try:
            return await stream_and_play(self._ark.stream(text), self._tts, self._clock)
        except StreamingReplyError as error:
            if error.stage == "ark" and self._play_network_error is not None:
                try:
                    await self._play_network_error()
                except VoiceAdapterError:
                    pass
            raise StreamingTurnError(error.stage, error.sentences_played) from error


class StreamingTurnError(VoiceAdapterError):
    """Redacted streaming failure with enough data for loop reporting."""

    def __init__(self, failure_stage: str, sentences_played: int) -> None:
        super().__init__("streaming reply failed")
        self.failure_stage = failure_stage
        self.sentences_played = sentences_played


@dataclass(frozen=True)
class LoopAdapters:
    """Fully constructed collaborators for one real or fake VoiceLoop."""

    listen_for_wake: ListenForWake
    play_cached_reply: PlayCachedReply
    recognize_turn: RecognizeTurn
    speak: Speak
    clock: Clock = time.monotonic
    delay: Delay = asyncio.sleep
    choose: Callable[[tuple[str, ...]], str] = random.choice
    report_latency: Callable[[str], None] | None = None
    respond_to_turn: Callable[[str], Awaitable[StreamingReplyResult]] | None = None
    wake_motion: Callable[[], Awaitable[None]] | None = None
    report_motion: Callable[[str], None] | None = None
    owned_resources: tuple[object, ...] = ()


def build_voice_loop(
    *,
    history: ConversationHistory,
    asker: AskAdapter,
    adapters: LoopAdapters,
) -> VoiceLoop:
    """Build a loop whose controller and delay use one actual clock domain."""
    controller = ConversationController(adapters.clock, adapters.choose)
    return VoiceLoop(
        controller,
        adapters.listen_for_wake,
        adapters.play_cached_reply,
        adapters.recognize_turn,
        asker,
        adapters.speak,
        adapters.clock,
        adapters.delay,
        history=history,
        owned_resources=adapters.owned_resources,
        report_latency=adapters.report_latency,
        respond_to_turn=adapters.respond_to_turn,
        wake_motion=adapters.wake_motion,
        report_motion=adapters.report_motion,
    )


@dataclass(frozen=True)
class StartupValidation:
    config: VoiceConfig
    microphone: AlsaDevice
    speaker: AlsaDevice


def _validate_cache(config: VoiceConfig) -> None:
    WakeReplyCache(
        config.wake_cache_dir,
        resource_id=config.tts_resource_id,
    ).validate()


def _construct_runtime(
    startup: StartupValidation, history: ConversationHistory
) -> LoopAdapters:
    config = startup.config
    detector = SherpaWakeWordDetector(WakeWordConfig(config.kws_model_dir))
    wake_listener = WakeListenAdapter(startup.microphone.device, detector)
    cache = WakeReplyCache(
        config.wake_cache_dir,
        resource_id=config.tts_resource_id,
    )
    stream_ark_adapter = ArkStreamAdapter(config, history)
    sentence_tts = TtsPlaybackAdapter(config, startup.speaker)
    wake_motion = (
        WakeMotionAdapter(Esp32ServoClient(config.esp32_serial_by_id))
        if config.esp32_serial_by_id is not None
        else None
    )
    return LoopAdapters(
        listen_for_wake=wake_listener,
        play_cached_reply=CachedReplyPlaybackAdapter(cache, startup.speaker),
        recognize_turn=LiveAsrAdapter(config, startup.microphone.device),
        speak=TtsPlaybackAdapter(config, startup.speaker),
        clock=time.monotonic,
        delay=asyncio.sleep,
        choose=random.choice,
        report_latency=lambda message: print(message, flush=True),
        respond_to_turn=StreamingTurnAdapter(
            stream_ark_adapter,
            sentence_tts,
            play_network_error=lambda: CachedReplyPlaybackAdapter(
                cache, startup.speaker
            )(NETWORK_ERROR_REPLY),
        ),
        wake_motion=wake_motion,
        report_motion=lambda message: print(message, flush=True),
        owned_resources=(wake_listener, stream_ark_adapter),
    )


def _run_loop(loop: VoiceLoop) -> None:
    asyncio.run(loop.run_forever())


def _resolve_real_device(usb_id: str) -> AlsaDevice:
    return discover_alsa_device(usb_id, Path("/proc/asound"))


@dataclass(frozen=True)
class CliBindings:
    """Injectable startup seams; defaults are the real, side-effecting adapters."""

    load_config: Callable[[Path], VoiceConfig] = load_voice_config
    validate_models: Callable[[Path], object] = validate_model_dir
    validate_cache: Callable[[VoiceConfig], None] = _validate_cache
    resolve_device: Callable[[str], AlsaDevice] = _resolve_real_device
    import_dependency: Callable[[str], object] = importlib.import_module
    construct_runtime: Callable[[StartupValidation, ConversationHistory], LoopAdapters] = _construct_runtime
    run_loop: Callable[[VoiceLoop], None] = _run_loop


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LumiLamp 本地唤醒与半双工语音对话"
    )
    parser.add_argument("--config", type=Path, default=Path(".env.voice"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证配置、缓存、USB 身份与依赖，不打开音频或网络",
    )
    return parser


def _validate_startup(config_path: Path, bindings: CliBindings) -> StartupValidation:
    try:
        config = bindings.load_config(config_path)
    except (OSError, ValueError, ImportError) as error:
        raise StartupValidationError(
            "voice configuration is missing, unreadable, or invalid"
        ) from error

    try:
        bindings.validate_models(config.kws_model_dir)
    except (OSError, ValueError) as error:
        raise StartupValidationError("wake-word model files are missing or invalid") from error

    try:
        bindings.validate_cache(config)
    except (OSError, ValueError) as error:
        raise StartupValidationError("wake reply cache is missing or invalid") from error

    try:
        microphone = bindings.resolve_device(DEFAULT_MICROPHONE_USB_ID)
        speaker = bindings.resolve_device(SPEAKER_USB_ID)
    except (AudioDeviceNotFoundError, OSError, ValueError) as error:
        raise StartupValidationError("required USB audio device was not found") from error

    for dependency in DEPENDENCIES:
        try:
            bindings.import_dependency(dependency)
        except ImportError as error:
            raise StartupValidationError(
                f"required Python dependency is unavailable: {dependency}"
            ) from error

    return StartupValidation(config, microphone, speaker)


def main(
    argv: Sequence[str] | None = None,
    *,
    adapters: CliBindings | None = None,
) -> int:
    args = _parser().parse_args(argv)
    bindings = adapters if adapters is not None else CliBindings()
    try:
        startup = _validate_startup(args.config, bindings)
        if args.dry_run:
            print("voice dry-run: validation passed")
            return 0

        history = ConversationHistory()
        asker = ArkAskAdapter(startup.config, history)
        try:
            runtime = bindings.construct_runtime(startup, history)
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            raise StartupValidationError("voice runtime could not initialize") from error
        loop = build_voice_loop(history=history, asker=asker, adapters=runtime)
        print("voice loop starting; press Ctrl-C to stop")
        bindings.run_loop(loop)
        return 0
    except StartupValidationError as error:
        print(f"voice setup failed: {error}", file=sys.stderr)
        return 1
    except VoiceAdapterError:
        print("voice loop stopped after an operational adapter failure", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("voice loop stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
