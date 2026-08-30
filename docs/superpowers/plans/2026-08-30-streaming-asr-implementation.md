# LumiLamp Streaming ASR 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot Raspberry Pi CLI that streams live USB-microphone PCM to Doubao Streaming ASR 2.0, displays partial transcripts, and prints the final transcript.

**Architecture:** ALSA `arecord` supplies 20 ms mono 16 kHz PCM chunks. A pure utterance gate performs RMS-based start/end detection, a WebSocket session sends aggregated 200 ms packets while concurrently consuming server frames, and a thin CLI owns configuration, device discovery, output, and cleanup.

**Tech Stack:** Python 3.13 standard library, ALSA utilities, `websockets>=15,<16`, `unittest`, Doubao bidirectional WebSocket protocol.

**Spec:** `docs/superpowers/specs/2026-08-30-streaming-asr-design.md`

## Global Constraints

- Use endpoint `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`.
- Use resource ID `volc.seedasr.sauc.duration` with legacy-compatible `APP ID + Access Token` authentication.
- Read secrets only from ignored `.env.voice`; never log credentials, request headers, or PCM.
- Identify the microphone by USB ID `08bb:2902`; never persist ALSA numeric card indexes.
- Capture mono, signed 16-bit, 16 kHz PCM in 20 ms chunks; send 200 ms packets.
- End after 800 ms trailing silence or 10 seconds total.
- Do not save recordings, start a background service, invoke TTS/LLM, upload ESP32 firmware, or control hardware.
- Do not commit or push without explicit user authorization. Each task ends with tests plus `git diff`/`git status`, not a commit.

---

### Task 1: ASR-only private configuration

**Files:**
- Modify: `src/lumilamp/voice/config.py`
- Modify: `tests/test_voice_config.py`

**Interfaces:**
- Produces: `AsrConfig(app_id: str, access_token: str, resource_id: str)`.
- Produces: `load_asr_config(path: Path) -> AsrConfig`.
- Preserves: existing `VoiceConfig` and `load_voice_config` behavior.

- [ ] **Step 1: Write failing ASR-only configuration tests**

Add tests that create a three-key temporary file, assert successful loading, assert the token is absent from `repr(config)`, and assert a missing `DOUBAO_ACCESS_TOKEN` raises `ValueError` without printing values:

```python
from lumilamp.voice.config import AsrConfig, load_asr_config

def test_loads_asr_only_settings_without_exposing_token(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ".env.voice"
        path.write_text(
            "DOUBAO_APP_ID=app-123\n"
            "DOUBAO_ACCESS_TOKEN=private-token\n"
            "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration\n",
            encoding="utf-8",
        )
        config = load_asr_config(path)
    self.assertEqual(config.app_id, "app-123")
    self.assertEqual(config.resource_id, "volc.seedasr.sauc.duration")
    self.assertNotIn("private-token", repr(config))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_voice_config -v
```

Expected: import failure because `AsrConfig` and `load_asr_config` do not exist.

- [ ] **Step 3: Implement the minimal ASR configuration API**

Add an immutable dataclass with `access_token=field(repr=False)`. Extract a private key-value reader shared by both loaders, and make `load_asr_config` require exactly the three ASR keys while leaving the full voice loader compatible.

```python
@dataclass(frozen=True)
class AsrConfig:
    app_id: str
    access_token: str = field(repr=False)
    resource_id: str

def load_asr_config(path: Path) -> AsrConfig:
    values = _load_values(path)
    required = ("DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN", "DOUBAO_ASR_RESOURCE_ID")
    _require_values(values, required)
    return AsrConfig(
        app_id=values["DOUBAO_APP_ID"],
        access_token=values["DOUBAO_ACCESS_TOKEN"],
        resource_id=values["DOUBAO_ASR_RESOURCE_ID"],
    )
```

- [ ] **Step 4: Verify GREEN and regression safety**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_voice_config -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: all tests pass; only intended files are modified.

---

### Task 2: Doubao bidirectional protocol and structured results

**Files:**
- Modify: `src/lumilamp/voice/asr.py`
- Modify: `tests/test_voice_asr.py`

**Interfaces:**
- Consumes: `AsrConfig` from Task 1.
- Produces: `ASR_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"`.
- Produces: `AsrResult(text: str, is_final: bool, sequence: int | None)`.
- Produces: `parse_server_frame(frame: bytes) -> AsrResult | None`.
- Preserves: `build_start_frame`, `build_audio_frame`, and legacy authentication headers.

- [ ] **Step 1: Write failing endpoint and result tests**

Add tests asserting the async endpoint and parsing both an interim response and a final response. Construct frames from JSON so the tests exercise real framing rather than mocks:

