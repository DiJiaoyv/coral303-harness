"""弧光管理后台视图。"""
from __future__ import annotations

import json

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from admin.forms import ArcAutoAdvanceForm, ArcGoalEditForm, ArcGoalForm, ArcStageForm
from app.models.user import CharacterRecord
from arc.config import ADMIN_LOG_LIMIT, STAGE_LABELS
from arc.manager import (
    ArcNotFoundError,
    ArcValidationError,
    add_goal,
    complete_goal,
    delete_goal,
    get_arc,
    get_recent_logs,
    set_auto_advance,
    update_goal,
    update_stage,
)
from arc.renderer import render_arc_progress_bar
from extensions import db


def _get_character_or_404(character_id: int) -> CharacterRecord:
    return CharacterRecord.query.filter_by(
        id=character_id, deleted=False
    ).first_or_404()


@admin_bp.route("/arc/<int:character_id>", methods=["GET", "POST"])
@admin_required
def arc_dashboard(character_id: int):
    character = _get_character_or_404(character_id)
    arc_state = get_arc(character_id)
    operator = f"admin:{current_user.username}"

    stage_form = ArcStageForm()
    goal_form = ArcGoalForm()
    goal_edit_form = ArcGoalEditForm()
    auto_form = ArcAutoAdvanceForm()

    stage_form.new_stage.choices = [
        (s, STAGE_LABELS.get(s, s)) for s in arc_state.stages
    ]
    auto_form.auto_advance.data = arc_state.auto_advance

    if request.method == "POST":
        action = request.form.get("action", "")

        try:
            if action == "update_stage" and stage_form.validate_on_submit():
                update_stage(
                    character_id,
                    stage_form.new_stage.data,
                    operator=operator,
                    user_id=current_user.id,
                )
                flash("弧光阶段已更新", "success")
                log_admin_action(
                    "arc_update_stage", character_id, stage_form.new_stage.data
                )

            elif action == "add_goal" and goal_form.validate_on_submit():
                add_goal(
                    character_id,
                    goal_form.title.data,
                    goal_form.description.data or "",
                    operator=operator,
                    user_id=current_user.id,
                )
                flash("目标已添加", "success")
                log_admin_action("arc_add_goal", character_id, goal_form.title.data)

            elif action == "edit_goal" and goal_edit_form.validate_on_submit():
                update_goal(
                    character_id,
                    goal_edit_form.goal_id.data,
                    goal_edit_form.title.data,
                    goal_edit_form.description.data or "",
                    operator=operator,
                    user_id=current_user.id,
                )
                flash("目标已更新", "success")

            elif action == "toggle_goal":
                goal_id = request.form.get("goal_id", "")
                completed = request.form.get("completed") == "1"
                complete_goal(
                    character_id,
                    goal_id,
                    completed=completed,
                    operator=operator,
                    user_id=current_user.id,
                )
                flash("目标状态已更新", "success")

            elif action == "delete_goal":
                goal_id = request.form.get("goal_id", "")
                delete_goal(
                    character_id,
                    goal_id,
                    operator=operator,
                    user_id=current_user.id,
                )
                flash("目标已删除", "success")

            elif action == "auto_advance" and auto_form.validate_on_submit():
                set_auto_advance(
                    character_id,
                    auto_form.auto_advance.data,
                    operator=operator,
                    user_id=current_user.id,
                )
                flash("自动推进设置已保存", "success")

            else:
                flash("提交无效或校验失败", "warning")

        except (ArcValidationError, ArcNotFoundError) as exc:
            flash(str(exc), "danger")

        return redirect(url_for("admin.arc_dashboard", character_id=character_id))

    arc_state = get_arc(character_id)
    logs = get_recent_logs(character_id, limit=ADMIN_LOG_LIMIT)
    progress_html = render_arc_progress_bar(arc_state)

    return render_template(
        "arc_dashboard.html",
        character=character,
        arc_state=arc_state,
        stage_labels=STAGE_LABELS,
        stage_form=stage_form,
        goal_form=goal_form,
        goal_edit_form=goal_edit_form,
        auto_form=auto_form,
        progress_html=progress_html,
        logs=logs,
    )
