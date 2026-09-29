# emotion.py - AI 角色情绪状态管理
import json
import os


_POSITIVE_WORDS = ("谢谢", "感谢", "好", "不错", "同意", "成交", "合作", "信任", "帮助")
_NEGATIVE_WORDS = ("不", "拒绝", "威胁", "危险", "骗", "背叛", "杀", "滚", "讨厌", "愤怒")


class Emotion:
    """管理角色情绪分数，支持持久化到 emotion_state.json。"""

    MIN_SCORE = 1.0
    MAX_SCORE = 10.0

    def __init__(self, default_score: float = 5.0):
        self.score = self._clamp(default_score)
        self.update_count = 0

    @staticmethod
    def _clamp(value: float) -> float:
        return max(Emotion.MIN_SCORE, min(Emotion.MAX_SCORE, value))

    def estimate_delta(self, text: str) -> float:
        """根据文本关键词估算情绪变化量。"""
        delta = 0.0
        for word in _POSITIVE_WORDS:
            if word in text:
                delta += 0.2
        for word in _NEGATIVE_WORDS:
            if word in text:
                delta -= 0.2
        return delta

    def update_from_text(self, text: str) -> tuple[float, float]:
        """
        根据文本更新情绪分数。

        Returns:
            (old_score, new_score)
        """
        old_score = self.score
        delta = self.estimate_delta(text)
        self.score = self._clamp(self.score + delta)
        if old_score != self.score:
            self.update_count += 1
        return old_score, self.score

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "update_count": self.update_count,
        }

    def save(self, filepath: str = "emotion_state.json") -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"[Emotion] 状态已保存至 {filepath}")

    def load(self, filepath: str = "emotion_state.json") -> None:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.score = self._clamp(float(data.get("score", self.score)))
            self.update_count = int(data.get("update_count", 0))
            print(f"[Emotion] 状态已从 {filepath} 加载 (score={self.score:.1f})")
        else:
            print(f"[Emotion] 未找到状态文件 {filepath}，使用默认情绪。")
