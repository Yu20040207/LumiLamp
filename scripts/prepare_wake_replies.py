#!/usr/bin/env python3
"""Explicitly prepare the local wake-reply WAV cache."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from lumilamp.voice.config import load_voice_config
from lumilamp.voice.tts import synthesize_to_wav
from lumilamp.voice.wake_cache import (
    NETWORK_ERROR_REPLY,
    WAKE_REPLIES,
    WakeReplyCache,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, metavar="PATH")
    parser.add_argument("--output-dir", required=True, type=Path, metavar="PATH")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    synthesize: Callable[[str, Path], None] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if not args.config.is_file():
        print("error: --config must name a readable file", file=sys.stderr)
        return 2
    if args.output_dir.exists() and not args.output_dir.is_dir():
        print("error: --output-dir must name a directory", file=sys.stderr)
        return 2

    try:
        config = load_voice_config(args.config)
        cache = WakeReplyCache(
            args.output_dir,
            resource_id=config.tts_resource_id,
        )
        if synthesize is None:
            synthesize = lambda text, path: synthesize_to_wav(config, text, path)
        cache.prepare(synthesize)
        cache.validate()
    except (OSError, ValueError, RuntimeError):
        print("failure: wake reply cache was not prepared", file=sys.stderr)
        return 1

    for text in (*WAKE_REPLIES, NETWORK_ERROR_REPLY):
        print(f"ready: {cache.path_for(text)}")
    print("success: wake reply cache prepared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
