#!/usr/bin/env python3
"""Generate Marc intent dataset v4 (+ RLCD) with mail / YouTube / multi-step labels.

Usage:
  python scripts/generate_intent_dataset_v4.py --per-intent 800 --holdout 100
Retrain (off-box / Colab): use data/datasets/kaggle_bundle/marc_intents_v4_rlcd.jsonl
then copy checkpoint to LAYA_MARC_INTENT_PATH and set marc_finetune_meta.json trained=true.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laya_router.intents import INTENT_LABELS, marc_intent_questions  # noqa: E402

V4_TEMPLATES: Dict[str, List[str]] = {
    "youtube_search": [
        "search youtube for {query}",
        "find {query} on youtube",
        "youtube search {query}",
        "search for {query} on youtube",
        "open youtube and search for {query}",
        "look up {query} on youtube",
    ],
    "youtube_media": [
        "next video",
        "previous video",
        "switch to the next video",
        "skip this video",
        "pause the video",
        "play the video",
        "resume youtube",
    ],
    "play_video": [
        "play the first",
        "play the second",
        "play the third",
        "open the first result",
        "play the first video",
        "click the first",
    ],
    "web_navigate": [
        "open youtube",
        "go to youtube",
        "open gmail",
        "go to gmail",
        "open mail",
    ],
    "mail_search": [
        "search mail for {query}",
        "search email for {query}",
        "find emails about {query}",
        "search inbox for {query}",
        "gmail search {query}",
    ],
    "mail_summarize": [
        "summarize my email",
        "summarize my emails",
        "summarize unread",
        "summarize my inbox",
        "read my emails",
        "summary of my mail",
        "what's in my inbox",
    ],
    "mail_compose": [
        "send email to {name} saying {text}",
        "email {name} about {text}",
        "mail {name} that {text}",
        "send an email to {name} saying {text}",
        "compose email to {name} saying {text}",
    ],
    "whatsapp_send": [
        "message {name} on whatsapp {text}",
        "send whatsapp to {name} saying {text}",
        "whatsapp {name} {text}",
        "copy that to whatsapp {name}",
    ],
    "multi_step": [
        "open browser and search for youtube and on youtube search for {query}",
        "open chrome then search youtube for {query}",
        "open browser and open youtube and search for {query}",
        "open notepad and type {text}",
        "open chrome plus gmail",
        "close camera and spotify",
        "open youtube and search for {query} and play the first",
    ],
    # Keep legacy intents lightly sampled so v4 stays compatible
    "open_app": ["open {app}", "launch {app}", "start {app}", "open the browser"],
    "close_app": ["close {app}", "quit {app}"],
    "focus_window": ["focus {app}", "switch to {app}"],
    "web_search": ["google {query}", "search for {query}", "look up {query}"],
    "type_text": ["type {text}", "write {text}"],
    "hotkey": ["copy", "paste", "fullscreen", "new tab", "screenshot"],
    "file_find": ["find the file {query}"],
    "file_open": ["open the file {query}"],
    "system_status": ["what time is it", "battery level"],
    "volume_media": ["mute", "volume up", "next track"],
    "clipboard": ["read the clipboard"],
    "settings": ["open wifi settings", "open settings"],
    "clarify": ["do the thing", "that one", "hmm"],
    "chat": ["how are you", "what can you do", "who are you"],
    "refuse": [
        "format the disk",
        "delete everything",
        "send all my emails",
        "wipe the drive",
        "rm -rf /",
    ],
}

APPS = ["chrome", "notepad", "spotify", "whatsapp", "camera", "calculator", "brave"]
QUERIES = ["samsung", "music", "lo-fi", "python", "news", "weather", "hangover", "cats"]
NAMES = ["Alex", "Mom", "Ranjith", "Sam", "Priya"]
TEXTS = ["hello", "hi there", "on my way", "thanks", "meeting at five"]


def _fill(tmpl: str) -> str:
    return (
        tmpl.replace("{app}", random.choice(APPS))
        .replace("{query}", random.choice(QUERIES))
        .replace("{name}", random.choice(NAMES))
        .replace("{text}", random.choice(TEXTS))
        .replace("{n}", str(random.randint(10, 90)))
    )


def _scores(intent: str) -> Dict[str, float]:
    needs_planner = 0.85 if intent in ("multi_step", "mail_compose", "clarify", "chat") else 0.15
    needs_confirm = 0.9 if intent in ("mail_compose", "whatsapp_send", "close_app", "refuse") else 0.1
    is_multi = 0.95 if intent == "multi_step" else 0.1
    destructive = 0.95 if intent == "refuse" else (0.4 if intent == "mail_compose" else 0.05)
    return {
        "needs_planner": needs_planner,
        "needs_confirm": needs_confirm,
        "is_multi_step": is_multi,
        "destructive": destructive,
    }


def make_row(intent: str, transcript: str) -> Dict[str, Any]:
    qs = marc_intent_questions()
    sc = _scores(intent)
    gold = {
        "intent": {"choice": intent, "confidence": 0.92},
        "needs_planner": {"noul": sc["needs_planner"]},
        "needs_confirm": {"noul": sc["needs_confirm"]},
        "is_multi_step": {"noul": sc["is_multi_step"]},
        "destructive": {"noul": sc["destructive"]},
    }
    return {
        "state": {"transcript": transcript},
        "questions": qs,
        "gold": gold,
        "meta": {"intent": intent, "dataset": "v4"},
    }


def make_rlcd(row: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten for RLCD trainers that expect stringified state/questions/gold."""
    return {
        "state": json.dumps(row["state"], ensure_ascii=False),
        "questions": json.dumps(row["questions"], ensure_ascii=False),
        "gold": json.dumps(row["gold"], ensure_ascii=False),
        "meta": row.get("meta") or {},
    }


