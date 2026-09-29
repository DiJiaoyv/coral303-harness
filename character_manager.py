# character_manager.py - 多角色切换与状态路径管理
import json
import os
import shutil

from soul import Soul
from soul.loader import load_soul_from_dir, save_soul_state
from soul.migration import soul_paths
from soul.writer import write_core
from soul.validator import validate_core, validate_state


DEFAULT_REGISTRY: dict = {
    "active": "幽灵",
    "base_dir": "characters",
    "characters": {
        "幽灵": {
            "name": "幽灵",
            "role": "星际赏金猎人",
            "core_traits": ["坚韧", "多疑", "外冷内热"],
            "core_drive": "在法外之地维持脆弱的秩序，坚信'信息即货币，信誉高于生命'。",
            "fear": "被最信任的系统背叛。",
            "catchphrases": ["钱收了，事办妥。", "……（不置可否的沉默）"],
            "vocabulary": ["信用点", "轨道", "契约", "数据碎片"],
            "arc_stage": "起点",
            "current_goal": "在涅克瑟斯星区获取下一份赏金契约。",
        },
        "老K": {
            "name": "老K",
            "role": "空间站军火商",
            "core_traits": ["圆滑", "贪婪", "消息灵通"],
            "core_drive": "在混乱星区靠情报和军火积累财富与影响力。",
            "fear": "库存被抄，客户名单泄露。",
            "catchphrases": ["货有了，价好谈。", "只收信用点，不赊账。"],
            "vocabulary": ["库存", "渠道", "行情", "保真"],
            "arc_stage": "起点",
            "current_goal": "出手一批军用级义体组件。",
        },
    },
}


class CharacterManager:
    """管理多角色的独立状态目录与切换。"""

    def __init__(
        self,
        registry_path: str = "characters.json",
        legacy_paths: dict | None = None,
        user_data_root: str | None = None,
    ):
        self.registry_path = registry_path
        self.legacy_paths = legacy_paths or {}
        self.user_data_root = user_data_root
        self.registry = self._load_registry()
        base = self.registry.get("base_dir", "characters")
        self.base_dir = (
            os.path.join(self.user_data_root, base)
            if self.user_data_root
            else base
        )
        self.active = self.registry.get("active", "幽灵")
        self._ensure_all_characters()
        self._migrate_legacy_if_needed()

    def _load_registry(self) -> dict:
        if os.path.exists(self.registry_path):
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_REGISTRY)
            merged.update({k: data[k] for k in data if k != "characters"})
            chars = dict(DEFAULT_REGISTRY.get("characters", {}))
            chars.update(data.get("characters", {}))
            merged["characters"] = chars
            return merged

        self._save_registry(DEFAULT_REGISTRY)
        return dict(DEFAULT_REGISTRY)

    def _save_registry(self, data: dict | None = None) -> None:
        data = data or self.registry
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def list_characters(self) -> list[str]:
        return list(self.registry.get("characters", {}).keys())

    def get_active(self) -> str:
        return self.active

    def set_active(self, name: str) -> None:
        if name not in self.registry.get("characters", {}):
            raise ValueError(f"未知角色: {name}")
        self.active = name
        self.registry["active"] = name
        self._save_registry()

    def get_character_dir(self, name: str | None = None) -> str:
        name = name or self.active
        return os.path.join(self.base_dir, name)

    def resolve_paths(self, name: str | None = None) -> dict[str, str]:
        char_dir = self.get_character_dir(name)
        paths = soul_paths(char_dir)
        return {
            "soul": paths["legacy"],
            "soul_core": paths["core"],
            "soul_state": paths["state"],
            "memory": os.path.join(char_dir, "memory_state.json"),
            "emotion": os.path.join(char_dir, "emotion_state.json"),
            "log_session": "logs/session_{session_id}.json",
        }

    def _ensure_character(self, name: str) -> None:
        char_dir = self.get_character_dir(name)
        os.makedirs(char_dir, exist_ok=True)
        paths = soul_paths(char_dir)
        template = self.registry["characters"].get(name, {})

        if not os.path.exists(paths["core"]) and not os.path.exists(paths["legacy"]):
            core, _ = validate_core(None, template=template)
            state, _ = validate_state(None, template=template)
            write_core(core, paths["core"], backup=False)
            save_soul_state(
                self._soul_from_parts(core, state),
                paths["state"],
            )
        elif not os.path.exists(paths["core"]):
            load_soul_from_dir(char_dir, template=template, auto_migrate=True)

    def _soul_from_parts(self, core: dict, state: dict) -> Soul:
        soul = Soul(name=core.get("name", "幽灵"), role=core.get("role", "未知"))
        for key in Soul.CORE_KEYS:
            if key in core:
                setattr(soul, key, core[key])
        for key in Soul.STATE_KEYS:
            if key in state:
                setattr(soul, key, state[key])
        return soul

    def _ensure_all_characters(self) -> None:
        for name in self.list_characters():
            self._ensure_character(name)

    def _migrate_legacy_if_needed(self) -> None:
        legacy_map = {
            "soul": self.legacy_paths.get("soul", "soul_state.json"),
            "memory": self.legacy_paths.get("memory", "memory_state.json"),
            "emotion": self.legacy_paths.get("emotion", "emotion_state.json"),
        }
        target = self.resolve_paths(self.active)
        for key, src in legacy_map.items():
            dst = target[key]
            if os.path.exists(src) and not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                print(f"[Character] 已迁移 {src} → {dst}")

    def get_soul_template(self, name: str | None = None) -> dict:
        name = name or self.active
        return self.registry.get("characters", {}).get(name, {})
