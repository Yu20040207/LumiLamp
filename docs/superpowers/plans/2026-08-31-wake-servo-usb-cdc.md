# 唤醒后单舵机 USB CDC 动作 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 LumiLamp 本地唤醒回应之后，通过稳定 USB CDC 对已有 ESP32-S3 安全固件执行受回应确认的 ID 1 小幅点头。

**Architecture:** `Esp32ServoClient` 独立负责稳定路径、命令、回应解析和 `torque off` 兜底。`VoiceLoop` 只接收可选 `wake_motion()`，在唤醒 WAV 播放完成且普通 ASR 之前调用。

**Tech Stack:** Python 3.13、标准库 `os`/`termios`/`select`、`asyncio.to_thread`、现有 `unittest`、ESP32-S3 USB CDC（115200）。

**Spec:** `docs/superpowers/specs/2026-08-31-wake-servo-usb-cdc-design.md`

## Global Constraints

- 只改树莓派 Python 语音软件；不改 ESP32 固件、GPIO、UART、舵机 ID、接线或供电。
- 仅接受显式 `/dev/serial/by-id/` 路径；不写死 `/dev/ttyACM0` 或 USB 序列号。
- 只用 `status`、`move 5`、`move -5`、`torque off`，逐条等待回应。
- 任意结束路径均尝试一次 `torque off`，只关闭自身打开的描述符。
- 自动化测试不得访问真实 USB、ESP32、麦克风、扬声器或网络；物理动作另行授权。
- 不执行 commit、push、reset、clean 或删除文件。

## File Structure

- Create `src/lumilamp/hardware/__init__.py`：硬件边界包标记。
- Create `src/lumilamp/hardware/esp32_servo.py`：USB CDC、协议和点头序列。
- Modify `src/lumilamp/voice/config.py`：可选稳定路径配置。
- Modify `src/lumilamp/voice/voice_loop.py`：可选唤醒动作和脱敏日志。
- Modify `src/lumilamp/voice/voice_cli.py`：延迟打开的适配器装配、关闭生命周期。
- Modify `README.md`：稳定路径和物理验证说明。
- Add `tests/test_esp32_servo.py`；更新现有配置、语音循环、CLI 测试。

### Task 1: USB CDC 命令客户端

**Files:** Create `src/lumilamp/hardware/esp32_servo.py`; test `tests/test_esp32_servo.py`.

**Interfaces:** `Esp32ServoError(stage: str)`、`ServoTelemetry(position: int, voltage: float, temperature: int)`、`Esp32ServoClient(device_path: Path, timeout_seconds: float = 3.0, pause_seconds: float = 0.5)` 和 `wake_nod() -> None`。

- [ ] **Step 1: Write failing tests.**

Use a fake line transport returning existing firmware responses. Assert success writes exactly `status\\n`, `move 5\\n`, `status\\n`, `move -5\\n`, `torque off\\n`. Test initial `BLOCKED:` and `move 5` timeout separately; both must skip later moves and end with `torque off\\n`.

- [ ] **Step 2: Verify RED.** Run `.venv/bin/python -m unittest tests.test_esp32_servo -v`; expect missing module.

- [ ] **Step 3: Implement minimal client.** Define private `LineTransport(write_line, read_line, close)`. OS transport opens only supplied path, configures 115200 8N1 with `termios`, and bounds reads with `select.select`. Full-line regex validators accept telemetry, `OK: target=...`, and `OK: torque disabled`. `wake_nod()` runs status/move/pause/status/move and uses `finally` for best-effort torque-off and close. Raise only `Esp32ServoError("open" | "status" | "move" | "torque_off" | "protocol")` without raw serial content.

- [ ] **Step 4: Verify GREEN.** Run focused tests, `compileall`, and `git diff --check`; expect fake-only passing tests.

### Task 2: 稳定路径配置

**Files:** Modify `src/lumilamp/voice/config.py`, `tests/test_voice_config.py`, `README.md`.

**Interfaces:** `VoiceConfig.esp32_serial_by_id: Path | None`, loaded from optional `LUMILAMP_ESP32_SERIAL_BY_ID`.

