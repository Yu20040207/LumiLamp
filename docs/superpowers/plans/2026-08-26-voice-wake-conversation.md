# LumiLamp Voice Wake Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local `你好露米` wake-word loop that opens a 30-second, half-duplex ASR → Ark → TTS conversation and returns silently to sleep.

**Architecture:** A single Python process owns an explicit conversation state machine. Vendor adapters (sherpa-onnx, Doubao ASR/TTS, Ark) remain isolated behind small interfaces; the controller accepts injected clock and random functions so state transitions are deterministic in tests. The only physical I/O in V1 is the configured USB microphone and USB speaker.

**Tech Stack:** Python 3.13 standard library, `websockets>=15,<16`, `sherpa-onnx>=1.12,<2`, ALSA command-line tools, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-26-voice-wake-conversation-design.md`

## Global Constraints

- Default operation remains simulation-only for motion and hardware control.
- Do not access GPIO, serial, ESP32-S3, or servos.
- Wake-word PCM never leaves the Raspberry Pi and is never written to disk.
- Cloud ASR starts only after wake-up and only for an active user utterance.
- Wake phrase is exactly `你好露米`.
- Conversation idle timeout is 30 seconds; each valid turn resets it.
- A user utterance ends after 800 ms silence and is capped at 10 seconds.
- TTS playback pauses ordinary ASR; V1 does not support interruption.
- Conversation playback volume is 70%; timeout sleep is silent.
- Two consecutive turn failures end the session silently.
- Keep credentials only in `/home/lamp/.config/lumilamp/voice.env` with mode `0600`; never log them.
- Do not install dependencies until the user explicitly approves installation.
- Do not delete files, commit Git, or push GitHub.

---

### Task 1: Ark Text Client

**Files:**
- Create: `src/lumilamp/voice/ark.py`
- Create: `tests/test_voice_ark.py`

**Interfaces:**
- Consumes: `VoiceConfig.ark_api_key: str`, `VoiceConfig.ark_model_id: str`.
- Produces: `build_chat_body(model_id: str, user_text: str) -> dict[str, object]`, `parse_chat_response(payload: dict[str, object]) -> str`, `ask_ark(config: VoiceConfig, user_text: str) -> str`.

- [ ] **Step 1: Write failing request/response contract tests**

```python
import unittest
from lumilamp.voice.ark import build_chat_body, parse_chat_response


class ArkClientTests(unittest.TestCase):
    def test_builds_short_chinese_assistant_request(self) -> None:
        body = build_chat_body("model-1", "你是谁？")
        self.assertEqual(body["model"], "model-1")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "你是谁？"})
        self.assertEqual(body["max_tokens"], 160)

    def test_extracts_assistant_text(self) -> None:
        payload = {"choices": [{"message": {"role": "assistant", "content": "我是露米。"}}]}
        self.assertEqual(parse_chat_response(payload), "我是露米。")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_ark.py -v`

Expected: import error because `lumilamp.voice.ark` does not exist.

- [ ] **Step 3: Implement the minimal Ark adapter**

Use `https://ark.cn-beijing.volces.com/api/v3/chat/completions`, `Authorization: Bearer <ARK_API_KEY>`, a concise LumiLamp system prompt, `max_tokens=160`, and a 30-second timeout. Reject blank input and blank/malformed responses. Error messages may include HTTP status and provider request ID but never request headers or body credentials.

- [ ] **Step 4: Verify GREEN and the full suite**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_ark.py -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Run one explicit cloud integration probe**

Load `voice.env` inside Python without printing it, send `你好，请用一句话介绍自己`, and print only the assistant text. This consumes a small amount of Ark quota and requires explicit user approval immediately before execution.

---

### Task 2: Safe ALSA Playback at Conversation Volume

**Files:**
- Create: `src/lumilamp/voice/audio_output.py`
- Create: `tests/test_audio_output.py`
- Modify: `src/lumilamp/voice/tts.py`

**Interfaces:**
- Consumes: a 24 kHz mono WAV `Path` from `synthesize_to_wav`.
- Produces: `set_usb_speaker_volume(card: int, percent: int = 70) -> None`, `play_wav(device: str, path: Path) -> None`, `speak(config: VoiceConfig, text: str, output_path: Path, card: int, device: str) -> None`.

- [ ] **Step 1: Write failing validation tests**

```python
import unittest
from lumilamp.voice.audio_output import validate_volume


class AudioOutputTests(unittest.TestCase):
    def test_accepts_conversation_volume(self) -> None:
        self.assertEqual(validate_volume(70), 70)

    def test_rejects_volume_above_one_hundred(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            validate_volume(101)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_audio_output.py -v`

