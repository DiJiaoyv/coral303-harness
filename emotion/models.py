"""PAD 情绪状态数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

from emotion.config import (
    CONFLICT_STAGE,
    DEFAULT_AROUSAL,
    DEFAULT_DOMINANCE,
    DEFAULT_PLEASURE,
    DEFAULT_STAGE,
    PAD_MAX,
    PAD_MIN,
)


def clamp_pad(value: float) -> float:
    return max(PAD_MIN, min(PAD_MAX, value))


@dataclass
class PADState:
    """Pleasure-Arousal-Dominance 三维情绪状态。"""

    pleasure: float = DEFAULT_PLEASURE
    arousal: float = DEFAULT_AROUSAL
    dominance: float = DEFAULT_DOMINANCE

    def apply_offset(
        self,
        pleasure: float = 0.0,
        arousal: float = 0.0,
        dominance: float = 0.0,
    ) -> "PADState":
        self.pleasure = clamp_pad(self.pleasure + pleasure)
        self.arousal = clamp_pad(self.arousal + arousal)
        self.dominance = clamp_pad(self.dominance + dominance)
        return self

    def decay_toward(self, baseline: "PADState", rate: float) -> "PADState":
        """向基线衰减指定比例。"""
        self.pleasure += (baseline.pleasure - self.pleasure) * rate
        self.arousal += (baseline.arousal - self.arousal) * rate
        self.dominance += (baseline.dominance - self.dominance) * rate
        self.pleasure = clamp_pad(self.pleasure)
        self.arousal = clamp_pad(self.arousal)
        self.dominance = clamp_pad(self.dominance)
        return self

    def copy(self) -> "PADState":
        return PADState(self.pleasure, self.arousal, self.dominance)

    def to_dict(self) -> dict:
        return {
            "pleasure": round(self.pleasure, 4),
            "arousal": round(self.arousal, 4),
            "dominance": round(self.dominance, 4),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "PADState":
        if not data:
            return cls()
        return cls(
            pleasure=float(data.get("pleasure", DEFAULT_PLEASURE)),
            arousal=float(data.get("arousal", DEFAULT_AROUSAL)),
            dominance=float(data.get("dominance", DEFAULT_DOMINANCE)),
        )


@dataclass
class EmotionStats:
    """剧情阶段判定所需的统计数据。"""

    total_rounds: int = 0
    secret_share_count: int = 0
    positive_interaction_count: int = 0
    consecutive_negative_count: int = 0
    positive_since_conflict: int = 0
    last_behavior: str = "neutral"

    def to_dict(self) -> dict:
        return {
            "total_rounds": self.total_rounds,
            "secret_share_count": self.secret_share_count,
            "positive_interaction_count": self.positive_interaction_count,
            "consecutive_negative_count": self.consecutive_negative_count,
            "positive_since_conflict": self.positive_since_conflict,
            "last_behavior": self.last_behavior,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "EmotionStats":
        if not data:
            return cls()
        return cls(
            total_rounds=int(data.get("total_rounds", 0)),
            secret_share_count=int(data.get("secret_share_count", 0)),
            positive_interaction_count=int(
                data.get("positive_interaction_count", 0)
            ),
            consecutive_negative_count=int(
                data.get("consecutive_negative_count", 0)
            ),
            positive_since_conflict=int(
                data.get("positive_since_conflict", 0)
            ),
            last_behavior=str(data.get("last_behavior", "neutral")),
        )


@dataclass
class EmotionRuntimeState:
    """完整情绪运行时状态（PAD + 阶段 + 统计）。"""

    pad: PADState = field(default_factory=PADState)
    stage: str = DEFAULT_STAGE
    stats: EmotionStats = field(default_factory=EmotionStats)
    update_count: int = 0

    @property
    def legacy_score(self) -> float:
        """将愉悦度映射为 1–10 分，供旧模块兼容。"""
        return max(1.0, min(10.0, 5.0 + self.pad.pleasure * 4.5))

    def to_dict(self) -> dict:
        return {
            "pad": self.pad.to_dict(),
            "stage": self.stage,
            "stats": self.stats.to_dict(),
            "update_count": self.update_count,
            "legacy_score": round(self.legacy_score, 2),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "EmotionRuntimeState":
        if not data:
            return cls()

        # 兼容旧版 emotion_state.json（仅 score 字段）
        if "score" in data and "pad" not in data:
            pleasure = (float(data["score"]) - 5.0) / 4.5
            return cls(
                pad=PADState(pleasure=pleasure),
                update_count=int(data.get("update_count", 0)),
            )

        return cls(
            pad=PADState.from_dict(data.get("pad")),
            stage=str(data.get("stage", DEFAULT_STAGE)),
            stats=EmotionStats.from_dict(data.get("stats")),
            update_count=int(data.get("update_count", 0)),
        )

    @classmethod
    def default(cls) -> "EmotionRuntimeState":
        return cls()
