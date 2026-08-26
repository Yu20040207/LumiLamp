# Task 2 Report: Safe ALSA Playback at Conversation Volume

## Scope

Implemented the Task 2 audio-output boundary only. The implementation remains
safe to exercise in software tests: ALSA subprocesses and cloud TTS are mocked
in tests, and no physical audio device or network service was contacted.

## Changes

- Added `src/lumilamp/voice/audio_output.py` with:
  - `validate_volume(percent)` enforcing the inclusive 0–100 range.
  - `set_usb_speaker_volume(card, percent=70)` invoking `amixer` with an
    argument list and `check=True`.
  - `play_wav(device, path)` invoking `aplay` with an argument list and
    `check=True`.
  - `speak(...)`, which synthesizes first, sets the conversation volume to 70,
    and then plays the generated WAV.
- Updated `build_tts_body(text, loudness_rate=0)` so normal conversation TTS
  uses provider loudness 0 while explicit tests can request 100.
- Added focused audio-output tests for validation, exact subprocess commands,
  no-shell boundaries, and speak ordering.
- Updated TTS tests for the normal default and explicit loudness override.

## TDD evidence

### RED

Ran:

```text
PYTHONPATH=src .venv/bin/python -m unittest tests/test_audio_output.py tests/test_voice_tts.py -v
```

The focused run failed as expected: `audio_output` could not be imported,
`build_tts_body` did not accept `loudness_rate`, and the existing default was
100 instead of 0.

### GREEN

After the minimal implementation and test correction for call-order
assertion, the focused suite passed:

```text
Ran 9 tests in 0.009s
OK
```

The full suite also passed:

```text
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
Ran 28 tests in 0.113s
OK
```

`compileall -q src tests` completed successfully, and no `git` executable is
available in this environment for a diff check.

## Validation boundaries

Static check: Python compilation completed; subprocess calls use explicit
argument lists and do not use `shell=True`.

Code test: Focused and full unittest suites passed; subprocess, TTS, and
playback/cloud boundaries were mocked, so tests produced no sound or network
requests.

Physical-hardware validation: 未进行。No microphone, speaker, GPIO, serial,
ESP32, or servo hardware was accessed.
