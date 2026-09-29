"""Character 包：角色本身的一切（静态身份 + 短期动态状态 + 说话风格 + 行为/关系规则）。

区分：
- ``characters/`` 目录 = 每个角色的 JSON 数据文件（持久化层）
- 本 ``character/`` 包 = Python 代码层，负责读写 / 校验 / 组装角色 Profile / State / Rules

目录结构（v0.2 第一阶段全部立即实现）：
    __init__.py           ← 对外 re-export
    profile.py            ← Character Profile（静态人设：name/role/traits/drive/fear...）
    state.py              ← Character State（短期动态：弧光阶段、当前目标、实时情绪引用）
    speech_style.py       ← 说话风格参数（口头禅、常用词、语气风格）
    behavioral_rules.py   ← 通用行为规则（该角色哪些行为绝对不允许）
    relationship_rules.py ← 该角色特有的关系推进规则（多高的 trust 才允许做什么）

版本号原则：
    所有持久化 JSON 的顶层都带有 schema_version，避免修改定义后不知道旧数据为何产生差异。
"""
from __future__ import annotations

from character.profile import (
    CHARACTER_PROFILE_SCHEMA_VERSION,
    CharacterProfile,
    load_profile_from_dir,
    profile_from_soul_core_dict,
    save_profile_to_dir,
)
from character.state import (
    CHARACTER_STATE_SCHEMA_VERSION,
    CharacterState,
    load_state_from_dir,
    save_state_to_dir,
    state_from_soul_state_dict,
)
from character.speech_style import SpeechStyle
from character.behavioral_rules import BehavioralRules
from character.relationship_rules import RelationshipRules

__all__ = [
    "CHARACTER_PROFILE_SCHEMA_VERSION",
    "CharacterProfile",
    "load_profile_from_dir",
    "profile_from_soul_core_dict",
    "save_profile_to_dir",
    "CHARACTER_STATE_SCHEMA_VERSION",
    "CharacterState",
    "load_state_from_dir",
    "save_state_to_dir",
    "state_from_soul_state_dict",
    "SpeechStyle",
    "BehavioralRules",
    "RelationshipRules",
]
