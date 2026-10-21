#!/usr/bin/env python3
"""Show recent Marc turn logs (intent / conf / awaiting / steps)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TURNS = ROOT / "data" / "logs" / "turns.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=15, help="Last N turns")
    ap.add_argument("--path", type=Path, default=TURNS)
    args = ap.parse_args()
    if not args.path.exists():
        print(f"No turn log yet at {args.path}")
        return 0
    lines = [ln for ln in args.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for ln in lines[-args.n :]:
        try:
            row = json.loads(ln)
        except Exception:  # noqa: BLE001
            print(ln[:120])
            continue
        steps = row.get("steps") or []
        tools = ",".join(s.get("tool") or "?" for s in steps[:6])
        print(
            f"{row.get('ts', '')[:19]}  "
            f"intent={row.get('intent')} conf={float(row.get('confidence') or 0):.2f} "
            f"src={row.get('source')} await={row.get('awaiting')} "
            f"pending={row.get('pending')} ok={row.get('tool_ok')} "
            f"steps=[{tools}]"
        )
        print(f"  “{(row.get('transcript') or '')[:80]}”")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
