"""Soul Core / State 管理后台视图。"""
from __future__ import annotations

import json

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from admin.forms.soul import SoulCoreForm, SoulStateForm
from admin.soul_paths import character_soul_dir, paths_for_character
from app.models.user import CharacterRecord
from soul.loader import load_soul_from_dir
from soul.validator import validate_state
from soul.writer import write_core_update, write_state


def _get_character_or_404(character_id: int) -> CharacterRecord:
    return CharacterRecord.query.filter_by(
        id=character_id, deleted=False
    ).first_or_404()


def _list_to_lines(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value or "")


def _lines_to_list(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _format_diff(diff: dict) -> list[dict]:
    rows = []
    for key, (old, new) in diff.items():
        rows.append({"field": key, "old": old, "new": new})
    return rows


@admin_bp.route("/soul/<int:character_id>/core", methods=["GET", "POST"])
@admin_required
def soul_core_edit(character_id: int):
    character = _get_character_or_404(character_id)
    char_dir = character_soul_dir(character.user_id, character.character_key)
    paths = paths_for_character(character)

    soul, core, _, warnings = load_soul_from_dir(char_dir)
    form = SoulCoreForm()

    if request.method == "GET":
        form.name.data = core.get("name", soul.name)
        form.role.data = core.get("role", soul.role)
        form.core_drive.data = core.get("core_drive", "")
        form.fear.data = core.get("fear", "")
        form.core_traits.data = _list_to_lines(core.get("core_traits", []))
        form.catchphrases.data = _list_to_lines(core.get("catchphrases", []))
        form.vocabulary.data = _list_to_lines(core.get("vocabulary", []))
        form.version.data = str(core.get("version", 1))
        form.locked.data = bool(core.get("locked", True))

    diff_rows = []
    if request.method == "POST" and form.validate_on_submit():
        confirm = request.form.get("confirm") == "1"
        force_unlock = request.form.get("force_unlock") == "1"
        if not confirm:
            flash("请勾选确认框后再保存核心修改。", "warning")
        else:
            updates = {
                "name": form.name.data.strip(),
                "role": (form.role.data or "").strip(),
                "core_drive": (form.core_drive.data or "").strip(),
                "fear": (form.fear.data or "").strip(),
                "core_traits": _lines_to_list(form.core_traits.data),
                "catchphrases": _lines_to_list(form.catchphrases.data),
                "vocabulary": _lines_to_list(form.vocabulary.data),
            }
            try:
                new_core, diff, new_version = write_core_update(
                    paths["core"],
                    updates,
                    force_unlock=force_unlock,
                )
                if diff:
                    diff_rows = _format_diff(diff)
                    log_admin_action(
                        "update_soul_core",
                        character_id,
                        json.dumps(diff, ensure_ascii=False),
                    )
                    flash(f"核心已更新（版本 {new_version}）。", "success")
                    return render_template(
                        "soul_core_edit.html",
                        form=form,
                        character=character,
                        core=new_core,
                        warnings=warnings,
                        diff_rows=diff_rows,
                        locked=new_core.get("locked", True),
                    )
                flash("未检测到变更。", "info")
            except PermissionError as exc:
                flash(str(exc), "danger")

    return render_template(
        "soul_core_edit.html",
        form=form,
        character=character,
        core=core,
        warnings=warnings,
        diff_rows=diff_rows,
        locked=bool(core.get("locked", True)),
    )


def _handle_state_post(character, paths, state, form):
    new_state = {
        "arc_stage": form.arc_stage.data,
        "current_goal": (form.current_goal.data or "").strip(),
    }
    validated, _ = validate_state(new_state)
    old_state = dict(state)
    write_state(validated, paths["state"])
    diff = {
        k: (old_state.get(k), validated.get(k))
        for k in validated
        if old_state.get(k) != validated.get(k)
    }
    if diff:
        log_admin_action(
            "update_soul_state",
            character.id,
            json.dumps(diff, ensure_ascii=False),
        )
        flash("叙事状态已保存。", "success")
        return True
    flash("未检测到变更。", "info")
    return False


@admin_bp.route("/soul/<int:character_id>/state", methods=["GET", "POST"])
@admin_required
def soul_state_edit(character_id: int):
    character = _get_character_or_404(character_id)
    char_dir = character_soul_dir(character.user_id, character.character_key)
    paths = paths_for_character(character)

    soul, _, state, warnings = load_soul_from_dir(char_dir)
    form = SoulStateForm()
    form.arc_stage.choices = [(s, s) for s in soul.ARC_STAGES]

    if request.method == "GET":
        form.arc_stage.data = state.get("arc_stage", soul.arc_stage)
        form.current_goal.data = state.get("current_goal", soul.current_goal)

    if request.method == "POST" and form.validate_on_submit():
        if _handle_state_post(character, paths, state, form):
            return redirect(url_for("admin.soul_state_edit", character_id=character_id))

    return render_template(
        "soul_state_edit.html",
        form=form,
        character=character,
        state=state,
        warnings=warnings,
    )


@admin_bp.route("/soul/<int:character_id>/state/user", methods=["GET", "POST"])
def soul_state_user_edit(character_id: int):
    """用户可编辑自己角色的叙事状态。"""
    if not current_user.is_authenticated:
        abort(401)
    character = _get_character_or_404(character_id)
    if character.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    char_dir = character_soul_dir(character.user_id, character.character_key)
    paths = paths_for_character(character)
    soul, _, state, warnings = load_soul_from_dir(char_dir)
    form = SoulStateForm()
    form.arc_stage.choices = [(s, s) for s in soul.ARC_STAGES]

    if request.method == "GET":
        form.arc_stage.data = state.get("arc_stage", soul.arc_stage)
        form.current_goal.data = state.get("current_goal", soul.current_goal)

    if request.method == "POST" and form.validate_on_submit():
        _handle_state_post(character, paths, state, form)
        return redirect(url_for("admin.soul_state_user_edit", character_id=character_id))

    return render_template(
        "soul_state_edit.html",
        form=form,
        character=character,
        state=state,
        warnings=warnings,
    )
