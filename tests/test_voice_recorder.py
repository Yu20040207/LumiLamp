import unittest
from unittest.mock import patch

from lumilamp.voice.recorder import record_wav


class RecorderTests(unittest.TestCase):
    def test_records_mono_16khz_wav_from_configured_device(self) -> None:
        with patch("lumilamp.voice.recorder.subprocess.run") as run:
            record_wav("plughw:CARD=Device,DEV=0", "/tmp/lumilamp-test.wav", 3)

        run.assert_called_once_with(
            [
                "arecord",
                "-D",
                "plughw:CARD=Device,DEV=0",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-d",
                "3",
                "/tmp/lumilamp-test.wav",
            ],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
