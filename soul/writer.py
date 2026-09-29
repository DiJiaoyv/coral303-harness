"""Write Soul Core and State files with backups."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

from soul.core_schema import CORE_FIELDS
from soul.state_schema import STATE_FIELDS

BACKUP_DIRNAME = "core_backups"


def _atomic_write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def backup_core(core_path: str, version: int) -> str:
    char_dir = os.path.dirname(core_path)
    backup_dir = os.path.join(char_dir, BACKUP_DIRNAME)
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = os.path.join(backup_dir, f"soul_core_v{version}_{stamp}.json")
    shutil.copy2(core_path, backup_path)
    return backup_path


def write_core(core: dict, core_path: str, *, backup: bool = True) -> int:
    """
    Persist core JSON. When backup=True and file exists, copy old version first.
    Returns new version number.
    """
    payload = {key: core.get(key) for key in ("version", "locked", *CORE_FIELDS)}
    payload["version"] = max(1, int(payload.get("version") or 1))
    payload["locked"] = bool(payload.get("locked", True))

    if backup and os.path.isfile(core_path):
        old_version = payload["version"]
        try:
            with open(core_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            old_version = int(old.get("version", old_version))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            old_version = payload["version"]
        backup_core(core_path, old_version)

    _atomic_write(core_path, payload)
    return int(payload["version"])


def write_core_update(
    core_path: str,
    updates: dict,
    *,
    force_unlock: bool = False,
) -> tuple[dict, dict, int]:
    """
    Apply core updates with version bump.
    Returns (new_core, diff, new_version).
    """
    if os.path.isfile(core_path):
        with open(core_path, "r", encoding="utf-8") as f:
            old = json.load(f)
    else:
        from soul.core_schema import default_core

        old = default_core()

    if old.get("locked") and not force_unlock:
        raise PermissionError("核心已锁定，需要强制解锁后才能修改。")

    new_core = dict(old)
    diff: dict[str, tuple] = {}

    if force_unlock:
        if old.get("locked"):
            diff["locked"] = (True, False)
        new_core["locked"] = False

    for key in CORE_FIELDS:
        if key not in updates:
            continue
        new_val = updates[key]
        old_val = old.get(key)
        if new_val != old_val:
            diff[key] = (old_val, new_val)
            new_core[key] = new_val

    if not diff:
        return new_core, diff, int(old.get("version", 1))

    new_version = int(old.get("version", 1)) + 1
    new_core["version"] = new_version
    write_core(new_core, core_path, backup=True)
    return new_core, diff, new_version


def write_state(state: dict, state_path: str) -> None:
    payload = {key: state.get(key) for key in STATE_FIELDS}
    _atomic_write(state_path, payload)


def write_state_from_soul(soul, state_path: str) -> None:
    from soul.loader import soul_to_state_dict

    write_state(soul_to_state_dict(soul), state_path)
