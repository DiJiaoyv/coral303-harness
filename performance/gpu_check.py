"""GPU 检测与监控（无 NVIDIA 驱动时优雅降级）。"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

from performance.config import get_config

logger = logging.getLogger(__name__)

_gpu_cache: dict[str, Any] | None = None


def _parse_nvidia_smi() -> dict[str, Any] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        lines = [ln.strip() for ln in proc.stdout.strip().splitlines() if ln.strip()]
        gpus = []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "memory_total_mb": float(parts[2]),
                "memory_free_mb": float(parts[3]),
                "memory_used_mb": float(parts[4]),
                "utilization_pct": float(parts[5]),
            })
        return gpus or None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _read_pynvml_util(device_index: int) -> float | None:
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        return float(util.gpu)
    except Exception:
        return None
    finally:
        try:
            import pynvml  # type: ignore

            pynvml.nvmlShutdown()
        except Exception:
            pass


def detect_gpu(force_refresh: bool = False) -> dict[str, Any]:
    """
    检测 GPU 可用性。

    Returns:
        {"available": False} 或包含型号、显存、利用率等字段的字典。
    """
    global _gpu_cache
    if _gpu_cache is not None and not force_refresh:
        return dict(_gpu_cache)

    cfg = get_config()
    if not cfg.GPU_ENABLED:
        result = {"available": False, "reason": "disabled_in_config"}
        _gpu_cache = result
        return dict(result)

    gpus = _parse_nvidia_smi()
    if not gpus:
        result = {"available": False, "reason": "no_nvidia_smi"}
        _gpu_cache = result
        return dict(result)

    idx = cfg.GPU_DEVICE_INDEX
    selected = next((g for g in gpus if g["index"] == idx), gpus[0])

    if cfg.GPU_MEMORY_LIMIT_MB > 0 and selected["memory_free_mb"] < cfg.GPU_MEMORY_LIMIT_MB:
        logger.warning(
            "GPU 显存不足 (free=%.0fMB, limit=%dMB)，降级 CPU",
            selected["memory_free_mb"],
            cfg.GPU_MEMORY_LIMIT_MB,
        )
        result = {
            "available": False,
            "reason": "insufficient_vram",
            "device_index": selected["index"],
            "name": selected["name"],
        }
        _gpu_cache = result
        return dict(result)

    util = _read_pynvml_util(selected["index"])
    if util is None:
        util = selected.get("utilization_pct", 0.0)

    result = {
        "available": True,
        "device_index": selected["index"],
        "name": selected["name"],
        "memory_total_mb": selected["memory_total_mb"],
        "memory_free_mb": selected["memory_free_mb"],
        "memory_used_mb": selected["memory_used_mb"],
        "utilization_pct": util,
        "gpu_count": len(gpus),
    }
    _gpu_cache = result
    return dict(result)


def current_gpu_utilization() -> float:
    """返回当前 GPU 利用率（0-100），无 GPU 时返回 0。"""
    info = detect_gpu(force_refresh=True)
    if not info.get("available"):
        return 0.0
    return float(info.get("utilization_pct") or 0.0)
