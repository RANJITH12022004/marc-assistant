# Marc Phase 7 roadmap (stubs — not implemented in Phase 6)

These items were explicitly deferred so Phase 6 could ship product features.

| Item | Why deferred | Notes |
|------|----------------|-------|
| Custom `hey_marc` ONNX wake model | Needs dataset + training pipeline | Keep OWW `hey_jarvis` + STT phrases |
| Silero VAD | Energy VAD already in `voice/stt.py` | Swap later for robustness |
| Screen-vision click targets | Heavy CV / UI automation | Optional Playwright DOM first |
| Local 7B+ brain replacing Gemini | GPU RAM + latency | Keep Gemini System-2 |
| Live Start-menu app discovery | Offline scan exists | Extend `scan_capability_inventory.py` |
| Outlook / non-Gmail mail | Gmail API covers primary mailbox | Graph API later |

When starting Phase 7, pick **one** of wake reliability, vision click, or local LLM — not all three at once.
