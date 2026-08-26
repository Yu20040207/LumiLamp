import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from lumilamp.voice.ark import ask_ark, build_chat_body, parse_chat_response
from lumilamp.voice.config import VoiceConfig


class ArkClientTests(unittest.TestCase):
    def test_builds_short_chinese_assistant_request(self) -> None:
        body = build_chat_body("model-1", "你是谁？")
        self.assertEqual(body["model"], "model-1")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "你是谁？"})
        self.assertEqual(body["max_tokens"], 160)

    def test_rejects_blank_input(self) -> None:
        with self.assertRaises(ValueError):
            build_chat_body("model-1", "  ")

    def test_rejects_blank_model_id(self) -> None:
        with self.assertRaises(ValueError):
            build_chat_body("  ", "你好")

    def test_includes_concise_lumilamp_system_prompt(self) -> None:
        body = build_chat_body("model-1", "你好")
        prompt = body["messages"][0]["content"]
        self.assertIn("露米", prompt)
        self.assertIn("台灯", prompt)
        self.assertLess(len(prompt), 150)

    def test_extracts_assistant_text(self) -> None:
        payload = {"choices": [{"message": {"role": "assistant", "content": "我是露米。"}}]}
        self.assertEqual(parse_chat_response(payload), "我是露米。")

    def test_rejects_malformed_or_blank_response(self) -> None:
        for payload in ({}, {"choices": []}, {"choices": [{"message": {"content": " "}}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_chat_response(payload)

    @patch("lumilamp.voice.ark.urlopen")
    def test_ask_ark_sends_bearer_and_returns_text(self, urlopen) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "你好。"}}]}).encode()

        urlopen.return_value = Response()
        config = VoiceConfig("app", "token", "asr", "tts", "secret-key", "model")
        self.assertEqual(ask_ark(config, "你好"), "你好。")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

    @patch("lumilamp.voice.ark.urlopen")
    def test_rejects_blank_api_key_without_request(self, urlopen) -> None:
        config = VoiceConfig("app", "token", "asr", "tts", "  ", "model")
        with self.assertRaisesRegex(ValueError, "API key"):
            ask_ark(config, "你好")
        urlopen.assert_not_called()

    @patch("lumilamp.voice.ark.urlopen")
    def test_http_error_redacts_credentials_and_body(self, urlopen) -> None:
        api_key = "super-secret-key"
        request_body_secret = "private-body-text"
        error = HTTPError(
            "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            401,
            request_body_secret,
            {"X-Request-Id": "req-123"},
            None,
        )
        urlopen.side_effect = error
        config = VoiceConfig("app", "token", "asr", "tts", api_key, "model")
        with self.assertRaises(RuntimeError) as caught:
            ask_ark(config, "你好")
        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("req-123", message)
        self.assertNotIn(api_key, message)
        self.assertNotIn(request_body_secret, message)


if __name__ == "__main__":
    unittest.main()
