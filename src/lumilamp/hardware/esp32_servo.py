"""Safe, one-shot commands for the existing ESP32 STS3215 test firmware."""

from __future__ import annotations

import re
import os
import select
import termios
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class LineTransport(Protocol):
    def write_line(self, line: str) -> None: ...
    def read_line(self, timeout_seconds: float) -> str: ...
    def close(self) -> None: ...


class Esp32ServoError(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


@dataclass(frozen=True)
class ServoTelemetry:
    position: int
    voltage: float
    temperature: int


_TELEMETRY = re.compile(r"position=(\d+) voltage=(\d+(?:\.\d+)?)V temperature=(\d+)C load=-?\d+ current_raw=-?\d+")
_TARGET = re.compile(r"OK: target=\d+ \(relative -?\d+(?:\.\d+)? degrees\)")


class Esp32ServoClient:
    def __init__(self, device_path: Path, *, timeout_seconds: float = 3.0, pause_seconds: float = 0.5, transport: LineTransport | None = None, transport_factory: Callable[[Path], LineTransport] | None = None, pause: Callable[[float], None] = time.sleep) -> None:
        self.device_path = Path(device_path)
        self.timeout_seconds = timeout_seconds
        self.pause_seconds = pause_seconds
        self._transport = transport
        self._transport_factory = transport_factory or _FileLineTransport
        self._pause = pause

    def _command(self, command: str) -> str:
        if self._transport is None:
            self._transport = self._transport_factory(self.device_path)
        self._transport.write_line(command + "\n")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            line = self._transport.read_line(remaining).strip()
            if line and line not in (command, ">") and line != f"> {command}":
                return line

    def _status(self) -> ServoTelemetry:
        line = self._command("status")
        match = _TELEMETRY.fullmatch(line)
        if match is None:
            raise Esp32ServoError("status")
        return ServoTelemetry(int(match.group(1)), float(match.group(2)), int(match.group(3)))

    def _move(self, degrees: int) -> None:
        if not _TARGET.fullmatch(self._command(f"move {degrees}")):
            raise Esp32ServoError("move")

    def wake_nod(self) -> None:
        failure: Esp32ServoError | None = None
        try:
            self._status()
            self._move(5)
            self._pause(self.pause_seconds)
            self._status()
            self._move(-5)
            self._pause(self.pause_seconds)
            self._status()
        except (OSError, TimeoutError, StopIteration) as error:
            failure = Esp32ServoError("status")
            raise failure from error
        except Esp32ServoError as error:
            failure = error
            raise
        finally:
            try:
                if self._command("torque off") != "OK: torque disabled" and failure is None:
                    raise Esp32ServoError("torque_off")
            finally:
                if self._transport is not None:
                    self._transport.close()


class _FileLineTransport:
    def __init__(self, path: Path) -> None:
        self._fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self._fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
        termios.tcflush(self._fd, termios.TCIOFLUSH)
        self._buffer = ""

    def write_line(self, line: str) -> None:
        os.write(self._fd, line.encode("ascii"))

    def read_line(self, timeout_seconds: float) -> str:
        deadline = time.monotonic() + timeout_seconds
        while True:
            if "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                return line.replace("\r", "")
            ready, _, _ = select.select([self._fd], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                raise TimeoutError
            self._buffer += os.read(self._fd, 512).decode("utf-8", errors="replace")

    def close(self) -> None:
        os.close(self._fd)
