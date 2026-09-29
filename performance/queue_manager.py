"""请求队列管理（线程安全，单机同步场景）。"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from performance.config import get_config
from performance.timeout_handler import InferenceTimeoutError, execute_with_timeout

T = TypeVar("T")
logger = logging.getLogger(__name__)


class QueueBusyError(Exception):
    """队列已满，无法接受新请求。"""


class RequestQueue:
    """FIFO 请求队列，单 worker 顺序执行，支持优先级（数值越小越优先）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        self._pending = 0
        self._task_queue: queue.PriorityQueue[tuple] = queue.PriorityQueue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="harness-inference-worker")
        self._worker.start()

    @property
    def queue_length(self) -> int:
        with self._lock:
            return self._pending

    def enqueue(self, request_func: Callable[[], T], priority: int = 0) -> T:
        cfg = get_config()
        with self._lock:
            if self._pending >= cfg.QUEUE_MAX_SIZE:
                raise QueueBusyError(cfg.BUSY_MESSAGE)
            self._pending += 1
            self._counter += 1
            seq = self._counter

        result_box: dict[str, Any] = {}
        done = threading.Event()

        def _on_complete(status: str, payload: Any) -> None:
            result_box["status"] = status
            result_box["payload"] = payload
            done.set()

        self._task_queue.put((priority, seq, request_func, _on_complete))

        # 比推理超时略宽裕；到期仍无回调 → 视为超时（不是队列满）
        wait_timeout = max(cfg.TIMEOUT_SECONDS + 5.0, 10.0)
        if not done.wait(timeout=wait_timeout):
            with self._lock:
                self._pending = max(0, self._pending - 1)
            logger.warning(
                "enqueue wait timed out after %.1fs (worker 可能卡住或超时处理过慢)",
                wait_timeout,
            )
            raise InferenceTimeoutError("inference timeout")

        with self._lock:
            self._pending = max(0, self._pending - 1)

        status = result_box.get("status")
        if status == "ok":
            return result_box["payload"]
        if status == "timeout":
            raise InferenceTimeoutError("inference timeout")
        if status == "busy":
            raise QueueBusyError(result_box.get("payload") or cfg.BUSY_MESSAGE)
        # status == "error" 或未知：不抛裸 RuntimeError，交由上层返回友好提示
        return cfg.TIMEOUT_MESSAGE

    def try_begin_stream(self) -> bool:
        """
        为流式请求占用一个队列槽位（不阻塞 worker）。

        一旦开始流式输出即视为已出队处理，其它请求仍可排队。
        """
        cfg = get_config()
        with self._lock:
            if self._pending >= cfg.QUEUE_MAX_SIZE:
                return False
            self._pending += 1
            return True

    def end_stream(self) -> None:
        """释放流式请求占用的队列槽位。"""
        with self._lock:
            self._pending = max(0, self._pending - 1)

    def cancel(self, request_id: int) -> bool:
        """预留接口：当前实现为顺序队列，暂不支持按 ID 取消。"""
        return False

    def _worker_loop(self) -> None:
        while True:
            _priority, _seq, func, callback = self._task_queue.get()
            cfg = get_config()
            try:
                result = execute_with_timeout(func, timeout=cfg.TIMEOUT_SECONDS)
                callback("ok", result)
            except InferenceTimeoutError:
                callback("timeout", None)
            except QueueBusyError as exc:
                callback("busy", str(exc))
            except Exception as exc:
                # 必须回调，否则 enqueue 会拿到空 status
                # 统一用 "error"，由 enqueue 返回友好提示（避免压测被 RuntimeError 打断）
                logger.exception("inference worker failed: %s", exc)
                callback("error", str(exc) if exc else None)


_queue_singleton: RequestQueue | None = None
_queue_lock = threading.Lock()


def get_request_queue() -> RequestQueue:
    global _queue_singleton
    with _queue_lock:
        if _queue_singleton is None:
            _queue_singleton = RequestQueue()
        return _queue_singleton
