# ollama_client.py - 本地 Ollama 服务交互客户端
import json
import logging
import sys
import threading
import time
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Ollama 客户端基础异常。"""


class OllamaConnectionError(OllamaError):
    """无法连接到 Ollama 服务。"""


class OllamaTimeoutError(OllamaError):
    """Ollama 请求超时。"""


class OllamaResponseError(OllamaError):
    """Ollama 响应格式异常。"""


def _host_root(base_url: str) -> str:
    """从 generate URL 推导 Ollama 根地址，如 http://localhost:11434。"""
    url = (base_url or "").rstrip("/")
    for suffix in ("/api/generate", "/api/chat", "/api/embeddings"):
        if url.endswith(suffix):
            return url[: -len(suffix)] or url
    if "/api/" in url:
        return url.split("/api/", 1)[0]
    return url


def cancel_ollama_request(
    base_url: str = "http://localhost:11434/api/generate",
    *,
    model: str | None = None,
    timeout: float = 2.0,
) -> bool:
    """
    尽力向 Ollama 发送取消请求。

    说明：Ollama 主流取消方式是关闭流式 HTTP 连接；部分构建可能提供
    ``POST /api/cancel``。本函数做 best-effort POST，失败不抛错。
    """
    root = _host_root(base_url)
    cancel_url = urljoin(root.rstrip("/") + "/", "api/cancel")
    payload: dict = {}
    if model:
        payload["model"] = model
    try:
        resp = requests.post(cancel_url, json=payload, timeout=timeout)
        if resp.status_code < 400:
            return True
        logger.debug("Ollama /api/cancel status=%s", resp.status_code)
        return False
    except Exception as exc:
        logger.debug("Ollama /api/cancel unavailable: %s", exc)
        return False


