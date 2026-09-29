"""取消管理器：每个用户同一时间仅一个活跃生成流。"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _call_once(fn: Callable[[], None]) -> Callable[[], None]:
    """包装为至多执行一次的回调（防双重释放队列槽）。"""
    lock = threading.Lock()
    done = False

    def _wrapped() -> None:
        nonlocal done
        with lock:
            if done:
                return
            done = True
        try:
            fn()
        except Exception:
            logger.exception("cancel release callback failed")

    return _wrapped


class CancelManager:
    """线程安全的取消事件表，key 通常为 user:{user_id}。"""

    def __init__(self) -> None:
        self._events: dict[str, threading.Event] = {}
        self._release: dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()

    def begin(
        self,
        token: str,
        on_release: Callable[[], None] | None = None,
    ) -> threading.Event:
        """
        开始新流：自动取消同一 token 的旧流并触发其释放回调，返回新 Event。

        on_release: 取消或结束时调用（如 end_stream、关闭 Ollama 连接），至多一次。
        """
        with self._lock:
            old = self._events.get(token)
            old_release = self._release.pop(token, None)
            if old is not None:
                old.set()
            event = threading.Event()
            self._events[token] = event
            if on_release is not None:
                self._release[token] = _call_once(on_release)
            else:
                self._release.pop(token, None)

        # 在锁外调用旧释放，避免死锁
        if old_release is not None:
            old_release()
        return event

    def set_release(self, token: str, on_release: Callable[[], None]) -> None:
        """在流已 begin 且占用队列槽后登记释放回调。"""
        with self._lock:
            if token not in self._events:
                return
            self._release[token] = _call_once(on_release)

    def set_cancel(self, token: str) -> bool:
        """
        标记取消，并立即调用释放回调（end_stream / 关闭模型连接）。

        返回是否找到对应事件。
        """
        with self._lock:
            event = self._events.get(token)
            if event is None:
                return False
            event.set()
            release = self._release.pop(token, None)

        if release is not None:
            release()
        return True

    def release(self, token: str) -> None:
        """流正常结束时释放资源（若取消时已释放则 no-op）。"""
        with self._lock:
            release = self._release.pop(token, None)
        if release is not None:
            release()

    def is_cancelled(self, token: str) -> bool:
        with self._lock:
            event = self._events.get(token)
            return bool(event is not None and event.is_set())

    def clear(self, token: str) -> None:
        with self._lock:
            self._events.pop(token, None)
            self._release.pop(token, None)

    def get_event(self, token: str) -> threading.Event | None:
        with self._lock:
            return self._events.get(token)


_manager: CancelManager | None = None
_manager_lock = threading.Lock()


def get_cancel_manager() -> CancelManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = CancelManager()
        return _manager


def stream_token_for_user(user_id: int) -> str:
    return f"user:{user_id}"
