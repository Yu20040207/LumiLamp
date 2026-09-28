import unittest
from pathlib import Path
from unittest.mock import patch

from lumilamp.voice.audio_output import (
    play_wav,
    set_usb_speaker_volume,
    speak,
    validate_volume,
)
from lumilamp.voice.config import VoiceConfig


class AudioOutputTests(unittest.TestCase):
    def test_accepts_conversation_volume(self) -> None:
        self.assertEqual(validate_volume(70), 70)

    def test_rejects_volume_above_one_hundred(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            validate_volume(101)

    def test_rejects_negative_volume(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            validate_volume(-1)

    @patch("lumilamp.voice.audio_output.subprocess.run")
    def test_sets_volume_with_safe_argument_list(self, run) -> None:
        set_usb_speaker_volume(2, 70)
        run.assert_called_once_with(
            ["amixer", "-c", "2", "sset", "Speaker", "70%", "unmute"],
            check=True,
        )

    @patch("lumilamp.voice.audio_output.subprocess.run")
    def test_plays_wav_with_safe_argument_list(self, run) -> None:
        output_path = Path("/tmp/test.wav")

        play_wav("plughw:Device", output_path)

        run.assert_called_once_with(
            ["aplay", "-D", "plughw:Device", str(output_path)],
            check=True,
        )

    @patch("lumilamp.voice.audio_output.play_wav")
    @patch("lumilamp.voice.audio_output.set_usb_speaker_volume")
    @patch("lumilamp.voice.audio_output.synthesize_to_wav")
    def test_speak_synthesizes_sets_volume_then_plays(
        self, synthesize, set_volume, play
    ) -> None:
        config = VoiceConfig("app", "token", "asr", "tts", "key", "model")
        output_path = Path("/tmp/test.wav")

        order: list[str] = []
        synthesize.side_effect = lambda *args: order.append("synthesize")
        set_volume.side_effect = lambda *args: order.append("volume")
        play.side_effect = lambda *args: order.append("play")

        speak(config, "你好", output_path, card=2, device="plughw:Device")

        self.assertEqual(
            [call.args for call in synthesize.call_args_list],
            [(config, "你好", output_path)],
        )
        self.assertEqual(set_volume.call_args.args, (2, 70))
        self.assertEqual(play.call_args.args, ("plughw:Device", output_path))
        self.assertEqual(order, ["synthesize", "volume", "play"])


if __name__ == "__main__":
    unittest.main()
