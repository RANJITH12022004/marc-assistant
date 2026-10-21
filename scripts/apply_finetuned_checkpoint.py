#!/usr/bin/env python3
"""Copy a downloaded RLCD checkpoint into E:\\laya-models\\marc-intent and set trained:true."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from settings import settings  # noqa: E402

NEEDED = [
    "model.safetensors",
    "rl_agent_config.json",
]


def apply(src: Path) -> Path:
    dst = settings.laya_marc_intent_path
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise SystemExit(f"Source not found: {src}")

    # Copy known weight files + tokenizer/encoder if present
    copied = []
    for rel in NEEDED:
        s = src / rel
        if s.exists():
            shutil.copy2(s, dst / rel)
            copied.append(rel)
    for sub in ("encoder", "tokenizer"):
        sdir = src / sub
        if sdir.is_dir():
            ddir = dst / sub
            if ddir.exists():
                shutil.rmtree(ddir)
            shutil.copytree(sdir, ddir)
            copied.append(sub + "/")

    # Also accept flat dumps from Kaggle working dir
    for p in src.rglob("model.safetensors"):
        if p.parent == src:
            break
        shutil.copy2(p, dst / "model.safetensors")
        cfg = p.parent / "rl_agent_config.json"
        if cfg.exists():
            shutil.copy2(cfg, dst / "rl_agent_config.json")
        copied.append(str(p))
        break

    meta_path = dst / "marc_finetune_meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "trained": True,
            "dataset": str(ROOT / "data" / "datasets" / "marc_intents_v3.jsonl"),
            "source_checkpoint": str(src),
            "note": "RLCD fine-tuned marc-intent. Hybrid router may prefer Laya over rules.",
        }
    )
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"deployed to {dst}")
    print(f"copied: {copied}")
    print("trained: true")
    return dst


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", type=Path, required=True, help="Downloaded Kaggle checkpoint folder")
    args = p.parse_args()
    apply(args.src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
