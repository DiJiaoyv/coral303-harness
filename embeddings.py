# embeddings.py - Ollama 向量嵌入客户端
import time

import requests


class EmbeddingError(Exception):
    """嵌入请求失败。"""


class EmbeddingClient:
    """调用 Ollama /api/embeddings 生成文本向量。"""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434/api/embeddings",
        timeout: int = 60,
        max_retries: int = 2,
    ):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

    def embed(self, text: str) -> list[float]:
        """将文本转为 embedding 向量。"""
        text = text.strip()
        if not text:
            return []

        payload = {"model": self.model, "prompt": text}
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.base_url,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                vector = data.get("embedding", [])
                if not isinstance(vector, list) or not vector:
                    raise EmbeddingError("响应中无有效 embedding 字段")
                return [float(v) for v in vector]
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = EmbeddingError(f"嵌入请求失败: {exc}")
            except requests.exceptions.RequestException as exc:
                last_exc = EmbeddingError(f"嵌入请求失败: {exc}")
            except (ValueError, KeyError, TypeError) as exc:
                last_exc = EmbeddingError(f"嵌入响应解析失败: {exc}")

            if attempt < self.max_retries:
                time.sleep(1 + attempt)

        assert last_exc is not None
        raise last_exc


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
