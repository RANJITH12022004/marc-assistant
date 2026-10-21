# Marc intent RLCD upload (v3)

1. Open: https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb
2. Upload `marc_intents_v3_rlcd.jsonl` as the training dataset.
3. Start from HuggingFace `convaiinnovations/laya` (or your E:\\laya-models English base).
4. Train ~4 epochs on 2xT4 (`torchrun --standalone --nproc_per_node=2 train_ddp.py ...`).
5. Download the output checkpoint folder.
6. On the laptop run:

```powershell
python scripts/apply_finetuned_checkpoint.py --src PATH\TO\DOWNLOADED\CHECKPOINT
python scripts/finetune_marc_intent.py --calibrate --limit 500
python scripts/finetune_marc_intent.py --eval-only --limit 500
```

Target: holdout intent accuracy >= 0.85, then use `main.py voice --laya --seconds 3`.
