"""情绪渲染器：将 PAD 状态转为自然语言描述，拼入 system prompt。"""
from __future__ import annotations

from emotion.models import PADState
from emotion.stage import get_stage_label, get_stage_tendency


def _pleasure_label(value: float) -> str:
    if value >= 0.6:
        return "非常开心"
    if value >= 0.3:
        return "开心"
    if value >= 0.1:
        return "愉快"
    if value > -0.1:
        return "平静"
    if value > -0.3:
        return "有些低落"
    if value > -0.6:
        return "难过"
    return "非常沮丧"


def _arousal_label(value: float) -> str:
    if value >= 0.5:
        return "非常激动"
    if value >= 0.2:
        return "比较兴奋"
    if value > -0.1:
        return "平和"
    if value > -0.3:
        return "有些疲倦"
    return "非常平静"


def _dominance_label(value: float) -> str:
    if value >= 0.5:
        return "自信"
    if value >= 0.2:
        return "主动"
    if value > -0.1:
        return "自然"
    if value > -0.3:
        return "有些害羞"
    return "顺从"


def _overall_summary(pad: PADState, stage: str) -> str:
    p, a, d = pad.pleasure, pad.arousal, pad.dominance
    tendency = get_stage_tendency(stage)

    if stage == "conflict":
        return "角色心情不佳，语气冷淡疏离，倾向于简短回应或回避深入交流。"

    if p >= 0.5 and a >= 0.2:
        return "角色心情很好，说话语气活泼开朗，愿意主动分享。"
    if p >= 0.3:
        return "角色心情不错，语气轻松自然，会适度表达关心。"
    if p <= -0.3 and a >= 0.2:
        return "角色情绪低落但情绪激动，语气可能生硬或带有防备。"
    if p <= -0.2:
        return "角色心情低落，话少且语气平淡，不太愿意展开话题。"
    if a <= -0.2:
        return "角色比较安静，回复简短克制，不主动延伸话题。"

    if tendency:
        return f"角色处于{get_stage_label(stage)}阶段，表现倾向：{tendency}。"
    return "角色情绪平稳，以符合当前关系阶段的语气回复。"


def render_emotion(pad_state: PADState, stage: str) -> str:
    """将 PAD 状态与剧情阶段渲染为 prompt 片段。"""
    stage_label = get_stage_label(stage)
    lines = [
        "当前情绪状态：",
        f"愉悦度：{pad_state.pleasure:.1f}（{_pleasure_label(pad_state.pleasure)}）",
        f"激活度：{pad_state.arousal:.1f}（{_arousal_label(pad_state.arousal)}）",
        f"支配度：{pad_state.dominance:.1f}（{_dominance_label(pad_state.dominance)}）",
        f"剧情阶段：{stage_label}",
        f"综合表现：{_overall_summary(pad_state, stage)}",
        "【情绪合规】情绪仅用于塑造角色语气与态度，不得用于诱导用户消费或操纵用户行为。",
    ]
    return "\n".join(lines)
