"""Local, deterministic WAV cache for the four wake acknowledgements."""

from __future__ import annotations

import json
import uuid
import wave
from collections.abc import Callable
from pathlib import Path

from .tts import DEFAULT_SPEAKER


WAKE_REPLIES: tuple[str, ...] = ("我在呀", "你好呀", "嗯？", "请吩咐")
NETWORK_ERROR_REPLY = "网络好像断开了"
_CACHED_REPLIES = (*WAKE_REPLIES, NETWORK_ERROR_REPLY)
WAKE_REPLY_FORMAT_VERSION = 2

_FILENAMES = {
    "我在呀": "wo-zai-ya.wav",
    "你好呀": "ni-hao-ya.wav",
    "嗯？": "en.wav",
    "请吩咐": "qing-fen-fu.wav",
    NETWORK_ERROR_REPLY: "network-interrupted.wav",
}


class WakeReplyCache:
    """Prepare and verify the local acknowledgement-audio cache."""

    def __init__(
        self,
        root: Path,
        *,
        speaker: str = DEFAULT_SPEAKER,
        resource_id: str = "",
    ) -> None:
        self.root = Path(root)
        self.speaker = speaker
        self.resource_id = resource_id

    @property
    def manifest_path(self) -> Path:
        return self.root / "wake-replies.manifest.json"

    def path_for(self, text: str) -> Path:
        try:
            return self.root / _FILENAMES[text]
        except KeyError as error:
            raise ValueError(f"unsupported wake reply: {text!r}") from error

    def path_for_error(self) -> Path:
        return self.path_for(NETWORK_ERROR_REPLY)

    def manifest(self) -> dict[str, object]:
        return {
            "format_version": WAKE_REPLY_FORMAT_VERSION,
            "speaker": self.speaker,
            "resource_id": self.resource_id,
            "replies": [
                {"text": text, "file": self.path_for(text).name}
                for text in _CACHED_REPLIES
            ],
        }

    def validate(self) -> None:
        for text in _CACHED_REPLIES:
            self._validate_wav(self.path_for(text), text)

        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("wake reply cache manifest is missing or invalid") from error
        if manifest != self.manifest():
            raise ValueError("wake reply cache manifest does not match this cache")

    def prepare(self, synthesize: Callable[[str, Path], None]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError(f"wake reply cache path is not a directory: {self.root}")

        for text in _CACHED_REPLIES:
            destination = self.path_for(text)
            if self._is_valid_wav(destination, text):
                continue
            self._prepare_one(text, destination, synthesize)

        self.validate_wavs()
        self._write_manifest()

    def validate_wavs(self) -> None:
        """Verify cache audio files without requiring a manifest during preparation."""
        for text in _CACHED_REPLIES:
            self._validate_wav(self.path_for(text), text)

    def _prepare_one(
        self,
        text: str,
        destination: Path,
        synthesize: Callable[[str, Path], None],
    ) -> None:
        temporary = self._temporary_path(destination)
        try:
            synthesize(text, temporary)
            self._validate_wav(temporary, text)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"wake reply synthesis failed: {text}") from None

        if self._is_valid_wav(destination, text):
            temporary.unlink(missing_ok=True)
            return
        temporary.replace(destination)

    def _write_manifest(self) -> None:
        temporary = self._temporary_path(self.manifest_path)
        try:
            temporary.write_text(
                json.dumps(self.manifest(), ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.manifest_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _temporary_path(self, destination: Path) -> Path:
        return destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")

    @staticmethod
    def _is_valid_wav(path: Path, text: str) -> bool:
        try:
            WakeReplyCache._validate_wav(path, text)
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_wav(path: Path, text: str) -> None:
        try:
            with wave.open(str(path), "rb") as audio:
                if audio.getnchannels() != 1:
                    raise ValueError(f"wake reply {text!r} must be mono")
                if audio.getsampwidth() != 2:
                    raise ValueError(f"wake reply {text!r} must use 16-bit samples")
                if audio.getframerate() != 24000:
                    raise ValueError(f"wake reply {text!r} must use 24000 Hz audio")
                if audio.getnframes() <= 0:
                    raise ValueError(f"wake reply {text!r} must contain audio frames")
        except (OSError, EOFError, wave.Error) as error:
            raise ValueError(f"wake reply {text!r} is not a valid RIFF/WAVE file") from error
