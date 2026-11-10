# Marc

Personal action assistant for Ranjith. Talk to it, or tell it to do something on the phone, the Windows laptop, or the home Linux server.

Repository: [github.com/RANJITH12022004/marc-assistant](https://github.com/RANJITH12022004/marc-assistant)

**Live product spec:** [docs/marc_prd.md](docs/marc_prd.md)

TV Lock and any TV / device remote-controller are out of scope.

## What it does

- **Act locally first.** Open, type, YouTube, Google, Spotify, WhatsApp on the phone without waiting for the home server.
- **Hermes agent plans leftovers.** Meta AI (and Needle as a local LLM) back Hermes. Instant/scripted paths stay model-free.
- **Reach the other machines.** Laptop tools via the Windows worker (including agent-desktop GUI); server status/restarts via Rox.
- **Remember.** Mind vault for “what was I doing”; Cognee brain for deeper recall.
- **Office.** A Cursor agent against `/home/rox/office/work` from desk or phone.

Default planner is Hermes (`MARC_PLANNER=hermes`). Rollback: `needle` or `qwen`. See [docs/hermes_cognee.md](docs/hermes_cognee.md).

Reboot, shutdown, and `rm -rf /` are refused before anything runs. Mail compose/send, dial, and food search confirm first.

## Pieces

| Piece | Role |
| --- | --- |
| Home server `marc-api` (`:8090`) | Coordinator. Instant phrases, Hermes leftovers, mind, Cognee, Office, laptop/server tools |
| marc-muse / Hermes (`:8096`) | Agent that plans leftovers with Meta AI |
| Needle on Rox (`:8094`) | Local LLM fallback (not an agent) |
| Needle on phone (`:18096`) | On-device LLM for leftover phone tools |
| Meta AI Muse | Cloud LLM for Hermes (`api.meta.ai`) |
| Cognee | Graph brain beside the mind vault |
| Web desk Roxx (`:8095`) | Chat, Office, Agent, Mind, Laptop, Phone, Server, Disks, System, Settings |
| `marc-cursor` (`:8093`) | Office coding agent |
| Laptop worker | Apps/mail/search + agent-desktop GUI tools. No model |
| Phone app | Camera-cutout overlay, Chat, queued phone tools, on-device Needle |
| Mind vault | Obsidian markdown at `/home/rox/marc/mind` |

Sources for the live stack live in `_island/` (`marc_api.py`, `hermes_client.py`, `muse_client.py`, `cognee_bridge.py`, `desk.html`, `NeedleEngine.java`, `LocalMarc.java`, `mind_store.py`). The laptop voice loop (`main.py`, `orchestrator/`, `tools/`) is the older local Windows path.

## Talk vs do

The desk and phone send small talk to `POST /chat` and commands to `POST /utterance`. A command can:

1. Hit a fast path (hi, time, remember/forget, IP, open/close, server status).
2. Hit a scripted phone path (`open X type Y send it`, YouTube, Google).
3. Hit Needle on the phone for leftover phone-only tools, or Hermes on Rox (Meta AI / Needle LLM) for leftovers that reach the coordinator.
4. Execute on the named device and speak one short line.

Server shell runs as user `rox` in `/home/rox/marc`, 15s timeout, deny-list for reboot, shutdown, sudo, and delete-root.

## Laptop voice (optional)

Local Windows loop: wake word, speech-to-text, rules, then OS tools.

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
laya_router/            Intent routing (idle while Needle is planner)
_island/marc_api.py     Home-server coordinator
_island/desk.html       Web desk
_island/laptop_worker.py
_island/*.java          Phone app sources
docs/marc_prd.md        Live product requirements
docs/                   Older briefs and setup notes
```

Do not commit `.env`, OAuth tokens, or model weight folders. Copy `.env.example` and keep `MARC_TOKEN` only on the machines that need it.

## License

Private project for personal use unless the owner says otherwise.
