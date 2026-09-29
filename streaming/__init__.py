"""流式输出与取消生成。"""
from streaming.cancel_manager import (
    CancelManager,
    get_cancel_manager,
    stream_token_for_user,
)
from streaming.sse import default_idle_timeout_sec, sse_generator, sse_pack
from streaming.stream_adapter import adapt_deepseek_stream, adapt_ollama_stream

__all__ = [
    "CancelManager",
    "get_cancel_manager",
    "stream_token_for_user",
    "sse_pack",
    "sse_generator",
    "default_idle_timeout_sec",
    "adapt_ollama_stream",
    "adapt_deepseek_stream",
]
