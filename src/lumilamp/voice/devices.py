"""Stable ALSA capture-device discovery for LumiLamp USB microphones."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MICROPHONE_USB_ID = "08bb:2902"
_SAFE_CARD_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class AudioDeviceNotFoundError(RuntimeError):
    """Raised when a USB ALSA device cannot be selected unambiguously."""


class MicrophoneNotFoundError(AudioDeviceNotFoundError):
    """Raised when a USB microphone cannot be selected unambiguously."""


@dataclass(frozen=True)
class AlsaDevice:
    """Stable ALSA card identity and its plug device name."""

    card_id: str
    device: str


def discover_alsa_device(usb_id: str, proc_root: Path) -> AlsaDevice:
    """Return the stable ALSA device for exactly one matching USB ID."""
    expected = usb_id.strip().lower()
    matches: list[str] = []
    for card in sorted(proc_root.glob("card[0-9]*")):
        if not card.is_dir() or not card.name[4:].isdigit():
            continue
        try:
            actual = (card / "usbid").read_text(encoding="ascii").strip().lower()
            card_id = (card / "id").read_text(encoding="ascii").strip()
        except (FileNotFoundError, OSError, UnicodeError):
            continue
        if actual != expected:
            continue
        if card_id == "default" or not _SAFE_CARD_ID.fullmatch(card_id):
            raise AudioDeviceNotFoundError(
                f"audio device {expected} has invalid ALSA card ID"
            )
        matches.append(card_id)

    if not matches:
        raise AudioDeviceNotFoundError(f"audio device USB ID {expected} was not found")
    if len(matches) > 1:
        raise AudioDeviceNotFoundError(f"multiple audio devices match USB ID {expected}")
    card_id = matches[0]
    return AlsaDevice(card_id, f"plughw:CARD={card_id},DEV=0")


def discover_alsa_capture_device(
    usb_id: str = DEFAULT_MICROPHONE_USB_ID,
    proc_root: Path = Path("/proc/asound"),
) -> str:
    """Return a stable ALSA plug device for exactly one matching USB ID."""
    try:
        return discover_alsa_device(usb_id, proc_root).device
    except AudioDeviceNotFoundError as error:
        raise MicrophoneNotFoundError(str(error).replace("audio device", "microphone")) from error
