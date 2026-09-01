"""Safe, explicit ALSA playback boundaries for conversation audio."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import VoiceConfig
from .tts import synthesize_to_wav


CONVERSATION_VOLUME_PERCENT = 80


def validate_volume(percent: int) -> int:
    """Validate and return an ALSA mixer percentage."""
    if not 0 <= percent <= 100:
        raise ValueError("volume must be between 0 and 100")
    return percent


def set_usb_speaker_volume(card_id: str, percent: int = 70) -> None:
    """Set the selected ALSA card's Speaker control without a shell."""
    validated = validate_volume(percent)
    subprocess.run(
        ["amixer", "-c", card_id, "sset", "Speaker", f"{validated}%", "unmute"],
        check=True,
    )


def play_wav(device: str, path: Path) -> None:
    """Play one WAV file through the selected ALSA device."""
    subprocess.run(["aplay", "-D", device, str(path)], check=True)


def speak(
    config: VoiceConfig,
    text: str,
    output_path: Path,
    card_id: str,
    device: str,
) -> None:
    """Synthesize, set conversation volume, and play one response."""
    synthesize_to_wav(config, text, output_path)
    set_usb_speaker_volume(card_id, CONVERSATION_VOLUME_PERCENT)
    play_wav(device, output_path)
