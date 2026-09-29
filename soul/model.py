# soul/model.py - 角色灵魂核心定义（兼容层）
import json
import os


class Soul:
    """定义 AI 角色的灵魂：核心身份（不变）与叙事状态（可演化）。"""

    ARC_STAGES = ("起点", "转折点", "终点")
    CORE_KEYS = (
        "name",
        "role",
        "core_traits",
        "core_drive",
        "fear",
        "catchphrases",
        "vocabulary",
    )
    STATE_KEYS = ("arc_stage", "current_goal")

    def __init__(self, name="幽灵", role="星际赏金猎人"):
        self.name = name
        self.role = role
        self.core_traits = ["坚韧", "多疑", "外冷内热"]
        self.core_drive = "在法外之地维持脆弱的秩序，坚信'信息即货币，信誉高于生命'。"
        self.fear = "被最信任的系统背叛。"
        self.catchphrases = ["钱收了，事办妥。", "……（不置可否的沉默）"]
        self.vocabulary = ["信用点", "轨道", "契约", "数据碎片"]
        self.arc_stage = "起点"
        self.current_goal = "在涅克瑟斯星区获取下一份赏金契约。"

    def apply_narrative_update(
        self,
        arc_stage: str | None = None,
        current_goal: str | None = None,
    ) -> dict[str, tuple]:
        changes: dict[str, tuple] = {}

        if arc_stage and arc_stage != self.arc_stage:
            if arc_stage not in self.ARC_STAGES:
                return changes
            old_idx = self.ARC_STAGES.index(self.arc_stage)
            new_idx = self.ARC_STAGES.index(arc_stage)
            if new_idx < old_idx or new_idx > old_idx + 1:
                return changes
            changes["arc_stage"] = (self.arc_stage, arc_stage)
            self.arc_stage = arc_stage

        if current_goal and current_goal.strip() != self.current_goal:
            new_goal = current_goal.strip()
            changes["current_goal"] = (self.current_goal, new_goal)
            self.current_goal = new_goal

        return changes

    def to_dict(self):
        return {
            "name": self.name,
            "role": self.role,
            "core_traits": self.core_traits,
            "core_drive": self.core_drive,
            "fear": self.fear,
            "catchphrases": self.catchphrases,
            "vocabulary": self.vocabulary,
            "arc_stage": self.arc_stage,
            "current_goal": self.current_goal,
        }

    def to_core_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.CORE_KEYS}

    def to_state_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.STATE_KEYS}

    def save(self, filepath="soul_state.json"):
        """保存可变状态（分层后仅写入 state 字段）。"""
        from soul.loader import save_soul_state

        save_soul_state(self, filepath)

    def load(self, filepath="soul_state.json"):
        """从角色目录加载 core + state（兼容旧版单文件）。"""
        from soul.loader import load_soul_from_paths

        char_dir = os.path.dirname(filepath) or "."
        template = self.to_dict()
        soul, _, _, warnings = load_soul_from_paths(
            filepath, template=template, auto_migrate=True
        )
        for key, value in soul.to_dict().items():
            setattr(self, key, value)
        for msg in warnings:
            print(f"[Soul] {msg}")
        if os.path.exists(filepath) or os.path.exists(
            os.path.join(char_dir, "soul_core.json")
        ):
            print(f"[Soul] 状态已从 {filepath} 加载")
        else:
            print(f"[Soul] 未找到状态文件 {filepath}，使用默认设定。")


if __name__ == "__main__":
    my_soul = Soul()
    print("角色创建成功:", my_soul.name)
    my_soul.save()
