"""Minimal, explicit client for the legacy Doubao streaming-ASR protocol."""

from __future__ import annotations

import asyncio
import gzip
import json
import struct
import uuid
import wave
from pathlib import Path
from typing import Any

from .config import VoiceConfig

ASR_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
_FRAME_HEADER = bytes((0x11,))


def build_start_frame(app_id: str, resource_id: str, sequence: int = 1) -> bytes:
    """Build the initial metadata frame; credentials are never included."""
    payload = {
        "user": {"uid": app_id},
        "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1, "codec": "raw"},
        "request": {
            "model_name": "bigmodel",
            "enable_punc": True,
            "enable_itn": True,
            "show_utterances": True,
            "resource_id": resource_id,
        },
    }
    compressed = gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    return (
        _FRAME_HEADER
        + bytes((0x11, 0x11, 0x00))
        + struct.pack(">i", sequence)
        + struct.pack(">I", len(compressed))
        + compressed
    )


def build_connection_headers(app_id: str, access_token: str, resource_id: str, request_id: str) -> dict[str, str]:
    """Return only the legacy speech-app authentication headers."""
    return {
        "X-Api-App-Key": app_id,
        "X-Api-Access-Key": access_token,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": request_id,
    }


def build_audio_frame(audio: bytes, sequence: int, final: bool) -> bytes:
    """Build a 200-ms PCM packet; a negative sequence marks the final packet."""
    if sequence <= 0:
        raise ValueError("audio sequence must be positive")
    compressed = gzip.compress(audio)
    signed_sequence = -sequence if final else sequence
    return (
        _FRAME_HEADER
        + bytes((0x23 if final else 0x21, 0x01, 0x00))
        + struct.pack(">i", signed_sequence)
        + struct.pack(">I", len(compressed))
        + compressed
    )


def parse_server_frame(frame: bytes) -> str | None:
    """Return ASR text or raise a non-sensitive error returned by the service."""
    if len(frame) < 8:
        return None
    header_size = (frame[0] & 0x0F) * 4
    if header_size < 4 or len(frame) < header_size + 4:
        return None
    message_type = frame[1] >> 4
    flags = frame[1] & 0x0F
    offset = header_size
    if message_type == 0x0F:
        if len(frame) < offset + 8:
            return None
        code = struct.unpack(">I", frame[offset : offset + 4])[0]
        size = struct.unpack(">I", frame[offset + 4 : offset + 8])[0]
        message = frame[offset + 8 : offset + 8 + size].decode(errors="replace")
        raise RuntimeError(f"Doubao ASR error {code}: {message}")
    if message_type != 0x09:
        return None
    if flags & 0x01:
        if len(frame) < offset + 4:
            return None
        offset += 4
    size = struct.unpack(">I", frame[offset : offset + 4])[0]
    body = frame[offset + 4 : offset + 4 + size]
    if frame[2] & 0x0F == 1:
        body = gzip.decompress(body)
    message: Any = json.loads(body.decode())
    result = message.get("result", {}) if isinstance(message, dict) else {}
    return result.get("text") if isinstance(result, dict) else None


def _read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as recording:
        if recording.getnchannels() != 1 or recording.getframerate() != 16000 or recording.getsampwidth() != 2:
            raise ValueError("ASR audio must be mono, 16 kHz, signed 16-bit WAV")
        return recording.readframes(recording.getnframes())


async def transcribe_wav(config: VoiceConfig, wav_path: Path) -> str:
    """Send a WAV recording to Doubao ASR and return its final transcript."""
    import websockets

    pcm = _read_pcm(wav_path)
    if not pcm:
        raise ValueError("ASR audio is empty")
    headers = build_connection_headers(
        config.app_id, config.access_token, config.asr_resource_id, str(uuid.uuid4())
    )
    transcript = ""
    async with websockets.connect(ASR_ENDPOINT, additional_headers=headers, open_timeout=15) as socket:
        await socket.send(build_start_frame(config.app_id, config.asr_resource_id, sequence=1))
        start_response = await asyncio.wait_for(socket.recv(), timeout=15)
        if isinstance(start_response, bytes):
            parse_server_frame(start_response)
        packet_size = 6400  # 200 ms at mono 16 kHz, signed 16-bit.
        total_packets = (len(pcm) + packet_size - 1) // packet_size
        for index in range(total_packets):
            packet = pcm[index * packet_size : (index + 1) * packet_size]
            await socket.send(build_audio_frame(packet, index + 2, index + 1 == total_packets))
            if index + 1 != total_packets:
                await asyncio.sleep(0.2)
        while True:
            response = await asyncio.wait_for(socket.recv(), timeout=15)
            if isinstance(response, str):
                continue
            text = parse_server_frame(response)
            if text:
                transcript = text
            if response[1] >> 4 == 0x09 and (response[1] & 0x0F) == 0x03:
                break
    if not transcript:
        raise RuntimeError("Doubao ASR returned no transcript")
    return transcript
