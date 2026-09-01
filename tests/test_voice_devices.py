import tempfile
import unittest
from pathlib import Path

from lumilamp.voice.devices import (
    AlsaDevice,
    AudioDeviceNotFoundError,
    MicrophoneNotFoundError,
    discover_alsa_device,
    discover_alsa_capture_device,
)


class VoiceDeviceTests(unittest.TestCase):
    @staticmethod
    def _write_card(root: Path, number: int, usb_id: str, card_id: str) -> None:
        card = root / f"card{number}"
        card.mkdir()
        (card / "usbid").write_text(f"{usb_id}\n", encoding="ascii")
        (card / "id").write_text(f"{card_id}\n", encoding="ascii")

    def test_selects_card_name_by_usb_id_not_card_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_card(root, 2, "1b3f:2008", "Speaker")
            self._write_card(root, 7, "08BB:2902", "Microphone")

            device = discover_alsa_capture_device(proc_root=root)

        self.assertEqual(device, "plughw:CARD=Microphone,DEV=0")

    def test_discovers_speaker_by_usb_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_card(root, 2, "1b3f:2008", "Device_1")

            device = discover_alsa_device("1b3f:2008", root)

        self.assertEqual(device, AlsaDevice("Device_1", "plughw:CARD=Device_1,DEV=0"))

    def test_rejects_two_matching_speakers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_card(root, 1, "1b3f:2008", "SpeakerA")
            self._write_card(root, 2, "1b3f:2008", "SpeakerB")

            with self.assertRaisesRegex(AudioDeviceNotFoundError, "multiple"):
                discover_alsa_device("1b3f:2008", root)

    def test_rejects_missing_microphone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MicrophoneNotFoundError, "08bb:2902"):
                discover_alsa_capture_device(proc_root=Path(directory))

    def test_rejects_ambiguous_microphone_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_card(root, 3, "08bb:2902", "MicA")
            self._write_card(root, 4, "08bb:2902", "MicB")

            with self.assertRaisesRegex(MicrophoneNotFoundError, "multiple"):
                discover_alsa_capture_device(proc_root=root)

    def test_rejects_unsafe_alsa_card_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_card(root, 3, "08bb:2902", "unsafe id")

            with self.assertRaisesRegex(MicrophoneNotFoundError, "invalid"):
                discover_alsa_capture_device(proc_root=root)


if __name__ == "__main__":
    unittest.main()
