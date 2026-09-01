# LumiLamp Interactive Voice Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Raspberry Pi half-duplex loop that locally detects `露米` or `你好露米`, plays a cached random acknowledgement, and supports repeated Doubao ASR → Ark → Doubao TTS turns for a 30-second session.

**Architecture:** One async orchestrator owns an explicit conversation state machine and calls focused adapters for ALSA devices, local sherpa-onnx KWS, streaming ASR, Ark chat, TTS, cache, and playback. All external I/O sits behind injectable functions so automated tests remain offline and hardware-free; physical validation is performed only after the complete mocked flow passes.

**Tech Stack:** Python 3.13, `unittest`, `asyncio`, `websockets>=15,<16`, `sherpa-onnx>=1.12,<2`, ALSA `arecord`/`aplay`/`amixer`, Doubao ASR/TTS 2.0, Volcengine Ark Chat Completions.

**Spec:** `docs/superpowers/specs/2026-08-30-interactive-voice-loop-design.md`

## Global Constraints

- Work only in `/home/lamp/pixarlamp/.worktrees/streaming-asr` on `feature/streaming-asr`.
- Preserve all existing user changes. Do not reset, clean, delete, overwrite, commit, or push without separate authorization.
- Do not access GPIO, serial, ESP32-S3, servos, or servo power.
- V1 is half-duplex. Microphone recognition must be stopped while any LumiLamp audio is playing; resume after approximately 300 ms.
- Wake phrases are exactly `露米` and `你好露米`.
- Wake replies are exactly `我在呀`, `你好呀`, `嗯？`, and `请吩咐`.
- Wake audio remains local and in memory. Do not save or upload sleeping-state PCM.
- The active conversation window is 30 seconds and resets after every successful turn.
- End a user utterance after 800 ms trailing silence and cap it at 10 seconds.
- Two consecutive processing failures end the session silently.
- Use stable USB identity discovery: microphone `08bb:2902`, speaker `1b3f:2008`; never persist numeric ALSA card indexes.
- Keep secrets in the ignored mode-`0600` `.env.voice`; never print or log secret values.
- Unit tests must not access the network, microphone, speaker, GPIO, serial, or servos.
- Dependency installation, model download, cloud probes, and real audio tests must be reported as separate evidence categories.
- Each task ends at a review checkpoint. The normal commit step is intentionally omitted because the user has not authorized commits.

## File Structure

- Modify `src/lumilamp/voice/config.py`: separate ASR legacy credentials from TTS 2.0 API-key credentials and add local model/cache settings.
- Modify `src/lumilamp/voice/tts.py`: implement the current TTS 2.0 HTTP chunked protocol and WAV output.
- Modify `src/lumilamp/voice/devices.py`: resolve both USB microphone and USB speaker without numeric card persistence.
- Modify `src/lumilamp/voice/wakeword.py`: support two configured phrases and explicit model validation.
- Create `src/lumilamp/voice/wake_cache.py`: prepare and validate the four deterministic wake-reply WAV cache entries.
- Modify `src/lumilamp/voice/streaming_audio.py`: retain a bounded pre-roll before speech begins.
- Modify `src/lumilamp/voice/ark.py`: carry bounded session history while retaining the single-turn adapter.
- Modify `src/lumilamp/voice/conversation.py`: represent exact replies and half-duplex timing transitions.
- Create `src/lumilamp/voice/voice_loop.py`: coordinate KWS, capture, ASR, Ark, TTS, playback, timeouts, and cleanup.
- Create `src/lumilamp/voice/voice_cli.py`: parse paths/options, build real adapters, and run the loop.
- Create `scripts/prepare_kws_model.sh`: explicit, repeatable official KWS model download and file verification; never runs automatically.
- Create `scripts/prepare_wake_replies.py`: explicit one-time TTS cache preparation command.
- Modify `README.md`: document setup, commands, evidence boundaries, and the absence of ESP32/servo validation.

---

### Task 1: Voice Configuration and Current TTS 2.0 Protocol

**Files:**
- Modify: `src/lumilamp/voice/config.py`
- Modify: `src/lumilamp/voice/tts.py`
- Modify: `tests/test_voice_config.py`
- Modify: `tests/test_voice_tts.py`

