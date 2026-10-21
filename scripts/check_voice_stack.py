#!/usr/bin/env python3
"""Dry-run voice stack import check (no mic required)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from voice import PushToTalk, SpeechToText, TextToSpeech
    from ui import TrayStatus

    stt = SpeechToText()
    tts = TextToSpeech()
    tray = TrayStatus()
    tray.set("idle")
    print("STT model setting:", stt.model_size, stt.device)
    print("TTS voice:", tts.voice)
    print("PTT hotkey class ok:", PushToTalk)

    # openWakeWord (active IdleWake path) — not Porcupine
    from voice.wake_listen import WakeListener

    wl = WakeListener(on_wake=None, threshold=0.4)
    wl._init_oww()
    if wl._use_oww and wl._model is not None:
        print("Wake: openWakeWord hey_jarvis OK")
    else:
        print("Wake: openWakeWord unavailable (STT hey marc fallback only)")
    print("voice stack import OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
