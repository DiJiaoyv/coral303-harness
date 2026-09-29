"""记忆搜索与过滤（关键词 + 重要性 + 时间 + 来源）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memory.config import PER_PAGE
from memory.io import load_raw_memories, memory_file_path, parse_date, sanitize_keyword
from memory.parser import parse_memory_file
import json
import os


def _importance_matches(item: dict, importance: str | int | None) -> bool:
    if importance is None or importance == "":
        return True
    if isinstance(importance, int) or str(importance).isdigit():
        return item.get("importance_raw") == int(importance)
    return item.get("importance") == str(importance)


def search_memories(
    user_id: int,
    character_key: str,
    *,
    keyword: str | None = None,
    importance: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
    page: int = 1,
    per_page: int = PER_PAGE,
    include_deleted: bool = False,
) -> tuple[list[dict], int]:
    keyword = sanitize_keyword(keyword)
    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    path = memory_file_path(user_id, character_key)
    all_items: list[dict] = []
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_items = parse_memory_file(
                data if isinstance(data, dict) else {},
                include_deleted=include_deleted,
            )
        except (json.JSONDecodeError, OSError):
            all_items = load_raw_memories(user_id, character_key)
    else:
        all_items = load_raw_memories(user_id, character_key)

    all_items.sort(key=lambda x: x["created_at"], reverse=True)

    start_dt = parse_date(date_from)
    end_dt = parse_date(date_to, end_of_day=True)

    filtered: list[dict] = []
    for item in all_items:
        if not include_deleted and item.get("deleted"):
            continue
        if not _importance_matches(item, importance):
            continue
        if source and item.get("source") != source:
            continue
        if keyword and keyword.lower() not in item["content"].lower():
            continue
        if start_dt and item["created_at"] < start_dt:
            continue
        if end_dt and item["created_at"] > end_dt:
            continue
        filtered.append(item)

    total = len(filtered)
    start = (page - 1) * per_page
    return filtered[start : start + per_page], total


def search_memories_by_character_id(
    character_id: int,
    *,
    user_id: int | None = None,
    keyword: str | None = None,
    importance: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
    page: int = 1,
    per_page: int = PER_PAGE,
    include_deleted: bool = False,
    require_owner: bool = False,
) -> tuple[list[dict], int, dict, int, str]:
    from app.models.user import CharacterRecord
    from extensions import db

    char = db.session.get(CharacterRecord, character_id)
    if not char or char.deleted:
        raise LookupError("角色不存在")
    if require_owner and user_id is not None and char.user_id != user_id:
        raise PermissionError("无权查看该角色记忆")

    items, total = search_memories(
        char.user_id,
        char.character_key,
        keyword=keyword,
        importance=importance,
        date_from=date_from,
        date_to=date_to,
        source=source,
        page=page,
        per_page=per_page,
        include_deleted=include_deleted,
    )

    all_items, _ = search_memories(
        char.user_id,
        char.character_key,
        per_page=10000,
        include_deleted=False,
    )
    high_count = sum(1 for x in all_items if x["importance"] == "high")
    stats = {
        "total": len(all_items),
        "high_count": high_count,
        "filtered_total": total,
        "trend_labels": [],
        "trend_values": [],
    }
    now = datetime.now(timezone.utc)
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        stats["trend_labels"].append(day.strftime("%m-%d"))
        count = sum(1 for x in all_items if x["created_at"].date() == day)
        stats["trend_values"].append(count)

    return items, total, stats, char.user_id, char.display_name
