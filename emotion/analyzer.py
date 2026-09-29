"""用户行为分析器：基于关键词与正则分类用户输入。"""
from __future__ import annotations

import re

from emotion.rules import BehaviorRule, load_rules


def analyze_user_input(text: str) -> str:
    """
    分析用户输入，返回行为类别 ID。

    未匹配任何规则时返回 ``neutral``。
    """
    if not text or not text.strip():
        return "neutral"

    normalized = text.strip()
    rules = load_rules()

    for rule in rules:
        if _match_rule(normalized, rule):
            return rule.id

    return "neutral"


def _match_rule(text: str, rule: BehaviorRule) -> bool:
    for keyword in rule.keywords:
        if keyword and keyword in text:
            return True

    for pattern in rule.patterns:
        if not pattern:
            continue
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            continue

    return False
