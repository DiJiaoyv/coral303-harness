"""记忆写入：增删改/恢复，直接操作 memory_state.json。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from memory.config import (
    MAX_CONTENT_LENGTH,
    SOFT_DELETE_RETENTION_DAYS,
    VALID_SOURCES,
)
from memory.parser import importance_level, parse_memory
from memory.io import memory_file_path

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPERATIONS_LOG = os.path.join(BASE_DIR, "memory_operations.log")


class MemoryValidationError(ValueError):
    pass


class MemoryNotFoundError(LookupError):
    pass


class MemoryPermissionError(PermissionError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_content(content: str) -> str:
    text = (content or "").strip()
    if not text:
        raise MemoryValidationError("记忆内容不能为空")
    if len(text) > MAX_CONTENT_LENGTH:
        raise MemoryValidationError(f"记忆内容不能超过 {MAX_CONTENT_LENGTH} 字符")
    return text


def _validate_importance(importance: int) -> int:
    try:
        value = int(importance)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("重要性必须是 1-5 的整数") from exc
    if value < 1 or value > 5:
        raise MemoryValidationError("重要性必须是 1-5 的整数")
    return value


def _validate_source(source: str) -> str:
    src = (source or "model").strip()
    if src not in VALID_SOURCES:
        raise MemoryValidationError("无效的来源类型")
    return src


def log_memory_operation(
    operator: str,
    character_id: int,
    memory_id: str,
    action: str,
    details: str = "",
) -> None:
    line = (
        f"{_now_iso()} | {operator} | character={character_id} | "
        f"memory={memory_id} | {action} | {details}\n"
    )
    try:
        with open(OPERATIONS_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        logger.exception("写入 memory_operations.log 失败")


def _resolve_character(
    character_id: int,
    user_id: int | None = None,
    *,
    require_owner: bool = False,
) -> tuple[int, str]:
    """返回 (owner_user_id, character_key)。"""
    try:
        from flask import has_app_context

        if has_app_context():
            from app.models.user import CharacterRecord

            char = CharacterRecord.query.get(character_id)
            if char is None or char.deleted:
                raise MemoryNotFoundError("角色不存在")
            if require_owner and user_id is not None and char.user_id != user_id:
                raise MemoryPermissionError("无权操作该角色记忆")
            return char.user_id, char.character_key
    except MemoryNotFoundError:
        raise
    except MemoryPermissionError:
        raise
    except Exception:
        pass

    from database.models import Character
    from database.session import SessionLocal

    session = SessionLocal()
    try:
        char = session.query(Character).filter_by(id=character_id, deleted=False).first()
        if char is None:
            raise MemoryNotFoundError("角色不存在")
        if require_owner and user_id is not None and char.user_id != user_id:
            raise MemoryPermissionError("无权操作该角色记忆")
        return char.user_id, char.character_key
    finally:
        session.close()


def _load_state(owner_user_id: int, character_key: str) -> tuple[str, dict]:
    path = memory_file_path(owner_user_id, character_key)
    if not os.path.isfile(path):
        return path, {
            "max_messages": 20,
            "short_term": [],
            "long_term": [],
            "use_vector": True,
        }
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("long_term", [])
    data.setdefault("short_term", [])
    return path, data


def _save_state(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _ensure_entry_id(entry: dict, index: int) -> str:
    if entry.get("id"):
        return str(entry["id"])
    content = str(entry.get("fact") or entry.get("content") or "")
    ts = entry.get("timestamp") or _now_iso()
    entry["id"] = hashlib.md5(f"{content}:{ts}:{index}".encode()).hexdigest()[:12]
    return entry["id"]


def _find_entry(long_term: list, memory_id: str) -> tuple[int, dict]:
    for i, entry in enumerate(long_term):
        if not isinstance(entry, dict):
            continue
        _ensure_entry_id(entry, i)
        if entry["id"] == memory_id:
            return i, entry
    raise MemoryNotFoundError(f"记忆不存在: {memory_id}")


def _purge_expired_deletions(long_term: list) -> int:
    """物理清理超过保留期的软删除记忆。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SOFT_DELETE_RETENTION_DAYS)
    kept: list[dict] = []
    removed = 0
    for i, entry in enumerate(long_term):
        if not isinstance(entry, dict):
            continue
        if entry.get("deleted"):
            deleted_at = entry.get("deleted_at")
            try:
                dt = datetime.fromisoformat(str(deleted_at).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                dt = None
            if dt and dt < cutoff:
                removed += 1
                continue
        kept.append(entry)
    long_term[:] = kept
    return removed


def get_raw_memory(
    user_id: int,
    character_id: int,
    memory_id: str,
    *,
    include_deleted: bool = False,
    require_owner: bool = False,
) -> dict:
    owner_id, character_key = _resolve_character(
        character_id, user_id, require_owner=require_owner
    )
    _, data = _load_state(owner_id, character_key)
    _, entry = _find_entry(data.get("long_term", []), memory_id)
    if entry.get("deleted") and not include_deleted:
        raise MemoryNotFoundError(f"记忆不存在: {memory_id}")
    idx = data["long_term"].index(entry)
    parsed = parse_memory(entry, index=idx, source=entry.get("source", "model"))
    if entry.get("embedding"):
        vec = entry["embedding"]
        parsed["embedding_preview"] = (
            f"[{vec[0]:.4f}, {vec[1]:.4f}, …] (dim={len(vec)})"
            if len(vec) >= 2
            else f"(dim={len(vec)})"
        )
    else:
        parsed["embedding_preview"] = None
    return parsed


def add_memory(
    user_id: int,
    character_id: int,
    content: str,
    importance: int = 3,
    source: str = "user",
    *,
    operator: str = "system",
) -> dict:
    content = _validate_content(content)
    importance = _validate_importance(importance)
    source = _validate_source(source)

    owner_id, character_key = _resolve_character(
        character_id, user_id, require_owner=True
    )
    path, data = _load_state(owner_id, character_key)
    memory_id = uuid.uuid4().hex[:12]
    entry = {
        "id": memory_id,
        "fact": content,
        "importance": importance,
        "timestamp": _now_iso(),
        "source": source,
        "deleted": False,
    }
    data.setdefault("long_term", []).append(entry)
    _purge_expired_deletions(data["long_term"])
    _save_state(path, data)

    log_memory_operation(operator, character_id, memory_id, "add", content[:80])
    return parse_memory(entry, index=len(data["long_term"]) - 1, source=source)


def update_memory(
    user_id: int,
    character_id: int,
    memory_id: str,
    *,
    content: str | None = None,
    importance: int | None = None,
    operator: str = "system",
    require_owner: bool = True,
) -> dict:
    owner_id, character_key = _resolve_character(
        character_id, user_id, require_owner=require_owner
    )
    path, data = _load_state(owner_id, character_key)
    long_term = data.get("long_term", [])
    _, entry = _find_entry(long_term, memory_id)

    if entry.get("deleted"):
        raise MemoryNotFoundError(f"记忆已删除: {memory_id}")

    old_content = entry.get("fact", "")
    if content is not None:
        entry["fact"] = _validate_content(content)
        if entry["fact"] != old_content:
            entry.pop("embedding", None)
    if importance is not None:
        entry["importance"] = _validate_importance(importance)

    entry["updated_at"] = _now_iso()
    _save_state(path, data)

    log_memory_operation(
        operator,
        character_id,
        memory_id,
        "edit",
        f"importance={entry.get('importance')}",
    )
    idx = long_term.index(entry)
    return parse_memory(entry, index=idx, source=entry.get("source", "model"))


def delete_memory(
    user_id: int,
    character_id: int,
    memory_id: str,
    *,
    soft: bool = True,
    operator: str = "system",
    require_owner: bool = True,
) -> None:
    owner_id, character_key = _resolve_character(
        character_id, user_id, require_owner=require_owner
    )
    path, data = _load_state(owner_id, character_key)
    long_term = data.get("long_term", [])
    idx, entry = _find_entry(long_term, memory_id)

    if soft:
        entry["deleted"] = True
        entry["deleted_at"] = _now_iso()
        _purge_expired_deletions(long_term)
        _save_state(path, data)
        log_memory_operation(operator, character_id, memory_id, "soft_delete")
        return

    long_term.pop(idx)
    _save_state(path, data)
    log_memory_operation(operator, character_id, memory_id, "hard_delete")


def restore_memory(
    user_id: int,
    character_id: int,
    memory_id: str,
    *,
    operator: str = "system",
    require_owner: bool = True,
) -> dict:
    owner_id, character_key = _resolve_character(
        character_id, user_id, require_owner=require_owner
    )
    path, data = _load_state(owner_id, character_key)
    long_term = data.get("long_term", [])
    _, entry = _find_entry(long_term, memory_id)

    entry["deleted"] = False
    entry.pop("deleted_at", None)
    entry["updated_at"] = _now_iso()
    _save_state(path, data)

    log_memory_operation(operator, character_id, memory_id, "restore")
    idx = long_term.index(entry)
    return parse_memory(entry, index=idx, source=entry.get("source", "model"))


def batch_delete_memories(
    user_id: int,
    character_id: int,
    memory_ids: list[str],
    *,
    soft: bool = True,
    operator: str = "system",
    require_owner: bool = True,
) -> int:
    count = 0
    for mid in memory_ids:
        try:
            delete_memory(
                user_id,
                character_id,
                mid,
                soft=soft,
                operator=operator,
                require_owner=require_owner,
            )
            count += 1
        except MemoryNotFoundError:
            continue
    return count
