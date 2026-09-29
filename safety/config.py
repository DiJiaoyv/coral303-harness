"""内容安全审核配置（支持 safety.env 热加载）。"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "safety.env")

_lock = threading.Lock()
_cached: SafetySettings | None = None
_cached_mtime: float = 0.0


@dataclass(frozen=True)
class SafetySettings:
    WORD_LISTS_DIR: str = os.path.join(_BASE_DIR, "word_lists")
    INPUT_BLOCKED_MESSAGE: str = "内容不合规，请重新输入"
    OUTPUT_BLOCKED_MESSAGE: str = "抱歉，我无法回答这个问题"
    UNICODE_NORMALIZE: bool = True
    LOG_RETENTION_DAYS: int = 90
    HOT_RELOAD_INTERVAL_SEC: float = 1.0
    FAIL_OPEN: bool = True


def _load_env_file() -> dict[str, str]:
    data: dict[str, str] = {}
    if not os.path.isfile(_CONFIG_PATH):
        return data
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            data[key.strip()] = val.strip()
    return data


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_int(value: str | None, default: int) -> int:
    if not value or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _build_settings() -> SafetySettings:
    file_vals = _load_env_file()

    def pick(name: str, default):
        env_val = os.environ.get(name)
        if env_val is not None:
            return env_val
        return file_vals.get(name, default)

    lists_dir = str(pick("WORD_LISTS_DIR", SafetySettings.WORD_LISTS_DIR))
    return SafetySettings(
        WORD_LISTS_DIR=lists_dir,
        INPUT_BLOCKED_MESSAGE=str(
            pick("INPUT_BLOCKED_MESSAGE", SafetySettings.INPUT_BLOCKED_MESSAGE)
        ),
        OUTPUT_BLOCKED_MESSAGE=str(
            pick("OUTPUT_BLOCKED_MESSAGE", SafetySettings.OUTPUT_BLOCKED_MESSAGE)
        ),
        UNICODE_NORMALIZE=_parse_bool(
            str(pick("UNICODE_NORMALIZE", "true")), True
        ),
        LOG_RETENTION_DAYS=max(
            1, _parse_int(str(pick("LOG_RETENTION_DAYS", "90")), 90)
        ),
        HOT_RELOAD_INTERVAL_SEC=float(
            pick("HOT_RELOAD_INTERVAL_SEC", "1.0") or 1.0
        ),
        FAIL_OPEN=_parse_bool(str(pick("FAIL_OPEN", "true")), True),
    )


def get_config() -> SafetySettings:
    global _cached, _cached_mtime
    mtime = os.path.getmtime(_CONFIG_PATH) if os.path.isfile(_CONFIG_PATH) else 0.0
    with _lock:
        if _cached is None or mtime != _cached_mtime:
            _cached = _build_settings()
            _cached_mtime = mtime
        return _cached


def reload_config() -> SafetySettings:
    """强制重新加载 safety.env。"""
    global _cached, _cached_mtime
    with _lock:
        _cached = None
        _cached_mtime = 0.0
    return get_config()
