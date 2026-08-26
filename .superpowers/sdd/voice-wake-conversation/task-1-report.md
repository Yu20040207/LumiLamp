# Task 1 report: Ark text client

## Scope

Implemented the standard-library Ark chat-completions adapter only. No cloud
request, dependency installation, hardware access, or credential-file access
was performed.

## TDD evidence

- RED: before implementation, the focused command failed at import with
  `ModuleNotFoundError: No module named 'lumilamp.voice.ark'`.
- GREEN: after implementation, the focused suite passed (`5` tests).
- Full suite passed (`17` tests).

## Files changed

- `src/lumilamp/voice/ark.py`
- `tests/test_voice_ark.py`
- `.superpowers/sdd/voice-wake-conversation/task-1-report.md`

## Behavior

- Builds a concise Chinese LumiLamp system prompt and limits responses to 160
  tokens.
- Rejects blank model IDs, blank user input, malformed responses, and blank
  assistant content.
- Sends `Authorization: Bearer ...` to the Ark chat-completions endpoint with a
  30-second timeout.
- Redacts credentials and request bodies from provider error messages; only
  HTTP status and an optional provider request ID are retained.

## Hardware/cloud status

- Cloud integration probe: not run; it requires fresh explicit approval.
- Physical-hardware validation: not performed.

## Fix round 1

Added offline regression coverage requested during review:

- blank Ark API key is rejected before `urlopen` is called;
- HTTP errors retain only status and optional request ID;
- API key and request-body content are absent from error text;
- blank model IDs are rejected;
- the system prompt is checked for concise Chinese LumiLamp behavior.

Evidence:

- Focused suite: `9` tests passed.
- Full suite: `21` tests passed.
- No network request or secret access was performed.

Changed files in this fix round:

- `tests/test_voice_ark.py`
- `.superpowers/sdd/voice-wake-conversation/task-1-report.md`
