# cloud_client.py - DeepSeek (OpenAI 兼容) 云端推理客户端
# 接口对齐 ollama_client.OllamaClient，可被 harness_core 直接注入替换。
# 通过环境变量读取密钥：
#   DEEPSEEK_API_KEY  (必填)
#   DEEPSEEK_BASE_URL (可选，默认 https://api.deepseek.com/v1/chat/completions)
#   DEEPSEEK_MODEL    (可选，覆盖 model_name)
import json
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

# 复用 OllamaClient 的异常族，保证 harness_core 异常处理兼容
try:
    from ollama_client import (
        OllamaError,
        OllamaConnectionError,
        OllamaTimeoutError,
        OllamaResponseError,
    )
except Exception:  # 兜底：异常族不可用时定义本地版本
    class OllamaError(Exception):
        pass

    class OllamaConnectionError(OllamaError):
        pass

    class OllamaTimeoutError(OllamaError):
        pass

    class OllamaResponseError(OllamaError):
        pass


DEFAULT_BASE_URL = "https://api.deepseek.com/v1/chat/completions"


class CloudClient:
    """DeepSeek OpenAI 兼容客户端，方法签名与 OllamaClient 一致。

    Harness 调用面：
        generate(prompt, **kwargs) -> str
        generate_stream(prompt, on_token=None, show_thinking=False, **kwargs) -> str
        iter_tokens(prompt, cancel_event=None, **kwargs) -> iterator[(field, token)]
        get_last_call() -> dict
        abort_stream() -> bool
        cancel_ollama_request(model=None) -> bool
    属性：model_name / base_url / last_request / last_response
    kwargs 约定：options={num_predict, temperature}，兼容 Ollama 调用习惯。
    """

    DEFAULT_OPTIONS = {"num_predict": 512, "temperature": 0.7}

    def __init__(
        self,
        model_name: str = "deepseek-chat",
        base_url: str | None = None,
        timeout: int = 120,
        max_retries: int = 2,
        allow_thinking_fallback: bool = True,
    ):
        self.model_name = os.getenv("DEEPSEEK_MODEL") or model_name
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.timeout = int(timeout)
        self.max_retries = max(0, max_retries)
        self.allow_thinking_fallback = allow_thinking_fallback
        self.last_request: dict | None = None
        self.last_response: dict | None = None
        self._active_stream_resp = None
        self._stream_lock = threading.Lock()
        self._system_prompt: str | None = None

    # ---------- 系统提示词 ----------
    def set_system_prompt(self, prompt: str | None) -> None:
        """设置默认 system prompt（generate 未显式传入时使用）。"""
        self._system_prompt = prompt

    # ---------- 调试 / 取消 ----------
    def get_last_call(self) -> dict:
        return {
            "request": self.last_request or {},
            "response": self.last_response or {},
        }

    def abort_stream(self) -> bool:
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
        return self.abort_stream()

    # ---------- 请求构造 ----------
    def _resolve_options(self, kwargs: dict) -> tuple[dict, float, int, str | None]:
        """从 kwargs 中解析 options/temperature/num_predict/system_prompt。"""
        options = {**self.DEFAULT_OPTIONS, **kwargs.pop("options", {})}
        temperature = float(kwargs.pop("temperature", options.get("temperature", 0.7)))
        max_tokens = int(kwargs.pop("num_predict", options.get("num_predict", 512)))
        system_prompt = kwargs.pop("system_prompt", self._system_prompt)
        return options, temperature, max_tokens, system_prompt

    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict]:
        msgs: list[dict] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def _post(self, payload: dict, stream: bool = False):
        if not self.api_key:
            raise OllamaError("DEEPSEEK_API_KEY 未设置")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return requests.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                    stream=stream,
                )
            except requests.exceptions.Timeout:
                last_exc = OllamaTimeoutError(f"请求超时（{self.timeout}s）")
            except requests.exceptions.ConnectionError:
                last_exc = OllamaConnectionError(f"无法连接云服务: {self.base_url}")
            except requests.exceptions.RequestException as exc:
                last_exc = OllamaError(f"云请求失败: {exc}")
            if attempt < self.max_retries:
                time.sleep(2 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    def _extract_text(self, data: dict) -> str:
        """从 OpenAI 兼容响应提取文本。"""
        choices = data.get("choices") if isinstance(data, dict) else None
        if choices and isinstance(choices, list):
            msg = choices[0].get("message", {}) if choices else {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        # 兼容 Ollama 风格
        if isinstance(data, dict) and isinstance(data.get("response"), str) and data["response"].strip():
            return data["response"].strip()
        raise OllamaResponseError("响应中未找到 content 字段")

    # ---------- 主生成接口 ----------
    def generate(self, prompt: str, **kwargs) -> str:
        """非流式生成。kwargs 中 stream=True 时退化为 generate_stream。"""
        if kwargs.get("stream"):
            kwargs = dict(kwargs)
            kwargs.pop("stream")
            return self.generate_stream(prompt, **kwargs)

        options, temperature, max_tokens, system_prompt = self._resolve_options(kwargs)
        messages = self._build_messages(prompt, system_prompt)
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        self.last_request = payload
        self.last_response = None
        resp = self._post(payload, stream=False)
        try:
            data = resp.json()
        except ValueError as exc:
            raise OllamaResponseError("响应不是有效的 JSON 格式") from exc
        if not isinstance(data, dict):
            raise OllamaResponseError("响应格式错误：期望 JSON 对象")
        # 4xx/5xx 时 DeepSeek 返回 {error: {...}}
        if resp.status_code >= 400:
            err = data.get("error", {})
            raise OllamaError(f"云服务返回 {resp.status_code}: {err.get('message', data)}")
        self.last_response = data
        return self._extract_text(data)

    def iter_tokens(self, prompt: str, cancel_event=None, **kwargs):
        """流式逐块 yield (field, token)。

        采用 DeepSeek SSE 流式，按 chunk content 增量 yield。
        若不支持流式则退化为整段返回（一次性 yield）。
        """
        options, temperature, max_tokens, system_prompt = self._resolve_options(kwargs)
        messages = self._build_messages(prompt, system_prompt)
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        self.last_request = payload
        self.last_response = None

        resp = self._post(payload, stream=True)
        resp.raise_for_status()
        with self._stream_lock:
            self._active_stream_resp = resp

        parts: list[str] = []
        try:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if cancel_event is not None and cancel_event.is_set():
                    break
                if not raw_line:
                    continue
                line = raw_line
                if line.startswith("data: "):
                    line = line[len("data: "):]
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content") or ""
                if token:
                    parts.append(token)
                    yield "response", token
        finally:
            with self._stream_lock:
                if self._active_stream_resp is resp:
                    self._active_stream_resp = None
            try:
                resp.close()
            except Exception:
                pass

        self.last_response = {
            "choices": [{"message": {"content": "".join(parts)}}],
            "stream": True,
        }

    def generate_stream(
        self,
        prompt: str,
        on_token=None,
        show_thinking: bool = False,
        **kwargs,
    ) -> str:
        """流式生成：逐 token 回调，返回完整文本。"""
        response_parts: list[str] = []
        for field, token in self.iter_tokens(prompt, **kwargs):
            if field == "response":
                response_parts.append(token)
                if on_token:
                    on_token(token, "response")
        aggregated = self.last_response or {}
        try:
            return self._extract_text(aggregated)
        except OllamaResponseError:
            return "".join(response_parts)


if __name__ == "__main__":
    # 自检：需要 DEEPSEEK_API_KEY
    key = os.getenv("DEEPSEEK_API_KEY", "")
    print(f"API Key: {key[:8]}...{key[-4:] if len(key) >= 4 else ''}")
    print(f"Model:   {os.getenv('DEEPSEEK_MODEL') or 'deepseek-chat'}")
    c = CloudClient()
    try:
        out = c.generate("用一句话介绍你自己。", options={"num_predict": 64, "temperature": 0.7})
        print(f"回复: {out}")
        print(f"用量: {c.last_response.get('usage')}")
    except Exception as exc:
        print(f"错误: {exc}")
