"""Small, redacted Ark chat-completions client for LumiLamp."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import VoiceConfig

ARK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
SYSTEM_PROMPT = (
    "你是露米，一盏固定桌面式拟人台灯。用温柔、简短、自然的中文回答，"
    "每次尽量不超过两句话；只回答对话，不执行任何硬件动作。"
)


def build_chat_body(model_id: str, user_text: str) -> dict[str, object]:
    if not model_id.strip():
        raise ValueError("Ark model ID must not be empty")
    if not user_text.strip():
        raise ValueError("Ark user input must not be empty")
    return {
        "model": model_id.strip(),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text.strip()},
        ],
        "max_tokens": 160,
    }


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


def ask_ark(config: VoiceConfig, user_text: str) -> str:
    body = json.dumps(
        build_chat_body(config.ark_model_id, user_text), ensure_ascii=False
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
            return parse_chat_response(payload)
    except HTTPError as exc:
        request_id = _request_id(exc)
        suffix = f" (request_id={request_id})" if request_id else ""
        raise RuntimeError(f"Ark HTTP error {exc.code}{suffix}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Ark request failed") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Ark response is not valid JSON") from None

