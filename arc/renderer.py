"""弧光渲染器：将弧光状态转为 Bootstrap HTML 片段。"""
from __future__ import annotations

from markupsafe import escape

from arc.config import STAGE_COLORS, STAGE_LABELS
from arc.models import ArcState


def _stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


def render_arc_card(arc_state: ArcState, *, readonly: bool = True) -> str:
    """
    生成 Bootstrap 弧光状态卡片 HTML。

    所有用户可控文本均经转义，防止 XSS。
    """
    stages = arc_state.stages
    current_idx = arc_state.stage_index()
    progress_pct = int(arc_state.progress * 100)

    segments = []
    for i, stage in enumerate(stages):
        color = STAGE_COLORS.get(stage, "#6c757d")
        active = " fw-bold" if stage == arc_state.current_stage else ""
        opacity = "1" if i <= current_idx else "0.35"
        label = escape(_stage_label(stage))
        segments.append(
            f'<span class="badge me-1{active}" '
            f'style="background-color:{color};opacity:{opacity}">{label}</span>'
        )

    goal_items = []
    for goal in arc_state.goals:
        checked = "checked" if goal.completed else ""
        disabled = "disabled" if readonly else ""
        strike = "text-decoration-line-through text-muted" if goal.completed else ""
        title = escape(goal.title)
        desc = escape(goal.description) if goal.description else ""
        desc_html = f'<small class="text-muted d-block">{desc}</small>' if desc else ""
        goal_items.append(
            f'<li class="list-group-item d-flex align-items-start gap-2">'
            f'<input type="checkbox" class="form-check-input mt-1" {checked} {disabled}>'
            f'<div class="{strike}"><strong>{title}</strong>{desc_html}</div>'
            f"</li>"
        )

    goals_html = (
        '<ul class="list-group list-group-flush">' + "".join(goal_items) + "</ul>"
        if goal_items
        else '<p class="text-muted small mb-0">暂无目标</p>'
    )

    auto_label = "开启" if arc_state.auto_advance else "关闭"
    current_label = escape(_stage_label(arc_state.current_stage))

    return f"""
<div class="card shadow-sm arc-status-card">
  <div class="card-header d-flex justify-content-between align-items-center">
    <span>弧光进度</span>
    <span class="badge bg-secondary">{current_label}</span>
  </div>
  <div class="card-body">
    <div class="mb-2">{"".join(segments)}</div>
    <div class="progress mb-3" style="height:8px;">
      <div class="progress-bar" role="progressbar"
           style="width:{progress_pct}%;background:#0d6efd;"
           aria-valuenow="{progress_pct}" aria-valuemin="0" aria-valuemax="100"></div>
    </div>
    <p class="small text-muted mb-2">总进度 {progress_pct}% · 自动推进 {auto_label}</p>
    <h6 class="mt-3">当前目标</h6>
    {goals_html}
  </div>
</div>
""".strip()


def render_arc_progress_bar(arc_state: ArcState) -> str:
    """管理后台用分段彩色进度条。"""
    parts = []
    seg_width = 100 / max(len(arc_state.stages), 1)
    for i, stage in enumerate(arc_state.stages):
        color = STAGE_COLORS.get(stage, "#dee2e6")
        active = i <= arc_state.stage_index()
        opacity = "1" if active else "0.25"
        label = escape(_stage_label(stage))
        highlight = "border border-dark" if stage == arc_state.current_stage else ""
        parts.append(
            f'<div class="text-center {highlight}" style="width:{seg_width}%;'
            f'background:{color};opacity:{opacity};padding:8px 4px;font-size:12px;">'
            f"{label}</div>"
        )
    return (
        '<div class="d-flex rounded overflow-hidden mb-3" style="min-height:36px;">'
        + "".join(parts)
        + "</div>"
    )
