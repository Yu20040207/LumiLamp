import unittest

from lumilamp.hardware.mock_bus import MockBus


class MockBusSafetyTests(unittest.TestCase):
    def test_targets_are_rejected_until_simulated_output_is_enabled(self) -> None:
        bus = MockBus()
        bus.connect()

        with self.assertRaisesRegex(RuntimeError, "output is disabled"):
            bus.send_targets({"head_yaw": 10.0})

    def test_emergency_stop_clears_commands_and_locks_output(self) -> None:
        bus = MockBus()
        bus.connect()
        bus.enable_output()
        bus.send_targets({"head_yaw": 10.0})

        bus.emergency_stop()

        self.assertEqual(bus.commands, [])
        with self.assertRaisesRegex(RuntimeError, "emergency stop is active"):
            bus.send_targets({"head_yaw": 0.0})


if __name__ == "__main__":
    unittest.main()