**Interfaces:**
- Produces: `VoiceConfig(asr: AsrConfig, tts_api_key: str, tts_resource_id: str, ark_api_key: str, ark_model_id: str, kws_model_dir: Path, wake_cache_dir: Path)`.
- Produces: `build_tts_headers(config: VoiceConfig, request_id: str) -> dict[str, str]`.
- Produces: `parse_tts_chunks(chunks: Iterable[bytes]) -> bytes` and `synthesize_to_wav(config: VoiceConfig, text: str, output_path: Path) -> None`.

- [ ] **Step 1: Write failing configuration tests for separate TTS authentication**

```python
def test_loads_tts_api_key_without_exposing_it(self) -> None:
    env_file.write_text(
        "\n".join((
            "DOUBAO_APP_ID=app-123",
            "DOUBAO_ACCESS_TOKEN=asr-secret",
            "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration",
            "DOUBAO_TTS_API_KEY=tts-secret",
            "DOUBAO_TTS_RESOURCE_ID=seed-tts-2.0",
            "ARK_API_KEY=ark-secret",
            "ARK_MODEL_ID=doubao-seed-2-0-lite-260428",
            "LUMILAMP_KWS_MODEL_DIR=/opt/lumilamp/models/kws",
            "LUMILAMP_WAKE_CACHE_DIR=/opt/lumilamp/cache/wake",
        )),
        encoding="utf-8",
    )
    config = load_voice_config(env_file)
    self.assertEqual(config.tts_resource_id, "seed-tts-2.0")
    self.assertNotIn("tts-secret", repr(config))
```

- [ ] **Step 2: Write failing TTS endpoint/header and chunk parser tests**

```python
def test_uses_current_tts_v2_endpoint_and_headers(self) -> None:
    self.assertEqual(TTS_ENDPOINT, "https://openspeech.bytedance.com/api/v3/tts/unidirectional")
    headers = build_tts_headers(make_config(), "request-1")
    self.assertEqual(headers["X-Api-Key"], "tts-secret")
    self.assertEqual(headers["X-Api-Resource-Id"], "seed-tts-2.0")
    self.assertEqual(headers["X-Api-Request-Id"], "request-1")
    self.assertNotIn("X-Api-App-Key", headers)
    self.assertNotIn("X-Api-Access-Key", headers)
```

- [ ] **Step 3: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_config.py tests/test_voice_tts.py -v`

Expected: failures for missing `DOUBAO_TTS_API_KEY`, new config fields, endpoint, headers, and chunk parser.

- [ ] **Step 4: Implement the minimal config and protocol migration**

Use this header boundary and keep the API key `repr=False`:

```python
TTS_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"

def build_tts_headers(config: VoiceConfig, request_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Api-Key": config.tts_api_key,
        "X-Api-Resource-Id": config.tts_resource_id,
        "X-Api-Request-Id": request_id,
    }
```

Parse each JSON chunk, reject nonzero provider errors, base64-decode nonempty `data`, and reject a response with no audio. Keep `speaker="zh_female_vv_uranus_bigtts"`, PCM 24 kHz mono, and `loudness_rate=0`.

- [ ] **Step 5: Run focused and full offline tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_config.py tests/test_voice_tts.py -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass; no network or audio device is accessed.

- [ ] **Step 6: Review checkpoint**

Inspect `git diff --check`. Review only added production lines with `git diff -- src/lumilamp ':!tests'` and confirm no value from the real `.env.voice` appears; test fixtures may contain the literal dummy values `tts-secret`, `ark-secret`, and `asr-secret`. Do not commit.

---

### Task 2: Stable Speaker Discovery

**Files:**
- Modify: `src/lumilamp/voice/devices.py`
- Modify: `src/lumilamp/voice/audio_output.py`
- Modify: `tests/test_voice_devices.py`
- Modify: `tests/test_audio_output.py`

**Interfaces:**
- Produces: `AlsaDevice(card_id: str, device: str)`.
- Produces: `discover_alsa_device(usb_id: str, proc_root: Path) -> AlsaDevice`.
- Preserves: `discover_alsa_capture_device(...) -> str` as a compatibility wrapper.
- Changes: `set_usb_speaker_volume(card_id: str, percent: int = 70) -> None`.

- [ ] **Step 1: Write failing speaker and ambiguity tests**

```python
def test_discovers_speaker_by_usb_id(self) -> None:
    make_card(self.proc_root, 2, "1b3f:2008", "Device_1")
    device = discover_alsa_device("1b3f:2008", self.proc_root)
    self.assertEqual(device.card_id, "Device_1")
    self.assertEqual(device.device, "plughw:CARD=Device_1,DEV=0")

