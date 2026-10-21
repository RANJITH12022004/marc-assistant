#!/usr/bin/env python3
"""Build and push Marc Laya RLCD Kaggle notebook (T4 x2)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP = Path.home() / ".cursor" / "mcp.json"

# Extract train_ddp body from upstream notebook dump if present; else embed minimal pointer.
TRAIN_DDP = r'''
import os, sys, time, json, random
import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from safetensors.torch import load_file, save_file
from transformers import AutoTokenizer
from laya.common import build_model, proper_reward, QTYPES

def collate_train_batch(items, pad_id):
    n, L = len(items), max(len(it["ids"]) for it in items)
    kmax = max(len(it["markers"]) for it in items)
    ids = torch.full((n, L), pad_id, dtype=torch.long)
    att = torch.zeros((n, L), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long)
    mmask = torch.zeros((n, kmax), dtype=torch.bool)
    target = torch.zeros((n, kmax), dtype=torch.float32)
    for i, it in enumerate(items):
        ids[i, : len(it["ids"])] = torch.tensor(it["ids"])
        att[i, : len(it["ids"])] = 1
        k = len(it["markers"])
        mpos[i, :k] = torch.tensor(it["markers"])
        mmask[i, :k] = True
        target[i, : len(it["target"])] = torch.tensor(it["target"], dtype=torch.float32)
    return {
        "input_ids": ids, "attention_mask": att, "marker_pos": mpos, "marker_mask": mmask,
        "target": target, "qtype": torch.tensor([it["qtype"] for it in items]),
        "label": torch.tensor([it["label"] for it in items]),
    }

def fit_one_temp(sel):
    if len(sel) < 10:
        return 1.0
    kmax = max(len(z) for z, _ in sel)
    Z = torch.full((len(sel), kmax), -1e4)
    T = torch.zeros((len(sel), kmax))
    for i, (z, t) in enumerate(sel):
        Z[i, :len(z)] = torch.tensor(z)
        T[i, :len(t)] = torch.tensor(t, dtype=torch.float32)
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)
    def closure():
        opt.zero_grad()
        loss = -(T * torch.log_softmax(Z / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss
    opt.step(closure)
    return float(torch.clamp(log_t.exp(), 0.1, 10.0).item())

def main():
    dist.init_process_group("nccl")
    rank = dist.get_rank()
    world_size = dist.get_world_size()
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)
    model_dir, output_dir = sys.argv[1], sys.argv[2]
    with open(os.path.join(model_dir, "rl_agent_config.json")) as f:
        cfg = json.load(f)
    cfg["gradient_checkpointing"] = True
    cfg["max_tokens_per_batch"] = 4096
    cfg["max_len"] = 1024
    cfg["head_max_len"] = 256
    tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))
    model = build_model(cfg, encoder_dir=os.path.join(model_dir, "encoder"))
    model.load_state_dict(load_file(os.path.join(model_dir, "model.safetensors")), strict=True)
    model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.head_checkpointing = True
    model.to(device)
    model.train()
    ddp_model = DDP(model, device_ids=[local_rank], find_unused_parameters=True)
    all_items = torch.load("/kaggle/working/train_items.pt", weights_only=False)
    CALIB_MAX = 400
    order = list(range(len(all_items)))
    random.Random(20260922).shuffle(order)
    n_calib = min(CALIB_MAX, len(all_items) // 10)
    calib_items = [all_items[i] for i in sorted(order[:n_calib])]
    train_items = [all_items[i] for i in sorted(order[n_calib:])]
    my_items = train_items[rank::world_size]
    EPOCHS, MICRO_BATCH, GRAD_ACCUM, GROUP_SIZE = 4, 8, 4, 4
    LR_ENCODER, LR_HEAD, SIGMA_START, SIGMA_END = 2.5e-5, 1.0e-4, 0.4, 0.1
    enc_params = [p for n, p in ddp_model.named_parameters() if "encoder." in n]
    head_params = [p for n, p in ddp_model.named_parameters() if "encoder." not in n]
    optimizer = torch.optim.AdamW([
        {"params": enc_params, "lr": LR_ENCODER},
        {"params": head_params, "lr": LR_HEAD},
    ], weight_decay=0.01)
    total_updates = (len(my_items) // (MICRO_BATCH * GRAD_ACCUM)) * EPOCHS
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, total_updates), eta_min=1e-6)
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    if rank == 0:
        print(f"Starting 2xT4 DDP: {len(train_items)} train / {len(calib_items)} calib | {len(my_items)}/rank | {EPOCHS} epochs")
    t0 = time.time()
    for epoch in range(EPOCHS):
        random.seed(42 + epoch + rank)
        random.shuffle(my_items)
        epoch_loss, n_batches, accum_step = 0.0, 0, 0
        optimizer.zero_grad(set_to_none=True)
        progress = epoch / max(1, EPOCHS - 1)
        sigma = SIGMA_START + (SIGMA_END - SIGMA_START) * progress
        for b_idx in range(0, len(my_items), MICRO_BATCH):
            chunk = my_items[b_idx:b_idx + MICRO_BATCH]
            if not chunk:
                continue
            batch = collate_train_batch(chunk, tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                logits, act = ddp_model(
                    batch["input_ids"].to(device), batch["attention_mask"].to(device),
                    batch["marker_pos"].to(device), batch["marker_mask"].to(device),
                    batch["qtype"].to(device),
                )
            logits = logits.float()
            mask = batch["marker_mask"].to(device)
            k = mask.sum(-1, keepdim=True).float()
            target = batch["target"].to(device)
            eps = torch.randn((GROUP_SIZE,) + logits.shape, device=device) * sigma * mask
            eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
            z = logits.detach().unsqueeze(0) + eps
            q = torch.softmax(z.masked_fill(~mask, -1e4), -1)
            with torch.no_grad():
                r = proper_reward(q, target.unsqueeze(0), batch["qtype"].to(device), mask, w_sph=0.75, w_rps=1.0)
                adv = r - r.mean(0, keepdim=True)
                adv = adv / (adv.std() + 1e-6)
            logp = -(((z - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma ** 2)
            loss_rl = -(adv * logp).mean()
            loss_ce = -(target * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)).sum(-1).mean()
            loss = (loss_rl + 1.0 * loss_ce) / GRAD_ACCUM + 0.0 * act.sum()
            scaler.scale(loss).backward()
            accum_step += 1
            if accum_step % GRAD_ACCUM == 0 or (b_idx + MICRO_BATCH) >= len(my_items):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(ddp_model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            epoch_loss += loss.item() * GRAD_ACCUM
            n_batches += 1
            if rank == 0 and (n_batches % 50) == 0:
                print(f" Epoch {epoch+1}/{EPOCHS} | Step {n_batches} | Loss {loss.item()*GRAD_ACCUM:.4f} | R {r.mean().item():.3f}")
        if rank == 0:
            print(f"=== Epoch {epoch+1}/{EPOCHS} done {time.time()-t0:.1f}s | avg {epoch_loss/max(1,n_batches):.4f} ===")
            ckpt_dir = os.path.join(output_dir, "checkpoint_latest")
            os.makedirs(ckpt_dir, exist_ok=True)
            ckpt_sd = {k: v.half().contiguous().cpu() for k, v in model.state_dict().items()}
            save_file(ckpt_sd, os.path.join(ckpt_dir, "model.safetensors"))
            model.encoder.config.save_pretrained(os.path.join(ckpt_dir, "encoder"))
            tok.save_pretrained(os.path.join(ckpt_dir, "tokenizer"))
            with open(os.path.join(ckpt_dir, "checkpoint_meta.json"), "w") as f:
                json.dump({"epoch": epoch + 1, "total_epochs": EPOCHS}, f, indent=2)
            print("Saved", ckpt_dir)
        dist.barrier()
    if rank == 0:
        print("Fitting temperatures...")
        del optimizer, scaler, scheduler
        torch.cuda.empty_cache()
        model.eval()
        calib_preds = []
        with torch.no_grad():
            for c_idx in range(0, len(calib_items), 16):
                c_chunk = calib_items[c_idx:c_idx + 16]
                cb = collate_train_batch(c_chunk, tok.pad_token_id)
                with torch.autocast("cuda", dtype=torch.float16):
                    l_sub, _ = model(
                        cb["input_ids"].to(device), cb["attention_mask"].to(device),
                        cb["marker_pos"].to(device), cb["marker_mask"].to(device),
                        cb["qtype"].to(device),
                    )
                l_np = l_sub.float().cpu().numpy()
                for ri, it in enumerate(c_chunk):
                    kk = len(it["markers"])
                    calib_preds.append((it["qtype"], l_np[ri, :kk], it["target"]))
        fitted_temps = [1.2, 1.2, 1.2]
        try:
            for qt in range(3):
                sel = [(z, t) for q_type, z, t in calib_preds if q_type == qt]
                if sel:
                    fitted_temps[qt] = fit_one_temp(sel)
            print("temps", [round(t, 3) for t in fitted_temps])
        except Exception as e:
            print("temp fallback", e)
        os.makedirs(output_dir, exist_ok=True)
        sd = {k: v.half().contiguous().cpu() for k, v in model.state_dict().items()}
        save_file(sd, os.path.join(output_dir, "model.safetensors"))
        model.encoder.config.save_pretrained(os.path.join(output_dir, "encoder"))
        tok.save_pretrained(os.path.join(output_dir, "tokenizer"))
        cfg["fine_tuned"] = True
        cfg["model_name"] = "marc-intent"
        cfg["temperature"] = fitted_temps
        cfg.pop("temperature_by_options", None)
        with open(os.path.join(output_dir, "rl_agent_config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        print("Saved model to", output_dir)
    dist.destroy_process_group()

if __name__ == "__main__":
    main()
'''.lstrip("\n")


def cell_source(text: str) -> list[str]:
    lines = text.strip("\n").split("\n")
    return [ln + "\n" for ln in lines]


def build_notebook() -> dict:
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": cell_source(
                "# Marc Laya RLCD fine-tune (GPU T4 x2)\n\n"
                "Dataset: `ranjithd0212/marc-intents-v3-rlcd`\n"
                "Output: `/kaggle/working/laya_finetuned_marc_intent`"
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
                "print('GPUs', n)\n"
                "assert n >= 1, 'Need a GPU'\n"
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
                "print('laya', laya.__version__, 'torch', torch.__version__)\n"
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
                'cands = glob.glob("/kaggle/input/**/marc_intents_v3_rlcd.jsonl", recursive=True)\n'
                "assert cands, 'dataset missing'\n"
                "MARC_JSONL = cands[0]\n"
                "print('Using', MARC_JSONL)\n"
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
                "print('Preprocessed', len(items))\n"
                'torch.save(items, "/kaggle/working/train_items.pt")\n'
                'open("/kaggle/working/model_dir.txt","w").write(model_dir)\n'
            ),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source("%%writefile /kaggle/working/train_ddp.py\n" + TRAIN_DDP),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": cell_source(
                "from huggingface_hub import snapshot_download\n"
                "import os, torch\n"
                'MODEL_DIR = open("/kaggle/working/model_dir.txt").read().strip() or snapshot_download("convaiinnovations/laya")\n'
                'OUTPUT_DIR = "/kaggle/working/laya_finetuned_marc_intent"\n'
                "os.makedirs(OUTPUT_DIR, exist_ok=True)\n"
                "nproc = max(1, torch.cuda.device_count())\n"
                'cmd = f"torchrun --standalone --nproc_per_node={nproc} /kaggle/working/train_ddp.py {MODEL_DIR} {OUTPUT_DIR}"\n'
                "print(cmd)\n"
                "os.system(cmd)\n"
                '!cd /kaggle/working && zip -r laya_finetuned_marc_intent.zip laya_finetuned_marc_intent\n'
                "print('done')\n"
            ),
        },
    ]
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def auth_header() -> str:
    cfg = json.loads(MCP.read_text(encoding="utf-8-sig"))
    auth = cfg["mcpServers"]["kaggle"]["headers"]["Authorization"]
    if not auth.startswith("Bearer "):
        auth = "Bearer " + auth
    return auth


def push_notebook(nb: dict) -> dict:
    text = json.dumps(nb)
    # Prefer Save & Run All with GPU
    body = {
        "newTitle": "Marc Laya RLCD Fine-tune T4x2",
        "slug": "ranjithd0212/marc-laya-rlcd-fine-tune-t4x2",
        "language": "python",
        "kernelType": "notebook",
        "isPrivate": True,
        "enableGpu": True,
        "enableInternet": True,
        "enableTpu": False,
        "datasetDataSources": ["ranjithd0212/marc-intents-v3-rlcd"],
        "text": text,
    }
    # Try dual T4 shape names
    for shape in ("NvidiaTeslaT4x2", "NVIDIATeslaT4x2", "T4x2", None):
        payload = dict(body)
        if shape:
            payload["machineShape"] = shape
        url = "https://www.kaggle.com/api/v1/kernels/push"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Authorization": auth_header(), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read().decode())
                resp["_machineShapeTried"] = shape
                return resp
        except Exception as e:
            err = e.read().decode() if hasattr(e, "read") else str(e)
            last = {"error": err[:800], "shape": shape}
    return last


def main() -> int:
    nb = build_notebook()
    out = ROOT / "scripts" / "marc_laya_rlcd_kaggle.ipynb"
    out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print("wrote", out, "bytes", out.stat().st_size)
    result = push_notebook(nb)
    print(json.dumps(result, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
