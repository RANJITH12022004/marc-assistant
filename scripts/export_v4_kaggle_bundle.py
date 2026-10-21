#!/usr/bin/env python3
"""Zip Marc v4 RLCD dataset for Colab/Kaggle upload."""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "datasets"
BUNDLE = DATA / "kaggle_bundle"
OUT = DATA / "marc_intents_v4_kaggle.zip"

FILES = [
    BUNDLE / "marc_intents_v4_rlcd.jsonl",
    BUNDLE / "marc_intents_v4_holdout_rlcd.jsonl",
    DATA / "marc_intents_v4_meta.json",
    ROOT / "scripts" / "FINETUNE_GPU.md",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    missing = [p for p in FILES if not p.exists()]
    if missing:
        print("Missing files — run: python scripts/generate_intent_dataset_v4.py --per-intent 1200")
        for m in missing:
            print(" ", m)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in FILES:
            zf.write(p, arcname=p.name)
        readme = (
            "Marc intents v4 RLCD bundle\n"
            "1. Upload this zip to Kaggle/Colab.\n"
            "2. Train with scripts/finetune_marc_intent.py (see FINETUNE_GPU.md).\n"
            "3. Download checkpoint folder.\n"
            "4. Apply: python scripts/apply_finetuned_v4.py --src <checkpoint_dir>\n"
        )
        zf.writestr("README_V4.txt", readme)
    print(f"Wrote {args.out} ({args.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
