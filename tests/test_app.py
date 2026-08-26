import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AppDemoTests(unittest.TestCase):
    def test_curious_demo_prints_deterministic_simulation_timeline(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        result = subprocess.run(
            [sys.executable, "-m", "lumilamp.app", "--demo", "curious"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "LumiLamp simulation mode (hardware output disabled)",
                "t=0.00s pose=neutral",
                "t=0.40s pose=prepare",
                "t=1.20s pose=curious",
                "t=1.60s pose=settle",
            ],
        )


if __name__ == "__main__":
    unittest.main()

