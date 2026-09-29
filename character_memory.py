"""[DEPRECATED] Read-Only Compatibility Shim —— v0.1 character_memory.Memory 的只读桥接层。

**v0.3 重要变更（用户硬约束）**：
    所有 memory 写入必须经过 MemoryWriter（用户硬约束「不要允许
    character_memory 直接写」）。本 shim 的 add_message / add_fact / save
    **已全部禁用**，直接抛 RuntimeError：既不做兼容层转发到 MemoryWriter，
    也不允许 fallback 直接写 `_session.add` / `_raw.add_from_extractor` /
    `_session.save`。老代码必须迁移到 v0.2 SessionBuffer / RawMemory /
    SemanticMemory + memory_writer.MemoryWriter。

**为什么这个文件还留着**：
    - tests/test_e2e.py 等老代码还在 `from character_memory import Memory`
      （仅 import 和读取/查询，不调写操作）
    - 保留只读 API（to_dict / load / get_relevant_facts）让老代码读取不崩
    - 写操作一律抛 RuntimeError，强制迁移到 MemoryWriter

**迁移时序**：

    Phase 1（现在）   本文件 = 只读 shim：写操作全禁用，读操作保留
                     所有 memory 写入通过 memory_writer.py（一等公民）
    Phase 2（后续）  把 tests/test_e2e.py 的 `from character_memory import Memory`
                     改成直接用 SessionBuffer + RawMemory + SemanticMemory + MemoryRetriever
    Phase 3（最后）  把本文件物理删除，完成拆分。

**Compat 内部实现（v0.3 起，只读）**：
    self.short_term → SessionBuffer.messages（同步镜像，只读）
    self.long_term  → RawMemory.entries（同步镜像，只读）
    self.max_messages = SessionBuffer.max_messages
    self.add_message / add_fact / save → 全部抛 RuntimeError（禁用）
    self.load(filepath) → 优先读 v0.2，回退 v0.1（只读不写）
    self.get_relevant_facts(query) → 查询，只读
"""
from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone
from typing import Callable

from embeddings import cosine_similarity

# —— 新架构 v0.2 模块 ——
from memory.session_buffer import SessionBuffer, SessionMessage
from memory.raw_memory import RawMemory, RawMemoryEntry

_WRITES_DISABLED_MSG = (
    "since v0.3, character_memory.Memory write operations are DISABLED "
    "(user hard constraint: all memory writes must go through memory_writer.py). "
    "Use memory_writer.MemoryWriter.add_session_message / write_raw_entry / "
    "save_all instead. This shim is now READ-ONLY "
    "(load / get_relevant_facts / to_dict)."
)

