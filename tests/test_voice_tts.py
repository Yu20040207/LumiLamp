import base64
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from lumilamp.voice.config import AsrConfig, VoiceConfig
from lumilamp.voice.tts import (
    TTS_ENDPOINT,
    build_tts_body,
    build_tts_headers,
    parse_tts_chunks,
    synthesize_to_wav,
)


def make_config() -> VoiceConfig:
    return VoiceConfig(
        asr=AsrConfig("app-123", "asr-secret", "volc.seedasr.sauc.duration"),
        tts_api_key="tts-secret",
        tts_resource_id="seed-tts-2.0",
        ark_api_key="ark-secret",
        ark_model_id="doubao-seed-2-0-lite-260428",
        kws_model_dir=Path("/opt/lumilamp/models/kws"),
        wake_cache_dir=Path("/opt/lumilamp/cache/wake"),
    )


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

    def test_uses_current_tts_v2_endpoint_and_headers(self) -> None:
        self.assertEqual(TTS_ENDPOINT, "https://openspeech.bytedance.com/api/v3/tts/unidirectional")
        config = make_config()
        headers = build_tts_headers(config, "request-1")
        self.assertEqual(headers["X-Api-Key"], "tts-secret")
        self.assertNotEqual(headers["X-Api-Key"], config.asr.access_token)
        self.assertEqual(headers["X-Api-Resource-Id"], "seed-tts-2.0")
        self.assertEqual(headers["X-Api-Request-Id"], "request-1")
        self.assertNotIn("X-Api-App-Key", headers)
        self.assertNotIn("X-Api-Access-Key", headers)

    def test_collects_audio_from_successful_json_chunks(self) -> None:
        first = base64.b64encode(b"first").decode()
        second = base64.b64encode(b"second").decode()
        chunks = (
            json.dumps({"code": 0, "data": first}).encode(),
            json.dumps({"code": 0, "data": second}).encode(),
        )

        self.assertEqual(parse_tts_chunks(chunks), b"firstsecond")

    def test_accepts_provider_terminal_success_after_audio(self) -> None:
        audio = base64.b64encode(b"pcm-audio").decode()
        chunks = (
            json.dumps({"code": 0, "data": audio}).encode(),
            json.dumps({"code": 20000000, "message": "OK", "data": ""}).encode(),
        )

        self.assertEqual(parse_tts_chunks(chunks), b"pcm-audio")

    def test_rejects_terminal_code_with_non_success_message(self) -> None:
        chunks = (json.dumps({"code": 20000000, "message": "failed", "data": ""}).encode(),)

        with self.assertRaisesRegex(RuntimeError, "20000000: failed"):
            parse_tts_chunks(chunks)

    def test_terminal_success_without_audio_still_rejects_response(self) -> None:
        chunks = (json.dumps({"code": 20000000, "message": "OK", "data": ""}).encode(),)

        with self.assertRaisesRegex(RuntimeError, "no audio"):
            parse_tts_chunks(chunks)

    def test_rejects_response_chunk_without_explicit_code(self) -> None:
        audio = base64.b64encode(b"pcm-audio").decode()
        chunks = (json.dumps({"data": audio}).encode(),)

        with self.assertRaisesRegex(ValueError, "code"):
            parse_tts_chunks(chunks)

    def test_rejects_response_chunk_with_non_numeric_code(self) -> None:
        chunks = (json.dumps({"code": "0", "data": ""}).encode(),)

        with self.assertRaisesRegex(ValueError, "code"):
            parse_tts_chunks(chunks)

    def test_rejects_non_string_audio_data(self) -> None:
        chunks = (json.dumps({"code": 0, "data": 123}).encode(),)

        with self.assertRaisesRegex(ValueError, "data"):
            parse_tts_chunks(chunks)

    def test_rejects_malformed_base64_audio_data(self) -> None:
        chunks = (json.dumps({"code": 0, "data": "cGNt$LWF1ZGlv"}).encode(),)

        with self.assertRaisesRegex(ValueError, "base64"):
            parse_tts_chunks(chunks)

    def test_rejects_terminal_success_before_audio(self) -> None:
        audio = base64.b64encode(b"pcm-audio").decode()
        chunks = (
            json.dumps({"code": 20000000, "message": "OK", "data": ""}).encode(),
            json.dumps({"code": 0, "data": audio}).encode(),
        )

        with self.assertRaisesRegex(RuntimeError, "before audio"):
            parse_tts_chunks(chunks)

    def test_rejects_frame_after_terminal_success(self) -> None:
        audio = base64.b64encode(b"pcm-audio").decode()
        chunks = (
            json.dumps({"code": 0, "data": audio}).encode(),
            json.dumps({"code": 20000000, "message": "OK", "data": ""}).encode(),
            json.dumps({"code": 0, "data": audio}).encode(),
        )

        with self.assertRaisesRegex(RuntimeError, "after terminal"):
            parse_tts_chunks(chunks)

    def test_rejects_nonzero_provider_error_chunk(self) -> None:
        chunks = (json.dumps({"code": 123, "message": "bad request"}).encode(),)

        with self.assertRaisesRegex(RuntimeError, "123: bad request"):
            parse_tts_chunks(chunks)

    def test_rejects_response_without_audio(self) -> None:
        chunks = (json.dumps({"code": 0, "data": ""}).encode(),)

        with self.assertRaisesRegex(RuntimeError, "zero bytes"):
            parse_tts_chunks(chunks)

    @patch("lumilamp.voice.tts.urlopen")
    def test_synthesizes_json_chunks_to_pcm_wav_without_external_io(self, urlopen) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                encoded = base64.b64encode(b"pcm-audio!").decode()
                return iter((json.dumps({"code": 0, "data": encoded}).encode(),))

        urlopen.return_value = Response()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "speech.wav"
            synthesize_to_wav(make_config(), "你好", output_path)

            with wave.open(str(output_path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getframerate(), 24000)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.readframes(audio.getnframes()), b"pcm-audio!")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, TTS_ENDPOINT)
        self.assertEqual(request.get_header("X-api-key"), "tts-secret")
