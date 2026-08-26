# Task 3: Utterance Capture and Silence Endpointing

Implement only Task 3 from `docs/superpowers/plans/2026-08-26-voice-wake-conversation.md`.

Files: modify `src/lumilamp/voice/recorder.py`; create `tests/test_utterance_recorder.py`.

Interfaces: `LevelConfig(start_threshold, silence_threshold, trailing_silence_ms=800, max_seconds=10)`, `pcm_level(chunk)`, `should_finish(started, silent_ms, elapsed_ms, config)`, and `record_utterance(device, output_path, config) -> bool`.

Requirements:

- Strict TDD with recorded RED/GREEN evidence.
- RMS of signed 16-bit PCM via `array('h')`; handle non-little-endian hosts explicitly; no NumPy/PyAudio.
- `arecord -D <device> -t raw -f S16_LE -r 16000 -c 1`; use argument list without shell.
- Read 20 ms / 640-byte chunks. Retain accepted audio only once start threshold is crossed.
- Stop after 800 ms trailing silence or 10 seconds; write mono 16 kHz WAV only for accepted speech.
- Return False and avoid cloud requests when speech never begins.
- Terminate/wait only this function's child; never broad kill commands.
- Automated tests must mock capture and never open a microphone.
- Run focused tests, existing recorder tests, compileall, and full suite.
- No network, secrets, speaker/microphone physical I/O, hardware control, installs, deletes, Git commits, or subagents.
- Report to `.superpowers/sdd/voice-wake-conversation/task-3-report.md`.

