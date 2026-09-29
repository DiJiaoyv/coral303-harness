"""链路追踪数据类（11.2 Observability）。

每轮对话一条 TurnTrace，含若干 TurnStep。step_name 取以下值之一：

    context_built     — Context Builder 完成
                        detail: {"retrieved_memory_ids": [...],
                                 "context_tokens": int,
                                 "axes_values_at_turn": {"trust": 0.62, ...}}

    llm_generated     — LLM 候选回复产出
                        detail: {"candidate": str, "tokens": int,
                                 "attempt": int}

    harness_evaluated — Harness 评估候选
                        detail: {"candidate_preview": str,
                                 "scores": {...},
                                 "violations": [...],
                                 "rewrite_instruction": str,
                                 "passed": bool}

    regen_attempt     — 重生成尝试（接续 harness_evaluated 失败后）
                        detail: {"attempt": int,
                                 "triggered_by_violation": str}

    memory_written   — Memory Writer 完成写入
                        detail: {"raw_added": int,
                                 "semantic_updated": int,
                                 "relationship_updated": {"axis": "delta"},
                                 "gate_passed": bool,
                                 "gate_reason": str}

    turn_finalized    — 整轮结束
                        detail: {"final_response_preview": str,
                                 "total_regen_count": int,
                                 "total_llm_calls": int,
                                 "duration_ms": float}

各步骤附 start_ts / end_ts，便于定位延迟瓶颈。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TurnStep:
    """链路追踪中的单个步骤。

    step_name、start_ts 是必填；end_ts 在 step 调用结束时补；
    detail 是该步骤的具体内容（不同 step_name 有不同 schema，见模块 docstring）。
    """
    step_name: str
    start_ts: str = field(default_factory=_now_iso)
    end_ts: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def mark_end(self) -> "TurnStep":
        """在步骤结束时调用，补 end_ts。返回 self 便于链式调用。"""
        self.end_ts = _now_iso()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnTrace:
    """单轮对话的完整链路追踪。

    生命周期：
        1. 调用方在 turn 开始时 `trace = TurnTrace(turn_id=..., user_message=...)`
        2. 每个步骤：trace.add_step(TurnStep(step_name="...", detail={...}))
           或：trace.begin_step("step_name") → ... → trace.end_step(detail=...)
        3. turn 结束时 `trace.finalize(duration_ms=...)`，并通过
           Logger.log_turn_trace(trace) 落盘。
    """
    turn_id: str
    user_message: str = ""
    steps: list[TurnStep] = field(default_factory=list)
    # 元数据：参与本 turn 的版本号快照，便于审计回溯
    schema_versions: dict[str, str] = field(default_factory=dict)
    finalized: bool = False
    final_duration_ms: float = 0.0

    def add_step(self, step: TurnStep) -> TurnStep:
        """已完成的 step（start_ts/end_ts 都填好）追加进 trace。"""
        self.steps.append(step)
        return step

    def begin_step(self, step_name: str, detail: dict[str, Any] | None = None) -> TurnStep:
        """开始一个新 step，返回引用；后续可修改 detail，再调 end_step(step)。"""
        step = TurnStep(step_name=step_name, detail=detail or {})
        self.steps.append(step)
        return step

    def end_step(self, step: TurnStep, detail: dict[str, Any] | None = None) -> TurnStep:
        """结束 step：合并 detail（如果给了），补 end_ts。"""
        if detail:
            step.detail.update(detail)
        step.mark_end()
        return step

    def finalize(self, *, duration_ms: float = 0.0) -> "TurnTrace":
        """整轮 trace 收尾：标记 finalized + 记录总耗时。"""
        self.finalized = True
        self.final_duration_ms = float(duration_ms)
        return self

    def list_step_names(self) -> list[str]:
        return [s.step_name for s in self.steps]

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_message": self.user_message,
            "steps": [s.to_dict() for s in self.steps],
            "schema_versions": dict(self.schema_versions),
            "finalized": self.finalized,
            "final_duration_ms": self.final_duration_ms,
        }


def new_turn_id(prefix: str = "turn") -> str:
    """生成可读 turn_id：turn_YYYYMMDDHHMMSS_随机后缀。"""
    import random
    import string

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}_{ts}_{suffix}"
