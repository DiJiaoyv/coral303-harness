"""记忆读取：从 users/{user_id}/characters/{key}/memory_state.json 加载。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memory.config import PER_PAGE
from memory.io import memory_file_path
from memory.search import search_memories, search_memories_by_character_id

# 向后兼容导出
from memory.io import load_raw_memories as _load_raw_memories
from memory.io import parse_date as _parse_date
from memory.io import sanitize_keyword as _sanitize_keyword

__all__ = [
    "memory_file_path",
    "get_memories",
    "get_character_memories_by_id",
    "_load_raw_memories",
    "_parse_date",
    "_sanitize_keyword",
]


def get_memories(
    user_id: int,
    character_key: str,
    *,
    page: int = 1,
    per_page: int = PER_PAGE,
    keyword: str | None = None,
    importance_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
) -> tuple[list[dict], int, dict]:
    items, total = search_memories(
        user_id,
        character_key,
        keyword=keyword,
        importance=importance_filter,
        date_from=date_from,
        date_to=date_to,
        source=source,
        page=page,
        per_page=per_page,
    )

    all_items, _ = search_memories(user_id, character_key, per_page=10000)
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

    return items, total, stats


def get_character_memories_by_id(
    character_id: int,
    *,
    page: int = 1,
    per_page: int = PER_PAGE,
    keyword: str | None = None,
    importance_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
    user_id: int | None = None,
) -> tuple[list[dict], int, dict, int, str]:
    return search_memories_by_character_id(
        character_id,
        user_id=user_id,
        keyword=keyword,
        importance=importance_filter,
        date_from=date_from,
        date_to=date_to,
        source=source,
        page=page,
        per_page=per_page,
        require_owner=user_id is not None,
    )
