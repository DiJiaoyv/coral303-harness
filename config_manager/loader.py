"""配置加载器：从多文件读取并合并为扁平字典。"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from config_manager.registry import MASK, REGISTRY, enrich_item, get_item, iter_items, is_sensitive

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_PATHS = {
    "config.json": os.path.join(PROJECT_ROOT, "config.json"),
    "performance.env": os.path.join(PROJECT_ROOT, "performance", "performance.env"),
    "safety.env": os.path.join(PROJECT_ROOT, "safety", "safety.env"),
    ".env": os.path.join(PROJECT_ROOT, ".env"),
}


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _read_env(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    if not os.path.isfile(path):
        return data
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            data[key.strip()] = val.strip()
    return data


def _get_nested(data: dict, dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def load_source_raw(source: str) -> dict:
    path = SOURCE_PATHS.get(source)
    if not path:
        return {}
    if source.endswith(".json"):
        return _read_json(path)
    return _read_env(path)


def load_all_configs(*, mask_sensitive: bool = True) -> dict[str, Any]:
    """
    返回 {registry_key: value}。

    敏感字段在 mask_sensitive=True 时显示为 MASK（空值仍为空）。
    """
    cache: dict[str, dict] = {}
    result: dict[str, Any] = {}

    for _gid, _glabel, item in iter_items():
        source = item["source"]
        if source not in cache:
            cache[source] = load_source_raw(source)

        raw = cache[source]
        path = item["path"]
        if source.endswith(".json"):
            value = _get_nested(raw, path)
        else:
            value = raw.get(path)

        if value is None or value == "":
            value = item["default"]
        else:
            # env 文件中的布尔/数字保持字符串，UI 层再转换；此处尽量还原类型
            from config_manager.validator import coerce_value

            try:
                value = coerce_value(item, value)
            except ValueError:
                value = item["default"]

        if mask_sensitive and item.get("sensitive"):
            if value not in (None, "", MASK):
                result[item["key"]] = MASK
            else:
                result[item["key"]] = ""
        else:
            result[item["key"]] = value

    return result


def get_config(key: str, *, mask_sensitive: bool = True) -> Any:
    item = get_item(key)
    if item is None:
        raise KeyError(key)
    all_vals = load_all_configs(mask_sensitive=mask_sensitive)
    return all_vals.get(key, item["default"])


def get_config_version() -> str:
    """
    配置源指纹：用于乐观锁，检测并发管理员修改。

    基于各源文件 mtime + size 计算短哈希。
    """
    parts: list[str] = []
    for source in sorted(SOURCE_PATHS.keys()):
        path = SOURCE_PATHS[source]
        if os.path.isfile(path):
            st = os.stat(path)
            parts.append(f"{source}:{st.st_mtime_ns}:{st.st_size}")
        else:
            parts.append(f"{source}:missing")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def load_grouped(*, mask_sensitive: bool = True) -> list[dict]:
    """供模板使用的分组结构。"""
    values = load_all_configs(mask_sensitive=mask_sensitive)
    groups = []
    for group_id, group in REGISTRY.items():
        items = []
        for meta in group["items"]:
            entry = enrich_item(meta)
            entry["value"] = values.get(meta["key"], meta["default"])
            entry["display_value"] = entry["value"]
            items.append(entry)
        groups.append({
            "id": group_id,
            "label": group["label"],
            "items": items,
        })
    return groups


def export_dict(*, include_sensitive: bool = False) -> dict[str, Any]:
    """导出扁平配置；默认脱敏。"""
    return load_all_configs(mask_sensitive=not include_sensitive)