def test_rejects_two_matching_speakers(self) -> None:
    make_card(self.proc_root, 1, "1b3f:2008", "SpeakerA")
    make_card(self.proc_root, 2, "1b3f:2008", "SpeakerB")
    with self.assertRaisesRegex(AudioDeviceNotFoundError, "multiple"):
        discover_alsa_device("1b3f:2008", self.proc_root)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_devices.py tests/test_audio_output.py -v`

Expected: import/signature failures for `AlsaDevice`, generic discovery, and string card IDs.

- [ ] **Step 3: Implement generic discovery and safe playback arguments**

Use `/proc/asound/card*/usbid` plus each card's `id`, validate the ID against `_SAFE_CARD_ID`, and never select `default`. Ensure subprocess calls remain argument arrays:

```python
subprocess.run(
    ["amixer", "-c", card_id, "sset", "Speaker", f"{percent}%", "unmute"],
    check=True,
)
subprocess.run(["aplay", "-D", device, str(path)], check=True)
```

- [ ] **Step 4: Run focused and full offline tests**

Run the two focused modules, then `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`.

Expected: all pass; mocked subprocess assertions show no `shell=True` and no numeric persisted card.

- [ ] **Step 5: Review checkpoint**

Run `git diff --check`. Do not probe or change real mixer state in this task. Do not commit.

---

### Task 3: Dual-Phrase Local KWS and Explicit Model Preparation

**Files:**
- Modify: `src/lumilamp/voice/wakeword.py`
- Modify: `tests/test_wakeword.py`
- Create: `scripts/prepare_kws_model.sh`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces: `WAKE_PHRASES: tuple[str, ...] = ("露米", "你好露米")`.
- Produces: `WakeWordConfig(model_dir: Path, phrases: tuple[str, ...] = WAKE_PHRASES, threshold: float = 0.25, score: float = 1.0)`.
- Produces: `validate_model_dir(model_dir: Path) -> dict[str, Path]`.
- `SherpaWakeWordDetector.accept_pcm(samples: array[int]) -> str | None` returns the matched phrase.

- [ ] **Step 1: Replace single-phrase tests with failing dual-phrase tests**

```python
def test_defaults_to_both_confirmed_phrases(self) -> None:
    self.assertEqual(WakeWordConfig(MODEL_DIR).phrases, ("露米", "你好露米"))

def test_returns_the_matched_phrase(self) -> None:
    detector, spotter = make_detector()
    spotter.ready = True
    spotter.result = "露米"
    self.assertEqual(detector.accept_pcm(array("h", [1, -1])), "露米")
```

Also assert empty phrases, duplicates, or unsupported phrases raise `ValueError`, and all four official model files plus `keywords_lumilamp.txt` are required before importing `sherpa_onnx`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_wakeword.py -v`

Expected: failures because the existing config has one `keyword` and `accept_pcm` returns `bool`.

- [ ] **Step 3: Implement dual-phrase configuration and matched-text return**

Keep lazy `import sherpa_onnx`. Return `None` when there is no match; when the spotter returns a configured phrase, reset the stream and return it. Reject an unexpected nonempty model result instead of treating it as a valid wake event.

- [ ] **Step 4: Add an explicit official model preparation script**

The script must use exact constants and stop on any missing file:

```bash
MODEL_URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2'
MODEL_NAME='sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
```

It accepts one explicit destination argument, downloads to a `mktemp -d` directory, extracts there, copies only the named model directory after verification, and writes `keywords_lumilamp.txt` with exactly these two lines:

```text
露 米
你 好 露 米
```

Before accepting the file, verify every space-separated token occurs in the downloaded `tokens.txt`. The script must refuse to overwrite an existing destination. Add the model/cache directory patterns to `.gitignore` without ignoring source code.

- [ ] **Step 5: Validate shell and Python tests without downloading**

Run:

