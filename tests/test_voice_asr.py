import gzip
import json
import struct
import unittest

from lumilamp.voice.asr import (
    ASR_ENDPOINT,
    build_audio_frame,
    build_connection_headers,
    build_start_frame,
    parse_server_frame,
)


class VoiceAsrProtocolTests(unittest.TestCase):
    @staticmethod
    def _server_result_frame(text: str, flags: int, sequence: int) -> bytes:
        body = json.dumps({"result": {"text": text}}).encode()
        return (
            bytes((0x11, 0x90 | flags, 0x10, 0x00))
            + (struct.pack(">i", sequence) if flags & 0x01 else b"")
            + struct.pack(">I", len(body))
            + body
        )

    def test_uses_bidirectional_streaming_endpoint(self) -> None:
        self.assertEqual(
            ASR_ENDPOINT,
            "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
        )

    def test_start_frame_has_gzipped_json_payload(self) -> None:
        frame = build_start_frame("lamp", "volc.seedasr.sauc.duration")

        self.assertEqual(frame[:4], bytes((0x11, 0x11, 0x11, 0x00)))
        self.assertEqual(struct.unpack(">i", frame[4:8])[0], 1)
        payload_size = struct.unpack(">I", frame[8:12])[0]
        payload = json.loads(gzip.decompress(frame[12 : 12 + payload_size]))
        self.assertEqual(payload["user"]["uid"], "lamp")
        self.assertEqual(payload["audio"]["rate"], 16000)
        self.assertEqual(payload["request"]["resource_id"], "volc.seedasr.sauc.duration")

    def test_final_audio_frame_has_negative_sequence(self) -> None:
        frame = build_audio_frame(b"pcm", sequence=3, final=True)

        self.assertEqual(frame[:4], bytes((0x11, 0x23, 0x01, 0x00)))
        self.assertEqual(struct.unpack(">i", frame[4:8])[0], -3)
        payload_size = struct.unpack(">I", frame[8:12])[0]
        self.assertEqual(gzip.decompress(frame[12 : 12 + payload_size]), b"pcm")

    def test_parse_server_frame_extracts_result_text(self) -> None:
        body = json.dumps({"result": {"text": "你好，LumiLamp"}}).encode()
        frame = bytes((0x11, 0x90, 0x10, 0x00)) + struct.pack(">I", len(body)) + body

        result = parse_server_frame(frame)

        self.assertEqual(result.text, "你好，LumiLamp")
        self.assertFalse(result.is_final)
        self.assertIsNone(result.sequence)

    def test_parse_server_frame_distinguishes_partial_and_final_results(self) -> None:
        partial = parse_server_frame(self._server_result_frame("你好", 0x01, 2))
        final = parse_server_frame(
            self._server_result_frame("你好露米", 0x03, -3)
        )

        self.assertEqual((partial.text, partial.is_final, partial.sequence), ("你好", False, 2))
        self.assertEqual((final.text, final.is_final, final.sequence), ("你好露米", True, -3))

    def test_connection_headers_use_connect_id(self) -> None:
        headers = build_connection_headers("app", "token", "resource", "request-id")

        self.assertEqual(headers["X-Api-Connect-Id"], "request-id")
