# Marc intent fine-tune (GPU / Kaggle)

This laptop is CPU-only for full RLCD. Train on **Kaggle 2×T4** (~4–5 hours), then deploy.

## 0. Prepare data (on this machine)

```powershell
cd C:\Users\ranjith\mark-laptop
C:\Users\ranjith\laya\.venv\Scripts\python.exe scripts\generate_intent_dataset.py --n 25000 --seed 7 --from-config
C:\Users\ranjith\laya\.venv\Scripts\python.exe scripts\export_rlcd_dataset.py --version v3
```

Outputs:

- `data/datasets/marc_intents_v3.jsonl` (~22.5k train) + `_holdout.jsonl` (~2.5k)
- `data/datasets/kaggle_bundle/` + `data/datasets/marc_kaggle_bundle.zip`
- RLCD-mapped: `marc_intents_v3_rlcd.jsonl`

## 0b. Ensure English Laya base weights

Prefer `E:\laya-models` (already present). If missing:

```powershell
C:\Users\ranjith\laya\.venv\Scripts\python.exe -c "import laya; laya.load(r'E:\laya-models')"
```

Or download Hub root `convaiinnovations/laya` (~808 MB) into that folder. Marc-intent fine-tune **starts from this base**.

Bootstrap a marc-intent folder from base (no RLCD yet):

```powershell
C:\Users\ranjith\laya\.venv\Scripts\python.exe scripts\finetune_marc_intent.py --bootstrap-checkpoint
```

## 1. Kaggle notebook

1. Open: https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb  
2. Enable **GPU T4 x2**  
3. Upload `marc_intents_v3_rlcd.jsonl` (from the zip)  
4. Point the notebook dataset path at that file (rows already have `state` / `questions` / `gold` JSON strings with soft `probabilities`)  
5. Start from HuggingFace `convaiinnovations/laya`  
6. Typical launch:

```bash
torchrun --standalone --nproc_per_node=2 /kaggle/working/train_ddp.py {MODEL_DIR} {OUTPUT_DIR}
```

Hyperparams (notebook defaults): ~4 epochs, micro-batch 8, grad accum 4, GRPO group 4.

## 2. Deploy checkpoint back to the laptop

Download the output folder, then:

```powershell
cd C:\Users\ranjith\mark-laptop
C:\Users\ranjith\laya\.venv\Scripts\python.exe scripts\apply_finetuned_checkpoint.py --src PATH\TO\DOWNLOADED\CHECKPOINT
```

This copies weights into `E:\laya-models\marc-intent\` and sets `"trained": true` in `marc_finetune_meta.json`.

## 3. Calibrate + eval

```powershell
C:\Users\ranjith\laya\.venv\Scripts\python.exe scripts\finetune_marc_intent.py --calibrate --limit 500 --holdout data\datasets\marc_intents_v3_holdout.jsonl --rules-only
C:\Users\ranjith\laya\.venv\Scripts\python.exe scripts\finetune_marc_intent.py --eval-only --limit 500 --holdout data\datasets\marc_intents_v3_holdout.jsonl
```

Success bar: holdout intent accuracy **≥ 0.85** (rules-only baseline ~0.75).

## 4. Use in voice

```powershell
C:\Users\ranjith\laya\.venv\Scripts\python.exe main.py voice --laya --seconds 3
```

Until `trained: true`, the hybrid router still prefers high-confidence rules (≥0.85).