```bash
bash -n scripts/prepare_kws_model.sh
PYTHONPATH=src .venv/bin/python -m unittest tests/test_wakeword.py -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: syntax and tests pass; no download has occurred.

- [ ] **Step 6: Review checkpoint**

Verify the model archive URL, exact chunk-8 filenames, and that no model binary appears in `git status`. Do not install or download yet. Do not commit.

---

### Task 4: Deterministic Wake-Reply WAV Cache

**Files:**
- Create: `src/lumilamp/voice/wake_cache.py`
- Create: `tests/test_wake_cache.py`
- Create: `scripts/prepare_wake_replies.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `WAKE_REPLIES: tuple[str, ...] = ("我在呀", "你好呀", "嗯？", "请吩咐")`.
- Produces: `WakeReplyCache(root: Path)` with `path_for(text: str) -> Path`, `validate() -> None`, and `prepare(synthesize: Callable[[str, Path], None]) -> None`.
- Produces CLI: `prepare_wake_replies.py --config PATH --output-dir PATH`.

- [ ] **Step 1: Write failing mapping, validation, and no-overwrite tests**

```python
def test_maps_all_exact_replies_to_stable_names(self) -> None:
    cache = WakeReplyCache(Path("/cache"))
    self.assertEqual(
        {text: cache.path_for(text).name for text in WAKE_REPLIES},
        {"我在呀": "wo-zai-ya.wav", "你好呀": "ni-hao-ya.wav", "嗯？": "en.wav", "请吩咐": "qing-fen-fu.wav"},
    )

def test_prepare_synthesizes_only_missing_files(self) -> None:
    existing.write_bytes(valid_wav_bytes())
    cache.prepare(fake_synthesize)
    self.assertNotIn(existing, synthesized_paths)
```

Validate RIFF/WAVE, mono, 16-bit, 24 kHz, nonempty frames, and a manifest containing the exact text, speaker, resource ID, and format version.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_wake_cache.py -v`

Expected: import error for the new module.

- [ ] **Step 3: Implement cache validation and preparation**

Use `wave.open` for structural checks and atomic per-file creation via a sibling `.partial` file followed by `Path.replace`. Never overwrite a valid WAV. If synthesis fails, leave the existing cache untouched and report the failing reply without exposing credentials.

- [ ] **Step 4: Implement explicit cache preparation CLI**

The CLI loads config, validates directory paths, calls `synthesize_to_wav` four times only where needed, and prints file paths plus success/failure—never secrets. It must not run during package import, installation, or normal tests.

- [ ] **Step 5: Run focused and full offline tests**

Run focused tests, `compileall`, then the complete unittest suite. Expected: all pass and no network/audio access occurs.

- [ ] **Step 6: Review checkpoint**

Confirm WAV/cache outputs are ignored by Git and no real cache was generated. Do not call TTS yet. Do not commit.

---

### Task 5: ASR Pre-Roll Without Uploading Sleeping Audio

**Files:**
- Modify: `src/lumilamp/voice/streaming_audio.py`
- Modify: `src/lumilamp/voice/live_asr.py`
- Modify: `tests/test_streaming_audio.py`
- Modify: `tests/test_live_asr.py`

**Interfaces:**
- Changes: `UtterancePacketizer(config: LevelConfig, packet_chunks: int = 10, pre_roll_chunks: int = 10)`.
- Preserves: `push(chunk: bytes) -> StreamDecision`, `finish() -> tuple[bytes, ...]`.
- Guarantee: pre-roll is at most 200 ms and is emitted only after local speech start.

- [ ] **Step 1: Write failing bounded pre-roll tests**

```python
def test_prepends_only_the_last_two_hundred_ms(self) -> None:
    packetizer = UtterancePacketizer(self.config, pre_roll_chunks=10)
    for index in range(12):
        packetizer.push(silence_chunk(index))
    decision = packetizer.push(self.speech)
    first_packet = decision.packets[0]
    self.assertEqual(first_packet, b"".join(last_ten_silence_chunks + [self.speech]))

def test_never_emits_pre_roll_before_speech(self) -> None:
    decision = UtterancePacketizer(self.config).push(self.silence)
    self.assertFalse(decision.packets)
```

Adjust packet expectations so the first network packet may contain pre-roll plus the triggering speech chunk without exceeding the packetizer's documented aggregation rule.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_streaming_audio.py tests/test_live_asr.py -v`

Expected: constructor/signature and first-packet assertions fail.

- [ ] **Step 3: Implement a bounded deque pre-roll**

