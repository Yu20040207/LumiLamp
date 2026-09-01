import unittest
from pathlib import Path

from lumilamp.hardware.esp32_servo import Esp32ServoClient, Esp32ServoError


class FakeTransport:
    def __init__(self, replies: list[str]) -> None:
        self.replies = iter(replies)
        self.writes: list[str] = []
        self.closed = False

    def write_line(self, line: str) -> None:
        self.writes.append(line)

    def read_line(self, _: float) -> str:
        return next(self.replies)

    def close(self) -> None:
        self.closed = True


class Esp32ServoClientTests(unittest.TestCase):
    def test_client_does_not_open_device_until_motion_is_requested(self) -> None:
        opened: list[Path] = []

        def factory(path: Path):
            opened.append(path)
            return FakeTransport([
                "position=3213 voltage=12.3V temperature=35C load=0 current_raw=0",
                "OK: target=3270 (relative 5.00 degrees)",
                "position=3267 voltage=12.3V temperature=35C load=-32 current_raw=1",
                "OK: target=3210 (relative -5.00 degrees)",
                "position=3210 voltage=12.3V temperature=35C load=0 current_raw=0",
                "OK: torque disabled",
            ])

        client = Esp32ServoClient(Path("/dev/serial/by-id/fake"), transport_factory=factory, pause=lambda _: None)
        self.assertEqual(opened, [])
        client.wake_nod()
        self.assertEqual(opened, [Path("/dev/serial/by-id/fake")])

    def test_wake_nod_uses_verified_command_sequence_then_turns_torque_off(self) -> None:
        transport = FakeTransport([
            "position=3213 voltage=12.3V temperature=35C load=0 current_raw=0",
            "OK: target=3270 (relative 5.00 degrees)",
            "position=3267 voltage=12.3V temperature=35C load=-32 current_raw=1",
            "OK: target=3210 (relative -5.00 degrees)",
            "position=3210 voltage=12.3V temperature=35C load=0 current_raw=0",
            "OK: torque disabled",
        ])
        client = Esp32ServoClient(Path("/dev/serial/by-id/fake"), transport=transport, pause=lambda _: None)

        client.wake_nod()

        self.assertEqual(transport.writes, ["status\n", "move 5\n", "status\n", "move -5\n", "status\n", "torque off\n"])
        self.assertTrue(transport.closed)

    def test_wake_nod_ignores_firmware_command_echoes_and_prompts(self) -> None:
        transport = FakeTransport([
            "status", "> ", "position=3213 voltage=12.3V temperature=35C load=0 current_raw=0",
            "> move 5", "OK: target=3270 (relative 5.00 degrees)",
            "status", "position=3267 voltage=12.3V temperature=35C load=-32 current_raw=1",
            "> move -5", "OK: target=3210 (relative -5.00 degrees)",
            "> status", "position=3210 voltage=12.3V temperature=35C load=0 current_raw=0",
            "torque off", "OK: torque disabled",
        ])
        client = Esp32ServoClient(Path("/dev/serial/by-id/fake"), transport=transport, pause=lambda _: None)

        client.wake_nod()

        self.assertTrue(transport.closed)

    def test_rejected_initial_status_skips_motion_and_attempts_torque_off(self) -> None:
        transport = FakeTransport(["ERROR: no valid feedback from servo ID 1", "OK: torque disabled"])
        client = Esp32ServoClient(Path("/dev/serial/by-id/fake"), transport=transport, pause=lambda _: None)

        with self.assertRaises(Esp32ServoError) as raised:
            client.wake_nod()

        self.assertEqual(raised.exception.stage, "status")
        self.assertEqual(transport.writes, ["status\n", "torque off\n"])
        self.assertTrue(transport.closed)
