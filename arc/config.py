"""弧光产品化配置：默认阶段、颜色映射、自动推进条件。"""
from __future__ import annotations

# 默认阶段序列（可自定义）
DEFAULT_STAGES = ["stranger", "acquaintance", "trust", "intimate"]
DEFAULT_STAGE = "stranger"

# 阶段显示名
STAGE_LABELS: dict[str, str] = {
    "stranger": "初遇",
    "acquaintance": "熟悉",
    "trust": "信任",
    "intimate": "亲密",
}

# Bootstrap / Chart.js 颜色映射
STAGE_COLORS: dict[str, str] = {
    "stranger": "#6c757d",
    "acquaintance": "#0d6efd",
    "trust": "#198754",
    "intimate": "#d63384",
}

# Soul 叙事阶段 → 产品弧光阶段映射（引擎自动同步用）
SOUL_TO_ARC_STAGE: dict[str, str] = {
    "起点": "stranger",
    "转折点": "acquaintance",
    "终点": "trust",
}

# 自动推进条件（rounds 来自引擎轮次，goals_completed 来自已完成目标数）
AUTO_ADVANCE_RULES: dict[str, dict] = {
    "acquaintance": {"min_rounds": 10},
    "trust": {"min_rounds": 30, "min_goals_completed": 1},
    "intimate": {"min_rounds": 50, "min_goals_completed": 2},
}

# 输入校验
MAX_STAGE_LEN = 50
MAX_GOAL_TITLE_LEN = 200
MAX_GOAL_DESC_LEN = 1000
STAGE_NAME_PATTERN = r"^[a-zA-Z0-9_]+$"

# 日志保留条数（管理后台展示最近 N 条）
ADMIN_LOG_LIMIT = 20
