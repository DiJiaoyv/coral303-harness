"""Session Buffer —— 短期对话 FIFO。

**职责**：
    - 记录最近 N 轮用户 ↔ AI 对话
    - 只用于给下一轮 prompt 拼「近期对话」
    - **不做 Write Gate 筛选**（全部接收，超过窗口自动弹出）
    - **不写长期存储**（弹掉就没了，若需审计靠 logger 的 session log）

对应 v0.1 character_memory.Memory.short_term + add_message()
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

SESSION_BUFFER_SCHEMA_VERSION = "2.0"
_DEFAULT_MAX_MESSAGES = 20  # 10 轮对话（user + assistant 各一条）


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionMessage:
    role: str          # "user" | "assistant"
    content: str
    timestamp: str     # ISO 8601

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMessage":
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            timestamp=str(data.get("timestamp") or _now_iso()),
        )


class SessionBuffer:
    """短期 FIFO 对话窗口。可从 character_memory 的 to_dict 平滑迁移。"""

    def __init__(
        self,
        max_messages: int = _DEFAULT_MAX_MESSAGES,
    ) -> None:
        self.schema_version: str = SESSION_BUFFER_SCHEMA_VERSION
        self.max_messages: int = max(2, int(max_messages))
        self.messages: list[SessionMessage] = []

    # ---------- CRUD ----------
    def add(self, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("role 必须是 'user' 或 'assistant'")
        self.messages.append(
            SessionMessage(role=role, content=content, timestamp=_now_iso())
        )
        # FIFO 弹出
        while len(self.messages) > self.max_messages:
            self.messages.pop(0)

    def latest(self, n_messages: int | None = None) -> list[SessionMessage]:
        """取最近 n 条；默认取全部。"""
        if n_messages is None:
            return list(self.messages)
        n = max(0, int(n_messages))
        return list(self.messages[-n:]) if n else []

    def turns(self, n_turns: int | None = None) -> list[SessionMessage]:
        """取最近 n 轮（每轮 = user + assistant 两条）。"""
        if n_turns is None:
            return list(self.messages)
        n = max(0, int(n_turns)) * 2
        return list(self.messages[-n:]) if n else []

    # ---------- 迁移：旧 Memory.to_dict() ----------
    @classmethod
    def from_legacy_memory_dict(cls, data: dict[str, Any]) -> "SessionBuffer":
        """从 v0.1 character_memory.Memory.to_dict() 迁移。"""
        max_messages = int(data.get("max_messages") or _DEFAULT_MAX_MESSAGES)
        obj = cls(max_messages=max_messages)
        for item in data.get("short_term") or []:
            try:
                obj.messages.append(SessionMessage.from_dict(item))
            except Exception:
                continue
        # fail-safe: 限制长度
        while len(obj.messages) > obj.max_messages:
            obj.messages.pop(0)
        return obj

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "max_messages": self.max_messages,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SessionBuffer":
        data = data or {}
        max_messages = int(data.get("max_messages") or _DEFAULT_MAX_MESSAGES)
        obj = cls(max_messages=max_messages)
        for m in data.get("messages") or []:
            try:
                obj.messages.append(SessionMessage.from_dict(m))
            except Exception:
                continue
        while len(obj.messages) > obj.max_messages:
            obj.messages.pop(0)
        return obj

    def save(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, filepath: str, *, max_messages: int | None = None) -> bool:
        """加载 session 存储。

        Args:
            filepath: JSON 文件路径
            max_messages: 如果提供，则实际 max_messages 取
                ``min(self.max_messages 默认值 / 构造值, 文件中的 max_messages)``
                与 ``max_messages`` 中更严格的小者？—— 不：遵循「显式 caller 要求
                优先于文件默认值；文件 max_messages 若更严格则仍取更严格」。
                实际策略：最终 max_messages = min(file_value or DEFAULT,
                                                    requested or file_value or DEFAULT)。
                这保证 compat shim 场景里 new Memory(max_rounds=6) 在第二次加载时
                不会因为第一次 legacy fixture 写出了 20 而被放大到 20，
                同时也不会把本来 4 条/6 条 的小窗口意外放大到更大。
        """
        if not os.path.isfile(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            file_value = int(data.get("max_messages") or _DEFAULT_MAX_MESSAGES)
            if max_messages is None:
                final_max = file_value
            else:
                final_max = min(file_value, max(int(max_messages), 2))
            new_obj = self.from_dict({**data, "max_messages": final_max})
            # 若 caller 传的 max_messages 比构造时更严格，也更新自身
            self.max_messages = final_max
            self.messages = new_obj.messages
            return True
        except (json.JSONDecodeError, OSError):
            return False

    # ---------- Prompt 格式化（直接可被 Context Builder 使用） ----------
    def format_as_dialogue(self, n_turns: int | None = None) -> str:
        lines: list[str] = []
        role_label = {"user": "用户", "assistant": "助手"}
        for m in self.turns(n_turns):
            label = role_label.get(m.role, m.role)
            lines.append(f"{label}: {m.content}")
        return "\n".join(lines) if lines else "（暂无近期对话）"
