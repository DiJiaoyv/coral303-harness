"""memory 包（新架构分层版本）—— 「角色记住了什么」。

v0.2 新架构分层：
    memory/session_buffer.py  ← 短期对话 FIFO（只保留 N 轮，用于给近期对话拼 prompt）
    memory/raw_memory.py      ← 事件记忆（加 Write Gate 筛选，通过 Memory Writer 写入）
    memory/semantic_memory.py ← 用户画像（confidence + evidence_count，防单轮污染）
    memory/retrieval.py       ← 跨三层统一检索入口（向量优先 + 关键词回退）

**与 v0.1 character_memory.py 的关系**：
    v0.1 Memory.short_term[]  →  拆分到 session_buffer.py
    v0.1 Memory.long_term[] 一部分（事件） →  raw_memory.py
    v0.1 Memory.long_term[] 另一部分（可提炼为稳定画像） → semantic_memory.py
    v0.1 Memory.get_relevant_facts() / _vector_search / _keyword_search
                                  → 整合为 retrieval.py 统一接口

**与老 memory/ 包的关系**：
    旧 ``memory/`` 是 memory.io 的增删改查 helper；新架构不再直接使用它。
    为避免名称冲突，本包内各子模块使用绝对 import。
"""
from __future__ import annotations

from memory.session_buffer import (
    SESSION_BUFFER_SCHEMA_VERSION,
    SessionBuffer,
    SessionMessage,
)
from memory.raw_memory import (
    RAW_MEMORY_SCHEMA_VERSION,
    RawMemory,
    RawMemoryEntry,
)
from memory.semantic_memory import (
    SEMANTIC_MEMORY_SCHEMA_VERSION,
    SemanticMemory,
    SemanticEntry,
    compute_confidence,
)
from memory.retrieval import (
    RetrievalResult,
    MemoryRetriever,
)

__all__ = [
    "SESSION_BUFFER_SCHEMA_VERSION",
    "SessionBuffer",
    "SessionMessage",
    "RAW_MEMORY_SCHEMA_VERSION",
    "RawMemory",
    "RawMemoryEntry",
    "SEMANTIC_MEMORY_SCHEMA_VERSION",
    "SemanticMemory",
    "SemanticEntry",
    "compute_confidence",
    "RetrievalResult",
    "MemoryRetriever",
]
