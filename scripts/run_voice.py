#!/usr/bin/env python3
"""CLI entry for Marc voice."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice.loop import run_voice  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Marc voice — free STT/TTS, no login")
    p.add_argument("--seconds", type=float, default=5.0)
    p.add_argument("--laya", action="store_true", help="Load Laya (slower)")
    p.add_argument("--hotkey", action="store_true", help="Also enable Ctrl+Shift+M")
    p.add_argument("--tray", action="store_true")
    p.add_argument(
        "--stt",
        choices=["google", "whisper"],
        default="google",
        help="Primary STT backend (default: google free)",
    )
    args = p.parse_args(argv)
    return run_voice(
        seconds=args.seconds,
        no_laya=not args.laya,
        use_hotkey=args.hotkey,
        tray=args.tray,
        stt_prefer=args.stt,
    )


if __name__ == "__main__":
    raise SystemExit(main())
