#!/usr/bin/env python3
"""Mine misroutes + turn logs into v5 intent candidate rows for the next RLCD cycle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laya_router.clause_plan import parse_clause_plan  # noqa: E402
from laya_router.intents import INTENT_LABELS, marc_intent_questions  # noqa: E402
from laya_router.rules import rule_classify  # noqa: E402

LOGS = ROOT / "data" / "logs"
OUT = ROOT / "data" / "datasets" / "marc_intents_v5_candidates.jsonl"


def _guess_intent(transcript: str, note: str = "") -> str:
    cplan = parse_clause_plan(transcript)
    if cplan and cplan.get("intent"):
        intent = cplan["intent"]
        if intent in INTENT_LABELS:
            return intent
        if intent.startswith("youtube"):
            return "youtube_search" if "youtube_search" in INTENT_LABELS else "web_search"
        if intent.startswith("mail"):
            return "mail_search" if "mail_search" in INTENT_LABELS else "clarify"
    intent, conf = rule_classify(transcript)
    if conf >= 0.5 and intent in INTENT_LABELS:
        return intent
    low = (transcript or "").lower()
    if "whatsapp" in low:
        return "whatsapp_send"
    if "email" in low or "mail" in low:
        if "summar" in low:
            return "mail_summarize"
        if "send" in low:
            return "mail_compose"
        return "mail_search"
    if "remind" in low or "alarm" in low:
        return "clarify"  # until set_reminder in labels
    if note and "fail" in note:
        return "clarify"
    return intent if intent in INTENT_LABELS else "clarify"


def _row(transcript: str, intent: str, source: str) -> Dict[str, Any]:
    return {
        "state": {"transcript": transcript},
        "questions": marc_intent_questions(),
        "gold": {
            "intent": {"choice": intent, "confidence": 0.8},
            "needs_planner": {"noul": 0.7 if intent in ("multi_step", "clarify") else 0.2},
            "needs_confirm": {"noul": 0.8 if intent in ("mail_compose", "whatsapp_send") else 0.1},
            "is_multi_step": {"noul": 0.9 if intent == "multi_step" else 0.1},
            "destructive": {"noul": 0.9 if intent == "refuse" else 0.05},
        },
        "meta": {"intent": intent, "dataset": "v5_candidates", "mined_from": source},
    }


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows


def mine(limit: int = 500) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for path, source in (
        (LOGS / "misroutes.jsonl", "misroutes"),
        (LOGS / "turns.jsonl", "turns"),
    ):
        for row in _read_jsonl(path):
            transcript = (row.get("transcript") or "").strip()
            if not transcript or len(transcript) < 2:
                continue
            key = transcript.lower()
            if key in seen:
                continue
            # Prefer failures / low conf / clarify
            conf = float(row.get("confidence") or 0)
            intent_logged = row.get("intent") or ""
            tool_ok = row.get("tool_ok", True)
            if source == "turns" and tool_ok and conf >= 0.85 and intent_logged not in (
                "clarify",
                "",
            ):
                continue
            seen.add(key)
            guess = _guess_intent(transcript, note=row.get("note") or "")
            out.append(_row(transcript, guess, source))
            if len(out) >= limit:
                return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = mine(args.limit)
    print(f"Mined {len(rows)} candidates")
    if args.dry_run:
        for r in rows[:5]:
            print(" ", r["state"]["transcript"][:60], "→", r["meta"]["intent"])
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {args.out}")
    print("Curate then merge into next RLCD train.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
