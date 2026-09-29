"""将原始记忆条目转换为统一展示格式。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from memory.config import IMPORTANCE_HIGH, IMPORTANCE_LOW, IMPORTANCE_MEDIUM


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def importance_level(raw: int) -> str:
    raw = max(1, min(5, int(raw or 3)))
    if raw in IMPORTANCE_HIGH:
        return "high"
    if raw in IMPORTANCE_MEDIUM:
        return "medium"
    if raw in IMPORTANCE_LOW:
        return "low"
    return "medium"


def _make_summary(content: str, limit: int = 50) -> str:
    text = (content or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def parse_memory(raw: dict, *, index: int = 0, source: str = "model") -> dict:
    """
    将单条原始记忆转为统一格式。

    支持 long_term: {fact, importance, timestamp, id, source, deleted}
    或 short_term: {role, content, timestamp}
    """
    if "fact" in raw:
        content = str(raw.get("fact", ""))
        imp_raw = int(raw.get("importance", 3))
        src = str(raw.get("source") or source or "model")
    else:
        role = raw.get("role", "user")
        content = str(raw.get("content", ""))
        imp_raw = 2 if role == "user" else 3
        src = "user" if role == "user" else "model"

    ts = _parse_ts(raw.get("timestamp"))
    updated = _parse_ts(raw.get("updated_at")) if raw.get("updated_at") else ts
    content = content.strip()
    uid = raw.get("id") or hashlib.md5(
        f"{content}:{ts.isoformat()}:{index}".encode()
    ).hexdigest()[:12]

    return {
        "id": uid,
        "summary": _make_summary(content),
        "content": content,
        "importance": importance_level(imp_raw),
        "importance_raw": imp_raw,
        "source": src,
        "created_at": ts,
        "updated_at": updated,
        "deleted": bool(raw.get("deleted", False)),
        "deleted_at": raw.get("deleted_at"),
    }


def parse_memory_file(data: dict, *, include_deleted: bool = False) -> list[dict]:
    """解析 memory_state.json 全部长期记忆。"""
    items: list[dict] = []
    for i, entry in enumerate(data.get("long_term", []) or []):
        if not isinstance(entry, dict):
            continue
        if entry.get("deleted") and not include_deleted:
            continue
        src = str(entry.get("source") or "model")
        items.append(parse_memory(entry, index=i, source=src))
    return items
