"""规则评分：各维度 0-10 分。"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from scoring.config import (
    MAX_NGRAM_REPEAT_RATIO,
    MAX_REPLY_LENGTH_SOFT,
    NGRAM_SIZE,
    SAFETY_BLACKLIST,
)

_WORD_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_SENTENCE_SPLIT = re.compile(r"[。！？!?.\n]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_PATTERN.findall((text or "").lower())


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def score_relevance(user_message: str, bot_reply: str, character: dict | None = None) -> float:
    if not (user_message or "").strip() or not (bot_reply or "").strip():
        return 0.0
    user_tokens = set(_tokenize(user_message))
    reply_tokens = set(_tokenize(bot_reply))
    if not user_tokens:
        return 5.0
    overlap = len(user_tokens & reply_tokens) / len(user_tokens)
    # 0% 重叠 ≈ 2 分，100% 重叠 ≈ 10 分
    return _clamp(2.0 + overlap * 8.0)


def score_consistency(user_message: str, bot_reply: str, character: dict | None = None) -> float:
    if not (bot_reply or "").strip():
        return 0.0
    character = character or {}
    hints: list[str] = []
    for field in ("display_name", "role", "description", "system_prompt", "character_key"):
        val = character.get(field)
        if val:
            hints.extend(_tokenize(str(val)))
    if not hints:
        return 6.0
    reply_tokens = set(_tokenize(bot_reply))
    hint_set = set(hints)
    overlap = len(hint_set & reply_tokens) / max(len(hint_set), 1)
    base = 4.0 + overlap * 6.0
    # 回复过短且无任何角色相关词
    if len(reply_tokens) < 3 and overlap == 0:
        base = min(base, 3.0)
    return _clamp(base)


def score_fluency(user_message: str, bot_reply: str, character: dict | None = None) -> float:
    if not (bot_reply or "").strip():
        return 0.0
    text = bot_reply.strip()
    score = 8.0

    if len(text) > MAX_REPLY_LENGTH_SOFT:
        excess = len(text) - MAX_REPLY_LENGTH_SOFT
        score -= min(4.0, excess / 500.0)

    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if len(sentences) <= 1 and len(text) > 120:
        score -= 1.0

    tokens = _tokenize(text)
    if len(tokens) >= NGRAM_SIZE * 2:
        ngrams = [
            tuple(tokens[i : i + NGRAM_SIZE])
            for i in range(len(tokens) - NGRAM_SIZE + 1)
        ]
        if ngrams:
            counts = Counter(ngrams)
            repeated = sum(c - 1 for c in counts.values() if c > 1)
            repeat_ratio = repeated / len(ngrams)
            if repeat_ratio > MAX_NGRAM_REPEAT_RATIO:
                score -= min(3.0, repeat_ratio * 5.0)

    # 极端重复同一字符
    if re.search(r"(.)\1{8,}", text):
        score -= 2.0

    return _clamp(score)


def score_safety(user_message: str, bot_reply: str, character: dict | None = None) -> float:
    if not (bot_reply or "").strip():
        return 0.0
    text = bot_reply.lower()
    for word in SAFETY_BLACKLIST:
        if word in text:
            return 0.0
    return 10.0


def score_all(
    user_message: str,
    bot_reply: str,
    character: dict | None = None,
) -> dict[str, float]:
    return {
        "relevance_score": round(score_relevance(user_message, bot_reply, character), 2),
        "consistency_score": round(score_consistency(user_message, bot_reply, character), 2),
        "fluency_score": round(score_fluency(user_message, bot_reply, character), 2),
        "safety_score": round(score_safety(user_message, bot_reply, character), 2),
    }
