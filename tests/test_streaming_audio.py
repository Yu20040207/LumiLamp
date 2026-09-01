import struct
import unittest

from lumilamp.voice.recorder import LevelConfig
from lumilamp.voice.streaming_audio import UtterancePacketizer


class StreamingAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LevelConfig(0.02, 0.01, trailing_silence_ms=800, max_seconds=10)
        self.speech = struct.pack("<" + "h" * 320, *(2000,) * 320)
        self.silence = bytes(640)

    def test_discards_silence_before_speech(self) -> None:
        packetizer = UtterancePacketizer(self.config)

        decisions = [packetizer.push(self.silence) for _ in range(20)]

        self.assertTrue(all(not decision.started for decision in decisions))
        self.assertTrue(all(not decision.packets for decision in decisions))

    def test_prepends_at_most_two_hundred_ms_without_oversized_packet(self) -> None:
        packetizer = UtterancePacketizer(self.config, pre_roll_chunks=10)
        quiet_chunks = [
            struct.pack("<" + "h" * 320, *(index,) * 320) for index in range(12)
        ]

        for chunk in quiet_chunks:
            decision = packetizer.push(chunk)
            self.assertFalse(decision.started)
            self.assertFalse(decision.packets)

        decision = packetizer.push(self.speech)

        self.assertTrue(decision.started)
        self.assertEqual(decision.packets, (b"".join(quiet_chunks[-10:]),))
        self.assertEqual(len(decision.packets[0]), 10 * 640)
        self.assertEqual(packetizer.finish(), (self.speech,))

    def test_never_emits_pre_roll_before_speech(self) -> None:
        packetizer = UtterancePacketizer(self.config, pre_roll_chunks=10)

        decision = packetizer.push(self.silence)

        self.assertFalse(decision.started)
        self.assertFalse(decision.packets)

    def test_emits_one_network_packet_for_ten_started_chunks(self) -> None:
        packetizer = UtterancePacketizer(self.config)

        decisions = [packetizer.push(self.speech) for _ in range(10)]

        self.assertEqual(decisions[-1].packets, (self.speech * 10,))
        self.assertTrue(decisions[-1].started)
        self.assertFalse(decisions[-1].finished)

    def test_finishes_after_trailing_silence_and_flushes_remainder(self) -> None:
        packetizer = UtterancePacketizer(self.config)
        packetizer.push(self.speech)

        decisions = [packetizer.push(self.silence) for _ in range(40)]
        remainder = packetizer.finish()

        self.assertTrue(decisions[-1].finished)
        self.assertEqual(remainder, (self.silence,))
        self.assertEqual(packetizer.finish(), ())

    def test_finishes_at_ten_second_limit_even_without_speech(self) -> None:
        packetizer = UtterancePacketizer(self.config)

        decision = None
        for _ in range(500):
            decision = packetizer.push(self.silence)

        self.assertIsNotNone(decision)
        self.assertTrue(decision.finished)
        self.assertFalse(decision.started)

    def test_rejects_chunk_with_wrong_size(self) -> None:
        packetizer = UtterancePacketizer(self.config)

        with self.assertRaisesRegex(ValueError, "640"):
            packetizer.push(b"short")


if __name__ == "__main__":
    unittest.main()
