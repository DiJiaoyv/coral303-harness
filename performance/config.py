"""性能保障配置（支持热加载：修改后下次读取自动生效）。"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "performance.env")
_lock = threading.Lock()
_cached: PerformanceSettings | None = None
_cached_mtime: float = 0.0


@dataclass(frozen=True)
class PerformanceSettings:
    GPU_ENABLED: bool = True
    GPU_DEVICE_INDEX: int = 0
    GPU_MEMORY_LIMIT_MB: int = 0
    QUEUE_MAX_SIZE: int = 10
    TIMEOUT_SECONDS: float = 30.0
    BUSY_MESSAGE: str = "系统繁忙，请稍后重试"
    TIMEOUT_MESSAGE: str = "抱歉，我思考太久了，请再问一次"


def _parse_bool(value: str, default: bool) -> bool:
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


def _parse_float(value: str | None, default: float) -> float:
    if not value or not value.strip():
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _load_from_env_file() -> dict[str, str]:
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


def _build_settings() -> PerformanceSettings:
    file_vals = _load_from_env_file()

    def pick(name: str, default):
        env_val = os.environ.get(name)
        if env_val is not None:
            return env_val
        return file_vals.get(name, default)

    timeout = _parse_float(str(pick("TIMEOUT_SECONDS", "30")), 30.0)
    if timeout < 5:
        timeout = 5.0

    return PerformanceSettings(
        GPU_ENABLED=_parse_bool(str(pick("GPU_ENABLED", "true")), True),
        GPU_DEVICE_INDEX=_parse_int(str(pick("GPU_DEVICE_INDEX", "0")), 0),
        GPU_MEMORY_LIMIT_MB=_parse_int(str(pick("GPU_MEMORY_LIMIT_MB", "0")), 0),
        QUEUE_MAX_SIZE=max(1, _parse_int(str(pick("QUEUE_MAX_SIZE", "10")), 10)),
        TIMEOUT_SECONDS=timeout,
        BUSY_MESSAGE=str(pick("BUSY_MESSAGE", PerformanceSettings.BUSY_MESSAGE)),
        TIMEOUT_MESSAGE=str(pick("TIMEOUT_MESSAGE", PerformanceSettings.TIMEOUT_MESSAGE)),
    )


def get_config() -> PerformanceSettings:
    """读取配置（检测 performance.env 变更后热加载）。"""
    global _cached, _cached_mtime
    mtime = os.path.getmtime(_CONFIG_PATH) if os.path.isfile(_CONFIG_PATH) else 0.0
    with _lock:
        if _cached is None or mtime != _cached_mtime:
            _cached = _build_settings()
            _cached_mtime = mtime
        return _cached


def reload_config() -> PerformanceSettings:
    """强制重新加载配置。"""
    global _cached, _cached_mtime
    with _lock:
        _cached = None
        _cached_mtime = 0.0
    return get_config()
