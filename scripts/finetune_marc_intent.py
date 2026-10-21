#!/usr/bin/env python3
"""
Fine-tune / calibrate helper for Marc intents.

Full RLCD training (upstream Kaggle notebook) needs a GPU. On this laptop we:
1. Prefer copying a trained checkpoint into E:\\laya-models\\marc-intent
2. Optionally run a lightweight calibration pass that stores temperatures JSON
3. Evaluate holdout accuracy using current Laya (or rules) as baseline

Usage:
  python scripts/finetune_marc_intent.py --eval-only
  python scripts/finetune_marc_intent.py --bootstrap-checkpoint
  python scripts/finetune_marc_intent.py --calibrate
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from settings import settings  # noqa: E402


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def bootstrap_checkpoint() -> Path:
    """Copy English base weights into marc-intent folder as fine-tune starting point."""
    src = settings.laya_model_path
    dst = settings.laya_marc_intent_path
    dst.mkdir(parents=True, exist_ok=True)
    files = [
        "model.safetensors",
        "rl_agent_config.json",
        "encoder/config.json",
        "tokenizer/tokenizer.json",
        "tokenizer/tokenizer_config.json",
    ]
    for rel in files:
        s = src / rel
        d = dst / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if not s.exists():
            print(f"missing {s}")
            continue
        if d.exists() and d.stat().st_size == s.stat().st_size:
            print(f"skip existing {d}")
            continue
        print(f"copy {s} → {d}")
        shutil.copy2(s, d)
    meta = {
        "base": str(src),
        "trained": False,
        "kaggle_bundle": str(ROOT / "data" / "datasets" / "marc_kaggle_bundle.zip"),
        "note": (
            "Bootstrap English Laya. Upload marc_kaggle_bundle.zip to Kaggle, train RLCD, "
            "then run: python scripts/apply_finetuned_checkpoint.py --src <download>"
        ),
        "dataset": str(ROOT / "data" / "datasets" / "marc_intents_v3.jsonl"),
        "dataset_version": "v3",
        "voice_flags": "main.py voice --laya --seconds 3",
    }
    (dst / "marc_finetune_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"bootstrap ready at {dst}")
    return dst


def evaluate(holdout: Path, limit: int = 100, rules_only: bool = False) -> Dict[str, Any]:
    from laya_router import MarcLayaRouter
    from laya_router.rules import rule_classify

    rows = load_jsonl(holdout)[:limit]
    router = MarcLayaRouter(preload=not rules_only, rules_only=rules_only)
    correct_laya = 0
    correct_rules = 0
    for row in rows:
        gold = row["answers"]["intent"]["choice"]
        transcript = row["state"]["transcript"]
        pred = router.classify(transcript)
        if pred.intent == gold:
            correct_laya += 1
        r_intent, _ = rule_classify(transcript)
        if r_intent == gold:
            correct_rules += 1
    n = max(1, len(rows))
    report = {
        "n": len(rows),
        "router_accuracy": correct_laya / n,
        "rules_accuracy": correct_rules / n,
        "rules_only": rules_only,
        "source_note": "Unfine-tuned Laya is expected near-chance; rules should lead until RLCD train.",
    }
    out = ROOT / "data" / "logs" / "intent_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def calibrate(holdout: Path, limit: int = 200, rules_only: bool = False) -> Path:
    """
    Fit simple per-question temperature placeholders.

    Full proper calibration requires logits; we store empirical confidence stats
    for gating policy until a GPU fine-tune ships fitted temps in the checkpoint.
    """
    from laya_router import MarcLayaRouter

    rows = load_jsonl(holdout)[:limit]
    router = MarcLayaRouter(preload=not rules_only, rules_only=rules_only)
    confs = []
    for row in rows:
        transcript = row["state"]["transcript"]
        pred = router.classify(transcript)
        confs.append(pred.confidence)
    import statistics

    stats = {
        "n": len(confs),
        "mean_confidence": statistics.fmean(confs) if confs else 0.0,
        "median_confidence": statistics.median(confs) if confs else 0.0,
        "recommended_threshold": 0.85,
        "rules_only": rules_only,
        "note": "Replace with fitted temperatures after RLCD fine-tune.",
    }
    out = settings.laya_marc_intent_path
    out.mkdir(parents=True, exist_ok=True)
    path = out / "marc_calibration.json"
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    print(json.dumps(stats, indent=2))
    return path


def write_colab_pointer() -> Path:
    """Keep FINETUNE_GPU.md as the source of truth (do not overwrite custom docs)."""
    path = ROOT / "scripts" / "FINETUNE_GPU.md"
    if path.exists() and path.stat().st_size > 200:
        return path
    path.write_text(
        "See scripts/export_rlcd_dataset.py and apply_finetuned_checkpoint.py.\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bootstrap-checkpoint", action="store_true")
    p.add_argument("--eval-only", action="store_true")
    p.add_argument("--calibrate", action="store_true")
    p.add_argument("--rules-only", action="store_true", help="Eval/calibrate without loading Laya")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument(
        "--holdout",
        type=Path,
        default=ROOT / "data" / "datasets" / "marc_intents_v3_holdout.jsonl",
    )
    args = p.parse_args()

    write_colab_pointer()

    if args.bootstrap_checkpoint:
        bootstrap_checkpoint()
    if args.calibrate:
        if not args.holdout.exists():
            print("holdout missing; run generate_intent_dataset.py first")
            return 1
        calibrate(args.holdout, limit=args.limit, rules_only=args.rules_only)
    if args.eval_only or not any([args.bootstrap_checkpoint, args.calibrate]):
        if not args.holdout.exists():
            print("holdout missing; run generate_intent_dataset.py first")
            return 1
        evaluate(args.holdout, limit=args.limit, rules_only=args.rules_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
