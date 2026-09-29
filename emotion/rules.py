"""情绪规则引擎：用户行为 → PAD 偏移，支持热加载。"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

from emotion.config import RULES_FILE

logger = logging.getLogger(__name__)

DEFAULT_RULES: dict = {
    "version": 1,
    "behaviors": [
        {
            "id": "praise",
            "label": "夸奖",
            "keywords": ["你好棒", "厉害", "喜欢"],
            "patterns": [],
            "offset": {"pleasure": 0.2, "arousal": 0.1, "dominance": 0.1},
        },
        {
            "id": "criticism",
            "label": "批评",
            "keywords": ["你真笨", "讨厌", "差劲"],
            "patterns": [],
            "offset": {"pleasure": -0.3, "arousal": 0.2, "dominance": -0.1},
        },
        {
            "id": "share_secret",
            "label": "分享秘密",
            "keywords": ["告诉你一个秘密", "其实我"],
            "patterns": [],
            "offset": {"pleasure": 0.1, "arousal": -0.1, "dominance": 0.3},
        },
        {
            "id": "comfort",
            "label": "安慰",
            "keywords": ["别难过", "没事的", "加油"],
            "patterns": [],
            "offset": {"pleasure": 0.3, "arousal": -0.2, "dominance": 0.1},
        },
        {
            "id": "provocation",
            "label": "挑衅",
            "keywords": ["你敢吗", "来啊", "不服"],
            "patterns": [],
            "offset": {"pleasure": -0.1, "arousal": 0.4, "dominance": 0.2},
        },
        {
            "id": "indifference",
            "label": "冷漠",
            "keywords": ["哦", "知道了", "随便"],
            "patterns": [],
            "offset": {"pleasure": -0.1, "arousal": -0.2, "dominance": -0.1},
        },
        {
            "id": "farewell",
            "label": "告别",
            "keywords": ["再见", "拜拜", "我先走了"],
            "patterns": [],
            "offset": {"pleasure": -0.1, "arousal": -0.3, "dominance": 0.0},
        },
    ],
}

_cache: dict | None = None
_cache_mtime: float = 0.0
_last_check: float = 0.0
_CHECK_INTERVAL = 1.0


@dataclass(frozen=True)
class BehaviorRule:
    id: str
    label: str
    keywords: tuple[str, ...]
    patterns: tuple[str, ...]
    offset: dict[str, float]


def _parse_rules(data: dict) -> list[BehaviorRule]:
    rules: list[BehaviorRule] = []
    for item in data.get("behaviors", []):
        offset = item.get("offset", {})
        rules.append(
            BehaviorRule(
                id=str(item.get("id", "unknown")),
                label=str(item.get("label", "")),
                keywords=tuple(item.get("keywords", [])),
                patterns=tuple(item.get("patterns", [])),
                offset={
                    "pleasure": float(offset.get("pleasure", 0.0)),
                    "arousal": float(offset.get("arousal", 0.0)),
                    "dominance": float(offset.get("dominance", 0.0)),
                },
            )
        )
    return rules


def load_rules(force: bool = False) -> list[BehaviorRule]:
    """加载规则表，文件缺失或解析失败时返回内置默认规则。"""
    global _cache, _cache_mtime, _last_check

    now = time.time()
    if not force and _cache is not None and now - _last_check < _CHECK_INTERVAL:
        return _parse_rules(_cache)

    _last_check = now
    path = RULES_FILE
    try:
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            if force or _cache is None or mtime != _cache_mtime:
                with open(path, "r", encoding="utf-8") as f:
                    _cache = json.load(f)
                _cache_mtime = mtime
            return _parse_rules(_cache)
    except Exception as exc:
        logger.warning("情绪规则加载失败，使用默认规则: %s", exc)

    _cache = DEFAULT_RULES
    return _parse_rules(_cache)


def get_offset_for_behavior(behavior_id: str) -> dict[str, float]:
    """获取指定行为的 PAD 偏移量。"""
    for rule in load_rules():
        if rule.id == behavior_id:
            return dict(rule.offset)
    return {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0}


def reload_rules() -> list[BehaviorRule]:
    """强制热加载规则文件。"""
    return load_rules(force=True)
