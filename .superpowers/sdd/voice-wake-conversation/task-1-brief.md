# Task 1: Ark Text Client

Implement only Task 1 from `docs/superpowers/plans/2026-08-26-voice-wake-conversation.md`.

Create `src/lumilamp/voice/ark.py` and `tests/test_voice_ark.py`.

Required interfaces:

- `build_chat_body(model_id: str, user_text: str) -> dict[str, object]`
- `parse_chat_response(payload: dict[str, object]) -> str`
- `ask_ark(config: VoiceConfig, user_text: str) -> str`

Requirements:

- Follow strict TDD: tests first, demonstrate RED, then minimal implementation and GREEN.
- Endpoint: `https://ark.cn-beijing.volces.com/api/v3/chat/completions`.
- Authorization is `Bearer <ARK_API_KEY>` and must never be exposed in errors or logs.
- Include a concise LumiLamp Chinese system prompt and `max_tokens=160`.
- Use a 30-second timeout.
- Reject blank user input and blank/malformed provider responses.
- Errors may include HTTP status and provider request ID, but never headers, request bodies, API keys, or credentials.
- Tests must not access the network or secrets.
- Run focused tests and the full suite.
- Do not perform the Step 5 cloud integration probe; it requires fresh user approval.
- Do not install dependencies, touch GPIO/serial/ESP32/servos, commit Git, delete files, or spawn subagents.
- Write the detailed report to `.superpowers/sdd/voice-wake-conversation/task-1-report.md` including RED/GREEN evidence and files changed.

