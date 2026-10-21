#!/usr/bin/env python3
"""Export Marc JSONL → RLCD-ready JSONL for the Laya Kaggle notebook + upload bundle."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]


def marc_to_rlcd(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map Marc answers → soft probabilities expected by upstream typed-decisions train."""
    answers = row["answers"]
    questions = row["questions"]
    gold: Dict[str, Any] = {}

    # choice → one-hot probabilities over criteria keys
    intent_q = questions["intent"]
    criteria = list(intent_q.get("criteria") or {})
    choice = answers["intent"]["choice"]
    probs = {k: (1.0 if k == choice else 0.0) for k in criteria}
    if choice not in probs and criteria:
        # unknown label — put mass on first key (should not happen)
        probs[criteria[0]] = 1.0
    gold["intent"] = {"probabilities": probs}

    for noul_key in ("needs_planner", "destructive"):
        val = float(answers[noul_key]["noul"])
        gold[noul_key] = {
            "probabilities": {"false": 1.0 - val, "true": val}
        }

    return {
        "state": json.dumps(row["state"], ensure_ascii=False),
        "questions": json.dumps(questions, ensure_ascii=False),
        "gold": json.dumps(gold, ensure_ascii=False),
        "meta": json.dumps(row.get("meta") or {}, ensure_ascii=False),
    }


def convert_file(src: Path, dst: Path) -> int:
    n = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open(encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            fout.write(json.dumps(marc_to_rlcd(row), ensure_ascii=False) + "\n")
            n += 1
    return n


def build_bundle(out_dir: Path, version: str = "v3") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    train_src = ROOT / "data" / "datasets" / f"marc_intents_{version}.jsonl"
    hold_src = ROOT / "data" / "datasets" / f"marc_intents_{version}_holdout.jsonl"
    if not train_src.exists():
        raise SystemExit(f"missing {train_src} — run generate_intent_dataset.py first")
    train_rlcd = out_dir / f"marc_intents_{version}_rlcd.jsonl"
    hold_rlcd = out_dir / f"marc_intents_{version}_holdout_rlcd.jsonl"
    n1 = convert_file(train_src, train_rlcd)
    n2 = convert_file(hold_src, hold_rlcd) if hold_src.exists() else 0
    print(f"RLCD train rows: {n1}")
    print(f"RLCD holdout rows: {n2}")

    readme = out_dir / "KAGGLE_README.md"
    readme.write_text(
        f"""# Marc intent RLCD upload ({version})

1. Open: https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb
2. Upload `marc_intents_{version}_rlcd.jsonl` as the training dataset.
3. Start from HuggingFace `convaiinnovations/laya` (or your E:\\\\laya-models English base).
4. Train ~4 epochs on 2xT4 (`torchrun --standalone --nproc_per_node=2 train_ddp.py ...`).
5. Download the output checkpoint folder.
6. On the laptop run:

```powershell
python scripts/apply_finetuned_checkpoint.py --src PATH\\TO\\DOWNLOADED\\CHECKPOINT
python scripts/finetune_marc_intent.py --calibrate --limit 500
python scripts/finetune_marc_intent.py --eval-only --limit 500
```

Target: holdout intent accuracy >= 0.85, then use `main.py voice --laya --seconds 3`.
""",
        encoding="utf-8",
    )

    # Keep Marc-native JSONL too for debugging
    shutil.copy2(train_src, out_dir / train_src.name)
    if hold_src.exists():
        shutil.copy2(hold_src, out_dir / hold_src.name)

    zip_path = ROOT / "data" / "datasets" / "marc_kaggle_bundle.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in out_dir.iterdir():
            zf.write(p, arcname=p.name)
    print(f"bundle zip → {zip_path}")
    return zip_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "data" / "datasets" / "kaggle_bundle",
    )
    p.add_argument("--version", default="v3")
    args = p.parse_args()
    build_bundle(args.out_dir, version=args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
