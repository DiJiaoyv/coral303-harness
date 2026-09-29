"""审核结果与通用扫描逻辑。"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass

from safety.config import get_config
from safety.loader import load_word_lists

logger = logging.getLogger(__name__)

_LEVEL_ORDER = ("prohibited", "warning", "monitor")


@dataclass(frozen=True)
class FilterResult:
    hit: bool
    level: str | None = None
    matched_word: str | None = None
    matched_raw: str | None = None
    action: str = "allowed"


def mask_word(word: str) -> str:
    if not word:
        return "***"
    if len(word) <= 4:
        return "***"
    return f"{word[:2]}***{word[-2:]}"


def normalize_text(text: str) -> str:
    cfg = get_config()
    normalized = text or ""
    if cfg.UNICODE_NORMALIZE:
        normalized = unicodedata.normalize("NFKC", normalized)
    return normalized.casefold()


def scan_text(text: str) -> FilterResult:
    """扫描文本，返回最高优先级命中结果；无命中则 hit=False。"""
    try:
        cfg = get_config()
        if not text or not text.strip():
            return FilterResult(hit=False)

        normalized = normalize_text(text)
        word_lists = load_word_lists()

        for level in _LEVEL_ORDER:
            for word in word_lists.get(level, []):
                needle = normalize_text(word)
                if needle and needle in normalized:
                    action = "blocked" if level == "prohibited" else "logged"
                    if level != "prohibited":
                        action = "allowed"
                    return FilterResult(
                        hit=True,
                        level=level,
                        matched_word=mask_word(word),
                        matched_raw=word,
                        action=action if level != "prohibited" else "blocked",
                    )
        return FilterResult(hit=False)
    except Exception:
        logger.exception("内容安全扫描异常")
        cfg = get_config()
        if cfg.FAIL_OPEN:
            return FilterResult(hit=False)
        return FilterResult(
            hit=True,
            level="prohibited",
            matched_word="***",
            matched_raw=None,
            action="blocked",
        )