```python
def server_result_frame(text: str, flags: int, sequence: int) -> bytes:
    body = json.dumps({"result": {"text": text}}).encode()
    return (
        bytes((0x11, 0x90 | flags, 0x10, 0x00))
        + (struct.pack(">i", sequence) if flags & 0x01 else b"")
        + struct.pack(">I", len(body))
        + body
    )

def test_parses_partial_and_final_results(self) -> None:
    partial = parse_server_frame(server_result_frame("你好", 0x01, 2))
    final = parse_server_frame(server_result_frame("你好露米", 0x03, -3))
    self.assertEqual((partial.text, partial.is_final), ("你好", False))
    self.assertEqual((final.text, final.is_final), ("你好露米", True))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_voice_asr -v
```

Expected: endpoint mismatch and attribute errors because parsing currently returns `str`.

- [ ] **Step 3: Implement structured parsing and async endpoint**

Add `AsrResult` and preserve server sequence information. Treat response flag `0x03` as final, validate payload boundaries before unpacking, and keep server error messages free of local credentials.

```python
@dataclass(frozen=True)
class AsrResult:
    text: str
    is_final: bool
    sequence: int | None
```

Update `transcribe_wav` temporarily to consume `.text` and `.is_final` so existing callers remain valid until the live session replaces it.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_voice_asr -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: protocol and full unit suites pass.

---

### Task 3: Stable USB microphone discovery

**Files:**
- Create: `src/lumilamp/voice/devices.py`
- Create: `tests/test_voice_devices.py`

**Interfaces:**
- Produces: `MicrophoneNotFoundError(RuntimeError)`.
- Produces: `discover_alsa_capture_device(usb_id: str = "08bb:2902", proc_root: Path = Path("/proc/asound")) -> str`.
- Returns: stable ALSA name such as `plughw:CARD=Device,DEV=0`.

- [ ] **Step 1: Write failing discovery tests**

Build temporary `card3/usbid`, `card3/id`, `card4/usbid`, and `card4/id` files. Assert the requested USB ID selects the correct card name regardless of directory number, and assert zero or multiple matches raise a descriptive error.

```python
def test_selects_card_name_by_usb_id_not_card_number(self) -> None:
    (root / "card3").mkdir()
    (root / "card3" / "usbid").write_text("08bb:2902\n")
    (root / "card3" / "id").write_text("Device\n")
    self.assertEqual(
        discover_alsa_capture_device(proc_root=root),
        "plughw:CARD=Device,DEV=0",
    )
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_voice_devices -v
```

Expected: module import failure.

- [ ] **Step 3: Implement minimal `/proc/asound` discovery**

Iterate only directories named `card` followed by digits, compare normalized lowercase `usbid` content, read the ALSA stable `id`, validate it contains only letters, numbers, underscore, or hyphen, and return `plughw:CARD=<id>,DEV=0`. Never derive the result from the numeric directory suffix.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_voice_devices -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: discovery and full suites pass.

---

### Task 4: Pure streaming VAD and packet aggregation

**Files:**
- Create: `src/lumilamp/voice/streaming_audio.py`
- Create: `tests/test_streaming_audio.py`

**Interfaces:**
- Consumes: `pcm_level` and `LevelConfig` from `lumilamp.voice.recorder`.
- Produces: `StreamDecision(packets: tuple[bytes, ...], finished: bool, started: bool)`.
- Produces: `UtterancePacketizer(config: LevelConfig, packet_chunks: int = 10)`.
- Produces: `UtterancePacketizer.push(chunk: bytes) -> StreamDecision` and `finish() -> tuple[bytes, ...]`.

- [ ] **Step 1: Write failing packetizer tests**

Use real 640-byte 20 ms chunks. Assert pre-speech silence emits nothing, ten speech chunks emit one 6,400-byte packet, 40 silent chunks after speech mark completion, a final partial packet is flushed, and 500 chunks enforce the 10-second limit.

```python
def test_emits_one_network_packet_for_ten_started_chunks(self) -> None:
    gate = UtterancePacketizer(LevelConfig(0.02, 0.01))
    decisions = [gate.push(self.speech) for _ in range(10)]
    self.assertEqual(decisions[-1].packets, (self.speech * 10,))
    self.assertTrue(decisions[-1].started)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_streaming_audio -v
```

Expected: module import failure.

- [ ] **Step 3: Implement the state machine**

Keep elapsed and silent time in 20 ms increments, buffer only after start, emit each full group of ten chunks, and flush any remainder exactly once. Reject chunks whose length is not 640 bytes so timing cannot silently drift.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_streaming_audio -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: packetization and full suites pass.

---

### Task 5: Concurrent live microphone/WebSocket session

**Files:**
- Create: `src/lumilamp/voice/live_asr.py`
- Create: `tests/test_live_asr.py`

**Interfaces:**
- Consumes: `AsrConfig`, protocol frame functions, `AsrResult`, and `UtterancePacketizer`.
- Produces: `async recognize_microphone(config: AsrConfig, device: str, level_config: LevelConfig, on_partial: Callable[[str], None]) -> str`.

- [ ] **Step 1: Write failing orchestration tests**

