"""Soul 文件路径与角色目录解析。"""
from __future__ import annotations

import os

from soul.migration import soul_paths

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def character_soul_dir(user_id: int, character_key: str) -> str:
    return os.path.join(BASE_DIR, "users", str(user_id), "characters", character_key)


def paths_for_character(character) -> dict[str, str]:
    char_dir = character_soul_dir(character.user_id, character.character_key)
    return soul_paths(char_dir)
