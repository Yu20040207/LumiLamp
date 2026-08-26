"""Command-line entry point for hardware-free LumiLamp demos."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


_DEMOS = {
    "curious": (
        (0.00, "neutral"),
        (0.40, "prepare"),
        (1.20, "curious"),
        (1.60, "settle"),
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a LumiLamp simulation demo")
    parser.add_argument("--demo", choices=sorted(_DEMOS), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print("LumiLamp simulation mode (hardware output disabled)")
    for timestamp, pose in _DEMOS[args.demo]:
        print(f"t={timestamp:.2f}s pose={pose}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