_DEPRECATION_MSG = (
    "character_memory.Memory is deprecated and will be removed. "
    "Use memory.SessionBuffer / memory.RawMemory / memory.SemanticMemory / "
    "memory.MemoryRetriever directly (v0.2 layered architecture). "
    "For bulk migration of legacy memory_state.json, use: "
    "`python -m memory.migration migrate --input <path>`."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _legacy_session_path(dir_: str) -> str:
    return os.path.join(dir_, "memory_session.json")


def _legacy_raw_path(dir_: str) -> str:
    return os.path.join(dir_, "memory_raw.json")


def _legacy_semantic_path(dir_: str) -> str:
    return os.path.join(dir_, "memory_semantic.json")


class Memory:
    """Deprecated READ-ONLY bridge class.

    v0.3 起：所有写操作（add_message / add_fact / save）已禁用，抛 RuntimeError。
    只保留读取 / 查询 API（load / get_relevant_facts / to_dict）。

        Memory(max_rounds=10, embed_fn=None, use_vector=True)
        .load(filepath)                                      # 只读
        .get_relevant_facts(query, limit=3) -> list[dict]    # 只读查询
        .to_dict() -> dict                                   # 只读快照
        # add_message / add_fact / save → 抛 RuntimeError（请用 memory_writer.MemoryWriter）
    """

    def __init__(
        self,
        max_rounds: int = 10,
        embed_fn: Callable[[str], list[float]] | None = None,
        use_vector: bool = True,
    ):
        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

        # ==== v0.2 权威存储（只读：写入统一走 memory_writer.MemoryWriter）====
        self._session = SessionBuffer(max_messages=max(2, int(max_rounds) * 2))
        self._raw = RawMemory()
        self._raw.set_embedder(embed_fn)
        self._embed_fn = embed_fn
        self.use_vector = bool(use_vector)

        # ==== v0.1 镜像字段（老代码直接读这些属性，所以必须保留）====
        self.max_messages = self._session.max_messages
        self.short_term: list[dict] = []
        self.long_term: list[dict] = []

        # 第一次同步镜像
        self._sync_mirrors_from_v2()

    # ------------------------------------------------------------------
    # 内部：v0.2 → 镜像字段同步
    # ------------------------------------------------------------------
    def _sync_mirrors_from_v2(self) -> None:
        self.short_term = [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
            }
            for m in self._session.messages
        ]
        self.long_term = [
            {
                "fact": e.content,
                "importance": e.importance,
                "timestamp": e.timestamp,
                # 注意：v0.2 不持久化 embedding；这里也不塞，避免磁盘膨胀
                "deleted": bool(e.deleted),
                "memory_id": e.memory_id,
                "category": e.category,
            }
            for e in self._raw.entries
        ]

    # ------------------------------------------------------------------
    # 公开 API（与 v0.1 完全同形参同返回类型）
    # ------------------------------------------------------------------
    def add_message(self, role: str, content: str) -> None:
        """已禁用：所有 memory 写入必须经过 memory_writer.MemoryWriter。

        请改用 `MemoryWriter.add_session_message(role=..., session_buffer=...)`。
        """
        raise RuntimeError(_WRITES_DISABLED_MSG)

    def add_fact(
        self,
        fact: str,
        importance: int = 3,
        embedding: list[float] | None = None,
    ) -> None:
        """已禁用：所有 memory 写入必须经过 memory_writer.MemoryWriter。

        请改用 `MemoryWriter.write_raw_entry(raw_memory=..., fact=..., importance=..., category="fact")`。
        """
        raise RuntimeError(_WRITES_DISABLED_MSG)

    # ------------------------------------------------------------------
    # 查询 API（get_relevant_facts 返回 legacy-dict，老代码不崩）
    # ------------------------------------------------------------------
    def _keyword_search(self, query: str, limit: int) -> list[dict]:
        # 走新 RawMemory 但返回 v0.1 dict 格式
        hits = self._raw.keyword_search(query, limit)
        return [self._raw_entry_to_legacy_dict(h) for h in hits]

    def _vector_search(self, query: str, limit: int) -> list[dict]:
        hits = self._raw.vector_search(query, limit)
        return [self._raw_entry_to_legacy_dict(h) for h in hits]

    def _vector_search_active(
        self, query: str, limit: int, active: list[dict]
    ) -> list[dict]:
        """v0.1 原来在 get_relevant_facts 里会调这个（带 active 过滤）。

        在 shim 里，我们先调新模块的 vector_search，再从结果里挑那些存在于
        active["memory_id"] 里的条目；实在没命中就退化为老逻辑。
        """
        hits = self._raw.vector_search(query, limit * 2)
        active_ids = {a.get("memory_id") for a in active if a.get("memory_id")}
        filtered = [h for h in hits if h.memory_id in active_ids][:limit]
        if filtered:
            return [self._raw_entry_to_legacy_dict(h) for h in filtered]

        # 退化：用老逻辑
        if not self._embed_fn:
            return []
        try:
            query_vec = self._embed_fn(query)
        except Exception:
            return []
        if not query_vec:
            return []
        scored = []
        for entry in active:
            vec = entry.get("embedding")
            if not vec:
                continue
            sim = cosine_similarity(query_vec, vec)
            if sim > 0:
                scored.append((sim * int(entry.get("importance", 3)), entry))
        if not scored:
            return []
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def _keyword_search_active(
        self, query: str, limit: int, active: list[dict]
    ) -> list[dict]:
        keywords = [w.strip().lower() for w in query.split() if w.strip()]
        if not keywords:
            return active[-limit:]
        scored = []
        for entry in active:
            fact_lower = str(entry.get("fact", "")).lower()
            match_count = sum(1 for kw in keywords if kw in fact_lower)
            if match_count > 0:
                scored.append((match_count * int(entry.get("importance", 3)), entry))
        if not scored:
            return active[-limit:]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def get_relevant_facts(self, query: str, limit: int = 3) -> list[dict]:
        """向量优先，关键词回退。返回 v0.1 dict 格式，保证老调用方签名不变。"""
        if limit <= 0 or not self.long_term:
            return []
        active = [e for e in self.long_term if not e.get("deleted")]
        if not active:
            return []
        if self.use_vector and self._embed_fn:
            vector_hits = self._vector_search_active(query, limit, active)
            if vector_hits:
                return vector_hits
        return self._keyword_search_active(query, limit, active)

    @staticmethod
    def _raw_entry_to_legacy_dict(e: RawMemoryEntry) -> dict:
        return {
            "fact": e.content,
            "importance": e.importance,
            "timestamp": e.timestamp,
            "deleted": e.deleted,
            "memory_id": e.memory_id,
            "category": e.category,
        }

    # ------------------------------------------------------------------
    # 序列化（to_dict / save / load：双写 + 优先读 v0.2）
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """返回 v0.1 字典（给老代码序列化用）。"""
        return {
            "max_messages": self.max_messages,
            "short_term": list(self.short_term),
            "long_term": [
                {
                    "fact": e["fact"],
                    "importance": e["importance"],
                    "timestamp": e["timestamp"],
                    "deleted": bool(e.get("deleted", False)),
                }
                for e in self.long_term
            ],
            "use_vector": self.use_vector,
        }

    def save(self, filepath: str = "memory_state.json") -> None:
        """已禁用：所有 memory 写入必须经过 memory_writer.MemoryWriter。

        请改用 `MemoryWriter.save_all(memory_dir=..., session_buffer=...,
        raw_memory=..., semantic_memory=...)`。若确需 legacy v0.1 双写，
        用 `MemoryWriter.save_legacy_v01(...)`（需环境变量开关）。
        """
        raise RuntimeError(_WRITES_DISABLED_MSG)

    def load(self, filepath: str = "memory_state.json") -> None:
        """优先读 v0.2，不存在再回退 memory_state.json。

        读取后同步回 short_term / long_term 镜像字段，保持老代码行为一致。
        """
        dir_ = os.path.dirname(os.path.abspath(filepath)) or "."
        v02_session = _legacy_session_path(dir_)
        v02_raw = _legacy_raw_path(dir_)

        if os.path.isfile(v02_session) and os.path.isfile(v02_raw):
            # 权威：v0.2 三文件
            # 显式把 caller 当前 max_rounds * 2 传给 SessionBuffer.load，
            # 保证构造方（如 harness_core 的 max_rounds）不会被旧文件更大的
            # max_messages 覆盖放大。也不会放大到更宽松的旧窗口。
            self._session.load(v02_session, max_messages=self.max_messages)
            self._raw.load(v02_raw)
            self.max_messages = self._session.max_messages
            self._sync_mirrors_from_v2()
            print(f"[Memory][shim] 已从 v0.2 存储加载: {dir_}")
            return

        if os.path.exists(filepath):
            # v0.1 → 走一次「内存中迁移」，等价于 memory.migration 的核心逻辑，
            # 但我们**不自动落盘 v0.2**，避免隐藏副作用；用户可显式调
            # `python -m memory.migration migrate --input <filepath>` 来真的落盘。
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._session = SessionBuffer.from_legacy_memory_dict(data)
            self._raw = RawMemory.from_legacy_memory_dict(data)
            # 恢复 embed_fn
            self._raw.set_embedder(self._embed_fn)
            self.max_messages = int(data.get("max_messages", self.max_messages))
            self.use_vector = bool(data.get("use_vector", self.use_vector))
            self._sync_mirrors_from_v2()
            print(f"[Memory][shim] 从 v0.1 加载并在内存迁移: {filepath}")
            return

        print(f"[Memory][shim] 未找到状态文件 {filepath}，使用空记忆。")
