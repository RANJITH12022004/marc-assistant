#!/usr/bin/env python3
"""Marc laptop CLI — text REPL and voice modes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_orchestrator(speak: bool, preload_laya: bool):
    from orchestrator import MarcOrchestrator
    from voice import TextToSpeech

    tts = TextToSpeech() if speak else None

    def speak_fn(msg: str) -> None:
        if tts:
            tts.speak(msg)
        else:
            print(f"Marc: {msg}")

    def confirm_fn(msg: str) -> bool:
        print(msg)
        ans = input("Confirm [y/N]: ").strip().lower()
        return ans in ("y", "yes")

    return MarcOrchestrator(preload_laya=preload_laya, confirm_fn=confirm_fn, speak_fn=speak_fn)


def cmd_repl(args: argparse.Namespace) -> int:
    from orchestrator.session import SessionState

    orch = build_orchestrator(speak=args.speak, preload_laya=not args.no_laya)
    orch.session = SessionState()
    print("Marc CLI (session memory on). Type a command (or 'quit' / 'sleep').")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        result = orch.handle(line)
        print(
            f"[{result.source}] intent={result.intent} conf={result.confidence:.2f} "
            f"continue={result.should_continue} spoken={result.spoken!r}"
        )
        if not result.should_continue:
            print("(session sleeping — say anything to continue in voice mode)")
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    orch = build_orchestrator(speak=args.speak, preload_laya=not args.no_laya)
    result = orch.handle(args.text)
    print(
        f"[{result.source}] intent={result.intent} conf={result.confidence:.2f} "
        f"planner={result.used_planner}"
    )
    print(result.reply)
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    from voice.loop import run_voice
    from settings import settings

    use_laya = bool(getattr(args, "laya", False)) and not args.no_laya
    wake_th = getattr(args, "wake_threshold", None)
    if wake_th is None:
        wake_th = settings.wake_threshold
    return run_voice(
        seconds=getattr(args, "seconds", 5.0),
        no_laya=not use_laya,
        use_hotkey=bool(getattr(args, "enable_hotkey", False)),
        tray=bool(getattr(args, "tray", False)),
        stt_prefer=getattr(args, "stt", "google"),
        island=not bool(getattr(args, "no_island", False)),
        listen_gap=float(getattr(args, "listen_gap", 0.6)),
        followup_seconds=float(getattr(args, "followup_seconds", 12.0)),
        wake_threshold=float(wake_th),
        wake_word=str(getattr(args, "wake_word", "jarvis") or "jarvis"),
        debug_turns=bool(getattr(args, "debug_turns", False)),
    )


def cmd_smoke(args: argparse.Namespace) -> int:
    """Phase 0 smoke: load Laya from SD card and classify sample phrases."""
    from laya_router import MarcLayaRouter

    router = MarcLayaRouter(preload=True)
    samples = [
        "open Chrome",
        "search YouTube for lo-fi beats",
        "type hello world",
        "what time is it",
        "delete everything on disk",
    ]
    for s in samples:
        r = router.classify(s)
        print(f"{s!r:45} → {r.intent:14} conf={r.confidence:.2f} src={r.source}")
    return 0


def cmd_google_auth(args: argparse.Namespace) -> int:
    """OAuth for Gmail + Calendar + Drive (Desktop client JSON in data/gmail_credentials.json)."""
    from tools.google_oauth import authorize

    result = authorize(
        readonly=bool(getattr(args, "readonly", False)),
        force=bool(getattr(args, "force", False)),
    )
    print(result.message)
    return 0 if result.ok else 1


def cmd_gmail_auth(args: argparse.Namespace) -> int:
    """Alias for google-auth (kept for older docs/scripts)."""
    return cmd_google_auth(args)


def main(argv: Optional[list] = None) -> int:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--no-laya", action="store_true", help="Skip Laya load (rules only)")
    parent.add_argument("--speak", action="store_true", help="Speak replies via TTS")

    p = argparse.ArgumentParser(
        description="Marc — laptop Jarvis/Edith assistant",
        parents=[parent],
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("repl", help="Interactive text REPL", parents=[parent])
    once = sub.add_parser("once", help="Run one text command", parents=[parent])
    once.add_argument("text", help="Utterance")
    voice = sub.add_parser("voice", help="Continuous voice session + Dynamic Island", parents=[parent])
    voice.add_argument("--seconds", type=float, default=6.0, help="Listen window seconds")
    voice.add_argument("--followup-seconds", type=float, default=12.0, help="Listen window while awaiting pick/slot")
    voice.add_argument("--listen-gap", type=float, default=0.15, help="Pause after action before re-listen")
    voice.add_argument("--tray", action="store_true", help="Legacy tray badge")
    voice.add_argument("--no-island", action="store_true", help="Disable Dynamic Island UI")
    voice.add_argument("--laya", action="store_true", help="Load Laya (slower)")
    voice.add_argument("--enable-hotkey", action="store_true", help="Ctrl+Shift+M wakes from sleep")
    voice.add_argument(
        "--stt",
        choices=["google", "whisper"],
        default="google",
        help="STT backend (google=free no login)",
    )
    voice.add_argument(
        "--wake-word",
        default="jarvis",
        help="Wake label hint (OWW uses hey_jarvis; STT also accepts hey marc)",
    )
    voice.add_argument(
        "--wake-threshold",
        type=float,
        default=0.25,
        help="openWakeWord score threshold (default 0.25; env MARC_WAKE_THRESHOLD)",
    )
    voice.add_argument(
        "--debug-turns",
        action="store_true",
        help="Print one-line turn cards after each command",
    )
    sub.add_parser("smoke", help="Laya SD-card smoke test", parents=[parent])
    for name, help_txt in (
        ("google-auth", "Authorize Gmail + Calendar + Drive (OAuth Desktop)"),
        ("gmail-auth", "Alias for google-auth"),
    ):
        gauth = sub.add_parser(name, help=help_txt)
        gauth.add_argument(
            "--readonly",
            action="store_true",
            help="Request readonly scopes only (no send / no create event)",
        )
        gauth.add_argument(
            "--force",
            action="store_true",
            help="Delete saved token and re-consent (needed after adding Calendar/Drive)",
        )

    args = p.parse_args(argv)
    if args.cmd == "once":
        return cmd_once(args)
    if args.cmd == "voice":
        return cmd_voice(args)
    if args.cmd == "smoke":
        return cmd_smoke(args)
    if args.cmd in ("google-auth", "gmail-auth"):
        return cmd_google_auth(args)
    # default REPL
    if not hasattr(args, "no_laya"):
        args.no_laya = False
    if not hasattr(args, "speak"):
        args.speak = False
    return cmd_repl(args)


if __name__ == "__main__":
    raise SystemExit(main())
