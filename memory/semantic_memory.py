"""Semantic Memory —— 用户画像 + 稳定知识（带 confidence / evidence_count 防污染）。

**职责**：
    - 存储从多次 Raw Memory 中提炼出的「稳定画像条目」
    - **关键设计**：初始 confidence 很低（1 次证据≈15%），必须 evidence_count 多次累加后才可信
    - 发现矛盾时 confidence -= Δ；低于阈值标记为待清理

注意：
    unified_analyzer.py / memory_extractor.py 都是**分析器**（只输出候选），
    「累加 confidence / 检查矛盾 / 新建条目」全部在此模块内部完成，
    不回写进分析器。

数据结构示例见 v0.2 架构文档 §4。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SEMANTIC_MEMORY_SCHEMA_VERSION = "2.0"

_VALID_BUCKETS = {"preferences", "identity", "relationships_to_others", "flags"}
_CONFIDENCE_MIN = 0.0
_CONFIDENCE_MAX = 1.0
_DEFAULT_INITIAL_CONFIDENCE = 0.15
_PENDING_CLEANUP_THRESHOLD = 0.2
_RETRIEVAL_MIN_CONFIDENCE = 0.3   # 给 Context Builder 取条目时的最小 confidence


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Confidence 数学公式（纯代码计算，不调 LLM） ----------
def compute_confidence(
    evidence_count: int,
    contradiction_count: int,
    *,
    initial: float = _DEFAULT_INITIAL_CONFIDENCE,
    growth_rate: float = 0.35,
    contradiction_penalty: float = 0.2,
    ceiling: float = 0.98,
) -> float:
    """
    根据证据数和矛盾数计算置信度。

    - evidence_count=1  → initial（默认 0.15，低可信度）
    - evidence_count 越大 → 越接近 ceiling（上限默认 0.98，不给 1.0 留安全余量）
    - 每 1 次 contradiction 扣 contradiction_penalty，但不会低于 0
    """
    ev = max(0, int(evidence_count))
    if ev <= 0:
        return 0.0
    ctr = max(0, int(contradiction_count))
    # 增长曲线：ceiling - (ceiling - initial) * exp(-growth_rate * (ev - 1))
    growth = ceiling - (ceiling - float(initial)) * math.exp(-growth_rate * (ev - 1))
    penalty = float(contradiction_penalty) * ctr
    val = growth - penalty
    return max(_CONFIDENCE_MIN, min(_CONFIDENCE_MAX, val))


@dataclass
class SemanticEntry:
    """一条稳定画像条目。"""

    key: str                                  # e.g. "likes_cats"
    value: Any                                # e.g. True
    bucket: str = "preferences"               # preferences / identity / relationships_to_others / flags
    confidence: float = _DEFAULT_INITIAL_CONFIDENCE
    evidence_count: int = 1
    contradiction_count: int = 0
    first_observed: str = field(default_factory=_now_iso)
    last_confirmed: str = field(default_factory=_now_iso)
    # 证据引用（raw memory id）；保持一个小窗口，不无限增长
    evidence_refs: list[str] = field(default_factory=list)
    pending_cleanup: bool = False

    def __post_init__(self) -> None:
        if self.bucket not in _VALID_BUCKETS:
            self.bucket = "flags"
        self.evidence_count = max(0, int(self.evidence_count))
        self.contradiction_count = max(0, int(self.contradiction_count))
        # 以公式重算一遍 confidence 作为 fail-safe
        computed = compute_confidence(self.evidence_count, self.contradiction_count)
        if abs(self.confidence - computed) > 0.001:
            # 仍保留调用方传进来的值，但若落在 [0,1] 外则 clamp
            self.confidence = max(_CONFIDENCE_MIN, min(_CONFIDENCE_MAX, float(self.confidence)))
        if self.confidence < _PENDING_CLEANUP_THRESHOLD:
            self.pending_cleanup = True
        # evidence_refs 上限
        if len(self.evidence_refs) > 8:
            # 保留最后一条 + 最旧前 7 条
            self.evidence_refs = self.evidence_refs[:7] + self.evidence_refs[-1:]

    def recompute_confidence(self) -> None:
        self.confidence = compute_confidence(self.evidence_count, self.contradiction_count)
        self.pending_cleanup = self.confidence < _PENDING_CLEANUP_THRESHOLD

    def bump_evidence(self, raw_memory_ref: str | None = None) -> None:
        """新增一次同向证据。"""
        self.evidence_count += 1
        self.last_confirmed = _now_iso()
        if raw_memory_ref and raw_memory_ref not in self.evidence_refs:
            self.evidence_refs.append(raw_memory_ref)
        self.recompute_confidence()

    def record_contradiction(self) -> None:
        """记录一次反向矛盾说法。"""
        self.contradiction_count += 1
        self.last_confirmed = _now_iso()
        self.recompute_confidence()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticEntry":
        return cls(
            key=str(data.get("key", "unknown")),
            value=data.get("value"),
            bucket=str(data.get("bucket", "flags")),
            confidence=float(data.get("confidence", _DEFAULT_INITIAL_CONFIDENCE)),
            evidence_count=int(data.get("evidence_count", 1)),
            contradiction_count=int(data.get("contradiction_count", 0)),
            first_observed=str(data.get("first_observed") or _now_iso()),
            last_confirmed=str(data.get("last_confirmed") or _now_iso()),
            evidence_refs=list(data.get("evidence_refs") or []),
            pending_cleanup=bool(data.get("pending_cleanup", False)),
        )


class SemanticMemory:
    """语义画像（用户画像 / 关键人物关系 / 重要 flags）集合。"""

    def __init__(self, user_id: int | None = None) -> None:
        self.schema_version: str = SEMANTIC_MEMORY_SCHEMA_VERSION
        self.user_id: int | None = user_id
        self.buckets: dict[str, dict[str, SemanticEntry]] = {b: {} for b in _VALID_BUCKETS}

    # ---------- 高层写入接口（给 Memory Writer 调用） ----------
    def upsert_candidate(
        self,
        *,
        key: str,
        value: Any,
        bucket: str = "preferences",
        raw_memory_ref: str | None = None,
    ) -> tuple[SemanticEntry, str]:
        """
        接收分析器输出的结构化候选，执行：
          - 若 bucket 中存在同 key 且同 value → bump_evidence
          - 若 bucket 中存在同 key 不同 value → 记录矛盾，必要时新建另一派 entry
          - 否则 → 新建 entry（confidence = 初始低可信度）

        Returns:
            (entry, action) —— action ∈ {"created","confirmed","contradicted","new_side_entry"}
        """
        if bucket not in self.buckets:
            bucket = "flags"
        container = self.buckets[bucket]

        if key not in container:
            new_entry = SemanticEntry(
                key=key,
                value=value,
                bucket=bucket,
                evidence_refs=[raw_memory_ref] if raw_memory_ref else [],
            )
            container[key] = new_entry
            return new_entry, "created"

        existing = container[key]
        # 值相同 → 加证据
        if existing.value == value:
            existing.bump_evidence(raw_memory_ref)
            return existing, "confirmed"
        # 值不同 → 记录矛盾，confidence 下降，但「不立即删除」
        # 即使 confidence < 0.2（pending_cleanup），也只标记不覆盖；
        # 真正清理由 cleanup_pending() 方法负责（可定期调用）
        existing.record_contradiction()
        return existing, "contradicted"

    # ---------- 读取：给 Context Builder / Retrieval 用 ----------
    def iter_entries(self) -> list[SemanticEntry]:
        out: list[SemanticEntry] = []
        for b in self.buckets.values():
            out.extend(b.values())
        return out

    def cleanup_pending(self) -> int:
        """清理所有 pending_cleanup=True 的条目。返回清理数量。

        可由 MemoryWriter 或编排层定期调用（如每 N 轮一次）。
        清理 = 从 buckets 中移除，不保留历史。
        """
        removed = 0
        for bucket_name, container in self.buckets.items():
            keys_to_remove = [
                k for k, e in container.items() if e.pending_cleanup
            ]
            for k in keys_to_remove:
                del container[k]
                removed += 1
        return removed

    def get_for_context(
        self,
        min_confidence: float = _RETRIEVAL_MIN_CONFIDENCE,
        include_pending_cleanup: bool = False,
    ) -> list[SemanticEntry]:
        """只返回置信度足够高、且默认过滤待清理的条目。"""
        threshold = float(min_confidence)
        results: list[SemanticEntry] = []
        for e in self.iter_entries():
            if e.confidence < threshold:
                continue
            if not include_pending_cleanup and e.pending_cleanup:
                continue
            results.append(e)
        # 优先输出 confidence 高、evidence_count 高的
        results.sort(
            key=lambda x: (x.confidence, x.evidence_count),
            reverse=True,
        )
        return results

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        buckets_as_lists: dict[str, list[dict[str, Any]]] = {}
        for name, mapping in self.buckets.items():
            buckets_as_lists[name] = [e.to_dict() for e in mapping.values()]
        return {
            "schema_version": self.schema_version,
            "user_id": self.user_id,
            **buckets_as_lists,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SemanticMemory":
        data = data or {}
        user_id = data.get("user_id")
        if isinstance(user_id, bool):
            user_id = None
        if user_id is not None:
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                user_id = None
        obj = cls(user_id=user_id)
        for name in _VALID_BUCKETS:
            for item in data.get(name) or []:
                try:
                    entry = SemanticEntry.from_dict(item)
                    obj.buckets[name][entry.key] = entry
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
            self.user_id = new_obj.user_id
            self.buckets = new_obj.buckets
            self.schema_version = new_obj.schema_version
            return True
        except (json.JSONDecodeError, OSError):
            return False
