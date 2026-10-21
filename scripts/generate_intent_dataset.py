#!/usr/bin/env python3
"""Generate synthetic Marc intent dataset for Laya fine-tuning (config-driven v2)."""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laya_router.intents import INTENT_LABELS, marc_intent_questions  # noqa: E402
from laya_router.synonyms import all_app_names  # noqa: E402
from settings import settings  # noqa: E402

TEMPLATES: Dict[str, List[str]] = {
    "open_app": [
        "open {app}",
        "launch {app}",
        "start {app}",
        "fire up {app}",
        "please open {app}",
        "can you open {app}",
        "bring up {app}",
        "run {app}",
        "hey marc open {app}",
        "remark open {app}",
        "open {app} open {app}",
    ],
    "close_app": [
        "close {app}",
        "quit {app}",
        "exit {app}",
        "kill {app}",
        "please close {app}",
    ],
    "focus_window": [
        "focus {app}",
        "switch to {app}",
        "go to {app}",
        "bring {app} to front",
        "please switch to {app}",
    ],
    "web_search": [
        "search for {query}",
        "google {query}",
        "look up {query}",
        "search youtube for {query}",
        "find {query} on youtube",
        "search {query} on google",
        "youtube search {query}",
        "search for {query} on youtube",
        "google search {query}",
        "search on google for {query}",
        "find {query} on google",
        "look up {query} on google",
        "browser search {query}",
        "search the web for {query}",
    ],
    "type_text": [
        "type {text}",
        "write {text}",
        "dictate {text}",
        "enter {text}",
        "type '{text}'",
        "please type {text}",
    ],
    "hotkey": [
        "copy",
        "paste",
        "cut",
        "undo",
        "redo",
        "save",
        "press copy",
        "hit paste",
        "take a screenshot",
        "press screenshot",
        "select all",
        "new tab",
        "close tab",
        "fullscreen",
        "full screen",
        "make it full screen",
        "snap left",
        "snap right",
        "maximize",
        "minimize",
        "lock",
        "show desktop",
        "task manager",
        "emoji",
        "task view",
        "refresh",
        "find",
        "new window",
        "address bar",
        "close window",
        "new desktop",
        "switch desktop left",
        "switch desktop right",
        "open explorer",
        "mute",
        "volume up",
        "volume down",
    ],
    "file_find": [
        "find the file {query}",
        "locate file {query}",
        "search for the file {query}",
        "find file {query}",
    ],
    "file_open": [
        "open the file {query}",
        "open file {query}",
        "please open the file {query}",
    ],
    "system_status": [
        "what time is it",
        "what's the time",
        "battery level",
        "what's my battery",
        "what is the date",
        "tell me the time",
    ],
    "volume_media": [
        "mute",
        "unmute",
        "volume up",
        "volume down",
        "set volume to {n}",
        "pause music",
        "play music",
        "next track",
        "previous track",
    ],
    "clipboard": [
        "read the clipboard",
        "what's on the clipboard",
        "show clipboard",
        "copy this to clipboard {text}",
    ],
    "settings": [
        "open settings",
        "open windows settings",
        "system settings",
        "open wifi settings",
        "open bluetooth settings",
        "open display settings",
        "wifi settings",
    ],
    "clarify": [
        "do the thing",
        "you know",
        "make it work",
        "that one",
        "hmm",
        "the other one",
        "yeah that",
        "Browser",
        "link",
        "result",
        "click",
        "Mahindra Tractor gadi",
    ],
    "chat": [
        "how are you",
        "tell me a joke",
        "what can you do",
        "who are you",
        "why is the sky blue",
        "what is marc",
        "are you listening",
    ],
    "refuse": [
        "format the disk",
        "delete everything",
        "wipe the drive",
        "shutdown now and delete system32",
        "send all my passwords",
        "rm -rf /",
    ],
}

