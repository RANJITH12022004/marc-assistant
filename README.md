# Marc

Personal assistant for Ranjith. Talk to it, or tell it to do something on the laptop, the phone, or the home Linux server.

Repository: [github.com/RANJITH12022004/marc-assistant](https://github.com/RANJITH12022004/marc-assistant)

## What it does

- **Talk:** questions go to a small Qwen chat model on the home server (`marc` in Ollama). No tools.
- **Do:** commands become tools. Open apps, mail, music, phone actions, server status, docker, and a bounded user shell.
- **Memory:** `remember I use Chrome on the laptop`, `who am I`, `forget Chrome`. Notes survive a restart of `marc-api`.
- **Targets:** Auto, Phone, Laptop, Server. Named phrases still win (`on my laptop`, `on my phone`, `on the server`).

Reboot, shutdown, and `rm -rf /` are refused in Python before anything runs. Mail, dial, and food search run without a confirm prompt.

## Pieces

| Piece | Role |
| --- | --- |
| Home server `marc-api` | Coordinator. Routes talk vs do, runs Laya for intent, runs Qwen for chat and the tool loop |
| Home server Laya | Fine-tuned intent classifier. Routes a turn; it does not block it |
| Home server Ollama | Chat and planner model `marc` (Qwen2.5 0.5B) |
| Web desk | Chat, Agent hops, laptop/phone/server pages, analog status rings |
| Laptop worker | Opens apps, mail, search, and other Windows tools. No model weights |
| Phone app | Overlay, Chat, and queued phone tools |

Sources for the live stack live in `_island/` (`marc_api.py`, `desk.html`, `desk_host.py`, `laptop_worker.py`, Android Java). The laptop voice loop (`main.py`, `orchestrator/`, `tools/`) is the older local Windows path.

## Talk vs do

The desk and phone send questions to `POST /chat` and commands to `POST /utterance`. A command can:

1. Hit a fast path (open/close, server status, remember/forget).
2. Enter a short Python-owned loop (max 5 hops). Qwen emits one JSON tool per hop. The harness runs it and feeds back a truncated observation.
3. Fall back to the one-shot planner if the loop returns nothing.

Server shell runs as user `rox` in `/home/rox/marc`, 15s timeout, deny-list for reboot, shutdown, sudo, and delete-root.

## Laptop voice (optional)

Local Windows loop: wake word, speech-to-text, rules, Laya, then OS tools.

```powershell
copy .env.example .env
python -m pip install -r requirements.txt
python main.py voice --laya --seconds 3
```

Put Google OAuth JSON at `data/gmail_credentials.json`, then `python main.py google-auth`. Add real emails in `config/contacts.json`.

## Layout

```
main.py                 Laptop CLI / voice
orchestrator/           Laptop turn loop
tools/                  Windows tools
laya_router/            Intent routing
_island/marc_api.py     Home-server coordinator
_island/desk.html       Web desk
_island/laptop_worker.py
_island/*.java          Phone app sources
docs/                   Design notes
```

Do not commit `.env`, OAuth tokens, or model weight folders. Copy `.env.example` and keep `MARC_TOKEN` only on the machines that need it.

## License

Private project for personal use unless the owner says otherwise.