Use `collections.deque(maxlen=pre_roll_chunks)`. Before speech, append only to the deque and return no packets. On the triggering chunk, move the deque into pending, append the trigger, clear the deque, and continue normal 200 ms aggregation. Zeroize references by clearing the deque on finish/reset; do not write PCM to disk or logs.

- [ ] **Step 4: Preserve delayed cloud connection behavior**

Update `recognize_microphone` tests to assert `_open_websocket` is not called before `decision.started` and that the first sent audio includes the pre-roll only after speech begins.

- [ ] **Step 5: Run focused and full offline tests**

Run both focused modules and the full suite. Expected: all pass with mocked ALSA/WebSocket; no real microphone or network access.

- [ ] **Step 6: Review checkpoint**

Confirm the pre-roll is bounded at 200 ms and no path writes microphone PCM. Do not run a live ASR probe yet. Do not commit.

---

### Task 6: Bounded Ark Session Context and Updated Conversation State

**Files:**
- Modify: `src/lumilamp/voice/ark.py`
- Modify: `src/lumilamp/voice/conversation.py`
- Modify: `tests/test_voice_ark.py`
- Modify: `tests/test_conversation.py`

**Interfaces:**
- Produces: `ConversationHistory(max_turns: int = 4)` with `messages() -> list[dict[str, str]]`, `append_turn(user_text: str, assistant_text: str) -> None`, and `clear() -> None`.
- Changes: `build_chat_body(model_id: str, messages: list[dict[str, str]]) -> dict[str, object]`.
- Changes: `ask_ark(config: VoiceConfig, history: ConversationHistory, user_text: str) -> str` appends only after a valid response.
- Changes: controller reply tuple to the four exact confirmed strings.
- Produces: `ready_after_playback(now: float, guard_seconds: float = 0.3) -> bool` or an equivalent injectable-clock transition that is unit-testable without sleeping.

- [ ] **Step 1: Write failing history, exact-copy, and guard-time tests**

```python
def test_history_keeps_only_four_complete_turns(self) -> None:
    history = ConversationHistory(max_turns=4)
    for index in range(5):
        history.append_turn(f"问{index}", f"答{index}")
    self.assertEqual(history.messages()[0]["content"], "问1")
    self.assertEqual(len(history.messages()), 8)

def test_wake_uses_exact_confirmed_replies(self) -> None:
    controller = ConversationController(clock=self.clock, choose=lambda replies: replies[0])
    self.assertEqual(controller.wake(), "我在呀")
    self.assertEqual(WAKE_REPLIES, ("我在呀", "你好呀", "嗯？", "请吩咐"))
```

Add a virtual-clock assertion that listening cannot resume at 0.299 seconds after playback but can at 0.300 seconds, and that sleeping clears history through the orchestrator-facing hook.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_ark.py tests/test_conversation.py -v`

Expected: missing history and old reply-copy failures.

- [ ] **Step 3: Implement bounded history and exact state behavior**

Keep the system prompt separate from stored messages. Reject blank user/assistant content. Slice by complete user/assistant pairs, never individual messages. Do not include credentials or raw audio in history.

- [ ] **Step 4: Run focused and full offline tests**

Run both focused modules and the entire suite. Expected: all pass; time behavior uses a fake clock and no real delay.

- [ ] **Step 5: Review checkpoint**

Confirm exact punctuation and that context clears when the session returns to `SLEEPING`. Do not call Ark. Do not commit.

---

### Task 7: Half-Duplex Voice Loop Orchestrator

**Files:**
- Create: `src/lumilamp/voice/voice_loop.py`
- Create: `tests/test_voice_loop.py`

**Interfaces:**
- Produces protocol-style callables/interfaces: `listen_for_wake() -> Awaitable[str]`, `play_cached_reply(text: str) -> Awaitable[None]`, `recognize_turn() -> Awaitable[str]`, `ask(text: str) -> Awaitable[str]`, `speak(text: str) -> Awaitable[None]`.
- Produces: `VoiceLoop(controller, listen_for_wake, play_cached_reply, recognize_turn, ask, speak, clock, delay)`.
- Produces: `run_forever() -> None` and a single-session `run_once() -> SessionResult` for deterministic tests.

- [ ] **Step 1: Write failing happy-path integration test with fakes**

```python
async def test_two_turns_then_idle_sleep(self) -> None:
    events: list[str] = []
    loop = make_loop(
        wakes=["露米"],
        transcripts=["你是谁", "今天天气怎么样", IDLE],
        ark_answers=["我是露米。", "今天适合出门。"],
        events=events,
    )
    result = await loop.run_once()
    self.assertEqual(result.turns, 2)
    self.assertEqual(result.reason, "idle_timeout")
    self.assert_ordered(events, ["wake:露米", "play_wake", "asr", "ark", "tts", "asr", "ark", "tts"])
