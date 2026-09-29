"""PAD 情绪管理器：整合分析、规则、衰减、阶段与持久化。"""
from __future__ import annotations

import json
import logging
import os
from typing import Callable

from emotion.analyzer import analyze_user_input
from emotion.config import (
    NEGATIVE_BEHAVIORS,
    POSITIVE_BEHAVIORS,
)
from emotion.decay import apply_decay
from emotion.models import EmotionRuntimeState
from emotion.renderer import render_emotion
from emotion.rules import get_offset_for_behavior, load_rules
from emotion.config import CONFLICT_STAGE
from emotion.stage import check_stage_transition, get_stage_baseline, get_stage_label

logger = logging.getLogger(__name__)


class PADEmotionManager:
    """
    Harness 引擎使用的情绪管理器。

    异常时 fail-open：使用默认情绪值，不中断对话。
    """

    def __init__(self, default_score: float = 5.0):
        self.state = EmotionRuntimeState.default()
        # 兼容旧配置：将 default_score 映射为初始愉悦度
        if default_score != 5.0:
            self.state.pad.pleasure = (default_score - 5.0) / 4.5
        self._log_callback: Callable[[str, str, object, object], None] | None = None

    @property
    def score(self) -> float:
        """兼容 unified_analyzer / arc_updater 的 1–10 情绪分。"""
        return self.state.legacy_score

    @property
    def pad(self):
        return self.state.pad

    @property
    def stage(self) -> str:
        return self.state.stage

    def set_log_callback(
        self, callback: Callable[[str, str, object, object], None] | None
    ) -> None:
        self._log_callback = callback

    def load(self, filepath: str = "emotion_state.json") -> None:
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.state = EmotionRuntimeState.from_dict(data)
                logger.debug("情绪状态已从 %s 加载", filepath)
            else:
                logger.debug("未找到情绪文件 %s，使用默认值", filepath)
        except Exception as exc:
            logger.warning("情绪状态加载失败，使用默认值: %s", exc)
            self.state = EmotionRuntimeState.default()

    def save(self, filepath: str = "emotion_state.json") -> None:
        try:
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("情绪状态保存失败: %s", exc)

    def sync_to_database(self, character_id: int | None) -> None:
        """将情绪状态同步至 Character.emotion_state（仅描述角色情绪）。"""
        if not character_id:
            return
        try:
            from app.models.user import CharacterRecord
            from extensions import db

            record = CharacterRecord.query.get(character_id)
            if record is None:
                return
            record.emotion_state = json.dumps(
                self.state.to_dict(), ensure_ascii=False
            )
            db.session.commit()
        except Exception as exc:
            logger.debug("情绪 DB 同步跳过: %s", exc)

    def process_user_turn(self, user_message: str) -> str:
        """
        处理单轮用户输入：分析行为 → 偏移 → 衰减 → 阶段切换。

        Returns:
            检测到的行为类别 ID
        """
        try:
            load_rules()
            behavior = analyze_user_input(user_message)
            self._apply_behavior(behavior)
            baseline = get_stage_baseline(self.state.stage)
            apply_decay(self.state.pad, baseline, rounds=1)
            self.state.stats.total_rounds += 1
            old_stage = self.state.stage
            self.state.stage = check_stage_transition(
                self.state.stage, self.state.stats
            )
            if self.state.stage == CONFLICT_STAGE and old_stage != CONFLICT_STAGE:
                self.state.stats.positive_since_conflict = 0
            if old_stage != self.state.stage and self._log_callback:
                self._log_callback(
                    "emotion", "stage", old_stage, self.state.stage
                )
            return behavior
        except Exception as exc:
            logger.warning("情绪处理异常，保持当前状态: %s", exc)
            return "neutral"

    def _apply_behavior(self, behavior: str) -> None:
        self.state.stats.last_behavior = behavior
        offset = get_offset_for_behavior(behavior)
        old_pad = self.state.pad.copy()
        self.state.pad.apply_offset(**offset)

        if behavior in POSITIVE_BEHAVIORS:
            self.state.stats.positive_interaction_count += 1
            self.state.stats.consecutive_negative_count = 0
            if self.state.stage == CONFLICT_STAGE:
                self.state.stats.positive_since_conflict += 1
            if behavior == "share_secret":
                self.state.stats.secret_share_count += 1
        elif behavior in NEGATIVE_BEHAVIORS:
            self.state.stats.consecutive_negative_count += 1
        elif behavior != "neutral":
            self.state.stats.consecutive_negative_count = 0

        if (
            old_pad.pleasure != self.state.pad.pleasure
            or old_pad.arousal != self.state.pad.arousal
            or old_pad.dominance != self.state.pad.dominance
        ):
            self.state.update_count += 1
            if self._log_callback:
                self._log_callback(
                    "emotion",
                    "pad",
                    old_pad.to_dict(),
                    self.state.pad.to_dict(),
                )

    def render_prompt_section(self) -> str:
        try:
            return render_emotion(self.state.pad, self.state.stage)
        except Exception as exc:
            logger.warning("情绪渲染失败，使用默认描述: %s", exc)
            return render_emotion(
                EmotionRuntimeState.default().pad,
                EmotionRuntimeState.default().stage,
            )

    def to_dict(self) -> dict:
        return self.state.to_dict()

    def to_admin_display(self) -> dict:
        """管理后台只读展示用。"""
        return {
            "pleasure": round(self.state.pad.pleasure, 2),
            "arousal": round(self.state.pad.arousal, 2),
            "dominance": round(self.state.pad.dominance, 2),
            "stage": self.state.stage,
            "stage_label": get_stage_label(self.state.stage),
            "total_rounds": self.state.stats.total_rounds,
        }