# Extra utterances labeled as open_app / hotkey / web_search (compound-covered at runtime)
EXTRA_BY_INTENT: Dict[str, List[str]] = {
    "open_app": [
        "open youtube",
        "open camera",
        "open the camera",
        "launch camera",
        "open photos",
        "open the picture",
        "open pictures",
        "start the camera",
        "open browser",
        "open google",
    ],
    "web_search": [
        "open the first result",
        "open the second result",
        "open the first",
        "play the first",
        "play the second",
        "play the third",
        "click the first link",
        "open the first link",
    ],
    "hotkey": [
        "take a photo",
        "click the picture",
        "take a picture",
        "start recording",
        "switch to video",
        "go to video mode",
        "go to barcode mode",
        "barcode mode",
        "switch to photo mode",
        "stop recording",
    ],
}

QUERIES = [
    "lo-fi beats",
    "weather today",
    "python tutorial",
    "nearest cafe",
    "stock market news",
    "how to boil an egg",
    "music",
    "hangover",
    "coding interview",
    "windows tips",
    "best pasta recipe",
    "local news",
]

TEXTS = [
    "hello world",
    "meeting at 5",
    "thanks",
    "on my way",
    "see you soon",
    "please review this",
    "ok",
]

FILE_QUERIES = [
    "report.pdf",
    "budget.xlsx",
    "notes.txt",
    "resume.docx",
    "photo.jpg",
    "invoice",
    "presentation",
]

WAKE_PREFIXES = ["", "hey marc ", "hey jarvis ", "remark ", "ok marc ", ""]


def _load_apps() -> List[str]:
    names = all_app_names()
    if names:
        return names
    return ["chrome", "notepad", "calculator", "explorer", "vscode", "cursor"]


def _load_hotkeys() -> List[str]:
    path = settings.hotkeys_config
    if not path.exists():
        return list(TEMPLATES["hotkey"])
    data = json.loads(path.read_text(encoding="utf-8"))
    # Prefer human-speakable actions (skip internal camera_* unless useful)
    out = []
    for k in data.keys():
        if k.startswith("camera_"):
            continue
        out.append(k)
        out.append(f"press {k}")
        out.append(f"hit {k}")
    return out or list(TEMPLATES["hotkey"])


def _needs_planner(intent: str) -> bool:
    return intent in ("chat", "clarify", "file_find", "file_open", "clipboard")


def _destructive(intent: str) -> bool:
    return intent == "refuse"


def make_example(intent: str, transcript: str, dataset: str = "v3") -> Dict[str, Any]:
    questions = marc_intent_questions()
    return {
        "state": {"transcript": transcript},
        "questions": questions,
        "answers": {
            "intent": {"choice": intent},
            "needs_planner": {"noul": 1.0 if _needs_planner(intent) else 0.0},
            "destructive": {"noul": 1.0 if _destructive(intent) else 0.0},
        },
        "meta": {"intent": intent, "dataset": dataset},
    }


