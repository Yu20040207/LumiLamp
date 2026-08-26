import base64
import json
import unittest

from lumilamp.voice.tts import build_tts_body, parse_sse_audio


class VoiceTtsTests(unittest.TestCase):
    def test_builds_normal_conversation_request_at_system_volume(self) -> None:
        body = build_tts_body("你好，我是 LumiLamp。")

        params = body["req_params"]
        self.assertEqual(params["speaker"], "zh_female_vv_uranus_bigtts")
        self.assertEqual(params["sample_rate"], 24000)
        self.assertEqual(params["audio_params"]["format"], "pcm")
        self.assertEqual(params["audio_params"]["loudness_rate"], 0)

    def test_allows_explicit_maximum_cloud_loudness(self) -> None:
        body = build_tts_body("你好，我是 LumiLamp。", loudness_rate=100)
        self.assertEqual(body["req_params"]["audio_params"]["loudness_rate"], 100)

    def test_collects_audio_from_successful_sse_events(self) -> None:
        first = base64.b64encode(b"first").decode()
        second = base64.b64encode(b"second").decode()
        stream = "\n".join(
            (
                f'data: {json.dumps({"code": 20000000, "data": first})}',
                f'data: {json.dumps({"code": 0, "data": second})}',
            )
        )

        self.assertEqual(parse_sse_audio(stream.splitlines()), b"firstsecond")
