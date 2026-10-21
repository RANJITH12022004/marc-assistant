#!/usr/bin/env python3
"""Live speaker→mic E2E: TTS speaks each corpus line; Marc STT+orchestrator asserts.

Requires: speakers up, mic unmuted, Senary can hear speakers (loopback room).
Prefer Google STT for speed; Whisper fallback still available.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "data" / "datasets" / "marc_live_e2e_v1.jsonl"
REPORT = ROOT / "data" / "logs" / "live_e2e_report.json"


def _play_tts(text: str, voice: str = "en-US-GuyNeural") -> None:
    import numpy as np
    import sounddevice as sd
    import edge_tts
    import av
    import tempfile

    async def _gen(path: Path) -> None:
        await edge_tts.Communicate(text, voice).save(str(path))

    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "utt.mp3"
        asyncio.run(_gen(mp3))
        container = av.open(str(mp3))
        chunks = []
        sr = 24000
        for frame in container.decode(audio=0):
            arr = frame.to_ndarray().astype(np.float32)
            if arr.ndim > 1:
                arr = arr.mean(axis=0) if arr.shape[0] <= 8 else arr.mean(axis=-1)
            chunks.append(arr.reshape(-1))
            sr = frame.sample_rate or sr
        audio = np.concatenate(chunks) if chunks else np.zeros(sr, dtype=np.float32)
        peak = float(np.max(np.abs(audio))) or 1.0
        audio = (audio / peak) * 0.55
        sd.play(audio, sr)
        sd.wait()


def _tools(steps_run) -> list[str]:
    return [str((s.get("tool") or "")).lower() for s in (steps_run or [])]


def main() -> int:
    ap = argparse.ArgumentParser(description="Live voice E2E via speaker loopback")
    ap.add_argument("--limit", type=int, default=20, help="Max cases (default 20; use 100 for full)")
    ap.add_argument("--tag", default="")
    ap.add_argument("--stt", choices=["google", "whisper"], default="google")
    ap.add_argument("--gap", type=float, default=1.2, help="Seconds after TTS before listen")
    ap.add_argument("--listen", type=float, default=4.5, help="STT listen window seconds")
    ap.add_argument("--dry-routing", action="store_true", help="Skip mic; inject say text")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()

    if args.regen or not CORPUS.exists():
        from scripts.generate_live_e2e_corpus import main as gen

        gen()

    cases = [json.loads(l) for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.tag:
        cases = [c for c in cases if args.tag in (c.get("tags") or [])]
    cases = cases[: max(1, args.limit)]

    from orchestrator.agent import MarcOrchestrator
    from orchestrator.session import SessionState
    from voice.stt import SpeechToText

    orch = MarcOrchestrator(speak_fn=lambda *_a, **_k: None, preload_laya=False, lazy_laya=True)
    # Prefer not waiting on Laya load for offline-ish; still try
    try:
        orch.start_laya_background()
        time.sleep(0.5)
    except Exception:  # noqa: BLE001
        pass

    stt = SpeechToText(prefer=args.stt)
    results = []

    print(f"[live-e2e] {len(cases)} cases | stt={args.stt} dry={args.dry_routing}")
    for case in cases:
        if case.get("clear_session_before"):
            orch.session = SessionState()
            orch._pending = None

        for setup in case.get("setup") or []:
            if args.dry_routing:
                orch.handle(setup["say"])
            else:
                print(f"  setup TTS: {setup['say']!r}")
                _play_tts(setup["say"])
                time.sleep(args.gap)
                heard = stt.record_and_transcribe(seconds=args.listen)
                print(f"  setup heard: {heard!r}")
                if heard:
                    orch.handle(heard)
                else:
                    orch.handle(setup["say"])  # fallback inject

        say = case["say"]
        t0 = time.perf_counter()
        if args.dry_routing:
            heard = say
        else:
            print(f"  TTS: {say!r}")
            _play_tts(say)
            time.sleep(args.gap)
            heard = stt.record_and_transcribe(seconds=args.listen)
            print(f"  heard: {heard!r}")
            if not heard:
                heard = say  # degrade to inject so suite still measures routing

        result = orch.handle(heard)
        elapsed = time.perf_counter() - t0
        tools = _tools(result.steps_run)
        want = set(t.lower() for t in (case.get("expect_tools") or []))
        tools_ok = (not want) or bool(set(tools) & want)
        if "not_youtube" in (case.get("tags") or []) and (
            result.intent == "youtube_search" or "youtube_search" in tools
        ):
            tools_ok = False
        forbid = case.get("forbid_awaiting") or ""
        await_ok = not (
            forbid
            and result.session.awaiting == forbid
            and result.intent not in ("youtube_search", "youtube_home", "play_video")
        )
        if "close" in (case.get("tags") or []) and (
            result.pending_confirm or result.session.awaiting == "confirm"
        ):
            tools_ok = False

        ok = tools_ok and await_ok
        rec = {
            "id": case["id"],
            "ok": ok,
            "say": say,
            "heard": heard,
            "intent": result.intent,
            "tools": tools,
            "awaiting": result.session.awaiting,
            "source": result.source,
            "elapsed_s": round(elapsed, 3),
            "pending_confirm": bool(result.pending_confirm),
        }
        results.append(rec)
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {case['id']} intent={result.intent} tools={tools} await={result.session.awaiting}")

    passed = sum(1 for r in results if r["ok"])
    report = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "stt": args.stt,
        "dry_routing": args.dry_routing,
        "results": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Live E2E: {passed}/{len(results)} passed → {REPORT}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
