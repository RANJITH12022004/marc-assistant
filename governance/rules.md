# Marc laptop — hard constraints

- Single user (Ranjith). No multi-account Gemini quota stacking.
- Laya is System-1 only (intent/confidence). Gemini is System-2 planner. OS tools execute.
- No raw shell/PowerShell from model output in v1.
- Destructive actions require explicit confirmation.
- File tools limited to Desktop, Downloads, Documents.
- Prefer push-to-talk until wake word is configured with Picovoice key.
- Never log secrets, passwords, or full clipboard contents beyond short previews.
- Models live on SD card (`E:\laya-models`); do not re-download multi-GB weights to C: casually.
- Do not couple to MARC emergency pipeline.
