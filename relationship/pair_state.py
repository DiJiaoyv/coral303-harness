"""Pair State —— User ↔ Character（及未来任意 subject ↔ target）的多边关系状态。

设计模式直接参考 emotion/models.py：

    PADState                          →  PairAxes
      apply_offset(+/+/+)               →  apply_delta(axis, +delta)
      decay_toward(baseline, rate)      →  decay_toward(baseline, rate)
      to_dict / from_dict               →  to_dict / from_dict

    Emotion.Stage (stranger→acquaintance→trust→intimate+conflict)
                                      →  PairStage（使用同一套阶段名，由 axes 阈值导出）

核心设计：**每次变化必须带 cause（变化理由）**，否则不准写入。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from emotion.config import (
    CONFLICT_STAGE,
    DEFAULT_STAGE,
    STAGE_ORDER,
    STAGE_LABELS,
)

RELATIONSHIP_STATE_SCHEMA_VERSION = "1.0"

_AXIS_MIN = 0.0
_AXIS_MAX = 1.0
# 每轮对话关系轴向基线衰减比例（默认比对情绪慢一点：2%/轮）
_DEFAULT_DECAY_RATE = 0.02

# 五轴定义：按「信任深度」和「情绪负荷」两条主线划分
AXIS_DEFINITIONS: dict[str, str] = {
    "familiarity":          "熟悉度：互相了解背景/名字/习性的程度",
    "trust":                "信任度：愿意暴露弱点 / 守信 / 不计较小事的程度",
    "emotional_closeness":  "亲密度：情感依赖、分享深层心事、主动靠近的意愿",
    "playfulness":          "嬉玩度：是否能轻松开玩笑、挑逗、打闹",
    "tension":              "紧张度：冲突、误解、未解决的争执（独立轴，不会被 trust 抵消）",
}
DEFAULT_AXES: dict[str, float] = {
    "familiarity":          0.0,
    "trust":                0.0,
    "emotional_closeness":  0.0,
    "playfulness":          0.0,
    "tension":              0.0,
}
# 阶段切换阈值（由 axes 综合判定，与 emotion/ 的 STAGE_ORDER 对应）
_STAGE_THRESHOLDS: dict[str, dict[str, float]] = {
    # acquaintance：熟悉度或信任有一项开始建立
    "acquaintance": {"familiarity": 0.2, "trust": 0.15},
    # trust：明显信任
    "trust":        {"trust": 0.4, "familiarity": 0.35},
    # intimate：情感亲密 + 信任都到位
    "intimate":     {"trust": 0.65, "emotional_closeness": 0.55},
}
# 冲突阶段单独判定：tension 过高且 emotional_closeness 不足以抵消
_CONFLICT_TENSION_THRESHOLD = 0.55
_CONFLICT_CLOSENESS_OFFSET = 0.15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_axes(v: float) -> float:
    return max(_AXIS_MIN, min(_AXIS_MAX, v))


# ---------- 五轴主体（与 PADState 同模式） ----------
@dataclass
class PairAxes:
    familiarity: float = 0.0
    trust: float = 0.0
    emotional_closeness: float = 0.0
    playfulness: float = 0.0
    tension: float = 0.0

    def apply_delta(self, axis: str, delta: float) -> float:
        """对单轴偏移，clamp 到 [0,1]。返回新值。"""
        if axis not in DEFAULT_AXES:
            raise ValueError(f"未知关系轴：{axis}")
        setattr(self, axis, clamp_axes(getattr(self, axis) + delta))
        return getattr(self, axis)

    def decay_toward(self, baseline: "PairAxes", rate: float = _DEFAULT_DECAY_RATE) -> None:
        """向基线以 rate 比例衰减（默认 2%/轮，比对情绪慢，避免关系值飘忽）。"""
        r = max(0.0, min(1.0, rate))
        for axis in DEFAULT_AXES:
            cur = getattr(self, axis)
            base = getattr(baseline, axis)
            new = cur + (base - cur) * r
            setattr(self, axis, clamp_axes(new))

    def as_dict(self) -> dict[str, float]:
        return {axis: round(getattr(self, axis), 4) for axis in DEFAULT_AXES}

    def copy(self) -> "PairAxes":
        return PairAxes(**self.as_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PairAxes":
        data = data or {}
        return cls(**{a: float(data.get(a, DEFAULT_AXES[a])) for a in DEFAULT_AXES})


class PairStage:
    """关系阶段（由 axes 计算出来的派生值，不持久化）。"""

    STAGES = STAGE_ORDER
    DEFAULT = DEFAULT_STAGE
    CONFLICT = CONFLICT_STAGE

    @staticmethod
    def compute(axes: PairAxes) -> str:
        """按阈值从高到低匹配：intimate → trust → acquaintance → stranger；高 tension 走冲突。"""
        # 冲突优先判断
        closeness_bonus = axes.emotional_closeness * _CONFLICT_CLOSENESS_OFFSET
        effective_tension = max(0.0, axes.tension - closeness_bonus)
        if effective_tension >= _CONFLICT_TENSION_THRESHOLD:
            return PairStage.CONFLICT
        # 从后往前匹配，命中最高阶段即返回
        for stage_name in reversed(PairStage.STAGES):
            if stage_name == PairStage.DEFAULT:
                continue
            thresholds = _STAGE_THRESHOLDS.get(stage_name, {})
            if not thresholds:
                continue
            # 命中规则：任一阈值达到即可视为进入该阶段
            # （信任可以先于熟悉 / 熟悉了但还没信任 都算「已经不是陌生人」。
            #  如果要多轴 ALL 约束，改回 all(...) 即可。默认 ANY 更宽松，
            #  避免 trust 0.5 但 familiarity 还没到 0.2 时仍被判定为 stranger）
            ok = any(getattr(axes, axis) >= thr for axis, thr in thresholds.items())
            if ok:
                return stage_name
        return PairStage.DEFAULT

    @staticmethod
    def label(stage: str) -> str:
        return STAGE_LABELS.get(stage, stage)


# ---------- 变化理由（每次写轴都要带） ----------
@dataclass
class RelationshipChange:
    timestamp: str = field(default_factory=_now_iso)
    axis: str = ""
    old_value: float = 0.0
    new_value: float = 0.0
    delta: float = 0.0
    cause: str = ""                      # 必须：人话解释为什么变
    raw_memory_ref: str | None = None    # 可选：引用哪条 raw memory
    evaluator_version: str | None = None # 版本化：哪个规则/模型版本决定的
    turn_id: str | None = None

    def __post_init__(self) -> None:
        if self.axis not in DEFAULT_AXES:
            raise ValueError(f"未知关系轴：{self.axis}")
        if not isinstance(self.cause, str) or not self.cause.strip():
            raise ValueError("RelationshipChange 必须带 cause（变化理由）")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationshipChange":
        return cls(
            timestamp=str(data.get("timestamp") or _now_iso()),
            axis=str(data.get("axis", "")),
            old_value=float(data.get("old_value", 0.0)),
            new_value=float(data.get("new_value", 0.0)),
            delta=float(data.get("delta", 0.0)),
            cause=str(data.get("cause", "")),
            raw_memory_ref=data.get("raw_memory_ref"),
            evaluator_version=data.get("evaluator_version"),
            turn_id=data.get("turn_id"),
        )


# ---------- 容器：PairState ----------
@dataclass
class PairState:
    """
    某个 subject ↔ target 之间的关系状态 + 变化历史。

    群聊预留：不硬编码 user_id / character_id。
    第一版实际调用：
        PairState(subject_type="user", subject_id=1,
                  target_type="character", target_id=5)
    """

    schema_version: str = RELATIONSHIP_STATE_SCHEMA_VERSION
    subject_type: str = "user"
    subject_id: int = 0
    target_type: str = "character"
    target_id: int = 0

    axes: PairAxes = field(default_factory=PairAxes)
    # 长期基线（长时间不互动 → 向此值衰减；初遇基线全 0）
    baseline: PairAxes = field(default_factory=PairAxes)
    # 历史变化（每条都有 cause，便于审计 & 版本回滚）
    history: list[RelationshipChange] = field(default_factory=list)

    # ---------- 派生属性 ----------
    @property
    def stage(self) -> str:
        return PairStage.compute(self.axes)

    @property
    def stage_label(self) -> str:
        return PairStage.label(self.stage)

    # ---------- 写入轴（带 cause） ----------
    def update_axis(
        self,
        axis: str,
        delta: float,
        cause: str,
        *,
        raw_memory_ref: str | None = None,
        evaluator_version: str | None = None,
        turn_id: str | None = None,
    ) -> RelationshipChange:
        """
        对单轴施加偏移，记录变化。
        如果 delta 被 clamp 截掉了，返回的 change.delta 会反映实际差值。
        """
        if not cause or not str(cause).strip():
            raise ValueError("Relationship 更新必须提供 cause（变化理由）")
        old = float(getattr(self.axes, axis))
        new = self.axes.apply_delta(axis, delta)
        actual_delta = round(new - old, 6)
        if actual_delta == 0.0:
            # 没有实际变化：不记录到 history（但也不抛异常）
            return RelationshipChange(
                axis=axis, old_value=old, new_value=new, delta=actual_delta,
                cause=cause, raw_memory_ref=raw_memory_ref,
                evaluator_version=evaluator_version, turn_id=turn_id,
            )
        change = RelationshipChange(
            axis=axis,
            old_value=old,
            new_value=new,
            delta=actual_delta,
            cause=str(cause).strip(),
            raw_memory_ref=raw_memory_ref,
            evaluator_version=evaluator_version,
            turn_id=turn_id,
        )
        self.history.append(change)
        # history 上限：保留最新 500 条（足够追溯最近几个月的变化脉络）
        if len(self.history) > 500:
            self.history = self.history[-500:]
        return change

    def apply_passive_decay(self, rounds: int = 1, rate: float = _DEFAULT_DECAY_RATE) -> None:
        """
        被动衰减：当有几轮没有任何关系驱动的事件时，axes 缓缓向基线回落。
        （只改数值，不写 history，因为这是被动回归不是主动事件。）
        """
        rounds = max(0, int(rounds))
        for _ in range(rounds):
            self.axes.decay_toward(self.baseline, rate)

    def last_change_summary(self, limit: int = 3) -> list[str]:
        """取最近 N 次主动变化的短摘要，给 Context Builder 注入 prompt。"""
        summaries: list[str] = []
        for ch in reversed(self.history):
            if ch.delta == 0.0:
                continue
            arrow = "↑" if ch.delta > 0 else "↓"
            label = {
                "familiarity": "熟悉度",
                "trust": "信任度",
                "emotional_closeness": "亲密度",
                "playfulness": "嬉玩度",
                "tension": "紧张度",
            }.get(ch.axis, ch.axis)
            summaries.append(
                f"{label} {arrow}{abs(round(ch.delta*100, 1))}%"
                f"（{ch.cause}）"
            )
            if len(summaries) >= limit:
                break
        return summaries

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "subject_type": self.subject_type,
            "subject_id": int(self.subject_id),
            "target_type": self.target_type,
            "target_id": int(self.target_id),
            "axes": self.axes.as_dict(),
            "baseline": self.baseline.as_dict(),
            "stage": self.stage,  # 派生值也输出，方便人工/工具直接读
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PairState":
        data = data or {}
        return cls(
            schema_version=str(data.get("schema_version", RELATIONSHIP_STATE_SCHEMA_VERSION)),
            subject_type=str(data.get("subject_type", "user")),
            subject_id=int(data.get("subject_id", 0) or 0),
            target_type=str(data.get("target_type", "character")),
            target_id=int(data.get("target_id", 0) or 0),
            axes=PairAxes.from_dict(data.get("axes")),
            baseline=PairAxes.from_dict(data.get("baseline")),
            history=[RelationshipChange.from_dict(h) for h in (data.get("history") or [])],
        )


def pair_state_file_path(
    base_dir: str,
    subject_type: str,
    subject_id: int,
    target_type: str,
    target_id: int,
) -> str:
    """
    统一命名：关系按 (subject, target) 对分别存。
    例：relationship__user_1__character_5.json
    """
    name = f"relationship__{subject_type}_{subject_id}__{target_type}_{target_id}.json"
    return os.path.join(base_dir, name)


def load_pair_state(filepath: str) -> PairState:
    if not os.path.isfile(filepath):
        return PairState()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PairState.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return PairState()


def save_pair_state(filepath: str, state: PairState) -> None:
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)


# ==============================================================
# 按身份加载/保存（群聊扩展友好）
#
# 用户原始约束：
#     第一版实际调用：
#         load_pair_state_by_id("user", 1, "character", 5)
#     以后群聊扩展无需改签名：
#         load_pair_state_by_id("character", 5, "character", 7)   # A↔B 关系
#
# 说明：原 load_pair_state(filepath) / save_pair_state(filepath, state)
# 是文件级 API（migration.py 等已有调用方）；这里新增「按身份查询」
# 便捷函数，封装 pair_state_file_path + 文件级读写，签名满足群聊扩展。
# ==============================================================
def load_pair_state_by_id(
    subject_type: str,
    subject_id: int,
    target_type: str,
    target_id: int,
    *,
    base_dir: str,
) -> PairState:
    """按 (subject, target) 身份四元组加载 PairState。

    第一版实际调用：
        load_pair_state_by_id("user", 1, "character", 5, base_dir=char_dir)

    以后群聊扩展无需改签名：
        load_pair_state_by_id("character", 5, "character", 7,
                              base_dir=world_dir)   # A↔B 关系
    """
    filepath = pair_state_file_path(
        base_dir, subject_type, subject_id, target_type, target_id,
    )
    return load_pair_state(filepath)


def save_pair_state_by_id(
    state: PairState,
    *,
    base_dir: str,
) -> str:
    """按 state 自身的 (subject_type, subject_id, target_type, target_id)
    落盘到 base_dir 下，返回最终写入路径。

    要求 state 的 subject/target 字段已正确设置（群聊扩展友好）。
    """
    filepath = pair_state_file_path(
        base_dir,
        state.subject_type, state.subject_id,
        state.target_type, state.target_id,
    )
    save_pair_state(filepath, state)
    return filepath