class OllamaClient:
    """封装与本地 Ollama API 的 HTTP 交互。"""

    DEFAULT_OPTIONS = {"num_predict": 200}

    def __init__(
        self,
        model_name: str = "deepseek-r1:8b",
        base_url: str = "http://localhost:11434/api/generate",
        timeout: int = 300,
        max_retries: int = 2,
        allow_thinking_fallback: bool = True,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.allow_thinking_fallback = allow_thinking_fallback
        self.last_request: dict | None = None
        self.last_response: dict | None = None
        self._active_stream_resp = None
        self._stream_lock = threading.Lock()

    def get_last_call(self) -> dict:
        """返回最近一次 API 调用的请求与响应原始数据。"""
        return {
            "request": self.last_request or {},
            "response": self.last_response or {},
        }

    def abort_stream(self) -> bool:
        """关闭当前活跃的流式 HTTP 连接，促使 Ollama 停止生成并释放资源。"""
        with self._stream_lock:
            resp = self._active_stream_resp
            self._active_stream_resp = None
        if resp is None:
            return False
        try:
            resp.close()
            return True
        except Exception:
            return False

    def cancel_ollama_request(self, model: str | None = None) -> bool:
        """
        取消本客户端相关的 Ollama 生成。

        1. 关闭活跃流式连接（官方推荐，可释放 GPU/CPU 推理）
        2. 尽力 POST ``/api/cancel``（若服务端支持）
        """
        closed = self.abort_stream()
        posted = cancel_ollama_request(
            self.base_url,
            model=model or self.model_name,
        )
        return closed or posted

    def _build_payload(self, prompt: str, **kwargs) -> dict:
        """组装 Ollama API 请求体，合并默认参数与用户参数。"""
        stream = kwargs.pop("stream", False)
        options = {**self.DEFAULT_OPTIONS, **kwargs.pop("options", {})}

        payload = {
            "model": kwargs.pop("model", self.model_name),
            "prompt": prompt,
            "stream": stream,
            "options": options,
        }
        payload.update(kwargs)
        return payload

    def _extract_text(self, data: dict) -> str:
        """
        从 Ollama 响应中提取文本。

        deepseek-r1 等推理模型可能将最终回复放在 response，
        将推理过程放在 thinking；response 为空时回退到 thinking。
        """
        response_text = data.get("response", "")
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()

        if not self.allow_thinking_fallback:
            raise OllamaResponseError(
                "响应中未找到有效的 response 字段（已禁用 thinking 回退）"
            )

        thinking_text = data.get("thinking", "")
        if isinstance(thinking_text, str) and thinking_text.strip():
            return thinking_text.strip()

        raise OllamaResponseError(
            "响应中未找到有效的 response 或 thinking 字段"
        )

    def _post(self, payload: dict, stream: bool):
        """发送 POST 请求，失败时自动重试。"""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return requests.post(
                    self.base_url,
                    json=payload,
                    timeout=self.timeout,
                    stream=stream,
                )
            except requests.exceptions.Timeout as exc:
                last_exc = OllamaTimeoutError(
                    f"请求超时（{self.timeout}s），模型可能仍在加载中"
                )
            except requests.exceptions.ConnectionError as exc:
                last_exc = OllamaConnectionError(
                    f"无法连接到 Ollama 服务: {self.base_url}"
                )
            except requests.exceptions.RequestException as exc:
                last_exc = OllamaError(f"Ollama 请求失败: {exc}")

            if attempt < self.max_retries:
                time.sleep(2 * (attempt + 1))

        assert last_exc is not None
        raise last_exc

    def iter_tokens(
        self,
        prompt: str,
        cancel_event=None,
        **kwargs,
    ):
        """
        流式生成迭代器，逐块 yield (field, token)。

        field 为 "response" 或 "thinking"。调用后可通过 get_last_call() 获取聚合结果。
        若传入 cancel_event 且被 set，则关闭 HTTP 连接并停止迭代（释放资源）。
        """
        payload = self._build_payload(prompt, stream=True, **kwargs)
        self.last_request = payload
        self.last_response = None

        resp = self._post(payload, stream=True)
        resp.raise_for_status()
        with self._stream_lock:
            self._active_stream_resp = resp

        response_parts: list[str] = []
        thinking_parts: list[str] = []
        final_chunk: dict = {}
        cancelled = False

        try:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue

                final_chunk.update(chunk)

                thinking_token = chunk.get("thinking") or ""
                if thinking_token:
                    thinking_parts.append(thinking_token)
                    yield "thinking", thinking_token

                response_token = chunk.get("response") or ""
                if response_token:
                    response_parts.append(response_token)
                    yield "response", response_token

                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
        finally:
            with self._stream_lock:
                if self._active_stream_resp is resp:
                    self._active_stream_resp = None
            try:
                resp.close()
            except Exception:
                pass
            if cancelled:
                # 额外 best-effort：通知 Ollama 取消（若支持 /api/cancel）
                try:
                    cancel_ollama_request(self.base_url, model=self.model_name)
                except Exception:
                    pass

        self.last_response = {
            **final_chunk,
            "response": "".join(response_parts),
            "thinking": "".join(thinking_parts),
            "stream": True,
            "cancelled": cancelled,
        }

    def generate_stream(
        self,
        prompt: str,
        on_token=None,
        show_thinking: bool = False,
        **kwargs,
    ) -> str:
        """
        流式生成：逐 token 回调，同时返回完整文本。

        Args:
            prompt: 提示词
            on_token: 回调 fn(token: str, field: str)，field 为 response 或 thinking
            show_thinking: 是否流式输出 thinking 字段（deepseek-r1 推理过程）
        """
        response_parts: list[str] = []
        thinking_parts: list[str] = []

        for field, token in self.iter_tokens(prompt, **kwargs):
            if field == "thinking":
                thinking_parts.append(token)
                if show_thinking and on_token:
                    on_token(token, "thinking")
            elif field == "response":
                response_parts.append(token)
                if on_token:
                    on_token(token, "response")

        aggregated = self.last_response or {}
        return self._extract_text(aggregated)

    def generate(self, prompt: str, **kwargs) -> str:
        """
        向 Ollama 发送生成请求并返回文本结果。

        kwargs 中 stream=True 时走流式路径（无 on_token 则只收集不打印）。
        """
        if kwargs.get("stream"):
            kwargs = dict(kwargs)
            kwargs.pop("stream")
            return self.generate_stream(prompt, **kwargs)

        payload = self._build_payload(prompt, **kwargs)
        self.last_request = payload
        self.last_response = None

        resp = self._post(payload, stream=False)
        resp.raise_for_status()

        try:
            data = resp.json()
        except ValueError as exc:
            raise OllamaResponseError("响应不是有效的 JSON 格式") from exc

        if not isinstance(data, dict):
            raise OllamaResponseError("响应格式错误：期望 JSON 对象")

        self.last_response = data
        return self._extract_text(data)


# 快速测试
if __name__ == "__main__":
    client = OllamaClient()

    print(f"模型: {client.model_name}")
    print(f"API:  {client.base_url}")
    print("流式测试（首次加载可能较慢）...\n")

    def _print_token(token: str, field: str) -> None:
        if field == "thinking":
            return
        sys.stdout.write(token)
        sys.stdout.flush()

    try:
        print("回复: ", end="")
        result = client.generate_stream(
            "用一句话介绍你自己。",
            on_token=_print_token,
        )
        print(f"\n\n完整长度: {len(result)} 字符")

    except OllamaConnectionError as e:
        print(f"[连接错误] {e}")
    except OllamaTimeoutError as e:
        print(f"[超时] {e}")
    except OllamaResponseError as e:
        print(f"[响应错误] {e}")
    except OllamaError as e:
        print(f"[错误] {e}")
