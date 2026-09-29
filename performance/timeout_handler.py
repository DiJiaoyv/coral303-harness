"""推理超时包装。"""
from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class InferenceTimeoutError(TimeoutError):
    """推理超时（对外不暴露内部细节）。"""


def execute_with_timeout(
    func: Callable[..., T],
    args: tuple | None = None,
    kwargs: dict | None = None,
    timeout: float | None = None,
) -> T:
    """
    在独立线程中执行 func，超时则抛出 InferenceTimeoutError。

    超时后不再 ``shutdown(wait=True)`` 阻塞队列 worker：
    否则底层 Ollama 请求未返回时，整个推理队列会被卡住，
    上层 ``done.wait(TIMEOUT+5)`` 到期后会误报「系统繁忙」。
    """
    args = args or ()
    kwargs = kwargs or {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise InferenceTimeoutError("inference timeout") from exc
    finally:
        # wait=False：超时后立刻释放 worker，允许处理下一个排队任务
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
