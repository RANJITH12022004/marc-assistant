#!/usr/bin/env python3
"""Obsidian-style markdown vault for Marc working memory."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("MARC_MIND_DIR", "/home/rox/marc/mind"))
_lock = threading.RLock()
_NOW_KEYS = ("Focus", "Last", "Open", "Office", "Updated")
_CHAT_KEEP = 20


def _now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (slug or "note")[:40]


def _safe(rel: str) -> Path | None:
    raw = (rel or "").replace("\\", "/").lstrip("/")
    if not raw or ".." in raw.split("/"):
        return None
    path = (ROOT / raw).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return None
    if path.suffix.lower() != ".md":
        return None
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def seed() -> None:
    with _lock:
        ROOT.mkdir(parents=True, exist_ok=True)
        (ROOT / "daily").mkdir(exist_ok=True)
        (ROOT / "projects").mkdir(exist_ok=True)
        (ROOT / "people").mkdir(exist_ok=True)
        if not (ROOT / "NOW.md").exists():
            _write(
                ROOT / "NOW.md",
                "# Now\n"
                "Focus:\n"
                "Last:\n"
                "Open:\n"
                "Office:\n"
                f"Updated: {_now_stamp()}\n",
            )
        if not (ROOT / "index.md").exists():
            _write(
                ROOT / "index.md",
                "# Mind\n\n"
                "- [[NOW]]\n"
                "- [[people/ranjith]]\n"
                "- [[projects/marc]]\n",
            )
        person = ROOT / "people" / "ranjith.md"
        if not person.exists():
            _write(person, "# Ranjith\n\nNotes live here.\n")
        project = ROOT / "projects" / "marc.md"
        if not project.exists():
            _write(project, "# Marc\n\nHome assistant on Rox.\n")


def _parse_now(text: str) -> dict:
    data = {key: "" for key in _NOW_KEYS}
    data["Last"] = []
    for line in (text or "").splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "Last":
            if value:
                data["Last"].append(value)
        elif key in data:
            data[key] = value
    data["Last"] = [item for item in data["Last"] if item][-3:]
    return data


def _render_now(fields: dict) -> str:
    last = fields.get("Last") or []
    if isinstance(last, str):
        last = [last] if last else []
    last = [str(item).strip()[:180] for item in last if str(item).strip()][-3:]
    lines = ["# Now"]
    for key in _NOW_KEYS:
        if key == "Last":
            if not last:
                lines.append("Last:")
            else:
                lines.append("Last: " + last[-1])
                for extra in last[:-1]:
                    lines.append("Last: " + extra)
        else:
            lines.append(f"{key}: {str(fields.get(key) or '').strip()[:240]}")
    body = "\n".join(lines[:20]).rstrip() + "\n"
    return body


def _update_now(**changes) -> dict:
    seed()
    path = ROOT / "NOW.md"
    fields = _parse_now(_read(path))
    if "Last" in changes and changes["Last"]:
        last = list(fields.get("Last") or [])
        item = str(changes.pop("Last")).strip()[:180]
        last = [row for row in last if row != item]
        last.append(item)
        fields["Last"] = last[-3:]
    for key, value in changes.items():
        if key in _NOW_KEYS and key != "Last":
            fields[key] = str(value or "").strip()[:240]
    fields["Updated"] = _now_stamp()
    _write(path, _render_now(fields))
    return fields


def now_text() -> str:
    seed()
    return _read(ROOT / "NOW.md").strip() or "Nothing yet."


def now_speak() -> str:
    fields = _parse_now(now_text())
    bits = []
    if fields.get("Focus"):
        bits.append("Focus: " + fields["Focus"])
    last = fields.get("Last") or []
    if last:
        bits.append("Last: " + last[-1])
    if fields.get("Open"):
        bits.append("Open: " + fields["Open"])
    if fields.get("Office"):
        bits.append("Office: " + fields["Office"])
    if not bits:
        return "I don't have a thread yet."
    return " ".join(bits)[:400]


def set_focus(text: str) -> str:
    with _lock:
        _update_now(Focus=text)
    return "I'll keep that as the focus."


def set_last(text: str, source: str = "") -> None:
    line = (text or "").strip()
    if source:
        line = f"{line} ({source})"
    if not line:
        return
    with _lock:
        _update_now(Last=line)


def set_office(text: str) -> None:
    with _lock:
        _update_now(Office=text)


def append_daily(line: str, source: str = "") -> None:
    text = (line or "").strip().replace("\n", " ")[:240]
    if not text:
        return
    stamp = time.strftime("%H:%M")
    prefix = f"- {stamp}"
    if source:
        prefix += f" ({source})"
    row = f"{prefix} {text}\n"
    with _lock:
        seed()
        path = ROOT / "daily" / f"{_today()}.md"
        current = _read(path)
        if not current:
            current = f"# {_today()}\n\n"
        if not current.endswith("\n"):
            current += "\n"
        _write(path, current + row)


def today_text() -> str:
    seed()
    return _read(ROOT / "daily" / f"{_today()}.md").strip()


def remember(note: str) -> str:
    note = (note or "").strip(" .")[:400]
    if not note:
        return "What should I remember?"
    with _lock:
        seed()
        path = ROOT / "people" / "ranjith.md"
        body = _read(path) or "# Ranjith\n\n"
        lines = [line for line in body.splitlines() if line.strip() != f"- {note}"]
        if not lines or lines[0].strip() != "# Ranjith":
            lines = ["# Ranjith", ""] + [line for line in lines if line.strip() != "# Ranjith"]
        notes = [line for line in lines if line.startswith("- ")]
        rest = [line for line in lines if not line.startswith("- ")]
        notes = (notes + [f"- {note}"])[-12:]
        _write(path, "\n".join(rest).rstrip() + "\n" + "\n".join(notes) + "\n")
        _update_now(Last=f"remembered {note[:80]}")
    append_daily(f"remembered {note}", "mind")
    return "I'll remember that."


def forget(needle: str) -> str:
    needle = (needle or "").strip(" .").lower()
    with _lock:
        seed()
        path = ROOT / "people" / "ranjith.md"
        body = _read(path)
        lines = body.splitlines()
        notes = [line for line in lines if line.startswith("- ")]
        rest = [line for line in lines if not line.startswith("- ")]
        if not notes:
            return "I don't have a note to drop."
        if not needle or needle in {"that", "it", "this"}:
            dropped = notes.pop().lstrip("- ").strip()
        else:
            kept = [line for line in notes if needle not in line.lower()]
            if len(kept) == len(notes):
                return "I don't have a matching note."
            dropped = "matching note"
            notes = kept
        _write(path, "\n".join(rest).rstrip() + "\n" + ("\n".join(notes) + "\n" if notes else ""))
        _update_now(Last=f"forgot {dropped[:80]}")
    return f"Forgot: {dropped}" if dropped != "matching note" else "Forgot it."


def speak_who() -> str:
    notes = person_notes()
    if not notes:
        return "You're Ranjith. I don't have extra notes yet."
    return "You're Ranjith. " + " ".join(notes[:6])


def person_notes() -> list[str]:
    seed()
    lines = _read(ROOT / "people" / "ranjith.md").splitlines()
    return [line.lstrip("- ").strip() for line in lines if line.startswith("- ")]


def write_note(title: str, body: str, kind: str = "projects") -> str:
    title = (title or "").strip()[:80] or "note"
    body = (body or "").strip()[:2000]
    folder = "people" if kind == "people" else "projects"
    slug = _slug(title)
    rel = f"{folder}/{slug}.md"
    path = ROOT / folder / f"{slug}.md"
    with _lock:
        seed()
        current = _read(path)
        if not current:
            current = f"# {title}\n\n"
        if body:
            stamp = _now_stamp()
            current = current.rstrip() + f"\n\n## {stamp}\n\n{body}\n"
        _write(path, current)
        index = _read(ROOT / "index.md")
        link = f"- [[{folder}/{slug}]]"
        if link not in index:
            _write(ROOT / "index.md", index.rstrip() + f"\n{link}\n")
        if folder == "projects":
            _update_now(Last=f"noted {title}", Focus=title)
        else:
            _update_now(Last=f"noted {title}")
    append_daily(f"note {title}", "mind")
    return f"Saved [[{folder}/{slug}]]."


def project_from_task(text: str) -> str:
    title = (text or "").strip()[:80] or "Office"
    write_note(title, "Started from Office.", "projects")
    with _lock:
        _update_now(Focus=title, Office=title)
    return title


def recall(query: str) -> str:
    query = (query or "").strip().lower()
    seed()
    hits = []
    for path in _iter_notes():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        text = _read(path)
        title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.strip()), path.stem)
        blob = (title + "\n" + text[:400]).lower()
        score = 0
        if not query:
            score = path.stat().st_mtime if path.exists() else 0
        else:
            if query in rel.lower() or query in title.lower():
                score += 5
            if query in blob:
                score += 2
            for word in query.split():
                if word and word in blob:
                    score += 1
        if score:
            preview = next((line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")), "")
            hits.append((score, path.stat().st_mtime if path.exists() else 0, rel, title, preview[:160]))
    hits.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not hits:
        return "Nothing in the mind matches that."
    lines = []
    for _score, _mtime, rel, title, preview in hits[:5]:
        bit = f"[[{rel[:-3]}]] {title}"
        if preview:
            bit += f" — {preview}"
        lines.append(bit)
    return "\n".join(lines)[:800]


def _iter_notes():
    if not ROOT.exists():
        return
    for path in ROOT.rglob("*.md"):
        if path.name.endswith(".tmp"):
            continue
        yield path


def read_note(rel: str) -> dict:
    path = _safe(rel)
    if path is None or not path.exists():
        return {"ok": False, "error": "not found", "path": rel or ""}
    return {"ok": True, "path": str(path.relative_to(ROOT)).replace("\\", "/"), "text": _read(path)}


def list_notes() -> list[dict]:
    seed()
    rows = []
    for folder in ("projects", "people"):
        directory = ROOT / folder
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            title = next((line.lstrip("# ").strip() for line in _read(path).splitlines() if line.strip()), path.stem)
            rows.append({
                "path": f"{folder}/{path.name}",
                "title": title,
                "kind": folder,
            })
    return rows


def chat_append(session: str, role: str, content: str) -> None:
    if role not in {"user", "assistant"}:
        return
    text = (content or "").strip().replace("\n", " ")[:400]
    if not text:
        return
    session = (session or "desk").strip() or "desk"
    line = {"role": role, "content": text, "t": int(time.time())}
    path = ROOT / "chat" / f"{session}.jsonl"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def chat_recent(session: str, limit: int = _CHAT_KEEP) -> list[dict]:
    session = (session or "desk").strip() or "desk"
    path = ROOT / "chat" / f"{session}.jsonl"
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for raw in rows[-max(1, limit):]:
        try:
            item = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(item, dict) and item.get("role") in {"user", "assistant"}:
            out.append({"role": item["role"], "content": str(item.get("content") or "")[:400]})
    return out


def snapshot() -> dict:
    seed()
    return {
        "ok": True,
        "now": now_text(),
        "today": today_text(),
        "notes": list_notes(),
        "chat": chat_recent("desk"),
        "updated": _now_stamp(),
    }


def after_turn(text: str, spoken: str, session: str, tools: list | None = None) -> None:
    session = session or "desk"
    said = (text or "").strip()[:180]
    heard = (spoken or "").strip()[:180]
    names = [str(tool) for tool in (tools or []) if tool]
    last = heard or said
    if names:
        last = f"{', '.join(names[:4])}: {last}".strip(": ")
    if last:
        set_last(last, session)
    if said:
        append_daily(said, session)


def after_office(prompt: str, summary: str, *, new_task: bool = False) -> None:
    text = (summary or prompt or "").strip()[:180]
    if new_task and prompt:
        project_from_task(prompt)
    if text:
        set_office(text)
        set_last(text, "office")
        append_daily(text, "office")