Provide fake async process stdout and fake WebSocket objects implementing the same `send`, `recv`, and context-manager behavior used by production. Assert command arguments, start frame ordering, ordinary/final packet ordering, partial callback delivery, final return value, timeout propagation, and process cleanup on success and exception.

```python
expected_command = (
    "arecord", "-D", "plughw:CARD=Device,DEV=0", "-t", "raw",
    "-f", "S16_LE", "-r", "16000", "-c", "1",
)
```

The production change that makes these tests pass is a session coordinator; mocks may replace only ALSA and network boundaries, while real framing and packetizer code remain in use.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_live_asr -v
```

Expected: module import failure.

- [ ] **Step 3: Implement the minimal concurrent coordinator**

Use `asyncio.create_subprocess_exec(..., stdout=PIPE, stderr=PIPE)` and `websockets.connect(..., additional_headers=headers, open_timeout=15)`. Start a receiver task before streaming microphone packets. Use 15-second response deadlines, send the last audio packet with a negative sequence, and cancel/await all owned tasks in `finally`. Terminate and await `arecord` on every exit path.

Do not include headers or PCM in raised errors. Return only a non-empty final transcript; otherwise raise `RuntimeError("Doubao ASR returned no final transcript")`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_live_asr -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: orchestration and full suites pass with no leaked-task warnings.

---

### Task 6: One-shot ASR CLI and dependency setup

**Files:**
- Create: `src/lumilamp/voice/asr_cli.py`
- Create: `tests/test_asr_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `load_asr_config`, `discover_alsa_capture_device`, and `recognize_microphone`.
- Produces: `main(argv: Sequence[str] | None = None) -> int`.
- Command: `PYTHONPATH=src .venv/bin/python -m lumilamp.voice.asr_cli`.

- [ ] **Step 1: Write failing CLI tests**

Patch only configuration loading, device discovery, and the live session boundary. Assert default `.env.voice`, automatic microphone discovery, `--device` override, partial-output replacement, final output, safe error text, and exit code `1` on known failures.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_asr_cli -v
```

Expected: module import failure.

- [ ] **Step 3: Implement the CLI**

Use `argparse` with `--config` defaulting to `.env.voice`, optional `--device`, and numeric threshold overrides. Print `请开始说话…`, render partial text without logging secrets, print `识别结果: <text>` once, and convert configuration/device/network errors to concise stderr messages and nonzero status. Handle Ctrl+C without a traceback.

- [ ] **Step 4: Document exact setup and invocation**

Add a README section with these commands:

```bash
cd /home/lamp/pixarlamp
python3 -m venv .venv
.venv/bin/python -m pip install 'websockets>=15,<16'
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.asr_cli
```

State that `.env.voice` must remain mode `600`, recordings stay in memory, and this command performs a real cloud request only when explicitly run.

- [ ] **Step 5: Verify GREEN and full regression suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_asr_cli -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: CLI and full suites pass.

---

### Task 7: Raspberry Pi dependency, static checks, and user-gated live validation

**Files:**
- No tracked source changes expected unless verification exposes a defect, in which case return to the relevant RED/GREEN task.

**Interfaces:**
- Validates the command produced by Task 6 against installed ALSA and Doubao service.

- [ ] **Step 1: Create an isolated runtime and install only WebSockets**

Run:

```bash
cd /home/lamp/pixarlamp
python3 -m venv .venv
.venv/bin/python -m pip install 'websockets>=15,<16'
.venv/bin/python -c 'import websockets; print(websockets.__version__)'
```

Expected: a `15.x` version. Do not install the project wholesale because that would also install `sherpa-onnx`, which is outside this task.

- [ ] **Step 2: Verify environment without exposing secrets**

Run checks for `.env.voice` mode `600`, the three non-empty ASR keys, USB ID `08bb:2902`, ALSA capture availability, and absence of an existing `arecord` process. Never print the credential values.

- [ ] **Step 3: Run fresh automated verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
git status --short --branch
```

Expected: zero failures and only intended tracked changes.

- [ ] **Step 4: Stop and obtain explicit approval for live audio/cloud use**

Tell the user the exact microphone device, that PCM will be sent to Doubao, the expected maximum recording duration, and the short phrase to speak. Do not start recording until the user explicitly confirms readiness.

- [ ] **Step 5: Run the one-shot live recognition command**

After approval only:

```bash
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.asr_cli
```

Confirm separately: ALSA capture opened, WebSocket authenticated, partial text received if any, final text received, process exited, and no `arecord` process remains.

- [ ] **Step 6: Report evidence by validation layer**

Report separately:

- `Environment installation`: WebSockets version and ALSA availability.
- `Static check`: files, credentials presence/permissions, endpoint/resource/device selection.
- `Code test`: exact passed/failed counts.
- `Cloud-service validation`: connection/authentication and server result.
- `Physical-hardware validation`: actual USB microphone capture result.
- `ESP32 Build/Upload`: not performed in this feature task.

Do not claim cloud or physical validation from unit tests alone.
