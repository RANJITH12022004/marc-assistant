"""Cognee brain beside the Obsidian mind vault.

Local stdlib-first remember/recall. Optional ``cognee`` package mirrors
into a graph when installed. Never logs secrets. No public listeners.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Any

_DEFAULT_DATASET = "personal"
_REDACT_MARKERS = (
    "authorization",
    "bearer",
    "api-key",
    "api_key",
    "marc_token",
    "password",
    "muse_api",
    "meta_ai_key",
)

_STORE: dict[str, list[dict[str, str]]] = {}
_STORE_LOCK = threading.Lock()

try:
    import cognee  # type: ignore
except Exception:  # pragma: no cover
    cognee = None


def data_dir() -> str:
    path = os.environ.get("COGNEE_DATA_DIR", "/home/rox/cognee/data")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def _redact_text(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    kept = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in _REDACT_MARKERS):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _normalize_datasets(datasets: Any) -> list[str]:
    if datasets is None:
        return [_DEFAULT_DATASET]
    if isinstance(datasets, str):
        return [datasets]
    try:
        items = list(datasets)
    except TypeError:
        return [_DEFAULT_DATASET]
    if not items:
        return [_DEFAULT_DATASET]
    return [str(d) for d in items]


def _store_add(dataset: str, text: str) -> dict[str, str]:
    entry = {"id": uuid.uuid4().hex, "text": text, "dataset": dataset}
    with _STORE_LOCK:
        _STORE.setdefault(dataset, []).append(entry)
    return entry


def _persist_line(dataset: str, text: str) -> None:
    try:
        root = data_dir()
        path = os.path.join(root, f"{dataset}.jsonl")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json_dumps({"text": text}) + "\n")
    except OSError:
        pass


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _load_dataset(dataset: str) -> None:
    path = os.path.join(data_dir(), f"{dataset}.jsonl")
    if not os.path.isfile(path):
        return
    with _STORE_LOCK:
        if _STORE.get(dataset):
            return
        rows: list[dict[str, str]] = []
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import json

                        obj = json.loads(line)
                    except Exception:
                        obj = {"text": line}
                    text = str(obj.get("text") or "").strip()
                    if text:
                        rows.append({"id": uuid.uuid4().hex, "text": text, "dataset": dataset})
        except OSError:
            return
        _STORE[dataset] = rows


def remember(text: str, dataset: str = _DEFAULT_DATASET) -> dict[str, Any]:
    dataset = str(dataset or _DEFAULT_DATASET)
    data_dir()
    redacted = _redact_text(text)
    if not redacted:
        return {"ok": True, "dataset": dataset, "skipped": True}
    _store_add(dataset, redacted)
    _persist_line(dataset, redacted)
    _cognee_mirror(redacted, dataset)
    return {"ok": True, "dataset": dataset}


def _cognee_mirror(text: str, dataset: str) -> None:
    if cognee is None or not text:
        return
    try:
        import asyncio
        import inspect

        async def _go() -> None:
            remember_fn = getattr(cognee, "remember", None) or getattr(cognee, "add", None)
            if remember_fn is None:
                return
            try:
                res = remember_fn(text, dataset_name=dataset)
            except TypeError:
                res = remember_fn(text)
            if inspect.isawaitable(res):
                await res

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            return
        if loop is None:
            asyncio.run(_go())
        else:
            loop.run_until_complete(_go())
    except Exception:
        pass


def _matches(query: str, text: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    t = (text or "").lower()
    if q in t:
        return True
    tokens = [tok for tok in q.split() if len(tok) > 2]
    return any(tok in t for tok in tokens)


def recall(query: str, datasets: Any = None, top_k: int = 8) -> dict[str, Any]:
    wanted = _normalize_datasets(datasets)
    data_dir()
    for ds in wanted:
        _load_dataset(ds)
    hits: list[dict[str, str]] = []
    with _STORE_LOCK:
        for ds in wanted:
            for entry in list(_STORE.get(ds, [])):
                if _matches(query, entry.get("text", "")):
                    hits.append({"text": entry["text"], "dataset": ds})
    hits = hits[: max(1, int(top_k))]
    spoken = ""
    if hits:
        spoken = " · ".join(h["text"][:120] for h in hits[:3])
    else:
        spoken = "Nothing in the brain for that yet."
    return {"ok": True, "text": spoken, "hits": hits, "message": spoken}


def remember_async(text: str, dataset: str = _DEFAULT_DATASET) -> None:
    """Fire-and-forget remember so voice path stays snappy."""

    def _run() -> None:
        try:
            remember(text, dataset=dataset)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def health() -> dict[str, Any]:
    path = data_dir()
    return {
        "ok": True,
        "data_dir": path,
        "cognee_package": cognee is not None,
        "datasets": sorted(_STORE.keys()) or [_DEFAULT_DATASET],
    }


def brain_speak(query: str) -> str:
    return str(recall(query).get("message") or "")
