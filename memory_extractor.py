# memory_extractor.py - 从对话中自动提取长期记忆（LLM）
import json
import re

from ollama_client import OllamaClient, OllamaError


class MemoryExtractor:
    """使用 LLM 从单轮对话中提取值得长期保存的关键事实。"""

    def __init__(
        self,
        ollama_client: OllamaClient,
        num_predict: int = 150,
        temperature: float = 0.3,
    ):
        self.ollama = ollama_client
        self.num_predict = num_predict
        self.temperature = temperature

    @staticmethod
    def _parse_facts_json(raw_text: str) -> list[dict]:
        """从 LLM 原始输出中解析 JSON 事实列表，容错处理 markdown 包裹等情况。"""
        text = raw_text.strip()

        # 尝试直接解析
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return MemoryExtractor._validate_facts(data)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 或 [...] 片段
        patterns = [
            r"```(?:json)?\s*(\[[\s\S]*?\])\s*```",
            r"(\[[\s\S]*?\])",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, list):
                        return MemoryExtractor._validate_facts(data)
                except json.JSONDecodeError:
                    continue

        return []

    @staticmethod
    def _validate_facts(items: list) -> list[dict]:
        """校验并规范化事实条目。"""
        valid = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fact = item.get("fact", "")
            if not isinstance(fact, str) or not fact.strip():
                continue
            importance = item.get("importance", 3)
            if not isinstance(importance, (int, float)):
                importance = 3
            importance = max(1, min(5, int(importance)))
            valid.append({"fact": fact.strip(), "importance": importance})
        return valid

    def _build_extraction_prompt(
        self,
        user_message: str,
        ai_response: str,
        existing_facts: list[dict],
    ) -> str:
        """组装记忆提取专用提示词。"""
        if existing_facts:
            existing_lines = "\n".join(f"- {f['fact']}" for f in existing_facts[-10:])
            existing_block = f"【已有长期记忆（请勿重复）】\n{existing_lines}\n\n"
        else:
            existing_block = "【已有长期记忆】\n（暂无）\n\n"

        return (
            "你是记忆提取助手。分析以下角色扮演对话，提取值得长期记住的关键事实。\n"
            "规则：\n"
            "1. 只提取对话中明确出现或强烈暗示的信息，不要编造\n"
            "2. 每条事实应简洁、独立、可检索\n"
            "3. importance 为 1-5：5=核心剧情，3=一般信息，1=次要细节\n"
            "4. 若无值得记录的新事实，返回空数组 []\n"
            "5. 只输出 JSON 数组，不要其他文字\n\n"
            f"{existing_block}"
            "【本轮对话】\n"
            f"用户: {user_message}\n"
            f"助手: {ai_response}\n\n"
            "输出格式示例：\n"
            '[{"fact": "用户委托追踪涅克瑟斯星区的走私犯", "importance": 4}]'
        )

    def extract(
        self,
        user_message: str,
        ai_response: str,
        existing_facts: list[dict] | None = None,
    ) -> tuple[list[dict], str]:
        """
        从一轮对话中提取新事实。

        Returns:
            (facts_list, raw_llm_output) — 解析后的事实列表与 LLM 原始输出
        """
        existing_facts = existing_facts or []
        prompt = self._build_extraction_prompt(
            user_message, ai_response, existing_facts
        )

        try:
            raw = self.ollama.generate(
                prompt,
                stream=False,
                options={
                    "num_predict": self.num_predict,
                    "temperature": self.temperature,
                },
            )
        except OllamaError:
            return [], ""

        facts = self._parse_facts_json(raw)
        return facts, raw

    @staticmethod
    def filter_new_facts(
        candidates: list[dict],
        existing_facts: list[dict],
    ) -> list[dict]:
        """过滤掉与已有记忆重复或高度相似的事实。"""
        existing_texts = {f["fact"].strip().lower() for f in existing_facts}
        new_facts = []

        for item in candidates:
            fact_lower = item["fact"].strip().lower()
            if fact_lower in existing_texts:
                continue
            # 简单相似度：互为子串则视为重复
            if any(
                fact_lower in ex or ex in fact_lower for ex in existing_texts
            ):
                continue
            new_facts.append(item)
            existing_texts.add(fact_lower)

        return new_facts
