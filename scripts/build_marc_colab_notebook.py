#!/usr/bin/env python3
"""Build Marc Laya RLCD Colab notebook (T4 fallback when Kaggle GPU is locked)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

push_path = ROOT / "scripts" / "push_marc_kaggle_notebook.py"
ns: dict = {"__file__": str(push_path), "__name__": "push_marc_kaggle_notebook"}
exec(push_path.read_text(encoding="utf-8"), ns)
TRAIN_DDP_COLAB = ns["TRAIN_DDP"].replace(
    "/kaggle/working/train_items.pt", "/content/train_items.pt"
)


def cell_source(text: str) -> list[str]:
    lines = text.strip("\n").split("\n")
    return [ln + "\n" for ln in lines]


def build_notebook() -> dict:
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": cell_source(
                "# Marc Laya RLCD fine-tune (Google Colab T4)\n\n"
                "1. **Runtime → Change runtime type → Hardware accelerator → T4 GPU → Save**\n"
                "2. Runtime → Run all\n"
                "3. Download `laya_finetuned_marc_intent.zip` from the Files panel when done\n\n"
                "Uses Kaggle dataset `ranjithd0212/marc-intents-v3-rlcd` via API token."
            ),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source(
                "!nvidia-smi\n"
                "import os, torch\n"
                'os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"\n'
                "n = torch.cuda.device_count()\n"
                'print("GPUs", n, torch.cuda.get_device_name(0) if n else None)\n'
                'assert n >= 1, "Runtime → Change runtime type → T4 GPU, then re-run"\n'
            ),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source(
                "# Paste your Kaggle API token (KGAT_...) once\n"
                "import os, getpass, pathlib\n"
                'tok = os.environ.get("KAGGLE_API_TOKEN") or getpass.getpass("Kaggle API token (KGAT_...): ").strip()\n'
                'if tok.startswith("Bearer "):\n'
                "    tok = tok[7:]\n"
                'pathlib.Path("/root/.kaggle").mkdir(parents=True, exist_ok=True)\n'
                'os.environ["KAGGLE_API_TOKEN"] = tok\n'
                "!pip -q install -U kaggle\n"
                "!kaggle datasets download -d ranjithd0212/marc-intents-v3-rlcd -p /content/data --unzip\n"
                "!ls -lh /content/data\n"
            ),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source(
                '!pip install -q -U "laya>=0.1.6" "transformers>=4.48.0" safetensors huggingface_hub accelerate\n'
                "import laya, torch\n"
                'print("laya", laya.__version__, "torch", torch.__version__)\n'
            ),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source(
                "import os, json, glob, torch\n"
                "from transformers import AutoTokenizer\n"
                "from huggingface_hub import snapshot_download\n"
                "from laya.agent import _fix_tokenizer_config\n"
                "from laya.common import build_sequence, render_options, QTYPES\n"
                'MODEL_ID = "convaiinnovations/laya"\n'
                "model_dir = snapshot_download(MODEL_ID)\n"
                "_fix_tokenizer_config(model_dir)\n"
                'tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))\n'
                'with open(os.path.join(model_dir, "rl_agent_config.json")) as f:\n'
                "    cfg = json.load(f)\n"
                'cands = glob.glob("/content/data/**/marc_intents_v3_rlcd.jsonl", recursive=True) or '
                'glob.glob("/content/**/marc_intents_v3_rlcd.jsonl", recursive=True)\n'
                'assert cands, "dataset missing — re-run download cell or upload marc_intents_v3_rlcd.jsonl"\n'
                "MARC_JSONL = cands[0]\n"
                'print("Using", MARC_JSONL)\n'
                "\n"
                "def build_training_item(state, q, gold_q):\n"
                '    t = q["type"]\n'
                '    crit = q.get("criteria", {})\n'
                '    if t == "choice":\n'
                "        keys = list(crit.keys())\n"
                '        target = [gold_q["probabilities"].get(k, 0.0) for k in keys]\n'
                '    elif t == "noul":\n'
                '        target = [gold_q["probabilities"].get("false", 0.5), gold_q["probabilities"].get("true", 0.5)]\n'
                '    elif t == "score":\n'
                "        n_levels = len(crit) if isinstance(crit, list) else 4\n"
                '        target = [gold_q["probabilities"].get(str(i), 0.0) for i in range(n_levels)]\n'
                "    else:\n"
                "        return None\n"
                "    s = sum(target)\n"
                "    target = [v / s for v in target] if s > 0 else [1.0 / len(target)] * len(target)\n"
                "    label = target.index(max(target))\n"
                '    k = len(render_options({"t": t, "crit": crit}))\n'
                '    seq, markers = build_sequence(tok, state, {"t": t, "ins": q["instructions"], "crit": crit}, cfg["max_len"], cfg["head_max_len"])\n'
                "    if len(markers) != k:\n"
                "        return None\n"
                '    return {"ids": seq, "markers": markers, "qtype": QTYPES[t], "target": target, "label": label}\n'
                "\n"
                "items = []\n"
                'with open(MARC_JSONL, encoding="utf-8") as f:\n'
                "    for line in f:\n"
                "        line = line.strip()\n"
                "        if not line:\n"
                "            continue\n"
                "        row = json.loads(line)\n"
                '        state = json.loads(row["state"]) if isinstance(row["state"], str) else row["state"]\n'
                '        questions = json.loads(row["questions"]) if isinstance(row["questions"], str) else row["questions"]\n'
                '        gold = json.loads(row["gold"]) if isinstance(row["gold"], str) else row["gold"]\n'
                "        for qid, q in questions.items():\n"
                "            if qid in gold:\n"
                "                it = build_training_item(state, q, gold[qid])\n"
                "                if it:\n"
                "                    items.append(it)\n"
                'print("Preprocessed", len(items))\n'
                'torch.save(items, "/content/train_items.pt")\n'
                'open("/content/model_dir.txt", "w").write(model_dir)\n'
            ),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source("%%writefile /content/train_ddp.py\n" + TRAIN_DDP_COLAB),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source(
                "from huggingface_hub import snapshot_download\n"
                "import os, torch\n"
                'MODEL_DIR = open("/content/model_dir.txt").read().strip() or snapshot_download("convaiinnovations/laya")\n'
                'OUTPUT_DIR = "/content/laya_finetuned_marc_intent"\n'
                "os.makedirs(OUTPUT_DIR, exist_ok=True)\n"
                "nproc = max(1, torch.cuda.device_count())\n"
                'cmd = f"torchrun --standalone --nproc_per_node={nproc} /content/train_ddp.py {MODEL_DIR} {OUTPUT_DIR}"\n'
                "print(cmd)\n"
                "rc = os.system(cmd)\n"
                'print("exit", rc)\n'
                "!cd /content && zip -r laya_finetuned_marc_intent.zip laya_finetuned_marc_intent\n"
                'print("Download /content/laya_finetuned_marc_intent.zip from the Files panel")\n'
            ),
        },
    ]
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "accelerator": "GPU",
        },
        "cells": cells,
    }


def main() -> int:
    out = ROOT / "scripts" / "marc_laya_rlcd_colab.ipynb"
    out.write_text(json.dumps(build_notebook(), indent=1), encoding="utf-8")
    print("wrote", out, "bytes", out.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
