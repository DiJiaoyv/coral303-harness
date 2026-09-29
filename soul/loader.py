"""Load Soul Core + State and merge into Soul instance."""
from __future__ import annotations

import json
import os

from soul.model import Soul
from soul.core_schema import CORE_FIELDS
from soul.migration import ensure_default_core, migrate_legacy, needs_migration, soul_paths
from soul.state_schema import STATE_FIELDS
from soul.validator import validate_core, validate_state


def soul_to_core_dict(soul: Soul) -> dict:
    return {key: getattr(soul, key) for key in CORE_FIELDS}


def soul_to_state_dict(soul: Soul) -> dict:
    return {key: getattr(soul, key) for key in STATE_FIELDS}


def apply_core_to_soul(soul: Soul, core: dict) -> None:
    for key in CORE_FIELDS:
        if key in core:
            setattr(soul, key, core[key])


def apply_state_to_soul(soul: Soul, state: dict) -> None:
    for key in STATE_FIELDS:
        if key in state:
            setattr(soul, key, state[key])


def load_core(core_path: str, *, template: dict | None = None) -> tuple[dict, list[str]]:
    data = None
    if os.path.isfile(core_path):
        try:
            with open(core_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return validate_core(data, template=template)


def load_state(state_path: str, *, template: dict | None = None) -> tuple[dict, list[str]]:
    data = None
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    elif os.path.isfile(state_path.replace("soul_state.json", "soul_state.json")):
        pass
    return validate_state(data, template=template)


def load_soul_from_dir(
    char_dir: str,
    *,
    template: dict | None = None,
    auto_migrate: bool = True,
) -> tuple[Soul, dict, dict, list[str]]:
    """
    Load layered soul from character directory.
    Returns (soul, core_dict, state_dict, warnings).
    """
    warnings: list[str] = []
    paths = soul_paths(char_dir)

    if auto_migrate and needs_migration(char_dir):
        ok, msgs = migrate_legacy(char_dir, template=template)
        warnings.extend(msgs)
        if not ok:
            warnings.append("自动迁移失败，将尝试兼容读取旧版文件。")

    if not os.path.isfile(paths["core"]):
        ensure_default_core(char_dir, template=template)
        warnings.append("缺少核心文件，已创建默认核心。")

    core, core_warn = load_core(paths["core"], template=template)
    warnings.extend(core_warn)

    state, state_warn = load_state(paths["state"], template=template)
    warnings.extend(state_warn)

    # Legacy fallback: core exists but state file still combined
    if not os.path.isfile(paths["state"]) and os.path.isfile(paths["legacy"]):
        try:
            with open(paths["legacy"], "r", encoding="utf-8") as f:
                legacy = json.load(f)
            if isinstance(legacy, dict):
                from soul.migration import is_legacy_combined

                if is_legacy_combined(legacy):
                    _, state_raw = _split_from_legacy(legacy, template)
                    state, extra = validate_state(state_raw, template=template)
                    warnings.extend(extra)
                else:
                    state, extra = validate_state(legacy, template=template)
                    warnings.extend(extra)
        except (json.JSONDecodeError, OSError):
            warnings.append("无法读取旧版状态文件，已使用默认状态。")

    soul = Soul(name=core.get("name", "幽灵"), role=core.get("role", "未知"))
    apply_core_to_soul(soul, core)
    apply_state_to_soul(soul, state)
    return soul, core, state, warnings


def _split_from_legacy(data: dict, template: dict | None) -> tuple[dict, dict]:
    core_raw = {key: data[key] for key in CORE_FIELDS if key in data}
    state_raw = {key: data[key] for key in STATE_FIELDS if key in data}
    core, _ = validate_core(core_raw, template=template)
    state, _ = validate_state(state_raw, template=template)
    return core, state


def load_soul_from_paths(
    soul_path: str,
    *,
    template: dict | None = None,
    auto_migrate: bool = True,
) -> tuple[Soul, dict, dict, list[str]]:
    """Compatibility helper: soul_path is legacy path under character dir."""
    char_dir = os.path.dirname(soul_path) or "."
    return load_soul_from_dir(char_dir, template=template, auto_migrate=auto_migrate)


def save_soul_state(soul: Soul, state_path: str) -> None:
    from soul.writer import write_state_from_soul

    write_state_from_soul(soul, state_path)
