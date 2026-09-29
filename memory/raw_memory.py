"""Raw Memory —— 事件记忆（具体发生过什么）。

**职责**：
    - 存储「某轮对话中发生了什么」这种可定位到时间点的事件
    - 条目带 importance（1–5）、可加 embedding 便于检索
    - **只通过 Memory Writer 写入**（Write Gate 规则优先 + 灰区可选 LLM）
    - **不会自动 FIFO 弹掉**，除非以后做 TTL 或分档归档

对应 v0.1 character_memory.Memory.long_term 的「具体事件部分」。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from embeddings import cosine_similarity

RAW_MEMORY_SCHEMA_VERSION = "2.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_VALID_CATEGORIES = {
    "fact",                 # 客观事实（用户提到的个人信息）
    "event",                # 对话事件（用户今天说怕黑）
    "promise",              # 承诺约定（角色答应帮忙找某人）
    "narrative_progress",   # 叙事推进（接下了某契约）
    "preference_hint",      # 偏好暗示（待 semantic 提炼的半成品，也允许先存 raw）
    "other",
}


@dataclass
class RawMemoryEntry:
    memory_id: str                       # e.g. "raw_20260827T0915_0001"
    category: str                        # 见 _VALID_CATEGORIES
    content: str                         # 事实文本
    importance: int = 3                  # 1 低 – 5 极高
    timestamp: str = field(default_factory=_now_iso)
    # 证据定位：方便回溯来源
    turn_id: str | None = None           # 哪一轮对话产生的
    session_id: str | None = None
    # 可选：embedding
    embedding: list[float] | None = None
    # 可选：是否已被 Semantic Memory 消费（方便以后做批处理回填）
    consumed_by_semantic: bool = False
    deleted: bool = False

    def __post_init__(self) -> None:
        if self.category not in _VALID_CATEGORIES:
            self.category = "other"
        self.importance = max(1, min(5, int(self.importance)))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # embedding 不存磁盘（避免 JSON 膨胀，按需重新生成 + 走 retrieval 缓存）
        d.pop("embedding", None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawMemoryEntry":
        return cls(
            memory_id=str(data.get("memory_id") or f"raw_{int(datetime.now().timestamp())}"),
            category=str(data.get("category", "other")),
            content=str(data.get("content", data.get("fact", ""))),
            importance=int(data.get("importance", 3)),
            timestamp=str(data.get("timestamp") or _now_iso()),
            turn_id=data.get("turn_id"),
            session_id=data.get("session_id"),
            embedding=None,  # 不持久化
            consumed_by_semantic=bool(data.get("consumed_by_semantic", False)),
            deleted=bool(data.get("deleted", False)),
        )


class RawMemory:
    """Raw Memory 集合：提供 append / 搜索 / 序列化。"""

    def __init__(self) -> None:
        self.schema_version: str = RAW_MEMORY_SCHEMA_VERSION
        self.entries: list[RawMemoryEntry] = []
        # embedding 缓存（运行时用，不存盘）
        self._embed_cache: dict[str, list[float]] = {}
        self._embed_fn: Callable[[str], list[float]] | None = None

    # ---------- 初始化 ----------
    def set_embedder(self, fn: Callable[[str], list[float]] | None) -> None:
        self._embed_fn = fn

    # ---------- 增删 ----------
    def add_entry(self, entry: RawMemoryEntry) -> None:
        # 简单 dedupe：如果有完全相同的 content 且没删除，视为重复不追加
        # （真正的"语义重复判断"留给 Memory Write Gate + Semantic）
        for existing in self.entries:
            if not existing.deleted and existing.content == entry.content:
                return
        self.entries.append(entry)

    def add_from_extractor(
        self,
        fact: str,
        importance: int = 3,
        *,
        category: str = "fact",
        turn_id: str | None = None,
        session_id: str | None = None,
    ) -> RawMemoryEntry:
        """从 memory_extractor.py 输出的 {fact, importance} 构造 RawMemoryEntry。"""
        import uuid
        mid = turn_id or uuid.uuid4().hex[:12]
        entry = RawMemoryEntry(
            memory_id=f"raw_{mid}_{len(self.entries):04d}",
            category=category,
            content=fact,
            importance=importance,
            turn_id=turn_id,
            session_id=session_id,
        )
        # 如设置了 embed_fn，生成 embedding（运行时用；不持久化）
        if self._embed_fn:
            try:
                entry.embedding = self._embed_fn(fact)
                self._embed_cache[entry.memory_id] = entry.embedding
            except Exception:
                entry.embedding = None
        self.add_entry(entry)
        return entry

    def active_entries(self) -> list[RawMemoryEntry]:
        return [e for e in self.entries if not e.deleted]

    # ---------- 搜索（供 retrieval 层用，一般不直接被 context_builder 调） ----------
    def keyword_search(
        self,
        query: str,
        limit: int = 3,
    ) -> list[RawMemoryEntry]:
        keywords = [w.strip().lower() for w in query.split() if w.strip()]
        active = self.active_entries()
        if not keywords:
            return active[-limit:]
        scored: list[tuple[float, RawMemoryEntry]] = []
        for e in active:
            text_lower = e.content.lower()
            match_count = sum(1 for kw in keywords if kw in text_lower)
            if match_count > 0:
                scored.append((match_count * e.importance, e))
        if not scored:
            return active[-limit:]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def vector_search(
        self,
        query: str,
        limit: int = 3,
    ) -> list[RawMemoryEntry]:
        if not self._embed_fn:
            return []
        try:
            query_vec = self._embed_fn(query)
        except Exception:
            return []
        if not query_vec:
            return []
        scored: list[tuple[float, RawMemoryEntry]] = []
        for e in self.active_entries():
            vec = self._resolve_embedding(e)
            if not vec:
                continue
            sim = cosine_similarity(query_vec, vec)
            if sim > 0:
                scored.append((sim * e.importance, e))
        if not scored:
            return []
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def _resolve_embedding(self, entry: RawMemoryEntry) -> list[float] | None:
        if entry.embedding:
            return entry.embedding
        cached = self._embed_cache.get(entry.memory_id)
        if cached:
            return cached
        if not self._embed_fn:
            return None
        try:
            vec = self._embed_fn(entry.content)
        except Exception:
            return None
        if vec:
            self._embed_cache[entry.memory_id] = vec
        return vec

    # ---------- 迁移：旧 Memory.to_dict() 的 long_term ----------
    @classmethod
    def from_legacy_memory_dict(cls, data: dict[str, Any]) -> "RawMemory":
        obj = cls()
        for idx, item in enumerate(data.get("long_term") or []):
            try:
                fact = item.get("fact", "")
                if not isinstance(fact, str) or not fact.strip():
                    continue
                entry = RawMemoryEntry(
                    memory_id=f"raw_legacy_{idx:05d}",
                    category="fact",
                    content=fact.strip(),
                    importance=int(item.get("importance", 3)),
                    timestamp=str(item.get("timestamp") or _now_iso()),
                    deleted=bool(item.get("deleted", False)),
                )
                obj.entries.append(entry)
            except Exception:
                continue
        return obj

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RawMemory":
        data = data or {}
        obj = cls()
        for e in data.get("entries") or []:
            try:
                obj.entries.append(RawMemoryEntry.from_dict(e))
            except Exception:
                continue
        return obj

    def save(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, filepath: str) -> bool:
        if not os.path.isfile(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            new_obj = self.from_dict(data)
            self.entries = new_obj.entries
            self.schema_version = new_obj.schema_version
            return True
        except (json.JSONDecodeError, OSError):
            return False