def generate(per_intent: int, holdout: int, seed: int = 42) -> None:
    random.seed(seed)
    out_dir = ROOT / "data" / "datasets"
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / "kaggle_bundle"
    bundle.mkdir(parents=True, exist_ok=True)

    train: List[Dict[str, Any]] = []
    hold: List[Dict[str, Any]] = []

    for intent in INTENT_LABELS:
        tmpls = V4_TEMPLATES.get(intent) or ["{query}"]
        for i in range(per_intent):
            tmpl = tmpls[i % len(tmpls)]
            row = make_row(intent, _fill(tmpl))
            if i < holdout:
                hold.append(row)
            else:
                train.append(row)

    random.shuffle(train)
    random.shuffle(hold)

    train_path = out_dir / "marc_intents_v4.jsonl"
    hold_path = out_dir / "marc_intents_v4_holdout.jsonl"
    rlcd_path = bundle / "marc_intents_v4_rlcd.jsonl"
    rlcd_hold = bundle / "marc_intents_v4_holdout_rlcd.jsonl"

    def write_jsonl(path: Path, rows: List[Dict[str, Any]], rlcd: bool = False) -> None:
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(make_rlcd(r) if rlcd else r, ensure_ascii=False) + "\n")

    write_jsonl(train_path, train)
    write_jsonl(hold_path, hold)
    write_jsonl(rlcd_path, train, rlcd=True)
    write_jsonl(rlcd_hold, hold, rlcd=True)

    meta = {
        "dataset": "marc_intents_v4",
        "intents": list(INTENT_LABELS.keys()),
        "train_rows": len(train),
        "holdout_rows": len(hold),
        "trained": False,
        "note": "Finetune with Laya RLCD on marc_intents_v4_rlcd.jsonl; set trained true after ship.",
    }
    (out_dir / "marc_intents_v4_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"Wrote {train_path} ({len(train)} rows)")
    print(f"Wrote {hold_path} ({len(hold)} rows)")
    print(f"Wrote {rlcd_path}")
    print(f"Wrote {rlcd_hold}")
    print("Retrain: use Colab/Kaggle on v4 RLCD, copy weights to LAYA_MARC_INTENT_PATH")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-intent", type=int, default=1200)
    ap.add_argument("--holdout", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    generate(args.per_intent, args.holdout, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
