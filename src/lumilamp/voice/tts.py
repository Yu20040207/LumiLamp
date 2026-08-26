"""Doubao TTS 2.0 synthesis using the standard-library HTTP client."""

from __future__ import annotations

import base64
import json
import uuid
import wave
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen

from .config import VoiceConfig

TTS_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"


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


def parse_sse_audio(lines: Iterable[str]) -> bytes:
    chunks: list[bytes] = []
    for line in lines:
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:].strip())
        code = event.get("code", 0)
        if code not in (0, 20000000):
            raise RuntimeError(f"Doubao TTS error {code}: {event.get('message', '')}")
        if event.get("data"):
            chunks.append(base64.b64decode(event["data"]))
    if not chunks:
        raise RuntimeError("Doubao TTS returned no audio")
    return b"".join(chunks)


def synthesize_to_wav(config: VoiceConfig, text: str, output_path: Path) -> None:
    body = json.dumps(build_tts_body(text), ensure_ascii=False).encode("utf-8")
    request = Request(
        TTS_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-App-Key": config.app_id,
            "X-Api-Access-Key": config.access_token,
            "X-Api-Resource-Id": config.tts_resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        },
    )
    with urlopen(request, timeout=60) as response:
        pcm = parse_sse_audio(line.decode("utf-8") for line in response)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(pcm)
