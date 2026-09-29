"""Soul State schema — mutable narrative state."""
from __future__ import annotations

STATE_FIELDS = ("arc_stage", "current_goal")

ARC_STAGES = ("起点", "转折点", "终点")

DEFAULT_STATE: dict = {
    "arc_stage": "起点",
    "current_goal": "在涅克瑟斯星区获取下一份赏金契约。",
}


def default_state(**overrides) -> dict:
    data = dict(DEFAULT_STATE)
    data.update(overrides)
    return data
