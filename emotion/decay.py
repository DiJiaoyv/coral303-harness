"""情绪自然衰减：随对话轮次缓慢回归阶段基线。"""
from __future__ import annotations

from emotion.config import DECAY_RATE_PER_ROUND
from emotion.models import PADState


def apply_decay(
    pad_state: PADState,
    baseline: PADState,
    rounds: int = 1,
    rate: float = DECAY_RATE_PER_ROUND,
) -> PADState:
    """
    将 PAD 状态向基线衰减。

    每轮按 ``rate`` 比例靠近基线，默认 5%。
    """
    rounds = max(0, int(rounds))
    for _ in range(rounds):
        pad_state.decay_toward(baseline, rate)
    return pad_state
