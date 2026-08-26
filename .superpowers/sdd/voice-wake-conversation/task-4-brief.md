# Task 4: Pure Conversation State Machine

Implement only Task 4 from the approved plan.

Create `src/lumilamp/voice/state.py`, `src/lumilamp/voice/conversation.py`, and `tests/test_conversation.py`.

Produce `ConversationState`: `SLEEPING`, `WAKING`, `LISTENING`, `RECOGNIZING`, `THINKING`, `SPEAKING`; and `ConversationController(clock, choose, timeout_seconds=30.0)` with `wake`, `begin_recognition`, `begin_thinking`, `begin_speaking`, `finish_turn`, `record_failure`, `expire_if_idle`.

Requirements:

- Strict TDD with RED/GREEN report.
- Exact wake replies: `("嗯？", "你好。", "我在，怎么啦？", "请吩咐。")`.
- Wake reply selected using injected `choose`; wake ends in LISTENING.
- 30-second timeout: 29.9 remains listening, 30.0 returns silently to sleeping; valid `finish_turn` resets deadline.
- Two consecutive failures sleep; successful turn resets failure count.
- Reject illegal transitions with RuntimeError.
- Pure modules: no microphone, network, playback, hardware I/O, or sleeps.
- Deterministic tests using injected clock/chooser.
- Run focused and full tests; no installs/deletes/Git/subagents.
- Report `.superpowers/sdd/voice-wake-conversation/task-4-report.md`.

