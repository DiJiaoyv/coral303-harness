"""敏感词库加载（支持热加载）。"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from safety.config import get_config

logger = logging.getLogger(__name__)

# ============================================================
# 版本号（11.1 Versioning）
# ============================================================
# 敏感词库规则版本：修改 prohibited.json / warning.json / monitor.json 后 bump 此版本号。
# audit log / trace 通过此版本号定位「当时生效的敏感词库是哪一版」。
SAFETY_RULES_VERSION = "1.0"

_lock = threading.Lock()
_cache: dict[str, list[str]] | None = None
_last_check: float = 0.0
_last_mtime: float = 0.0

_LEVEL_FILES = {
    "prohibited": "prohibited.json",
    "warning": "warning.json",
    "monitor": "monitor.json",
}


def _lists_mtime(lists_dir: str) -> float:
    mtimes = []
    for filename in _LEVEL_FILES.values():
        path = os.path.join(lists_dir, filename)
        if os.path.isfile(path):
            mtimes.append(os.path.getmtime(path))
    return max(mtimes) if mtimes else 0.0


def _read_json_list(path: str) -> list[str]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def load_word_lists(force: bool = False) -> dict[str, list[str]]:
    """从 JSON 文件加载分层敏感词库。

    返回 dict 包含三个层级键（prohibited / warning / monitor）。
    规则版本号通过 get_rules_version() 单独查询，避免污染 list 类型签名。
    """
    global _cache, _last_check, _last_mtime
    cfg = get_config()
    now = time.monotonic()

    with _lock:
        if not force and _cache is not None:
            if now - _last_check < cfg.HOT_RELOAD_INTERVAL_SEC:
                return dict(_cache)
        _last_check = now

        current_mtime = _lists_mtime(cfg.WORD_LISTS_DIR)
        if not force and _cache is not None and current_mtime == _last_mtime:
            return dict(_cache)

        loaded: dict[str, list[str]] = {}
        for level, filename in _LEVEL_FILES.items():
            path = os.path.join(cfg.WORD_LISTS_DIR, filename)
            loaded[level] = _read_json_list(path)
        _cache = loaded
        _last_mtime = current_mtime
        return dict(_cache)


def reload_word_lists() -> dict[str, list[str]]:
    """手动强制重新加载词库。"""
    return load_word_lists(force=True)


def get_rules_version() -> str:
    """便捷读取当前生效的敏感词库版本号。"""
    return SAFETY_RULES_VERSION
