"""配置备份：创建、列表、恢复；自动裁剪旧备份。"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any

from config_manager.loader import SOURCE_PATHS, load_source_raw
from config_manager.registry import MASK, PIN_MARKER, get_item, get_max_backups, is_sensitive, iter_items

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(PROJECT_ROOT, "config_manager", "backups")

_TS_RE = re.compile(r"^backup_(\d{8}T\d{6}(?:\.\d+)?Z)\.json$")


def _ensure_dir() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _redact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """备份中敏感字段脱敏。"""
    files = snapshot.get("files") or {}
    redacted_files: dict[str, Any] = {}
    for source, content in files.items():
        if source.endswith(".json"):
            redacted_files[source] = content
            continue
        if not isinstance(content, dict):
            redacted_files[source] = content
            continue
        env_copy = dict(content)
        for _g, _l, item in iter_items():
            if item["source"] != source or not item.get("sensitive"):
                continue
            path = item["path"]
            if path in env_copy and env_copy[path] not in ("", None):
                env_copy[path] = MASK
        redacted_files[source] = env_copy
    out = dict(snapshot)
    out["files"] = redacted_files
    out["redacted"] = True
    return out


def _is_pinned_note(note: str) -> bool:
    return PIN_MARKER in (note or "")


def _normalize_pin_note(note: str, *, pinned: bool) -> str:
    note = (note or "").strip()
    if pinned:
        if PIN_MARKER not in note:
            note = f"{PIN_MARKER} {note}".strip()
    else:
        note = note.replace(PIN_MARKER, "").strip()
    return note


def create_backup(*, note: str = "", redact: bool = True, pinned: bool = False) -> str:
    """
    备份当前全部配置源文件。

    pinned=True 或 note 含 [PIN] 时标记为关键备份，不参与自动裁剪。

    Returns:
        备份时间戳字符串
    """
    _ensure_dir()
    ts = _timestamp()
    note = _normalize_pin_note(note, pinned=pinned or _is_pinned_note(note))
    files: dict[str, Any] = {}
    for source, path in SOURCE_PATHS.items():
        if not os.path.isfile(path):
            files[source] = {} if source.endswith(".json") else {}
            continue
        files[source] = load_source_raw(source)

    snapshot = {
        "timestamp": ts,
        "note": note,
        "pinned": _is_pinned_note(note),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    if redact:
        snapshot = _redact_snapshot(snapshot)

    path = os.path.join(BACKUP_DIR, f"backup_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    _prune_old()
    return ts


def list_backups() -> list[dict[str, Any]]:
    _ensure_dir()
    items: list[dict[str, Any]] = []
    for name in os.listdir(BACKUP_DIR):
        m = _TS_RE.match(name)
        if not m:
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        note = ""
        pinned = False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            note = data.get("note") or ""
            pinned = bool(data.get("pinned")) or _is_pinned_note(note)
        except Exception:
            pass
        items.append({
            "timestamp": m.group(1),
            "filename": name,
            "path": path,
            "size": size,
            "mtime": mtime,
            "note": note,
            "pinned": pinned,
        })
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items


def get_backup(timestamp: str) -> dict[str, Any] | None:
    path = os.path.join(BACKUP_DIR, f"backup_{timestamp}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def restore_backup(timestamp: str) -> tuple[bool, str]:
    """
    恢复备份：先备份当前配置，再写回备份中的文件内容。

    注意：脱敏备份中的敏感字段不会覆盖真实密钥（跳过 MASK）。
    """
    snapshot = get_backup(timestamp)
    if snapshot is None:
        return False, f"备份不存在: {timestamp}"

    # 恢复前先快照当前状态
    create_backup(note=f"auto before restore {timestamp}", redact=True)

    files = snapshot.get("files") or {}
    try:
        from config_manager.writer import write_source_raw, reload_modules_for_sources

        touched: set[str] = set()
        for source, content in files.items():
            if source not in SOURCE_PATHS:
                continue
            if source.endswith(".json"):
                if isinstance(content, dict):
                    write_source_raw(source, content)
                    touched.add(source)
            else:
                if not isinstance(content, dict):
                    continue
                # 合并：MASK 表示未知，不覆盖
                current = load_source_raw(source)
                merged = dict(current)
                for k, v in content.items():
                    if v == MASK:
                        continue
                    merged[k] = v
                write_source_raw(source, merged)
                touched.add(source)

        ok, err = reload_modules_for_sources(touched)
        if not ok:
            return False, f"恢复后热重载失败: {err}"
        return True, "已恢复备份"
    except Exception as exc:
        return False, str(exc)


def set_backup_pinned(timestamp: str, pinned: bool) -> tuple[bool, str]:
    """固定或取消固定备份。"""
    snapshot = get_backup(timestamp)
    if snapshot is None:
        return False, f"备份不存在: {timestamp}"
    note = _normalize_pin_note(snapshot.get("note") or "", pinned=pinned)
    snapshot["note"] = note
    snapshot["pinned"] = pinned
    path = os.path.join(BACKUP_DIR, f"backup_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return True, "已固定备份" if pinned else "已取消固定"


def _prune_old() -> None:
    items = list_backups()
    limit = get_max_backups()
    unpinned = [i for i in items if not i.get("pinned")]
    to_remove = unpinned[limit:]
    for old in to_remove:
        try:
            os.remove(old["path"])
        except OSError:
            pass
