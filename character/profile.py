"""Character Profile —— 角色静态人设。

**不会频繁变化**：除非人工编辑或剧情大版本推进，否则不改。

对应 v0.1 Soul 的 CORE_KEYS（name / role / core_traits / core_drive / fear / catchphrases / vocabulary），
这里拆成：
    - CharacterProfile 本体：身份 + 核心人格
    - SpeechStyle（另一个文件）：口头禅 + 常用词汇 + 语气参数
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

CHARACTER_PROFILE_SCHEMA_VERSION = "2.0"

# Default profile: 幽灵（保持与 v0.1 Soul 默认值一致，方便平滑迁移）
_DEFAULT_NAME = "幽灵"
_DEFAULT_ROLE = "星际赏金猎人"
_DEFAULT_TRAITS = ["坚韧", "多疑", "外冷内热"]
_DEFAULT_CORE_DRIVE = "在法外之地维持脆弱的秩序，坚信'信息即货币，信誉高于生命'。"
_DEFAULT_FEAR = "被最信任的系统背叛。"
_DEFAULT_DESCRIPTION = ""


@dataclass
class CharacterProfile:
    """角色静态身份。字段变化需要升级 schema_version。"""

    schema_version: str = CHARACTER_PROFILE_SCHEMA_VERSION
    profile_version: int = 1  # 每次人工编辑后 profile_version += 1

    name: str = _DEFAULT_NAME
    role: str = _DEFAULT_ROLE
    description: str = _DEFAULT_DESCRIPTION

    # 核心人格
    core_traits: list[str] = field(default_factory=lambda: list(_DEFAULT_TRAITS))
    core_drive: str = _DEFAULT_CORE_DRIVE
    fear: str = _DEFAULT_FEAR

    # 说话风格由 speech_style.py 单独管理（Profile 里不重复）
    # 但 Profile 保留了「静态规则引用路径」字段
    behavioral_rules_ref: str | None = None
    relationship_rules_ref: str | None = None

    # 可选：世界观绑定（从 worlds/*.json 加载）
    world_ref: str | None = None

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # 防御性地重写一次 schema_version，防止 dataclass 构造传入旧值
        data["schema_version"] = CHARACTER_PROFILE_SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CharacterProfile":
        data = data or {}
        return cls(
            schema_version=data.get("schema_version", CHARACTER_PROFILE_SCHEMA_VERSION),
            profile_version=int(data.get("profile_version", 1)),
            name=str(data.get("name", _DEFAULT_NAME)),
            role=str(data.get("role", _DEFAULT_ROLE)),
            description=str(data.get("description", _DEFAULT_DESCRIPTION)),
            core_traits=list(data.get("core_traits") or _DEFAULT_TRAITS),
            core_drive=str(data.get("core_drive", _DEFAULT_CORE_DRIVE)),
            fear=str(data.get("fear", _DEFAULT_FEAR)),
            behavioral_rules_ref=data.get("behavioral_rules_ref"),
            relationship_rules_ref=data.get("relationship_rules_ref"),
            world_ref=data.get("world_ref"),
        )


def profile_file_path(char_dir: str) -> str:
    return os.path.join(char_dir, "character_profile.json")


def load_profile_from_dir(
    char_dir: str,
    *,
    template: dict[str, Any] | None = None,
) -> tuple[CharacterProfile, list[str]]:
    """
    从角色数据目录加载 Profile。
    兼容旧版 soul_core.json：若 character_profile.json 不存在，则从 soul_core.json 迁移生成。

    Returns:
        (profile, warnings)
    """
    warnings: list[str] = []
    path = profile_file_path(char_dir)

    # 1. 优先读新版 Profile 文件
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CharacterProfile.from_dict(data), warnings
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"读取 character_profile.json 失败（{exc}），尝试回退 soul_core.json")

    # 2. 回退：从旧 soul_core 字典（或 template）构造
    core_dict: dict[str, Any] = {}
    legacy_core_path = os.path.join(char_dir, "soul_core.json")
    if os.path.isfile(legacy_core_path):
        try:
            with open(legacy_core_path, "r", encoding="utf-8") as f:
                core_dict = json.load(f) or {}
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"读取 soul_core.json 也失败（{exc}），使用默认 Profile")
    if template:
        # template 优先级：传入模板覆盖 legacy 缺失项
        for k, v in template.items():
            core_dict.setdefault(k, v)

    profile = profile_from_soul_core_dict(core_dict)
    if not os.path.isfile(path):
        # 自动迁移时顺手写一份新版文件
        try:
            save_profile_to_dir(char_dir, profile)
            warnings.append("已自动从 soul_core 迁移生成 character_profile.json")
        except OSError as exc:
            warnings.append(f"写入新版 character_profile.json 失败（{exc}），但内存实例已构造")
    return profile, warnings


def save_profile_to_dir(char_dir: str, profile: CharacterProfile) -> None:
    os.makedirs(char_dir, exist_ok=True)
    path = profile_file_path(char_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)


def profile_from_soul_core_dict(core_dict: dict[str, Any] | None) -> CharacterProfile:
    """从 v0.1 Soul CORE dict 构造 CharacterProfile。"""
    core_dict = core_dict or {}
    return CharacterProfile(
        name=str(core_dict.get("name", _DEFAULT_NAME)),
        role=str(core_dict.get("role", _DEFAULT_ROLE)),
        description=str(core_dict.get("description", core_dict.get("role", _DEFAULT_DESCRIPTION))),
        core_traits=list(core_dict.get("core_traits") or _DEFAULT_TRAITS),
        core_drive=str(core_dict.get("core_drive", _DEFAULT_CORE_DRIVE)),
        fear=str(core_dict.get("fear", _DEFAULT_FEAR)),
    )
