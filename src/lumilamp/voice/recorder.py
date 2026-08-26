"""Explicit ALSA recording wrapper for the USB microphone."""

from __future__ import annotations

import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass
from math import sqrt
from pathlib import Path


_SAMPLE_RATE = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2
_CHUNK_MS = 20
_CHUNK_BYTES = _SAMPLE_RATE * _SAMPLE_WIDTH * _CHUNK_MS // 1000


@dataclass(frozen=True)
class LevelConfig:
    """Thresholds and limits for one user utterance."""

    start_threshold: float
    silence_threshold: float
    trailing_silence_ms: int = 800
    max_seconds: int = 10


def should_finish(
    started: bool, silent_ms: int, elapsed_ms: int, config: LevelConfig
) -> bool:
    """Return whether the current utterance has reached an endpoint."""
    if elapsed_ms >= config.max_seconds * 1000:
        return True
    return started and silent_ms >= config.trailing_silence_ms


def pcm_level(chunk: bytes) -> float:
    """Return the normalized RMS level of little-endian signed 16-bit PCM."""
    if not chunk:
        return 0.0
    samples = array("h")
    samples.frombytes(chunk)
    if sys.byteorder != "little":
        samples.byteswap()
    return sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768


def record_utterance(device: str, output_path: Path, config: LevelConfig) -> bool:
    """Capture one thresholded utterance into a mono 16 kHz WAV file."""
    process = subprocess.Popen(
        [
            "arecord",
            "-D",
            device,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(_SAMPLE_RATE),
            "-c",
            str(_CHANNELS),
        ],
        stdout=subprocess.PIPE,
    )
    accepted: list[bytes] = []
    started = False
    silent_ms = 0
    elapsed_ms = 0
    try:
        if process.stdout is None:
            raise RuntimeError("arecord did not provide PCM output")
        while True:
            chunk = process.stdout.read(_CHUNK_BYTES)
            if not chunk:
                break
            elapsed_ms += _CHUNK_MS
            level = pcm_level(chunk)
            if not started and level >= config.start_threshold:
                started = True
                accepted.append(chunk)
            elif started:
                accepted.append(chunk)
                silent_ms = (
                    silent_ms + _CHUNK_MS
                    if level < config.silence_threshold
                    else 0
                )
            if should_finish(started, silent_ms, elapsed_ms, config):
                break
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait()

    if not started:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as audio:
        audio.setnchannels(_CHANNELS)
        audio.setsampwidth(_SAMPLE_WIDTH)
        audio.setframerate(_SAMPLE_RATE)
        audio.writeframes(b"".join(accepted))
    return True


def record_wav(device: str, output_path: str, seconds: int) -> None:
    """Record a mono 16 kHz WAV file; no recording occurs until called."""
    if seconds <= 0:
        raise ValueError("recording duration must be positive")
    subprocess.run(
        [
            "arecord",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-d",
            str(seconds),
            output_path,
        ],
        check=True,
    )
