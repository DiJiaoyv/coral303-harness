"""评分引擎配置。"""

# ============================================================
# 版本号
# ============================================================
# 评分规则文件版本：修改 _CHARACTER_VIOLATION_PATTERNS / _RELATIONSHIP_STAGE_LIMITS
# 等规则表后必须 bump 此版本号，便于老数据诊断报告对比定位差异。
SCORING_RULES_VERSION = "1.0"


# 维度权重（总和应为 1.0）
DIMENSION_WEIGHTS = {
    "relevance": 0.25,
    "consistency": 0.25,
    "fluency": 0.25,
    "safety": 0.25,
}

# 默认评分方式: rule | model
DEFAULT_SCORING_METHOD = "rule"

# 低分阈值（管理后台高亮）
LOW_SCORE_THRESHOLD = 3.0

# 流畅度：回复超过此长度适当扣分
MAX_REPLY_LENGTH_SOFT = 2000

# 安全黑名单（检测到则 safety=0，total 受影响）
SAFETY_BLACKLIST = [
    "色情",
    "裸体",
    "强奸",
    "杀人",
    "炸弹",
    "恐怖主义",
    "台独",
    "法轮功",
]

# 重复 n-gram 检测
NGRAM_SIZE = 4
MAX_NGRAM_REPEAT_RATIO = 0.35

# LLM 评分（可选）
LLM_SCORING_ENABLED = False


# ============================================================
# 评估模式开关（11.3 成本预算）
# ============================================================
# EVAL_MODE: "rule" 走纯规则（毫秒级）；"llm_hybrid" 规则高分跳过 LLM、规则低分才调 LLM；
# "llm" 完全走 LLM（不推荐生产用，仅供调试）。
EVAL_MODE: str = "rule"

# MEMORY_GATE_MODE: "rule" 只走规则关键词判断是否值得记；
# "llm" 灰区调用 LLM 二次判断；"hybrid" 规则不通过但疑似重要时调 LLM 复核。
MEMORY_GATE_MODE: str = "rule"

# MEM_EXTRACT_MODE: "unified" 一次 LLM 调用同时输出 facts + narrative + relationship_delta；
# "split" 分多次调用（仅供调试对比，不推荐生产）。
MEM_EXTRACT_MODE: str = "unified"


# ============================================================
# 编排预算（11.3 成本与延迟预算）
# ============================================================
# 每轮对话的成本上限。任何一项超出都触发 rule_fallback_on_budget_exceeded
ORCHESTRATION_BUDGET = {
    # 单轮最大重生成次数（不含首轮候选）
    "max_regen_per_turn": 2,
    # 单轮最大 LLM 调用次数（含生成 + 评估 + 提取）
    "max_llm_calls_per_turn": 3,
    # 单轮总超时秒数（含全部重生成）
    "total_timeout_seconds": 30,
    # 预算超限时是否回退到纯规则（True=安全降级，False=抛 BudgetExceededError）
    "rule_fallback_on_budget_exceeded": True,
}


def get_budget_limit(key: str):
    """便捷读取 ORCHESTRATION_BUDGET[key]，未知 key 抛 KeyError。"""
    return ORCHESTRATION_BUDGET[key]