Expected: import error because `lumilamp.voice.audio_output` does not exist.

- [ ] **Step 3: Implement explicit ALSA subprocess boundaries**

`set_usb_speaker_volume` runs `amixer -c <card> sset Speaker <percent>% unmute`; `play_wav` runs `aplay -D <device> <path>`. Use argument lists with `check=True`, never `shell=True`. Change `build_tts_body(text)` so normal synthesis uses `loudness_rate=0`; system volume, not cloud amplification, controls conversation loudness. Add a `loudness_rate` argument only to the explicit TTS test path.

- [ ] **Step 4: Add a TTS regression test**

Assert the normal conversation request uses `loudness_rate == 0`, while `build_tts_body(text, loudness_rate=100)` remains available for deliberate speaker tests.

- [ ] **Step 5: Verify focused and full tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests/test_audio_output.py tests/test_voice_tts.py -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass; no audio is played by tests.

---

### Task 3: Utterance Capture and Silence Endpointing

**Files:**
- Modify: `src/lumilamp/voice/recorder.py`
- Create: `tests/test_utterance_recorder.py`

**Interfaces:**
- Produces: `LevelConfig(start_threshold: float, silence_threshold: float, trailing_silence_ms: int = 800, max_seconds: int = 10)`, `pcm_level(chunk: bytes) -> float`, `should_finish(started: bool, silent_ms: int, elapsed_ms: int, config: LevelConfig) -> bool`, `record_utterance(device: str, output_path: Path, config: LevelConfig) -> bool`.
- Returns `False` without creating a cloud request when no valid speech begins.

- [ ] **Step 1: Write failing pure endpointing tests**

```python
import unittest
from lumilamp.voice.recorder import LevelConfig, should_finish


class UtteranceEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LevelConfig(0.02, 0.01, trailing_silence_ms=800, max_seconds=10)

    def test_finishes_after_eight_hundred_ms_silence(self) -> None:
        self.assertTrue(should_finish(True, 800, 2400, self.config))

    def test_does_not_finish_before_speech_starts(self) -> None:
        self.assertFalse(should_finish(False, 900, 2400, self.config))

    def test_caps_an_utterance_at_ten_seconds(self) -> None:
        self.assertTrue(should_finish(True, 0, 10000, self.config))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_utterance_recorder.py -v`

Expected: missing `LevelConfig`/`should_finish`.

- [ ] **Step 3: Implement pure level and endpoint logic**

Calculate normalized RMS from signed 16-bit PCM with `array('h')`; handle endianness explicitly on non-little-endian systems. Do not use NumPy or PyAudio.

- [ ] **Step 4: Implement streaming capture**

Start `arecord -D <device> -t raw -f S16_LE -r 16000 -c 1`, read 20 ms chunks (640 bytes), retain audio only after the start threshold is crossed, stop after 800 ms trailing silence or 10 seconds, and wrap accepted PCM in a mono 16 kHz WAV. Terminate only the child process created by this function and wait for it; never use broad process-kill commands.

- [ ] **Step 5: Verify focused and full tests**

Run the focused tests, the existing recorder tests, compileall, then the full suite. No microphone access occurs in automated tests.

---

### Task 4: Pure Conversation State Machine

**Files:**
- Create: `src/lumilamp/voice/state.py`
- Create: `src/lumilamp/voice/conversation.py`
- Create: `tests/test_conversation.py`

**Interfaces:**
- Produces `ConversationState` enum: `SLEEPING`, `WAKING`, `LISTENING`, `RECOGNIZING`, `THINKING`, `SPEAKING`.
- Produces `ConversationController(clock: Callable[[], float], choose: Callable[[tuple[str, ...]], str], timeout_seconds: float = 30.0)`.
- Methods: `wake() -> str`, `begin_recognition() -> None`, `begin_thinking() -> None`, `begin_speaking() -> None`, `finish_turn() -> None`, `record_failure() -> bool`, `expire_if_idle() -> bool`.

- [ ] **Step 1: Write failing state-transition tests**

```python
import unittest
from lumilamp.voice.conversation import ConversationController
from lumilamp.voice.state import ConversationState


class ConversationTests(unittest.TestCase):
    def test_wake_selects_response_and_enters_listening(self) -> None:
        controller = ConversationController(clock=lambda: 0.0, choose=lambda items: items[2])
        self.assertEqual(controller.wake(), "我在，怎么啦？")
        self.assertEqual(controller.state, ConversationState.LISTENING)

    def test_two_consecutive_failures_return_to_sleep(self) -> None:
        controller = ConversationController(clock=lambda: 0.0, choose=lambda items: items[0])
        controller.wake()
        self.assertFalse(controller.record_failure())
        self.assertTrue(controller.record_failure())
        self.assertEqual(controller.state, ConversationState.SLEEPING)
```

