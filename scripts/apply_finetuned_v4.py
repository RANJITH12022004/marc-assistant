#!/usr/bin/env python3
"""Copy a v4 RLCD checkpoint into LAYA_MARC_INTENT_PATH and mark trained:true."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laya_router.intents import INTENT_LABELS  # noqa: E402
from settings import settings  # noqa: E402

NEEDED = ["model.safetensors", "rl_agent_config.json"]


def apply(src: Path) -> Path:
    dst = settings.laya_marc_intent_path
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise SystemExit(f"Source not found: {src}")

    copied: list[str] = []
    for rel in NEEDED:
        s = src / rel
        if s.exists():
            shutil.copy2(s, dst / rel)
            copied.append(rel)

    # Prefer checkpoint_latest layout from Colab exports
    latest = src / "checkpoint_latest"
    if latest.is_dir():
        for rel in NEEDED:
            s = latest / rel
            if s.exists():
                shutil.copy2(s, dst / rel)
                copied.append(f"checkpoint_latest/{rel}")
        for sub in ("encoder", "tokenizer"):
            sdir = latest / sub
            if sdir.is_dir():
                ddir = dst / sub
                if ddir.exists():
                    shutil.rmtree(ddir)
                shutil.copytree(sdir, ddir)
                copied.append(f"checkpoint_latest/{sub}/")

    for sub in ("encoder", "tokenizer"):
        sdir = src / sub
        if sdir.is_dir():
            ddir = dst / sub
            if ddir.exists():
                shutil.rmtree(ddir)
            shutil.copytree(sdir, ddir)
            copied.append(sub + "/")

    for p in src.rglob("model.safetensors"):
        if p.parent == src or p.parent.name == "checkpoint_latest":
            continue
        shutil.copy2(p, dst / "model.safetensors")
        cfg = p.parent / "rl_agent_config.json"
        if cfg.exists():
            shutil.copy2(cfg, dst / "rl_agent_config.json")
        copied.append(str(p.relative_to(src)))
        break

    meta_path = dst / "marc_finetune_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
    meta.update(
        {
            "trained": True,
            "dataset": "marc_intents_v4",
            "dataset_path": str(ROOT / "data" / "datasets" / "marc_intents_v4.jsonl"),
            "intents": list(INTENT_LABELS.keys()),
            "source_checkpoint": str(src),
            "note": "RLCD fine-tuned marc-intent v4 (mail/youtube/multi_step).",
        }
    )
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Mirror meta into workspace datasets folder
    local_meta = ROOT / "data" / "datasets" / "marc_intents_v4_meta.json"
    if local_meta.exists():
        try:
            lm = json.loads(local_meta.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            lm = {}
        lm["trained"] = True
        lm["applied_checkpoint"] = str(src)
        local_meta.write_text(json.dumps(lm, indent=2), encoding="utf-8")

    print(f"deployed to {dst}")
    print(f"copied: {copied}")
    print("trained: true (v4)")
    return dst


def main() -> int:
    p = argparse.ArgumentParser(description="Apply Marc Laya v4 checkpoint")
    p.add_argument(
        "--src",
        type=Path,
        required=True,
        help="Downloaded Kaggle/Colab checkpoint folder (or laya_finetuned_marc_intent root)",
    )
    args = p.parse_args()
    apply(args.src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
