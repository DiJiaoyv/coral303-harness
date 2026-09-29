"""记忆可视化配置。"""

PER_PAGE = 20
MAX_KEYWORD_LENGTH = 100
MAX_CONTENT_LENGTH = 2000
SOFT_DELETE_RETENTION_DAYS = 30

# importance 1-5 映射到 高/中/低
IMPORTANCE_HIGH = frozenset({4, 5})
IMPORTANCE_MEDIUM = frozenset({3})
IMPORTANCE_LOW = frozenset({1, 2})

IMPORTANCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

IMPORTANCE_BADGE_CLASS = {
    "high": "danger",
    "medium": "warning",
    "low": "success",
}

IMPORTANCE_NUMERIC_LABELS = {
    1: "1 - 很低",
    2: "2 - 低",
    3: "3 - 中",
    4: "4 - 高",
    5: "5 - 很高",
}

SOURCE_LABELS = {
    "user": "用户输入",
    "model": "模型推断",
    "system": "系统预设",
}

VALID_SOURCES = frozenset(SOURCE_LABELS.keys())
