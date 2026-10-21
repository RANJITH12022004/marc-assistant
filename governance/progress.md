# Marc laptop — progress

## Continuous Marc + Dynamic Island (done)

- [x] Phase A–E continuous voice / island / Playwright

## Phase 2 — Typical laptop mastery + Laya RLCD

- [x] Listen default 3s; YouTube home; Google open-Nth; Camera modes
- [x] App rescan; dataset v3; rename product **Marc**
- [x] Kaggle dataset `ranjithd0212/marc-intents-v3-rlcd`
- [x] Fine-tuned checkpoint applied → `E:\laya-models\marc-intent` (`trained: true`)
- [x] Voice: `python main.py voice --laya --seconds 3`

## Live-issue hardening (2026-09)

- [x] Routing P0: email≠WhatsApp, go-to ordinals, Bye., last-email, time+type, camera click, last photo
- [x] Voice: shared audio device, wake threshold 0.25, junk peak, barge skip ready, Esc keeps slots
- [x] Safety: placeholder email guard; docs match Gmail API reality

Run: `python main.py voice --laya --seconds 3`
