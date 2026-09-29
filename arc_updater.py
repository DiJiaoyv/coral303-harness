# arc_updater.py - 角色弧光与目标动态更新（LLM）
import json
import re

from ollama_client import OllamaClient, OllamaError
from soul import Soul


class ArcUpdater:
    """使用 LLM 评估对话是否应推动角色弧光或更新当前目标。"""

    def __init__(
        self,
        ollama_client: OllamaClient,
        num_predict: int = 120,
        temperature: float = 0.2,
    ):
        self.ollama = ollama_client
        self.num_predict = num_predict
        self.temperature = temperature

    @staticmethod
    def _parse_update_json(raw_text: str) -> dict | None:
        """从 LLM 输出解析 JSON 更新建议。"""
        text = raw_text.strip()

        for candidate in (text,):
            try:
                data = json.loads(candidate)
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
    ) -> str:
        stages = " / ".join(Soul.ARC_STAGES)
        return (
            "你是叙事分析助手。根据角色扮演对话，判断角色的弧光阶段或当前目标是否需要更新。\n"
            "规则：\n"
            f"1. arc_stage 只能是：{stages}，且只能保持或向前推进一阶（起点→转折点→终点）\n"
            "2. 仅当对话出现明确的剧情转折、任务接受/完成/变更时才更新\n"
            "3. 日常闲聊、简单问答不应触发更新\n"
            "4. current_goal 应简洁描述角色当前最想完成的事\n"
            "5. 只输出 JSON 对象，不要其他文字\n\n"
            "【当前角色叙事状态】\n"
            f"弧光阶段: {soul.arc_stage}\n"
            f"当前目标: {soul.current_goal}\n"
            f"情绪分数: {emotion_score:.1f}/10.0\n\n"
            "【本轮对话】\n"
            f"用户: {user_message}\n"
            f"助手: {ai_response}\n\n"
            "输出格式：\n"
            '{"should_update": true, "arc_stage": "转折点", '
            '"current_goal": "追踪并抓捕涅克瑟斯走私犯", "reason": "角色接受了新悬赏任务"}\n'
            "若无需更新：\n"
            '{"should_update": false}'
        )

    def evaluate(
        self,
        soul: Soul,
        user_message: str,
        ai_response: str,
        emotion_score: float,
    ) -> tuple[dict | None, str]:
        """
        评估是否应更新叙事状态。

        Returns:
            (update_dict, raw_llm_output)
            update_dict 为 None 表示无更新；否则含 arc_stage / current_goal / reason
        """
        prompt = self._build_prompt(
            soul, user_message, ai_response, emotion_score
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
            return None, ""

        data = self._parse_update_json(raw)
        if not data or not data.get("should_update"):
            return None, raw

        update: dict = {"reason": data.get("reason", "")}
        if data.get("arc_stage"):
            update["arc_stage"] = data["arc_stage"]
        if data.get("current_goal"):
            update["current_goal"] = data["current_goal"]

        if "arc_stage" not in update and "current_goal" not in update:
            return None, raw

        return update, raw

    def apply_to_soul(self, soul: Soul, update: dict) -> dict[str, tuple]:
        """将评估结果应用到 Soul，返回实际发生的变更。"""
        return soul.apply_narrative_update(
            arc_stage=update.get("arc_stage"),
            current_goal=update.get("current_goal"),
        )
