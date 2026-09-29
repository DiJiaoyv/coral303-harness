"""Validate Soul Core and State payloads."""
from __future__ import annotations

from soul.core_schema import CORE_FIELDS, DEFAULT_CORE
from soul.state_schema import ARC_STAGES, DEFAULT_STATE, STATE_FIELDS


def _as_str(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() if isinstance(value, (str, int, float)) else default


def _as_str_list(value, default: list[str] | None = None) -> list[str]:
    default = default or []
    if not isinstance(value, list):
        return list(default)
    return [str(item).strip() for item in value if str(item).strip()]


def validate_core(data: dict | None, *, template: dict | None = None) -> tuple[dict, list[str]]:
    """Return sanitized core dict and warning messages."""
    warnings: list[str] = []
    base = dict(DEFAULT_CORE)
    if template:
        for key in CORE_FIELDS:
            if key in template:
                base[key] = template[key]

    if not isinstance(data, dict):
        warnings.append("核心文件无效，已使用默认核心。")
        return base, warnings

    result = dict(base)
    result["version"] = max(1, int(data.get("version", base["version"]) or 1))
    result["locked"] = bool(data.get("locked", True))

    for key in CORE_FIELDS:
        if key not in data:
            warnings.append(f"核心缺少字段 {key}，已使用默认值。")
            continue
        if key in ("core_traits", "catchphrases", "vocabulary"):
            result[key] = _as_str_list(data.get(key), base.get(key, []))
        else:
            result[key] = _as_str(data.get(key), base.get(key, ""))

    if not result["name"]:
        result["name"] = base["name"]
        warnings.append("核心 name 为空，已回退默认值。")

    return result, warnings


def validate_state(data: dict | None, *, template: dict | None = None) -> tuple[dict, list[str]]:
    """Return sanitized state dict and warning messages."""
    warnings: list[str] = []
    base = dict(DEFAULT_STATE)
    if template:
        for key in STATE_FIELDS:
            if key in template:
                base[key] = template[key]

    if not isinstance(data, dict):
        warnings.append("状态文件无效，已重置为默认状态。")
        return base, warnings

    result = dict(base)
    arc = _as_str(data.get("arc_stage"), base["arc_stage"])
    if arc not in ARC_STAGES:
        warnings.append(f"弧光阶段 {arc!r} 无效，已重置为默认值。")
        arc = base["arc_stage"]
    result["arc_stage"] = arc
    result["current_goal"] = _as_str(data.get("current_goal"), base["current_goal"]) or base["current_goal"]
    return result, warnings
