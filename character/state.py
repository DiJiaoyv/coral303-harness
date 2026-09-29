"""Character State —— 角色短期动态状态。

**每轮可能变化**：弧光阶段、当前目标、对本回合的临时戒备、情绪指针引用等。

注意：情绪（emotion/）是比 Character State 更细、变化更频繁的独立系统；
Character State 里**不存 PAD 数值**，只存「叙事层的阶段性状态」——弧光、当前目标、以及
对近期对话的一些临时心智标记（比如“刚才用户有点生气”这种可解释的阶段提示）。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from soul.model import Soul

CHARACTER_STATE_SCHEMA_VERSION = "2.0"

_DEFAULT_ARC_STAGE = "起点"  # 与 Soul.ARC_STAGES 对齐：起点 / 转折点 / 终点
_DEFAULT_GOAL = "在涅克瑟斯星区获取下一份赏金契约。"
_VALID_ARC_STAGES = {"起点", "转折点", "终点"}


@dataclass
class CharacterState:
    """角色短期叙事动态。"""

    schema_version: str = CHARACTER_STATE_SCHEMA_VERSION

    # 叙事弧光（与 v0.1 Soul STATE_KEYS 对齐）
    arc_stage: str = _DEFAULT_ARC_STAGE
    current_goal: str = _DEFAULT_GOAL

    # 心智提示：可解释的短期心智状态，用于给 Context Builder 注入「此时角色心里在想什么」
    # 例如：["对用户刚才的试探有所戒备", "记得用户上次提到怕黑"]
    # 第一版可以不使用，保留接口（由 Memory Writer / Evaluator 写入）
    mental_notes: list[str] = field(default_factory=list)

    # 上一回合触发的违规摘要（如果 Evaluator 触发了重生成，这里保留最后一次的原因）
    last_violation_summary: str | None = None

    # 最近一次关系变化摘要（给 prompt 的简述，不替代 Relationship State 的权威源）
    last_relationship_shift_summary: str | None = None

    def validate(self) -> None:
        if self.arc_stage not in _VALID_ARC_STAGES:
            # fail-soft：不是合法阶段就回退到最近的合法阶段前面
            # 不抛异常，保证对话不中断
            self.arc_stage = _DEFAULT_ARC_STAGE

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = CHARACTER_STATE_SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CharacterState":
        data = data or {}
        obj = cls(
            schema_version=data.get("schema_version", CHARACTER_STATE_SCHEMA_VERSION),
            arc_stage=str(data.get("arc_stage", _DEFAULT_ARC_STAGE)),
            current_goal=str(data.get("current_goal", _DEFAULT_GOAL)),
            mental_notes=list(data.get("mental_notes") or []),
            last_violation_summary=data.get("last_violation_summary"),
            last_relationship_shift_summary=data.get("last_relationship_shift_summary"),
        )
        obj.validate()
        return obj


def state_file_path(char_dir: str) -> str:
    return os.path.join(char_dir, "character_state.json")


def load_state_from_dir(char_dir: str) -> tuple[CharacterState, list[str]]:
    """
    从角色目录加载 State；兼容旧版 soul_state.json（若存在 STATE_KEYS）。
    """
    warnings: list[str] = []
    path = state_file_path(char_dir)

    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CharacterState.from_dict(data), warnings
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"读取 character_state.json 失败（{exc}），尝试回退 soul_state.json")

    legacy_state_path = os.path.join(char_dir, "soul_state.json")
    state_dict: dict[str, Any] = {}
    if os.path.isfile(legacy_state_path):
        try:
            with open(legacy_state_path, "r", encoding="utf-8") as f:
                legacy = json.load(f) or {}
            state_dict = state_from_soul_state_dict(legacy).to_dict()
            if not os.path.isfile(path):
                # 自动迁移
                try:
                    save_state_to_dir(char_dir, CharacterState.from_dict(state_dict))
                    warnings.append("已自动从 soul_state 迁移生成 character_state.json")
                except OSError as exc:
                    warnings.append(f"写入新版 character_state.json 失败（{exc}）")
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"soul_state.json 读失败（{exc}），使用默认 State")

    return CharacterState.from_dict(state_dict), warnings


def save_state_to_dir(char_dir: str, state: CharacterState) -> None:
    state.validate()
    os.makedirs(char_dir, exist_ok=True)
    path = state_file_path(char_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)


def state_from_soul_state_dict(state_dict: dict[str, Any] | None) -> CharacterState:
    """从 v0.1 Soul STATE dict 构造 CharacterState。"""
    state_dict = state_dict or {}
    return CharacterState(
        arc_stage=str(state_dict.get("arc_stage", _DEFAULT_ARC_STAGE)),
        current_goal=str(state_dict.get("current_goal", _DEFAULT_GOAL)),
    )


def state_from_soul(soul: Soul) -> CharacterState:
    """从 v0.1 Soul 对象构造 CharacterState（只取叙事相关字段）。"""
    return CharacterState(
        arc_stage=soul.arc_stage,
        current_goal=soul.current_goal,
    )
