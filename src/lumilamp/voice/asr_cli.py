"""One-shot command line interface for live Doubao ASR."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import load_asr_config
from .devices import MicrophoneNotFoundError, discover_alsa_capture_device
from .live_asr import recognize_microphone
from .recorder import LevelConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LumiLamp 单次流式语音识别")
    parser.add_argument("--config", type=Path, default=Path(".env.voice"))
    parser.add_argument("--device", help="覆盖自动发现的 ALSA capture 设备")
    parser.add_argument("--start-threshold", type=float, default=0.02)
    parser.add_argument("--silence-threshold", type=float, default=0.018)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_asr_config(args.config)
        device = args.device or discover_alsa_capture_device()
        levels = LevelConfig(
            start_threshold=args.start_threshold,
            silence_threshold=args.silence_threshold,
            trailing_silence_ms=800,
            max_seconds=10,
        )

        print("请开始说话…")

        def show_partial(text: str) -> None:
            print(f"\r识别中: {text}", end="", flush=True)

        transcript = asyncio.run(
            recognize_microphone(config, device, levels, show_partial)
        )
        print(f"\n识别结果: {transcript}")
        return 0
    except KeyboardInterrupt:
        print("\n识别已取消", file=sys.stderr)
        return 130
    except (MicrophoneNotFoundError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"语音识别失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
