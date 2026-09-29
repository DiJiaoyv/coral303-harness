"""Relationship 包：「关系」的一切。

第一阶段只实现 pair_state.py（User ↔ Character 多边关系轴 + 变化理由 + 衰减日志），
设计模式复用 emotion/ 的 PADState：
    - PADState.decay_toward(baseline, rate)   →  PairAxes.decay_toward(baseline, rate)
    - PADState.apply_offset(+)               →  PairAxes.apply_delta(axis, delta, cause)
    - EmotionStats + stage.transition        →  history[] + 阶段判定（见 PairStage）

预留群聊扩展位：
    - 用 subject_type / subject_id / target_type / target_id，而不硬编码 user ↔ character
    - 第二阶段再加 social_graph.py 管理角色 ↔ 角色关系图
"""
from __future__ import annotations

from relationship.pair_state import (
    RELATIONSHIP_STATE_SCHEMA_VERSION,
    PairAxes,
    PairState,
    RelationshipChange,
    PairStage,
    clamp_axes,
    load_pair_state,
    save_pair_state,
    load_pair_state_by_id,
    save_pair_state_by_id,
    pair_state_file_path,
)

__all__ = [
    "RELATIONSHIP_STATE_SCHEMA_VERSION",
    "PairAxes",
    "PairState",
    "RelationshipChange",
    "PairStage",
    "clamp_axes",
    "load_pair_state",
    "save_pair_state",
    "load_pair_state_by_id",
    "save_pair_state_by_id",
    "pair_state_file_path",
]

# 群聊扩展子包占位（未实现，仅文档/类型提示用）
# 落地条件：当真出现 character↔character 多边关系 / 世界状态可见性需求时
# from relationship.future import social_graph  # noqa: F401
