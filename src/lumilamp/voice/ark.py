"""Small, redacted Ark chat-completions client for LumiLamp."""

from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import VoiceConfig
from .conversation import ConversationHistory

ARK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
SYSTEM_PROMPT = (
    "你是露米，一盏固定桌面式拟人台灯。用温柔、简短、自然的中文回答，"
    "每次尽量不超过两句话；只回答对话，不执行任何硬件动作。"
)


def build_chat_body(
    model_id: str, messages: list[dict[str, str]]
) -> dict[str, object]:
    if not model_id.strip():
        raise ValueError("Ark model ID must not be empty")
    normalized_messages: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("Ark messages must contain user or assistant text")
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Ark messages must not contain blank text")
        normalized_messages.append({"role": role, "content": normalized_content})
    if not normalized_messages:
        raise ValueError("Ark messages must not be empty")
    return {
        "model": model_id.strip(),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *normalized_messages,
        ],
        "max_tokens": 160,
    }


def build_stream_chat_body(
    model_id: str, messages: list[dict[str, str]]
) -> dict[str, object]:
    """Build one OpenAI-compatible Ark request for SSE output."""
    body = build_chat_body(model_id, messages)
    body["stream"] = True
    return body


def parse_sse_data(data: str) -> str | None:
    """Return an Ark text delta, or ``None`` for a normal terminal/meta frame."""
    if not isinstance(data, str):
        raise TypeError("SSE data must be a string")
    if data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        raise ValueError("Ark SSE data is not valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("Ark SSE data is malformed")
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise ValueError("Ark SSE choices are malformed")
    if not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("Ark SSE choice is malformed")
    delta = first.get("delta")
    if not isinstance(delta, dict):
        raise ValueError("Ark SSE delta is malformed")
    content = delta.get("content")
    if content is None:
        return None
    if not isinstance(content, str):
        raise ValueError("Ark SSE content is malformed")
    return content or None


def stream_ark(
    config: VoiceConfig, history: ConversationHistory, user_text: str
) -> Iterator[str]:
    """Yield ordered Ark SSE text deltas without recording a partial turn."""
    user = user_text.strip()
    if not user:
        raise ValueError("Ark user text must not be blank")
    if not config.ark_api_key.strip():
        raise ValueError("Ark API key is not configured")
    body = json.dumps(
        build_stream_chat_body(
            config.ark_model_id, [*history.messages(), {"role": "user", "content": user}]
        ),
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        ARK_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.ark_api_key}",
        },
    )
    done = False
    try:
        with urlopen(request, timeout=30) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    done = True
                    break
                delta = parse_sse_data(data)
                if delta is not None:
                    yield delta
    except HTTPError as exc:
        request_id = _request_id(exc)
        suffix = f" (request_id={request_id})" if request_id else ""
        raise RuntimeError(f"Ark HTTP error {exc.code}{suffix}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Ark request failed") from None
    except UnicodeDecodeError:
        raise ValueError("Ark SSE response is not UTF-8") from None
    if not done:
        raise ValueError("Ark SSE stream did not finish")


def parse_chat_response(payload: dict[str, object]) -> str:
    try:
        choices = payload["choices"]
        first = choices[0]  # type: ignore[index]
        message = first["message"]  # type: ignore[index]
        content = message["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Ark response is malformed") from None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Ark response contains no assistant text")
    return content.strip()


def _request_id(response: object) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("x-request-id") or headers.get("X-Request-Id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def ask_ark(
    config: VoiceConfig, history: ConversationHistory, user_text: str
) -> str:
    user = user_text.strip()
    messages = history.messages()
    messages.append({"role": "user", "content": user})
    body = json.dumps(
        build_chat_body(config.ark_model_id, messages), ensure_ascii=False
    ).encode("utf-8")
    if not config.ark_api_key.strip():
        raise ValueError("Ark API key is not configured")
    request = Request(
        ARK_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.ark_api_key}",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Ark response is malformed")
            assistant = parse_chat_response(payload)
            history.append_turn(user, assistant)
            return assistant
    except HTTPError as exc:
        request_id = _request_id(exc)
        suffix = f" (request_id={request_id})" if request_id else ""
        raise RuntimeError(f"Ark HTTP error {exc.code}{suffix}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Ark request failed") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Ark response is not valid JSON") from None
