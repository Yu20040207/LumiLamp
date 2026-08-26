import struct
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lumilamp.voice.recorder import (
    LevelConfig,
    pcm_level,
    record_utterance,
    should_finish,
)


class UtteranceEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LevelConfig(
            0.02, 0.01, trailing_silence_ms=800, max_seconds=10
        )

    def test_finishes_after_eight_hundred_ms_silence(self) -> None:
        self.assertTrue(should_finish(True, 800, 2400, self.config))

    def test_does_not_finish_before_speech_starts(self) -> None:
        self.assertFalse(should_finish(False, 900, 2400, self.config))

    def test_caps_an_utterance_at_ten_seconds(self) -> None:
        self.assertTrue(should_finish(True, 0, 10000, self.config))


class PcmLevelTests(unittest.TestCase):
    def test_returns_normalized_rms_for_signed_sixteen_bit_samples(self) -> None:
        chunk = struct.pack("<hhh", 0, 16384, -16384)

        self.assertAlmostEqual(pcm_level(chunk), 0.408248, places=6)

    def test_treats_an_empty_chunk_as_silence(self) -> None:
        self.assertEqual(pcm_level(b""), 0.0)


class ChunkStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.read_sizes: list[int] = []

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return next(self._chunks, b"")


class CaptureProcess:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = ChunkStream(chunks)
        self.terminated = False
        self.waited = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self) -> None:
        self.waited = True


class UtteranceCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LevelConfig(0.02, 0.01)
        self.speech = struct.pack("<" + "h" * 320, *(2000,) * 320)
        self.silence = bytes(640)

    @patch("lumilamp.voice.recorder.wave.open")
    @patch("lumilamp.voice.recorder.subprocess.Popen")
    def test_writes_only_audio_after_speech_starts_and_stops_at_trailing_silence(
        self, popen: MagicMock, open_wav: MagicMock
    ) -> None:
        process = CaptureProcess([self.silence] * 3 + [self.speech] + [self.silence] * 40)
        popen.return_value = process
        writer = MagicMock()
        open_wav.return_value.__enter__.return_value = writer

        recorded = record_utterance("plughw:USB", Path("recorded.wav"), self.config)

        self.assertTrue(recorded)
        popen.assert_called_once_with(
            [
                "arecord",
                "-D",
                "plughw:USB",
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
            ],
            stdout=subprocess.PIPE,
        )
        self.assertEqual(process.stdout.read_sizes, [640] * 44)
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)
        writer.setnchannels.assert_called_once_with(1)
        writer.setsampwidth.assert_called_once_with(2)
        writer.setframerate.assert_called_once_with(16000)
        writer.writeframes.assert_called_once_with(self.speech + self.silence * 40)

    @patch("lumilamp.voice.recorder.wave.open")
    @patch("lumilamp.voice.recorder.subprocess.Popen")
    def test_returns_false_without_writing_when_speech_never_starts(
        self, popen: MagicMock, open_wav: MagicMock
    ) -> None:
        process = CaptureProcess([self.silence] * 500 + [self.speech])
        popen.return_value = process

        recorded = record_utterance("plughw:USB", Path("not-recorded.wav"), self.config)

        self.assertFalse(recorded)
        self.assertEqual(process.stdout.read_sizes, [640] * 500)
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)
        open_wav.assert_not_called()


if __name__ == "__main__":
    unittest.main()