- [ ] **Step 2: Add a virtual-clock 30-second timeout test**

Use a mutable numeric clock; assert 29.9 seconds remains `LISTENING`, 30.0 seconds returns silently to `SLEEPING`, and `finish_turn()` resets the deadline.

- [ ] **Step 3: Run tests and verify RED**

Expected: missing state/controller modules.

- [ ] **Step 4: Implement the minimal state machine**

Reject illegal transitions with `RuntimeError`; never perform microphone, network, playback, or hardware I/O from these modules. The four response strings are exactly `("嗯？", "你好。", "我在，怎么啦？", "请吩咐。")`.

- [ ] **Step 5: Verify focused and full tests**

Expected: deterministic tests pass with no sleeps or external calls.

---

### Task 5: sherpa-onnx Wake-Word Adapter

**Files:**
- Modify: `pyproject.toml`
- Create: `src/lumilamp/voice/wakeword.py`
- Create: `tests/test_wakeword.py`
- Create: `configs/wakeword.example.yaml`
- Modify: `README.md`

**Interfaces:**
- Produces `WakeWordConfig(model_dir: Path, keyword: str = "你好露米", threshold: float = 0.25, score: float = 1.0)`.
- Produces `SherpaWakeWordDetector(config: WakeWordConfig)` with `accept_pcm(samples: array[int]) -> bool` and `reset() -> None`.
- Importing `lumilamp.voice.wakeword` must not open the microphone or load a model.

- [ ] **Step 1: Obtain explicit dependency approval**

Before any install or model download, report expected additions: one `sherpa-onnx` wheel plus the official ~38 MB Chinese/English 3M KWS model. Do nothing until the user explicitly confirms.

- [ ] **Step 2: Verify a compatible binary wheel exists**

Run inside the project venv:

```bash
.venv/bin/python -m pip install --dry-run "sherpa-onnx>=1.12,<2"
```

If pip proposes a source build or cannot satisfy Python 3.13/aarch64, stop and report the compatibility blocker; do not install compilers or system packages.

- [ ] **Step 3: Record dependencies only after approval and successful dry-run**

Set `dependencies = ["websockets>=15,<16", "sherpa-onnx>=1.12,<2"]` in `pyproject.toml`, install into `.venv`, and record the resolved versions in the verification report.

- [ ] **Step 4: Download the official KWS model without deleting archives**

Download and extract `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2` from the `k2-fsa/sherpa-onnx` `kws-models` GitHub release into `/home/lamp/.cache/lumilamp/models/`. Preserve the downloaded archive because project policy forbids deletion. List extracted files and sizes before loading them.

- [ ] **Step 5: Write a failing configuration/import-safety test**

```python
import unittest
from pathlib import Path
from lumilamp.voice.wakeword import WakeWordConfig


class WakeWordTests(unittest.TestCase):
    def test_defaults_to_confirmed_chinese_phrase(self) -> None:
        config = WakeWordConfig(Path("/models/kws"))
        self.assertEqual(config.keyword, "你好露米")
        self.assertEqual(config.threshold, 0.25)
```

- [ ] **Step 6: Implement lazy model construction**

Import `sherpa_onnx` inside `SherpaWakeWordDetector.__init__`, map the extracted encoder/decoder/joiner/tokens paths explicitly, generate the keyword-token file using the model's official `text2token.py` procedure, and keep the recognizer local. Do not log PCM or credentials.

- [ ] **Step 7: Verify with bundled/non-live audio first**

Run unit tests and feed a local WAV fixture through `accept_pcm`. This test must not access cloud endpoints.

---

### Task 6: Half-Duplex Conversation Orchestrator

**Files:**
- Create: `src/lumilamp/voice/session.py`
- Create: `tests/test_voice_session.py`

**Interfaces:**
- Consumes the controller and callable boundaries: `listen_wake() -> None`, `record_turn() -> Path | None`, `transcribe(Path) -> str`, `answer(str) -> str`, `speak(str) -> None`.
- Produces `VoiceSession.run_once() -> ConversationState` for one wake/session lifecycle and `VoiceSession.run_forever() -> None` for the CLI.

- [ ] **Step 1: Write a failing two-turn orchestration test**

Use small in-memory fakes with fixed return queues. Assert exact event order:

```python
[
    "wake",
    "speak:嗯？",
    "record:turn1",
    "asr:turn1",
    "ark:你好",
    "speak:你好，我是露米。",
    "record:turn2",
]
```