- [ ] **Step 1: Write failing tests.** `/dev/serial/by-id/usb-Espressif-if00` loads as `Path`; blank means `None`; `/dev/ttyACM0` raises a stable by-id `ValueError`.

- [ ] **Step 2: Verify RED.** Run `.venv/bin/python -m unittest tests.test_voice_config -v`; expect missing field or ignored variable.

- [ ] **Step 3: Implement parsing.** Empty is `None`; non-empty must be absolute with `/dev/serial/by-id` ancestor. Do not test device existence in config loader. Document only `LUMILAMP_ESP32_SERIAL_BY_ID=/dev/serial/by-id/<actual-ESP32-USB-device>`.

- [ ] **Step 4: Verify GREEN.** Run configuration tests, `compileall`, and `git diff --check`.

### Task 3: VoiceLoop 唤醒动作边界

**Files:** Modify `src/lumilamp/voice/voice_loop.py`, `tests/test_voice_loop.py`.

**Interfaces:** optional `WakeMotion = Callable[[], Awaitable[None]]`, `wake_motion`, and `report_motion`.

- [ ] **Step 1: Write failing tests.** Assert event order is `reply`, `guard`, `motion`, `recognition`. A motion fake raising `VoiceAdapterError("serial detail")` must still allow recognition and emit exactly `wake_motion status=error`.

- [ ] **Step 2: Verify RED.** Run `.venv/bin/python -m unittest tests.test_voice_loop -v`; expect no action boundary or wrong order.

- [ ] **Step 3: Implement.** After wake playback guard and before recognition, await optional motion. Catch only `VoiceAdapterError`, emit stable `wake_motion status=ok` or `wake_motion status=error`, and keep voice session running.

- [ ] **Step 4: Verify GREEN.** Run loop tests, `compileall`, and `git diff --check`.

### Task 4: CLI 装配和离线门禁

**Files:** Modify `src/lumilamp/voice/voice_cli.py`, `tests/test_voice_cli.py`, `README.md`.

**Interfaces:** `WakeMotionAdapter` wraps blocking `Esp32ServoClient.wake_nod()` with `asyncio.to_thread` and maps expected failures to `VoiceAdapterError("wake motion failed")`.

- [ ] **Step 1: Write failing tests.** Verify dry-run never constructs motion client; unset path gives `wake_motion=None`; configured fake failure is redacted; owned client resource closes.

- [ ] **Step 2: Verify RED.** Run `.venv/bin/python -m unittest tests.test_voice_cli -v`; expect missing adapter/wiring.

- [ ] **Step 3: Implement assembly.** Inject client factory; construct only for configured path; defer physical open until `wake_nod()`; pass adapter and terminal reporter through `LoopAdapters`. Preserve dry-run: no serial open/write.

- [ ] **Step 4: Full offline gate.** Run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`, `.venv/bin/python -m compileall -q src tests`, `git diff --check`, `git status --short`. Expect no real I/O and no commit.

### Task 5: Separate physical proof

**Files:** No source modification required.

- [ ] **Step 1: Obtain fresh physical authorization.** Restate independent 12V, URT-2 3V3, clear airspace and one-time `+5° -> -5° -> torque off` boundary.

- [ ] **Step 2: Check read-only state.** Run `ls -l /dev/serial/by-id/` and `id`; require existing stable path and `dialout` membership.

- [ ] **Step 3: One action only.** Run `wake_nod()` once; record telemetry, two accepted targets, torque-off acknowledgement and user-observed movement. Never retry, loop, upload or alter configuration automatically.

## Plan Self-Review

- Tasks 1–2 cover protocol and stable path; Task 3 covers half-duplex ordering; Task 4 covers lifecycle and offline proof; Task 5 isolates physical evidence.
- No placeholder, fallback port, automatic upload or implicit physical action remains.
- Type flow is `Esp32ServoClient.wake_nod()` -> `WakeMotionAdapter` -> `LoopAdapters.wake_motion` -> `VoiceLoop.wake_motion`.
