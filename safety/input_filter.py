"""用户输入过滤器。"""
from __future__ import annotations

from safety.config import get_config
from safety.scanner import FilterResult, scan_text


def filter_input(text: str) -> FilterResult:
    """检查用户输入；禁止级命中时 action=blocked。"""
    result = scan_text(text)
    if not result.hit:
        return result
    if result.level == "prohibited":
        return FilterResult(
            hit=True,
            level=result.level,
            matched_word=result.matched_word,
            matched_raw=result.matched_raw,
            action="blocked",
        )
    return FilterResult(
        hit=True,
        level=result.level,
        matched_word=result.matched_word,
        matched_raw=result.matched_raw,
        action="allowed",
    )


def input_blocked_message() -> str:
    return get_config().INPUT_BLOCKED_MESSAGE
