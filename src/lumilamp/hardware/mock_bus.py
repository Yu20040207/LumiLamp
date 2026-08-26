"""In-memory bus that never accesses physical hardware."""

from __future__ import annotations

from collections.abc import Mapping


class MockBus:
    """Record simulated targets while enforcing output safety state."""

    def __init__(self) -> None:
        self.connected = False
        self.output_enabled = False
        self.emergency_stopped = False
        self.commands: list[dict[str, float]] = []

    def connect(self) -> None:
        self.connected = True

    def enable_output(self) -> None:
        if self.emergency_stopped:
            raise RuntimeError("emergency stop is active")
        if not self.connected:
            raise RuntimeError("mock bus is not connected")
        self.output_enabled = True

    def disable_output(self) -> None:
        self.output_enabled = False

    def read_state(self) -> dict[str, bool]:
        return {
            "connected": self.connected,
            "output_enabled": self.output_enabled,
            "emergency_stopped": self.emergency_stopped,
        }

    def send_targets(self, targets: Mapping[str, float]) -> None:
        if self.emergency_stopped:
            raise RuntimeError("emergency stop is active")
        if not self.output_enabled:
            raise RuntimeError("output is disabled")
        self.commands.append(dict(targets))

    def emergency_stop(self) -> None:
        self.commands.clear()
        self.output_enabled = False
        self.emergency_stopped = True

