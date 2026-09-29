"""Migrate legacy single-file soul_state.json to Core + State layers."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

from soul.core_schema import CORE_FIELDS, DEFAULT_CORE
from soul.state_schema import STATE_FIELDS
from soul.validator import validate_core, validate_state
from soul.writer import write_core, write_state

LEGACY_FILENAME = "soul_state.json"
CORE_FILENAME = "soul_core.json"
STATE_FILENAME = "soul_state.json"
BACKUP_DIRNAME = "core_backups"


def soul_paths(char_dir: str) -> dict[str, str]:
    return {
        "legacy": os.path.join(char_dir, LEGACY_FILENAME),
        "core": os.path.join(char_dir, CORE_FILENAME),
        "state": os.path.join(char_dir, STATE_FILENAME),
        "backups": os.path.join(char_dir, BACKUP_DIRNAME),
    }


def is_legacy_combined(data: dict) -> bool:
    """True if JSON looks like an unsplit legacy soul file."""
    if not isinstance(data, dict):
        return False
    has_core = any(key in data for key in CORE_FIELDS)
    has_state = any(key in data for key in STATE_FIELDS)
    return has_core and has_state


def needs_migration(char_dir: str) -> bool:
    paths = soul_paths(char_dir)
    if os.path.isfile(paths["core"]):
        return False
    if not os.path.isfile(paths["legacy"]):
        return False
    try:
        with open(paths["legacy"], "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return is_legacy_combined(data)


def _split_legacy(data: dict, template: dict | None = None) -> tuple[dict, dict]:
    core_raw = {key: data[key] for key in CORE_FIELDS if key in data}
    state_raw = {key: data[key] for key in STATE_FIELDS if key in data}
    core, _ = validate_core(core_raw, template=template)
    state, _ = validate_state(state_raw, template=template)
    return core, state


def migrate_legacy(char_dir: str, *, template: dict | None = None) -> tuple[bool, list[str]]:
    """
    Backup legacy file, split into core + state, rollback on failure.
    Returns (success, messages).
    """
    paths = soul_paths(char_dir)
    messages: list[str] = []

    if not needs_migration(char_dir):
        return True, messages

    legacy_path = paths["legacy"]
    backup_name = (
        f"legacy_soul_state_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    backup_path = os.path.join(paths["backups"], backup_name)

    try:
        with open(legacy_path, "r", encoding="utf-8") as f:
            legacy_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        messages.append(f"无法读取旧版灵魂文件: {exc}")
        return False, messages

    core_data, state_data = _split_legacy(legacy_data, template=template)

    os.makedirs(paths["backups"], exist_ok=True)
    shutil.copy2(legacy_path, backup_path)
    messages.append(f"已备份旧版灵魂至 {backup_path}")

    core_tmp = paths["core"] + ".tmp"
    state_tmp = paths["state"] + ".tmp"
    try:
        write_core(core_data, core_tmp, backup=False)
        write_state(state_data, state_tmp)
        os.replace(core_tmp, paths["core"])
        os.replace(state_tmp, paths["state"])
        messages.append("已将旧版灵魂拆分为 core + state。")
        return True, messages
    except OSError as exc:
        for tmp in (core_tmp, state_tmp):
            if os.path.exists(tmp):
                os.remove(tmp)
        messages.append(f"迁移失败，已回滚: {exc}")
        return False, messages


def ensure_default_core(char_dir: str, *, template: dict | None = None) -> dict:
    """Create default core file if missing."""
    paths = soul_paths(char_dir)
    if os.path.isfile(paths["core"]):
        return paths["core"]
    os.makedirs(char_dir, exist_ok=True)
    core, _ = validate_core(None, template=template)
    write_core(core, paths["core"], backup=False)
    return paths["core"]
