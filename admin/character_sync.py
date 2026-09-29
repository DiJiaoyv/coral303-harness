"""角色数据与文件系统同步。"""
import json
import os
import re

from soul.loader import load_soul_from_dir, save_soul_state
from soul.migration import soul_paths
from soul.writer import write_core_update

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slug_character_key(name: str) -> str:
    key = re.sub(r"[^\w]", "_", name.strip(), flags=re.UNICODE)
    key = re.sub(r"_+", "_", key).strip("_")
    return (key[:32] or "character")


def sync_character_to_files(character) -> None:
    """将数据库角色同步到 users/{user_id}/characters/ 目录。"""
    user_root = os.path.join(BASE_DIR, "users", str(character.user_id))
    char_dir = os.path.join(user_root, "characters", character.character_key)
    os.makedirs(char_dir, exist_ok=True)

    registry_path = os.path.join(user_root, "characters.json")
    registry = {"active": character.character_key, "base_dir": "characters", "characters": {}}
    if os.path.isfile(registry_path):
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    registry.setdefault("characters", {})[character.character_key] = {
        "name": character.display_name,
        "role": character.role or "未知",
    }
    if character.system_prompt:
        registry["characters"][character.character_key]["system_prompt"] = (
            character.system_prompt
        )
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    paths = soul_paths(char_dir)
    soul, core, _, _ = load_soul_from_dir(char_dir)
    updates = {
        "name": character.display_name,
        "role": character.role or soul.role,
    }
    if os.path.isfile(paths["core"]):
        try:
            write_core_update(paths["core"], updates, force_unlock=not core.get("locked", True))
        except PermissionError:
            pass
    else:
        from soul.validator import validate_core
        from soul.writer import write_core

        core_data, _ = validate_core(None, template=updates)
        write_core(core_data, paths["core"], backup=False)
        save_soul_state(soul, paths["state"])
