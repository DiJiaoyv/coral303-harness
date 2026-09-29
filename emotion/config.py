"""情绪系统配置：PAD 初始值、衰减率、剧情阶段映射等。"""
from __future__ import annotations

import os

# PAD 维度范围
PAD_MIN = -1.0
PAD_MAX = 1.0

# 默认 PAD 初始值（初遇阶段）
DEFAULT_PLEASURE = 0.0
DEFAULT_AROUSAL = 0.0
DEFAULT_DOMINANCE = 0.0

# 每轮对话向阶段基线衰减的比例
DECAY_RATE_PER_ROUND = 0.05

# 规则文件路径（支持热加载）
RULES_FILE = os.path.join(os.path.dirname(__file__), "rules.json")

# 剧情阶段定义（顺序不可倒退，冲突可独立进入）
STAGE_ORDER = ("stranger", "acquaintance", "trust", "intimate")
DEFAULT_STAGE = "stranger"
CONFLICT_STAGE = "conflict"

# 各阶段情绪基线与行为倾向
STAGE_BASELINES: dict[str, dict] = {
    "stranger": {
        "pleasure": 0.0,
        "arousal": 0.0,
        "dominance": 0.0,
        "tendency": "礼貌、客气、保持距离感",
    },
    "acquaintance": {
        "pleasure": 0.2,
        "arousal": 0.1,
        "dominance": 0.1,
        "tendency": "放松、偶尔开玩笑",
    },
    "trust": {
        "pleasure": 0.4,
        "arousal": 0.2,
        "dominance": 0.3,
        "tendency": "主动分享、关心用户",
    },
    "intimate": {
        "pleasure": 0.6,
        "arousal": 0.3,
        "dominance": 0.5,
        "tendency": "撒娇、依赖、偶尔吃醋",
    },
    "conflict": {
        "pleasure": -0.3,
        "arousal": 0.4,
        "dominance": -0.2,
        "tendency": "冷淡、反驳、回避",
    },
}

# 阶段切换条件
STAGE_TRANSITION_RULES: dict[str, dict] = {
    "acquaintance": {"min_rounds": 10},
    "trust": {"min_rounds": 30, "min_secret_shares": 1},
    "intimate": {"min_rounds": 50, "min_positive_interactions": 3},
    "conflict": {"consecutive_negative": 3},
}

# 视为积极互动的行为类别
POSITIVE_BEHAVIORS = frozenset({"praise", "comfort", "share_secret"})

# 视为消极互动的行为类别
NEGATIVE_BEHAVIORS = frozenset({"criticism", "indifference"})

# 退出冲突所需的积极互动次数
CONFLICT_EXIT_POSITIVE_COUNT = 1

# 阶段显示名
STAGE_LABELS: dict[str, str] = {
    "stranger": "初遇",
    "acquaintance": "熟悉",
    "trust": "信任",
    "intimate": "亲密",
    "conflict": "冲突",
}
