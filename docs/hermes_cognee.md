# Hermes, Cognee, and Meta AI on Rox

Installed beside the live Marc coordinator. Secrets stay in env files; this doc lists paths only.

## Layout

| Piece | Path / port | Role |
|-------|-------------|------|
| marc-muse planner (Hermes agent + Meta AI) | `/home/rox/marc-muse`, loopback **:8096** | Agent that plans leftovers via Meta Muse; `MARC_PLANNER=muse` inside that service |
| Hermes project runner | `/home/rox/marc-muse/apps/server/hermes`, default **:8732** | Goal/workdir sandbox for Office-style project runs |
| Cognee adapter | `/home/rox/marc-muse/apps/server/cognee` | Local remember/recall; optional `cognee` package |
| Cognee data | `/home/rox/cognee/data` (`COGNEE_DATA_DIR`) | On-disk memory |
| Env | `/home/rox/marc-muse.env` | `MARC_PLANNER`, `MARC_MUSE_*`, `COGNEE_DATA_DIR`, token — no secrets in git |
| marc-api (this repo) | `/home/rox/marc`, **:8090** | Coordinator; leftover planner via `MARC_PLANNER=hermes\|needle\|qwen` |
| Needle LLM | `:8094` | Local LLM only (not an agent) |
| Meta AI | `https://api.meta.ai/v1` | Cloud LLM for Hermes / Muse |

## Units

- `marc-muse.service` — always on, bind `127.0.0.1:8096`
- `marc-cognee.service` — optional oneshot warmup
- `marc-needle.service` — Needle LLM
- `marc-api.service` — coordinator

## Env knobs used by mark-laptop `_island`

- `MARC_PLANNER=hermes` (rollback `needle` / `qwen`)
- `MARC_MUSE_URL=http://127.0.0.1:8096`
- `MARC_MUSE_TOKEN` / `MARC_MUSE_ENV` — marc-muse bearer (often differs from `marc/secret`; hermes_client reads `MARC_TOKEN` from `/home/rox/marc-muse.env` by default)
- `HERMES_URL=http://127.0.0.1:8732` (optional project runner; not required for leftover planning)
- `META_AI_KEY_FILE` or `MUSE_API_KEY_FILE` (file path; never log contents) — for direct Meta fallback when muse is down
- `COGNEE_DATA_DIR=/home/rox/cognee/data`
- Existing: `NEEDLE_URL`, `MARC_MIND_DIR`, `MARC_LAPTOP_URL`, `MARC_TOKEN_FILE`

## Laptop agent-desktop

- CLI: `npm install -g agent-desktop`
- Cursor skill: `.agents/skills/agent-desktop` (from `npx skills add https://github.com/vercel-labs/agent-desktop --skill agent-desktop`)
- Worker tools: `desktop_status`, `desktop_snapshot`, `desktop_click`, `desktop_type`, `desktop_press`
