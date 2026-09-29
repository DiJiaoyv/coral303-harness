"""SSE 工具：打包事件与可取消生成器包装。"""
from __future__ import annotations

import json
import time
from collections.abc import Generator, Iterable
from typing import Any


def default_idle_timeout_sec() -> float:
    """与性能模块 TIMEOUT_SECONDS 对齐（默认 30 秒）。"""
    try:
        from performance.config import get_config

        return float(get_config().TIMEOUT_SECONDS)
    except Exception:
        return 30.0


def sse_pack(event_type: str, data: Any) -> str:
    """生成 SSE 格式字符串。"""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False)
    # 多行 data 需按 SSE 规范拆分
    lines = payload.split("\n")
    data_block = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event_type}\n{data_block}\n\n"


def sse_generator(
    source: Iterable[tuple[str, Any]],
    cancel_event=None,
    *,
    idle_timeout_sec: float | None = None,
) -> Generator[str, None, None]:
    """
    将 (event_type, data) 迭代包装为 SSE 字符串流。

    每次 yield 前检查取消标志；超时无产出则发送 error 并结束。
    idle_timeout_sec 默认读取 performance.TIMEOUT_SECONDS。
    """
    if idle_timeout_sec is None:
        idle_timeout_sec = default_idle_timeout_sec()

    last_emit = time.monotonic()
    try:
        for event_type, data in source:
            if cancel_event is not None and cancel_event.is_set():
                yield sse_pack("cancelled", {"message": "生成已取消"})
                return

            now = time.monotonic()
            if now - last_emit > idle_timeout_sec:
                yield sse_pack("error", {"message": "连接超时，已断开"})
                return

            yield sse_pack(event_type, data)
            last_emit = now

            if cancel_event is not None and cancel_event.is_set():
                yield sse_pack("cancelled", {"message": "生成已取消"})
                return
    except GeneratorExit:
        raise
    except Exception as exc:
        yield sse_pack("error", {"message": str(exc)})
