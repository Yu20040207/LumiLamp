# Task 2: Safe ALSA Playback at Conversation Volume

Implement only Task 2 from `docs/superpowers/plans/2026-08-26-voice-wake-conversation.md`.

Files:

- Create `src/lumilamp/voice/audio_output.py`
- Create `tests/test_audio_output.py`
- Modify `src/lumilamp/voice/tts.py`
- Modify `tests/test_voice_tts.py` only as required for regression coverage

Required interfaces:

- `validate_volume(percent: int) -> int`
- `set_usb_speaker_volume(card: int, percent: int = 70) -> None`
- `play_wav(device: str, path: Path) -> None`
- `speak(config: VoiceConfig, text: str, output_path: Path, card: int, device: str) -> None`

Requirements:

- Follow strict TDD, recording RED and GREEN evidence.
- Validate volume is between 0 and 100 inclusive.
- Run `amixer -c <card> sset Speaker <percent>% unmute` with an argument list and `check=True`.
- Run `aplay -D <device> <path>` with an argument list and `check=True`.
- Never use `shell=True`.
- Normal `build_tts_body(text)` must use `loudness_rate=0`; allow explicit `build_tts_body(text, loudness_rate=100)` for deliberate speaker tests.
- `speak` synthesizes, sets system volume, then plays the WAV using the small helpers; tests must mock subprocess/cloud boundaries and must not produce sound or network calls.
- Run focused and full test suites.
- Do not access real microphone/speaker, network, secrets, GPIO, serial, ESP32, or servos.
- Do not install, delete files, commit Git, or spawn subagents.
- Write detailed report to `.superpowers/sdd/voice-wake-conversation/task-2-report.md`.

