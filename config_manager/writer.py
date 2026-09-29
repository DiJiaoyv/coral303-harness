"""配置写入器：写回文件并热重载；失败时回滚。"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from config_manager.loader import SOURCE_PATHS, get_config_version, load_all_configs, load_source_raw
from config_manager.registry import MASK, UNDO_WINDOW_SEC, get_item, requires_restart
from config_manager.validator import coerce_value, validate, validate_many

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_undo_lock = threading.Lock()
_undo_stack: dict[str, Any] | None = None


def _set_nested(data: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _env_value_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_source_raw(source: str, content: dict) -> None:
    """将完整内容写入配置源文件。"""
    path = SOURCE_PATHS[source]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if source.endswith(".json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return

    # .env 风格：保留未知键，按字母序写出已知+未知
    lines: list[str] = []
    for key in sorted(content.keys()):
        lines.append(f"{key}={_env_value_str(content[key])}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")


def reload_modules_for_sources(sources: set[str]) -> tuple[bool, str]:
    """按受影响的配置源触发模块热重载。"""
    modules: set[str] = set()
    for _g, _l, item in iter_items():
        if item["source"] in sources:
            modules.add(item.get("module") or "")

    try:
        if "performance" in modules or "performance.env" in sources:
            from performance.config import reload_config as perf_reload

            perf_reload()

        if "safety" in modules or "safety.env" in sources:
            from safety.config import reload_config as safety_reload
            from safety.loader import reload_word_lists

            safety_reload()
            try:
                reload_word_lists()
            except Exception:
                logger.exception("safety word list reload failed")

        if "harness" in modules or "config.json" in sources:
            # harness_config 无缓存；刷新已缓存引擎
            try:
                from app.routes import data_routes

                for engine in list(getattr(data_routes, "_engines", {}).values()):
                    if hasattr(engine, "reload_config"):
                        engine.reload_config()
            except Exception:
                logger.debug("engine reload skipped", exc_info=True)

        # flask/.env：写入即可，多数项需重启；不抛错
        return True, ""
    except Exception as exc:
        logger.exception("config reload failed")
        return False, str(exc)


def _snapshot_sources(sources: set[str]) -> dict[str, dict]:
    return {s: load_source_raw(s) for s in sources}


def _restore_sources(snapshots: dict[str, dict]) -> None:
    for source, content in snapshots.items():
        write_source_raw(source, content)


def _push_undo(snapshots: dict[str, dict], changes: dict[str, Any]) -> None:
    global _undo_stack
    with _undo_lock:
        _undo_stack = {
            "ts": time.time(),
            "snapshots": snapshots,
            "changes": changes,
        }


class ConfigVersionConflict(Exception):
    """乐观锁：配置版本与客户端不一致。"""

    def __init__(self, message: str = "配置已被其他管理员修改，请刷新后重试"):
        super().__init__(message)
        self.message = message


def check_config_version(client_version: str | None) -> None:
    """客户端 version 与当前不一致时抛出 ConfigVersionConflict。"""
    if client_version is None or client_version == "":
        return
    current = get_config_version()
    if client_version != current:
        raise ConfigVersionConflict()


def undo_last() -> tuple[bool, str]:
    """撤销窗口内撤销上一次保存。"""
    global _undo_stack
    with _undo_lock:
        stack = _undo_stack
        if not stack:
            return False, "没有可撤销的修改"
        if time.time() - stack["ts"] > UNDO_WINDOW_SEC:
            _undo_stack = None
            mins = UNDO_WINDOW_SEC // 60
            return (
                False,
                f"撤销窗口已过期（{mins} 分钟）。可从备份管理页面恢复历史配置。",
            )
        snapshots = stack["snapshots"]
        _undo_stack = None

    try:
        _restore_sources(snapshots)
        ok, err = reload_modules_for_sources(set(snapshots.keys()))
        if not ok:
            return False, f"撤销后热重载失败: {err}"
        return True, "已撤销到修改前状态"
    except Exception as exc:
        return False, str(exc)


def _restart_keys_from_changes(changes: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in changes:
        if requires_restart(key):
            item = get_item(key)
            labels.append(item["label"] if item else key)
    return labels


def save_configs(
    updates: dict[str, Any],
    *,
    skip_backup: bool = False,
    version: str | None = None,
) -> tuple[bool, str, dict[str, str]]:
    """
    批量保存配置。

    Returns:
        (ok, message, field_errors)
    """
    try:
        check_config_version(version)
    except ConfigVersionConflict as exc:
        return False, exc.message, {"_version": exc.message}

    if not updates:
        return False, "没有要保存的变更", {}

    # 过滤敏感掩码（表示未改）
    cleaned: dict[str, Any] = {}
    for key, value in updates.items():
        item = get_item(key)
        if item is None:
            return False, f"未知配置项: {key}", {key: "未知配置项"}
        if item.get("sensitive") and value == MASK:
            continue
        cleaned[key] = value

    if not cleaned:
        return True, "无实际变更（敏感字段未修改）", {}

    ok, errors = validate_many(cleaned)
    if not ok:
        return False, "校验失败", errors

    # 按 source 分组写入
    by_source: dict[str, list[tuple[dict, Any]]] = {}
    for key, value in cleaned.items():
        item = get_item(key)
        assert item is not None
        coerced = coerce_value(item, value)
        by_source.setdefault(item["source"], []).append((item, coerced))

    sources = set(by_source.keys())
    before = _snapshot_sources(sources)

    if not skip_backup:
        from config_manager.backup import create_backup

        create_backup(note="auto before save", redact=True)

    try:
        for source, pairs in by_source.items():
            raw = load_source_raw(source)
            if source.endswith(".json"):
                data = dict(raw) if raw else {}
                for item, coerced in pairs:
                    _set_nested(data, item["path"], coerced)
                write_source_raw(source, data)
            else:
                data = dict(raw)
                for item, coerced in pairs:
                    data[item["path"]] = _env_value_str(coerced)
                write_source_raw(source, data)

        reload_ok, reload_err = reload_modules_for_sources(sources)
        if not reload_ok:
            _restore_sources(before)
            reload_modules_for_sources(sources)
            return False, f"热重载失败已回滚: {reload_err}", {}

        _push_undo(before, cleaned)
        restart_keys = _restart_keys_from_changes(cleaned)
        msg = "配置已更新"
        if restart_keys:
            msg += "；请手动重启服务以使以下项生效：" + "、".join(restart_keys)
        return True, msg, {}
    except Exception as exc:
        logger.exception("save_configs failed")
        try:
            _restore_sources(before)
            reload_modules_for_sources(sources)
        except Exception:
            logger.exception("rollback failed")
        return False, f"保存失败已回滚: {exc}", {}


def save_config(key: str, value: Any) -> bool:
    """单键保存（兼容需求 API）。"""
    ok, _msg, _errs = save_configs({key: value})
    return ok


def reset_keys(keys: list[str] | None = None) -> tuple[bool, str]:
    """将指定键或全部重置为默认值。"""
    if keys is None:
        updates = {item["key"]: item["default"] for _g, _l, item in iter_items()}
    else:
        updates = {}
        for key in keys:
            item = get_item(key)
            if item is None:
                return False, f"未知配置项: {key}"
            updates[key] = item["default"]
    ok, msg, errs = save_configs(updates)
    if not ok and errs:
        return False, "; ".join(f"{k}: {v}" for k, v in errs.items())
    return ok, msg


def import_configs(
    data: dict[str, Any],
    *,
    version: str | None = None,
) -> tuple[bool, str, dict[str, str]]:
    """从导出的扁平 JSON 导入（忽略未知键与 MASK）。"""
    updates: dict[str, Any] = {}
    for key, value in data.items():
        if get_item(key) is None:
            continue
        if value == MASK:
            continue
        updates[key] = value
    return save_configs(updates, version=version)
