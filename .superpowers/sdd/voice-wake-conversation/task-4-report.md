# Task 4 Report: Pure Conversation State Machine

## Implementation

- Added `ConversationState` with the six approved conversation states.
- Added a pure `ConversationController` with injected clock and chooser boundaries only; it performs no microphone, network, playback, hardware, or sleep operations.
- The controller selects from the exact approved wake replies, enters `LISTENING` after wake, enforces the recognition → thinking → speaking sequence, rejects invalid transitions with `RuntimeError`, and returns silently to `SLEEPING` on expiry or a second consecutive failure.
- A completed speaking turn resets both the idle deadline and consecutive-failure count.

## TDD evidence

1. Added deterministic controller tests first, using an in-memory mutable clock and injected chooser.
2. `PYTHONPATH=src .venv/bin/python -m unittest tests/test_conversation.py -v` produced the expected RED result: `ModuleNotFoundError: No module named 'lumilamp.voice.conversation'`.
3. Added the minimum state enum and controller implementation.
4. The focused command then passed all 8 tests, covering wake reply selection, each active-turn transition, the 29.9/30.0 second timeout boundary, deadline reset after `finish_turn`, failure-count reset after a successful turn, two-failure sleep, and illegal transitions.

## Verification

Static check:

- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests` exited 0.
- Reviewed the two production modules and scanned them for hardware, serial, network, subprocess, time, and sleep imports; none are present.

Code test:

- `PYTHONPATH=src .venv/bin/python -m unittest tests/test_conversation.py -v` passed 8 tests.
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v` passed 43 tests.
- Tests use only injected in-memory clock and chooser functions; they access no devices or external services.

Physical-hardware validation:

- 未进行。No microphone, speaker, GPIO, serial, servo, or other physical hardware was accessed.