```

- [ ] **Step 2: Write failing safety/error tests**

Cover these exact cases:

- `recognize_turn` is never active while `play_cached_reply` or `speak` is active.
- A 300 ms injected delay occurs after both wake and answer playback.
- Empty/no-speech results do not call Ark or TTS.
- Two consecutive ASR/Ark failures return `reason="two_failures"`.
- Playback failure returns `reason="playback_error"` immediately.
- Cancellation closes only resources owned by the loop.
- No collaborator receives GPIO, serial, ESP32, or servo commands.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_loop.py -v`

Expected: import error for `voice_loop`.

- [ ] **Step 4: Implement the smallest explicit orchestration loop**

Use `try/finally` around each owned adapter context, call components sequentially, and inject `delay` rather than calling `asyncio.sleep` directly in tests. Represent idle as a typed result/sentinel, not an exception string. Catch only documented adapter failures, record a redacted error category, and let cancellation propagate after cleanup.

- [ ] **Step 5: Run focused and full offline tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_loop.py -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m compileall -q src tests
```

Expected: all pass; no network, audio, GPIO, serial, or servo access.

- [ ] **Step 6: Review checkpoint**

Inspect event-order assertions, cleanup paths, and `git diff --check`. Do not commit.

---

### Task 8: Real Adapter Wiring and CLI Dry Run

**Files:**
- Create: `src/lumilamp/voice/voice_cli.py`
- Create: `tests/test_voice_cli.py`
- Modify: `README.md`

**Interfaces:**
- Produces CLI: `python -m lumilamp.voice.voice_cli --config PATH --dry-run`.
- Produces operational mode: `python -m lumilamp.voice.voice_cli --config PATH`.
- `--dry-run` validates config, model files, wake cache, ALSA USB identities, and dependency imports without opening microphone, network, or speaker.
- Produces: `ArkAskAdapter(config: VoiceConfig, history: ConversationHistory)` with a read-only `history` property and `async ask(text: str) -> str`; the exact same history object must be injected into `VoiceLoop`.
- Adapter boundary converts expected ASR/Ark/TTS/playback transport and provider failures to `VoiceAdapterError`; cancellation and programming errors must continue to propagate.

- [ ] **Step 1: Write failing parser and dry-run tests**

```python
def test_dry_run_never_opens_audio_or_network(self) -> None:
    result = main(["--config", str(config), "--dry-run"], adapters=fakes)
    self.assertEqual(result, 0)
    self.assertFalse(fakes.microphone_opened)
    self.assertFalse(fakes.network_opened)
    self.assertFalse(fakes.speaker_opened)

def test_ark_adapter_and_loop_share_the_same_history(self) -> None:
    history = ConversationHistory()
    adapter = ArkAskAdapter(config, history)
    loop = build_voice_loop(history=history, asker=adapter, adapters=fakes)
    self.assertIs(loop.history, adapter.history)
```

Also assert missing config/model/cache/device produces a concise nonzero result without printing credential values.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_cli.py -v`

Expected: import error for `voice_cli`.

- [ ] **Step 3: Implement dependency construction and dry-run mode**

Build all real adapters from `VoiceConfig`, resolve both USB devices at startup, validate KWS/cache paths, and create async wrappers for blocking Ark/TTS/playback operations via `asyncio.to_thread`. `ArkAskAdapter` owns the successful-turn append through `ask_ark`; the loop only clears the shared history at session termination. Convert only documented recoverable adapter failures to `VoiceAdapterError`; do not swallow `CancelledError`, `TypeError`, `AssertionError`, or other programming faults. Do not print environment values. Handle `SIGINT`/Ctrl-C with orderly cancellation and owned-child cleanup.

- [ ] **Step 4: Document exact setup and run commands**

README must list:

```bash
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.voice_cli \
  --config /home/lamp/pixarlamp/.env.voice \
  --dry-run
```