def _load_misroutes() -> List[Dict[str, Any]]:
    path = ROOT / "data" / "logs" / "misroutes.jsonl"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    # Hard labels for known voice fails → better intents for v3
    remap = {
        "browser": ("open_app", "open chrome"),
        "click the picture": ("hotkey", "take a photo"),
        "click": ("clarify", "click"),
        "open the picture": ("open_app", "open photos"),
        "link": ("web_search", "open the first link"),
        "result": ("web_search", "open the first result"),
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = (row.get("transcript") or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in remap:
            intent, phrase = remap[key]
            rows.append(make_example(intent, phrase))
            rows.append(make_example(intent, t))
        else:
            # Keep as clarify so Laya learns short junk → clarify
            rows.append(make_example("clarify", t))
    return rows


def _fill(
    tmpl: str,
    rng: random.Random,
    apps: Sequence[str],
    hotkeys: Sequence[str],
) -> str:
    qpool = FILE_QUERIES if "file" in tmpl.lower() else QUERIES
    return (
        tmpl.format(
            app=rng.choice(apps),
            query=rng.choice(qpool),
            text=rng.choice(TEXTS),
            n=rng.choice([10, 20, 30, 40, 50, 70, 100]),
        )
        .replace("  ", " ")
        .strip()
    )


def synthesize(
    n: int,
    seed: int = 7,
    from_config: bool = True,
    stratified: bool = True,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    apps = _load_apps() if from_config else [
        "chrome", "edge", "firefox", "notepad", "calculator", "explorer",
        "vscode", "cursor", "spotify", "terminal", "paint", "brave", "youtube", "gmail", "camera",
    ]
    hotkeys = _load_hotkeys() if from_config else list(TEMPLATES["hotkey"])
    intents = list(INTENT_LABELS.keys())
    examples: List[Dict[str, Any]] = []

    if stratified:
        per = max(1, n // len(intents))
        for intent in intents:
            templates = list(TEMPLATES[intent])
            templates = list(dict.fromkeys(templates + EXTRA_BY_INTENT.get(intent, [])))
            if intent == "hotkey":
                # Mix static templates with config hotkeys as bare utterances
                templates = list(dict.fromkeys(templates + list(hotkeys)))
            for _ in range(per):
                tmpl = rng.choice(templates)
                if intent == "hotkey" and "{" not in tmpl:
                    transcript = tmpl
                elif intent in ("file_find", "file_open"):
                    transcript = tmpl.format(query=rng.choice(FILE_QUERIES))
                elif intent in ("clarify", "chat", "refuse", "system_status") and "{" not in tmpl:
                    transcript = tmpl
                elif intent == "open_app" and "{" not in tmpl:
                    transcript = tmpl
                elif intent == "web_search" and "{" not in tmpl:
                    transcript = tmpl
                else:
                    transcript = _fill(tmpl, rng, apps, hotkeys)
                # STT wake / noise variants (~25%)
                if rng.random() < 0.25 and intent not in ("refuse",):
                    prefix = rng.choice(WAKE_PREFIXES)
                    transcript = (prefix + transcript).strip()
                if rng.random() < 0.08 and len(transcript.split()) >= 2:
                    # doubled phrase STT artifact
                    transcript = f"{transcript} {transcript}"
                examples.append(make_example(intent, transcript))
        # Fold misroutes (repeat a few times for weight)
        mis = _load_misroutes()
        for _ in range(3):
            examples.extend(mis)
        # pad / trim to n
        while len(examples) < n:
            intent = rng.choice(intents)
            templates = list(dict.fromkeys(TEMPLATES[intent] + EXTRA_BY_INTENT.get(intent, [])))
            tmpl = rng.choice(templates)
            if "{" in tmpl:
                transcript = _fill(tmpl, rng, apps, hotkeys)
            else:
                transcript = tmpl
            examples.append(make_example(intent, transcript))
        rng.shuffle(examples)
        return examples[:n]

    while len(examples) < n:
        intent = rng.choice(intents)
        templates = TEMPLATES[intent]
        if intent == "hotkey":
            templates = list(dict.fromkeys(templates + list(hotkeys)))
        tmpl = rng.choice(templates)
        if intent == "hotkey" and "{" not in tmpl:
            transcript = tmpl
        elif intent in ("file_find", "file_open"):
            transcript = tmpl.format(query=rng.choice(FILE_QUERIES))
        else:
            transcript = _fill(tmpl, rng, apps, hotkeys)
        examples.append(make_example(intent, transcript))
    return examples


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=25000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "datasets" / "marc_intents_v3.jsonl",
    )
    p.add_argument("--holdout", type=float, default=0.1)
    p.add_argument("--from-config", action="store_true", default=True)
    p.add_argument("--no-from-config", action="store_false", dest="from_config")
    args = p.parse_args()

    examples = synthesize(args.n, args.seed, from_config=args.from_config)
    rng = random.Random(args.seed)
    rng.shuffle(examples)
    cut = int(len(examples) * (1 - args.holdout))
    train, hold = examples[:cut], examples[cut:]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    train_path = args.out
    hold_path = args.out.with_name(args.out.stem + "_holdout.jsonl")
    for path, rows in ((train_path, train), (hold_path, hold)):
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {len(rows)} -> {path}")

    # Also refresh legacy path symlink-style copy for older scripts
    legacy = ROOT / "data" / "datasets" / "marc_intents.jsonl"
    legacy_hold = ROOT / "data" / "datasets" / "marc_intents_holdout.jsonl"
    if args.out.resolve() != legacy.resolve():
        import shutil

        shutil.copy2(train_path, legacy)
        shutil.copy2(hold_path, legacy_hold)
        print(f"also copied -> {legacy} / {legacy_hold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
