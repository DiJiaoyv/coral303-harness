# unified_analyzer.py - 合并记忆提取与弧光评估为单次 LLM 调用
import json
import re

from ollama_client import OllamaClient, OllamaError
from soul import Soul
from memory_extractor import MemoryExtractor


class UnifiedAnalyzer:
    """一次 LLM 调用同时提取长期记忆并评估叙事状态。"""

    def __init__(
        self,
        ollama_client: OllamaClient,
        num_predict: int = 250,
        temperature: float = 0.25,
    ):
        self.ollama = ollama_client
        self.num_predict = num_predict
        self.temperature = temperature

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict | None:
        text = raw_text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        patterns = [
            r"```(?:json)?\s*(\{[\s\S]*?\})\s*```",
            r"(\{[\s\S]*?\})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue
        return None

    def _build_prompt(
        self,
        soul: Soul,
        user_message: str,
        ai_response: str,
        emotion_score: float,
        existing_facts: list[dict],
        analyze_facts: bool,
        analyze_arc: bool,
    ) -> str:
        stages = " / ".join(Soul.ARC_STAGES)
        if existing_facts:
            fact_lines = "\n".join(f"- {f['fact']}" for f in existing_facts[-10:])
            facts_block = f"【已有长期记忆（请勿重复）】\n{fact_lines}\n"
        else:
            facts_block = "【已有长期记忆】\n（暂无）\n"

        tasks = []
        if analyze_facts:
            tasks.append("提取新的长期记忆事实（facts 数组）")
        if analyze_arc:
            tasks.append("评估是否更新弧光阶段或当前目标（narrative 对象）")

        return (
            "你是叙事分析助手。根据角色扮演对话，完成以下分析任务：\n"
            + "\n".join(f"- {t}" for t in tasks)
            + "\n\n规则：\n"
            "1. facts 每项含 fact（字符串）和 importance（1-5 整数）\n"
            "2. 无新事实时 facts 返回 []\n"
            f"3. narrative.arc_stage 只能是：{stages}，仅可保持或向前推进一阶\n"
            "4. 仅在有明确剧情进展时 narrative.should_update 为 true\n"
            "5. 只输出 JSON 对象，不要其他文字\n\n"
            f"{facts_block}\n"
            "【当前叙事状态】\n"
            f"弧光阶段: {soul.arc_stage}\n"
            f"当前目标: {soul.current_goal}\n"
            f"情绪分数: {emotion_score:.1f}/10.0\n\n"
            "【本轮对话】\n"
            f"用户: {user_message}\n"
            f"助手: {ai_response}\n\n"
            "输出格式：\n"
            '{"facts": [{"fact": "...", "importance": 3}], '
            '"narrative": {"should_update": false}}\n'
            "或：\n"
            '{"facts": [], "narrative": {"should_update": true, '
            '"arc_stage": "转折点", "current_goal": "...", "reason": "..."}}'
        )

    def analyze(
        self,
        soul: Soul,
        user_message: str,
        ai_response: str,
        emotion_score: float,
        existing_facts: list[dict] | None = None,
        analyze_facts: bool = True,
        analyze_arc: bool = True,
    ) -> tuple[dict, str]:
        """
        执行合并分析。

        Returns:
            (parsed_dict, raw_llm_output)
            parsed_dict 含 facts (list) 与 narrative (dict)
        """
        existing_facts = existing_facts or []
        prompt = self._build_prompt(
            soul,
            user_message,
            ai_response,
            emotion_score,
            existing_facts,
            analyze_facts,
            analyze_arc,
        )

        empty = {"facts": [], "narrative": {"should_update": False}}

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
            return empty, ""

        data = self._parse_json_object(raw) or empty

        facts = data.get("facts", [])
        if isinstance(facts, list):
            facts = MemoryExtractor._validate_facts(facts)
        else:
            facts = []

        narrative = data.get("narrative", {})
        if not isinstance(narrative, dict):
            narrative = {"should_update": False}

        if not analyze_facts:
            facts = []
        if not analyze_arc:
            narrative = {"should_update": False}

        return {"facts": facts, "narrative": narrative}, raw
