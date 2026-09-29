"""记忆文件 I/O 与通用工具。"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from memory.config import MAX_KEYWORD_LENGTH
from memory.parser import parse_memory_file

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sanitize_keyword(keyword: str | None) -> str:
    if not keyword:
        return ""
    text = re.sub(r"[<>\"'&;]", "", keyword.strip())
    return text[:MAX_KEYWORD_LENGTH]


def memory_file_path(user_id: int, character_key: str) -> str:
    return os.path.join(
        BASE_DIR,
        "users",
        str(user_id),
        "characters",
        character_key,
        "memory_state.json",
    )


def load_raw_memories(user_id: int, character_key: str) -> list[dict]:
    path = memory_file_path(user_id, character_key)
    if not os.path.isfile(path):
        legacy = os.path.join(BASE_DIR, "memory_state.json")
        path = legacy if os.path.isfile(legacy) else path
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return parse_memory_file(data if isinstance(data, dict) else {})


def parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except ValueError:
        return None
