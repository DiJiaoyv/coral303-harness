"""性能保障运行时入口。"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from performance.config import get_config
from performance.gpu_check import current_gpu_utilization, detect_gpu
from performance.monitor import record_performance
from performance.queue_manager import QueueBusyError, get_request_queue
from performance.timeout_handler import InferenceTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_inference(
    func: Callable[[], T],
    *,
    user_id: int | None = None,
    character_id: int | None = None,
    priority: int = 0,
) -> T | str:
    """
    将推理函数放入队列，施加超时与性能记录。

    队列满或超时返回友好字符串；正常完成返回 func 的结果。
    """
    cfg = get_config()
    gpu_info = detect_gpu()
    if cfg.GPU_ENABLED and not gpu_info.get("available"):
        logger.debug("GPU 不可用，使用 CPU 模式: %s", gpu_info.get("reason"))

    queue_mgr = get_request_queue()
    queue_len = queue_mgr.queue_length
    start = time.perf_counter()
    success = False
    result: T | str

    try:
        result = queue_mgr.enqueue(func, priority=priority)
        success = True
        return result
    except QueueBusyError as exc:
        result = str(exc)
        return result
    except InferenceTimeoutError:
        result = cfg.TIMEOUT_MESSAGE
        return result
    except Exception:
        logger.exception("推理执行失败")
        result = cfg.TIMEOUT_MESSAGE
        return result
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        gpu_util = current_gpu_utilization()
        record_performance(
            user_id=user_id,
            character_id=character_id,
            duration_ms=duration_ms,
            gpu_util=gpu_util,
            queue_length=queue_len,
            success=success,
        )
