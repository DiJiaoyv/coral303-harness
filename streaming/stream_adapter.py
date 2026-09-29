"""流式适配器：将各模型供应商的流式输出转为统一 token 文本。"""
from __future__ import annotations

import json
from collections.abc import Generator, Iterable
from typing import Any


def adapt_ollama_stream(
    chunks: Iterable[Any],
    *,
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    将 Ollama 流式 chunk（dict 或 JSON 行）转为纯 response token。

    每个 chunk 期望含 ``response`` 字段（Ollama /api/generate 流式格式）。
    """
    for chunk in chunks:
        if cancel_event is not None and cancel_event.is_set():
            break

        if isinstance(chunk, (bytes, bytearray)):
            try:
                chunk = chunk.decode("utf-8")
            except UnicodeDecodeError:
                continue

        if isinstance(chunk, str):
            line = chunk.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

        if not isinstance(chunk, dict):
            continue

        token = chunk.get("response") or ""
        if token:
            yield token


def adapt_deepseek_stream(
    chunks: Iterable[Any],
    *,
    cancel_event=None,
) -> Generator[str, None, None]:
    """
    DeepSeek / OpenAI 兼容流式格式预留适配。

    chunk 形如 choices[0].delta.content。
    """
    for chunk in chunks:
        if cancel_event is not None and cancel_event.is_set():
            break

        if isinstance(chunk, str):
            line = chunk.strip()
            if not line or line == "[DONE]":
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

        if not isinstance(chunk, dict):
            continue

        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        token = delta.get("content") or ""
        if token:
            yield token
