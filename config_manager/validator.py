"""配置校验器。"""
from __future__ import annotations

from typing import Any

from config_manager.registry import MASK, get_item


def validate(config_key: str, value: Any) -> tuple[bool, str]:
    """根据 registry 规则校验。返回 (ok, error_msg)。"""
    item = get_item(config_key)
    if item is None:
        return False, f"未知配置项: {config_key}"

    # 敏感字段提交掩码表示未修改
    if item.get("sensitive") and value == MASK:
        return True, ""

    typ = item.get("type", "string")
    label = item.get("label", config_key)

    try:
        coerced = coerce_value(item, value)
    except (TypeError, ValueError) as exc:
        return False, str(exc) or f"{label} 类型无效"

    if typ == "enum":
        options = item.get("options") or []
        if coerced not in options:
            return False, f"{label} 必须是以下之一: {', '.join(map(str, options))}"

    if typ in ("int", "float"):
        lo = item.get("min")
        hi = item.get("max")
        if lo is not None and hi is not None:
            if coerced < lo or coerced > hi:
                return False, f"{label} 必须在 {lo}-{hi} 之间"
        elif lo is not None and coerced < lo:
            return False, f"{label} 必须 ≥ {lo}"
        elif hi is not None and coerced > hi:
            return False, f"{label} 必须 ≤ {hi}"

    if typ == "string":
        max_len = item.get("max_length", 1024)
        if len(str(coerced)) > max_len:
            return False, f"{label} 长度不能超过 {max_len}"

    return True, ""


def coerce_value(item: dict, value: Any) -> Any:
    """将输入强制转换为配置项类型。"""
    typ = item.get("type", "string")
    label = item.get("label", item.get("key", ""))

    if typ == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on", "是"):
            return True
        if s in ("0", "false", "no", "off", "否", ""):
            return False
        raise ValueError(f"{label} 必须是布尔值")

    if typ == "int":
        if isinstance(value, bool):
            raise ValueError(f"{label} 必须是整数")
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} 必须是整数") from exc

    if typ == "float":
        try:
            return float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} 必须是数字") from exc

    if typ == "enum":
        return str(value).strip()

    # string
    return str(value) if value is not None else ""


def validate_many(updates: dict[str, Any]) -> tuple[bool, dict[str, str]]:
    """批量校验。返回 (全部通过, {key: error})。"""
    errors: dict[str, str] = {}
    for key, value in updates.items():
        ok, msg = validate(key, value)
        if not ok:
            errors[key] = msg
    return (len(errors) == 0), errors
