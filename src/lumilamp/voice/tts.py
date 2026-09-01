"""Doubao TTS 2.0 synthesis using the standard-library HTTP client."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
import wave
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen

from .config import VoiceConfig

TTS_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"


def build_tts_headers(config: VoiceConfig, request_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Api-Key": config.tts_api_key,
        "X-Api-Resource-Id": config.tts_resource_id,
        "X-Api-Request-Id": request_id,
    }


def build_tts_body(text: str, loudness_rate: int = 0) -> dict[str, object]:
    if not text.strip():
        raise ValueError("TTS text must not be empty")
    return {
        "user": {"uid": "lumilamp"},
        "req_params": {
            "text": text.strip(),
            "speaker": DEFAULT_SPEAKER,
            "sample_rate": 24000,
            "audio_params": {
                "format": "pcm",
                "speech_rate": 0,
                "loudness_rate": loudness_rate,
            },
            "additions": json.dumps(
                {"disable_markdown_filter": False, "enable_latex_tn": False},
                separators=(",", ":"),
            ),
        },
    }


def parse_tts_chunks(chunks: Iterable[bytes]) -> bytes:
    audio_chunks: list[bytes] = []
    terminal_seen = False
    for chunk in chunks:
        if terminal_seen:
            raise RuntimeError("Doubao TTS returned frame after terminal success")
        event = json.loads(chunk)
        if not isinstance(event, dict):
            raise ValueError("Doubao TTS response chunk is malformed")
        code = event.get("code")
        if isinstance(code, bool) or not isinstance(code, int):
            raise ValueError("Doubao TTS response code must be an integer")
        data = event.get("data")
        if data is not None and not isinstance(data, str):
            raise ValueError("Doubao TTS response data must be a string")
        if code == 20000000 and event.get("message") == "OK" and not event.get("data"):
            if not audio_chunks:
                raise RuntimeError("Doubao TTS returned no audio: terminal success before audio")
            terminal_seen = True
            continue
        if code != 0:
            raise RuntimeError(f"Doubao TTS error {code}: {event.get('message', '')}")
        if data is not None:
            try:
                decoded = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("Doubao TTS response data is not valid base64") from error
            if not decoded:
                raise RuntimeError("Doubao TTS audio chunk decoded to zero bytes")
            audio_chunks.append(decoded)
    if not audio_chunks:
        raise RuntimeError("Doubao TTS returned no audio")
    return b"".join(audio_chunks)


def synthesize_to_wav(config: VoiceConfig, text: str, output_path: Path) -> None:
    body = json.dumps(build_tts_body(text), ensure_ascii=False).encode("utf-8")
    request = Request(
        TTS_ENDPOINT,
        data=body,
        method="POST",
        headers=build_tts_headers(config, str(uuid.uuid4())),
    )
    with urlopen(request, timeout=60) as response:
        pcm = parse_tts_chunks(response)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(pcm)
