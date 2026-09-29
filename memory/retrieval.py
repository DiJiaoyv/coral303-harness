"""Memory Retrieval —— 跨 SessionBuffer / RawMemory / SemanticMemory 的统一检索入口。

对外部模块（尤其是 Context Builder）暴露一个简单接口：::

    retriever.query(query_text, limit=...) -> RetrievalResult

其中 ``RetrievalResult`` 已经把三层的命中聚合好，Context Builder 无需关心内部结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from memory.session_buffer import SessionBuffer
from memory.raw_memory import RawMemory, RawMemoryEntry
from memory.semantic_memory import SemanticMemory, SemanticEntry


@dataclass
class RetrievalResult:
    """跨三层统一检索结果。"""

    # 来自 session buffer 的最近几条摘要（不检索，直接拿末尾 N 条）
    recent_messages: list[dict[str, str]] = field(default_factory=list)
    # 来自 raw memory 的命中
    raw_hits: list[RawMemoryEntry] = field(default_factory=list)
    # 来自 semantic memory 的命中（按 confidence 过滤后已经排好序）
    semantic_hits: list[SemanticEntry] = field(default_factory=list)

    def raw_hit_texts(self, *, with_importance: bool = True) -> list[str]:
        out: list[str] = []
        for e in self.raw_hits:
            text = e.content
            if with_importance:
                text = f"[重要度{e.importance}] {text}"
            out.append(text)
        return out

    def semantic_hit_texts(self, *, with_confidence: bool = True) -> list[str]:
        out: list[str] = []
        for e in self.semantic_hits:
            bucket_label = {"preferences": "偏好", "identity": "身份",
                            "relationships_to_others": "人际", "flags": "标记"}.get(e.bucket, e.bucket)
            text = f"[{bucket_label}] {e.key} = {e.value}"
            if with_confidence:
                text += f"（置信度 {round(e.confidence*100)}%，证据 {e.evidence_count} 条）"
            out.append(text)
        return out

    def has_any(self) -> bool:
        return bool(self.recent_messages or self.raw_hits or self.semantic_hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recent_messages": list(self.recent_messages),
            "raw_hits": [e.to_dict() for e in self.raw_hits],
            "semantic_hits": [e.to_dict() for e in self.semantic_hits],
        }


class MemoryRetriever:
    """把三层 memory 串起来，实现「向量优先、关键词回退、跨层去重」。"""

    def __init__(
        self,
        session_buffer: SessionBuffer,
        raw_memory: RawMemory,
        semantic_memory: SemanticMemory,
        *,
        embed_fn: Callable[[str], list[float]] | None = None,
        recent_dialogue_rounds: int = 5,
        raw_limit: int = 3,
        semantic_limit: int = 8,
        semantic_min_confidence: float = 0.3,
        prefer_vector: bool = True,
    ) -> None:
        self.session_buffer = session_buffer
        self.raw_memory = raw_memory
        self.semantic_memory = semantic_memory
        self.recent_dialogue_rounds = max(0, int(recent_dialogue_rounds))
        self.raw_limit = max(0, int(raw_limit))
        self.semantic_limit = max(0, int(semantic_limit))
        self.semantic_min_confidence = float(semantic_min_confidence)
        self.prefer_vector = bool(prefer_vector)

        # 注入：raw_memory 用 embed_fn 做向量检索
        if embed_fn is not None:
            raw_memory.set_embedder(embed_fn)
        self._embed_fn = embed_fn

    # ---------- 主入口 ----------
    def query(
        self,
        query_text: str,
        *,
        recent_rounds_override: int | None = None,
        raw_limit_override: int | None = None,
        semantic_limit_override: int | None = None,
    ) -> RetrievalResult:
        """跨三层聚合检索。query_text 通常是本轮用户输入。"""
        result = RetrievalResult()

        # (1) Session Buffer：不检索，直接取最近 N 轮
        n_rounds = (
            self.recent_dialogue_rounds
            if recent_rounds_override is None
            else int(recent_rounds_override)
        )
        for m in self.session_buffer.turns(n_rounds):
            result.recent_messages.append({
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
            })

        # (2) Raw Memory：向量优先，失败回退关键词
        raw_limit = self.raw_limit if raw_limit_override is None else int(raw_limit_override)
        if raw_limit > 0 and query_text:
            raw_hits: list[RawMemoryEntry] = []
            if self.prefer_vector and self._embed_fn:
                raw_hits = self.raw_memory.vector_search(query_text, raw_limit)
            if not raw_hits:
                raw_hits = self.raw_memory.keyword_search(query_text, raw_limit)
            result.raw_hits = raw_hits

        # (3) Semantic Memory：不需要 query，直接取高置信度的 top-N
        #    但如果有 query_text，优先挑那些和 query keyword 有关的
        sem_limit = (
            self.semantic_limit if semantic_limit_override is None else int(semantic_limit_override)
        )
        entries = self.semantic_memory.get_for_context(
            min_confidence=self.semantic_min_confidence
        )
        if query_text:
            # 做一个轻量「包含关键词」的排序加权
            keywords = {w.strip().lower() for w in query_text.split() if w.strip()}
            if keywords:
                def _sem_score(e: SemanticEntry) -> tuple[float, int]:
                    hit = 0
                    hay = f"{e.key} {e.value}".lower()
                    for kw in keywords:
                        if kw in hay:
                            hit += 1
                    # 先按命中次数排序，再按 confidence
                    return (float(hit) * 0.5 + e.confidence, e.evidence_count)
                entries.sort(key=_sem_score, reverse=True)
        result.semantic_hits = entries[:sem_limit]

        return result
