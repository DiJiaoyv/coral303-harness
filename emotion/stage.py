"""剧情阶段管理器：阶段定义、切换条件与情绪基线。"""
from __future__ import annotations

import logging

from emotion.config import (
    CONFLICT_EXIT_POSITIVE_COUNT,
    CONFLICT_STAGE,
    DEFAULT_STAGE,
    STAGE_BASELINES,
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_TRANSITION_RULES,
)
from emotion.models import EmotionStats, PADState

logger = logging.getLogger(__name__)


def get_stage_baseline(stage: str) -> PADState:
    """获取指定阶段的 PAD 基线。"""
    cfg = STAGE_BASELINES.get(stage, STAGE_BASELINES[DEFAULT_STAGE])
    return PADState(
        pleasure=float(cfg["pleasure"]),
        arousal=float(cfg["arousal"]),
        dominance=float(cfg["dominance"]),
    )


def get_stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


def get_stage_tendency(stage: str) -> str:
    cfg = STAGE_BASELINES.get(stage, STAGE_BASELINES[DEFAULT_STAGE])
    return str(cfg.get("tendency", ""))


def _stage_rank(stage: str) -> int:
    if stage == CONFLICT_STAGE:
        return -1
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return 0


def _can_advance(current: str, target: str) -> bool:
    """正向阶段只能向前推进，不可倒退。"""
    if target == CONFLICT_STAGE:
        return True
    if current == CONFLICT_STAGE:
        return target in STAGE_ORDER
    return _stage_rank(target) > _stage_rank(current)


def _meets_transition(stats: EmotionStats, stage: str) -> bool:
    rules = STAGE_TRANSITION_RULES.get(stage, {})
    if stage == "acquaintance":
        return stats.total_rounds >= rules.get("min_rounds", 10)
    if stage == "trust":
        return (
            stats.total_rounds >= rules.get("min_rounds", 30)
            and stats.secret_share_count >= rules.get("min_secret_shares", 1)
        )
    if stage == "intimate":
        return (
            stats.total_rounds >= rules.get("min_rounds", 50)
            and stats.positive_interaction_count
            >= rules.get("min_positive_interactions", 3)
        )
    if stage == CONFLICT_STAGE:
        return (
            stats.consecutive_negative_count
            >= rules.get("consecutive_negative", 3)
        )
    return False


def check_stage_transition(current_stage: str, stats: EmotionStats) -> str:
    """
    检查并返回新阶段。

    - 正向阶段仅向前推进
    - 冲突可随时进入
    - 冲突退出需积极互动
    """
    # 冲突退出：积极互动后回到可达的最高正向阶段
    if current_stage == CONFLICT_STAGE:
        if stats.positive_since_conflict >= CONFLICT_EXIT_POSITIVE_COUNT:
            best = DEFAULT_STAGE
            for stage in STAGE_ORDER:
                if _meets_transition(stats, stage):
                    best = stage
            logger.info("剧情阶段: conflict -> %s（积极互动退出冲突）", best)
            return best
        return CONFLICT_STAGE

    # 优先检测冲突进入
    if _meets_transition(stats, CONFLICT_STAGE):
        logger.info("剧情阶段: %s -> conflict（连续消极互动）", current_stage)
        return CONFLICT_STAGE

    # 正向推进：取满足条件的最高阶段
    best = current_stage
    for stage in STAGE_ORDER:
        if _meets_transition(stats, stage) and _can_advance(current_stage, stage):
            if _stage_rank(stage) > _stage_rank(best):
                best = stage

    if best != current_stage:
        logger.info(
            "剧情阶段: %s -> %s（rounds=%d）",
            current_stage,
            best,
            stats.total_rounds,
        )

    return best
