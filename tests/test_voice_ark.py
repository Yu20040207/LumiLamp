import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from lumilamp.voice.ark import (
    ask_ark,
    build_chat_body,
    build_stream_chat_body,
    parse_chat_response,
    parse_sse_data,
    stream_ark,
)
from lumilamp.voice.config import AsrConfig, VoiceConfig
from lumilamp.voice.conversation import ConversationHistory


def make_config(ark_api_key: str = "secret-key") -> VoiceConfig:
    return VoiceConfig(
        asr=AsrConfig("app", "asr-token", "asr-resource"),
        tts_api_key="tts-secret",
        tts_resource_id="seed-tts-2.0",
        ark_api_key=ark_api_key,
        ark_model_id="model",
        kws_model_dir=Path("/opt/lumilamp/models/kws"),
        wake_cache_dir=Path("/opt/lumilamp/cache/wake"),
    )


class ArkClientTests(unittest.TestCase):
    def test_build_stream_body_preserves_existing_chat_shape(self) -> None:
        body = build_stream_chat_body("model-1", [{"role": "user", "content": "你好"}])

        self.assertTrue(body["stream"])
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "你好"})
        self.assertEqual(body["max_tokens"], 160)

    def test_sse_parser_extracts_delta_and_ignores_done_or_usage(self) -> None:
        self.assertEqual(
            parse_sse_data('{"choices":[{"delta":{"content":"你好"}}]}'),
            "你好",
        )
        self.assertIsNone(parse_sse_data('{"choices":[]}'))
        self.assertIsNone(parse_sse_data("[DONE]"))

    def test_sse_parser_rejects_malformed_delta_shape(self) -> None:
        for frame in (
            "not-json",
            '{"choices": "wrong"}',
            '{"choices":[{"delta":{"content":3}}]}',
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                parse_sse_data(frame)

    @patch("lumilamp.voice.ark.urlopen")
    def test_stream_ark_yields_ordered_fragments_without_mutating_history(self, urlopen) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return iter(
                    (
                        'data: {"choices":[{"delta":{"content":"第一句"}}]}\n'.encode(),
                        'data: {"choices":[{"delta":{"content":"。"}}]}\n'.encode(),
                        b'data: [DONE]\n',
                    )
                )

        urlopen.return_value = Response()
        history = ConversationHistory()

        self.assertEqual(list(stream_ark(make_config(), history, "问题")), ["第一句", "。"])
        self.assertEqual(history.messages(), [])
        request = urlopen.call_args.args[0]
        self.assertIn(b'"stream": true', request.data)

    @patch("lumilamp.voice.ark.urlopen")
    def test_stream_ark_rejects_missing_done_without_mutating_history(self, urlopen) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return iter((
                    'data: {"choices":[{"delta":{"content":"未完成"}}]}\n'.encode(),
                ))

        urlopen.return_value = Response()
        history = ConversationHistory()

        with self.assertRaisesRegex(ValueError, "did not finish"):
            list(stream_ark(make_config(), history, "问题"))
        self.assertEqual(history.messages(), [])

    def test_history_keeps_only_four_complete_turns(self) -> None:
        history = ConversationHistory(max_turns=4)

        for index in range(5):
            history.append_turn(f"问{index}", f"答{index}")

        self.assertEqual(history.messages()[0]["content"], "问1")
        self.assertEqual(len(history.messages()), 8)
        self.assertEqual(
            history.messages()[-2:],
            [
                {"role": "user", "content": "问4"},
                {"role": "assistant", "content": "答4"},
            ],
        )

    def test_history_returns_a_copy_and_rejects_incomplete_turns(self) -> None:
        history = ConversationHistory()
        history.append_turn("用户", "助手")
        returned = history.messages()
        returned[0]["content"] = "篡改"

        self.assertEqual(history.messages()[0]["content"], "用户")
        for user_text, assistant_text in ((" ", "回答"), ("问题", "\t")):
            with self.subTest(user_text=user_text, assistant_text=assistant_text):
                with self.assertRaises(ValueError):
                    history.append_turn(user_text, assistant_text)
        self.assertEqual(len(history.messages()), 2)

    def test_history_clear_is_the_orchestrator_facing_sleep_hook(self) -> None:
        history = ConversationHistory()
        history.append_turn("用户", "助手")

        history.clear()

        self.assertEqual(history.messages(), [])

    def test_builds_short_chinese_assistant_request(self) -> None:
        messages = [{"role": "user", "content": "你是谁？"}]
        body = build_chat_body("model-1", messages)
        self.assertEqual(body["model"], "model-1")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "你是谁？"})
        self.assertEqual(body["max_tokens"], 160)

    def test_rejects_blank_input(self) -> None:
        with self.assertRaises(ValueError):
            build_chat_body("model-1", [{"role": "user", "content": "  "}])

    def test_rejects_blank_model_id(self) -> None:
        with self.assertRaises(ValueError):
            build_chat_body("  ", [{"role": "user", "content": "你好"}])

    def test_includes_concise_lumilamp_system_prompt(self) -> None:
        body = build_chat_body("model-1", [{"role": "user", "content": "你好"}])
        prompt = body["messages"][0]["content"]
        self.assertIn("露米", prompt)
        self.assertIn("台灯", prompt)
        self.assertLess(len(prompt), 150)

    def test_build_body_keeps_system_prompt_out_of_session_history(self) -> None:
        history = ConversationHistory()
        history.append_turn("第一问", "第一答")
        history.append_turn("第二问", "第二答")

        body = build_chat_body("model-1", history.messages())

        self.assertEqual(
            body["messages"][1:],
            [
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "第一答"},
                {"role": "user", "content": "第二问"},
                {"role": "assistant", "content": "第二答"},
            ],
        )
        self.assertEqual(history.messages()[0]["role"], "user")

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
        config = make_config()
        history = ConversationHistory()
        history.append_turn("之前的问题", "之前的回答")

        self.assertEqual(ask_ark(config, history, "你好"), "你好。")
        self.assertEqual(
            history.messages(),
            [
                {"role": "user", "content": "之前的问题"},
                {"role": "assistant", "content": "之前的回答"},
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好。"},
            ],
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

    @patch("lumilamp.voice.ark.urlopen")
    def test_rejects_blank_api_key_without_request(self, urlopen) -> None:
        config = make_config("  ")
        history = ConversationHistory()
        with self.assertRaisesRegex(ValueError, "API key"):
            ask_ark(config, history, "你好")
        urlopen.assert_not_called()
        self.assertEqual(history.messages(), [])

    @patch("lumilamp.voice.ark.urlopen")
    def test_failed_ark_response_does_not_append_a_partial_turn(self, urlopen) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"choices": []}'

        urlopen.return_value = Response()
        history = ConversationHistory()
        history.append_turn("已有问题", "已有回答")

        with self.assertRaisesRegex(ValueError, "malformed"):
            ask_ark(make_config(), history, "本轮问题")

        self.assertEqual(
            history.messages(),
            [
                {"role": "user", "content": "已有问题"},
                {"role": "assistant", "content": "已有回答"},
            ],
        )

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
        config = make_config(api_key)
        history = ConversationHistory()
        with self.assertRaises(RuntimeError) as caught:
            ask_ark(config, history, "你好")
        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("req-123", message)
        self.assertNotIn(api_key, message)
        self.assertNotIn(request_body_secret, message)
        self.assertEqual(history.messages(), [])


if __name__ == "__main__":
    unittest.main()