Document that removing `--dry-run` opens the real microphone and cloud services, and must happen only during an explicitly announced hardware validation step. State that no ESP32 upload or servo validation occurs.

- [ ] **Step 5: Run CLI-focused and full offline verification**

Run the CLI tests, full unittest discovery, compileall, and the CLI `--help`. Expected: all pass; `--help` does not initialize devices or load secrets.

- [ ] **Step 6: Review checkpoint**

Run `git diff --check`, inspect `git status --short`, and confirm no generated WAV/model/secret file is tracked. Do not commit.

---

### Task 9: Controlled Environment Installation and Static Validation

**Files:**
- No source changes expected; only the existing isolated `.venv`, ignored model directory, and ignored wake cache may change.

**Interfaces:**
- Consumes: completed Tasks 1–8 and explicit user authorization to install/download.
- Produces evidence only: installed versions, model file checks, dry-run result.

- [ ] **Step 1: Record the pre-install state**

Run `python3 --version`, `.venv/bin/python -m pip show websockets sherpa-onnx`, `git status --short`, and available disk space. Do not display credentials.

- [ ] **Step 2: Install only declared Python dependencies**

Run: `.venv/bin/python -m pip install -e .`

Expected: `websockets>=15,<16` and `sherpa-onnx>=1.12,<2`; no ROS, OpenCV, PyTorch, or system-wide package installation.

- [ ] **Step 3: Download and verify the official KWS model**

Run `scripts/prepare_kws_model.sh <explicit-ignored-model-directory>`. Verify the three exact ONNX files, `tokens.txt`, and `keywords_lumilamp.txt`; report sizes and installed package version. Do not add binaries to Git.

- [ ] **Step 4: Run complete offline tests and static dry run**

Run full unittest discovery, compileall, and `voice_cli --dry-run`. Expected: tests and validation pass without opening network or audio streams.

- [ ] **Step 5: Report evidence boundary**

Report separately: environment installation complete, static check complete, code tests complete. Explicitly report that cloud integration and real voice-loop validation have not yet run. Do not commit.

---

### Task 10: Explicit Cloud and Physical Audio Validation

**Files:**
- Generated only in ignored cache/output paths; no source changes expected unless a diagnosed defect requires a new TDD fix cycle.

**Interfaces:**
- Consumes: separate user confirmation immediately before quota-consuming/cloud or audible tests.
- Produces evidence: Ark response, TTS cache, both wake phrases, two-turn loop, idle timeout, and failure behavior.

- [ ] **Step 1: Run one redacted Ark text probe**

Load `.env.voice` without printing it, ask a short fixed question, and print only model ID, elapsed time, request outcome, and assistant text. Do not print request headers.

- [ ] **Step 2: Generate and validate four wake-reply WAV files**

Run `scripts/prepare_wake_replies.py` with explicit config/cache paths. Validate all four WAV headers and report filenames, durations, and sample format. This proves cloud TTS output generation, not speaker playback.

- [ ] **Step 3: Play each cached reply through the resolved USB speaker**

Resolve USB ID `1b3f:2008`, set the confirmed safe volume, play one file at a time, and ask the user to confirm audibility. This proves physical speaker playback only.

- [ ] **Step 4: Validate both local wake phrases**

With cloud conversation disabled, open USB microphone `08bb:2902` and test `露米` and `你好露米` separately at close range. Report matched phrase and latency; do not save PCM.

- [ ] **Step 5: Run the complete half-duplex loop**

Start the CLI, wake it, complete at least two turns without repeating the wake phrase, verify the random acknowledgement, ASR text, Ark answer, TTS playback, no self-recognition during playback, and microphone resume after approximately 300 ms.

- [ ] **Step 6: Validate timeout and cleanup**

Leave the session idle for 30 seconds, confirm silent sleep, then stop with Ctrl-C and verify no owned `arecord`, `aplay`, or voice-loop process remains.

- [ ] **Step 7: Final verification report**

Report these independently:

- Environment installation
- Static check
- Code test
- Cloud ASR validation
- Cloud Ark validation
- Cloud TTS validation
- USB microphone/KWS validation
- USB speaker validation
- Complete voice-loop validation
- Firmware upload: not executed
- ESP32/servo physical validation: not executed
- Installed-system validation: only claim if the complete loop was run on the target Raspberry Pi in its intended setup

Do not treat any earlier category as proof of a later one. Do not commit or push unless separately authorized.