The fake speaker exposes an `active` flag; the fake recorder must assert `active is False` whenever recording begins. This protects the no-ASR-during-TTS requirement.

- [ ] **Step 2: Add failure-path tests**

Test one blank ASR result triggers `我没听清，可以再说一次吗？`; two consecutive ASR/Ark failures end in `SLEEPING`; a TTS failure returns immediately to `SLEEPING` without retry.

- [ ] **Step 3: Run tests and verify RED**

Expected: `VoiceSession` is missing.

- [ ] **Step 4: Implement orchestration without hardware actions**

Keep the controller as the only state owner. `ActionSink` is a callable defaulting to a no-op/log-only implementation and receives only `"wake"` or `"sleep"`; it must never import hardware modules.

- [ ] **Step 5: Verify all software tests**

Run the focused tests, full unittest discovery, compileall, and the forbidden-import scan for `RPi`, `gpiozero`, `serial`, `smbus`, and `spidev`.

---

### Task 7: CLI Wiring and Explicit Live Checkpoints

**Files:**
- Create: `src/lumilamp/voice/app.py`
- Create: `tests/test_voice_app.py`
- Modify: `README.md`

**Interfaces:**
- CLI dry-run: `python -m lumilamp.voice.app --check-config`.
- One-session live mode: `python -m lumilamp.voice.app --once`.
- Continuous mode: `python -m lumilamp.voice.app --listen`.
- Defaults: config `/home/lamp/.config/lumilamp/voice.env`, capture `plughw:CARD=Device,DEV=0`, playback `plughw:CARD=Device_1,DEV=0`, mixer card `4`, volume `70`.

- [ ] **Step 1: Write a failing no-I/O config-check CLI test**

Call `main(["--check-config", "--config", fixture_path])`; assert exit code `0` and output contains only setting names/status, never fixture secret values.

- [ ] **Step 2: Run test and verify RED**

Expected: `lumilamp.voice.app` does not exist.

- [ ] **Step 3: Implement CLI wiring**

No mode starts implicitly. `--check-config` performs no device/network access; `--once` handles one wake/session; `--listen` is the only indefinite mode. Catch `KeyboardInterrupt`, close detector/recording resources, and exit without starting system services.

- [ ] **Step 4: Add README operator instructions**

Document privacy behavior, cloud quota use after wake, 70% playback volume, `/tmp` recording retention, Ctrl-C shutdown, and the fact that no GPIO/serial/servo output exists.

- [ ] **Step 5: Verify static and software acceptance**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
grep -RInE '^[[:space:]]*(import|from)[[:space:]]+(RPi|gpiozero|serial|smbus|spidev)' src tests || true
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.app --check-config
```

Expected: all tests pass, compileall exits 0, forbidden-import scan is empty, config check exposes no secret values.

---

### Task 8: Staged Physical Audio Validation

**Files:**
- Create: `docs/voice-validation.md`

**Interfaces:**
- Produces a dated manual validation table with columns: environment, distance, attempts, detections, false wakes, ASR text, TTS heard, timeout result.

- [ ] **Step 1: Document the physical test protocol**

Record exact safety conditions: USB-only microphone/speaker, speaker at 70%, no ESP32/servo connection, no GPIO/serial access. Include the difference between software test evidence and actual observed audio behavior.

- [ ] **Step 2: Ask for explicit live-listening approval**

Explain that the microphone will continuously process audio locally while `--listen` runs, cloud audio begins only after `你好露米`, and Ctrl-C stops listening. Do not start until the user confirms.

- [ ] **Step 3: Validate near-field wake-up**

Run five attempts at approximately 30 cm. Record detection count and false triggers; do not tune thresholds until all five baseline results are recorded.

- [ ] **Step 4: Validate one-meter wake-up**

Run five attempts at approximately 1 m and record results separately.

- [ ] **Step 5: Validate two-turn half-duplex conversation**

Complete two ASR → Ark → TTS turns without repeating the wake phrase. Confirm the microphone is not recording ordinary ASR during TTS playback.

- [ ] **Step 6: Validate silent timeout**

Wait 30 seconds after the last valid turn. Confirm no timeout speech plays and `你好露米` is required again.

- [ ] **Step 7: Report using required labels**

Separate `Static check`, `Code test`, and `Physical-hardware validation`. State explicitly that USB audio validation is not ESP32-S3 or servo validation.

---

## Final Acceptance Command Set

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
grep -RInE '^[[:space:]]*(import|from)[[:space:]]+(RPi|gpiozero|serial|smbus|spidev)' src tests || true
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.app --check-config
```

Live commands are deliberately excluded from automated acceptance. Each microphone, cloud, or speaker test requires a separate user-facing notice and explicit confirmation.
