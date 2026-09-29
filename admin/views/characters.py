import json
from datetime import datetime, timezone

from flask import flash, redirect, render_template, url_for
from flask_login import current_user

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.character_sync import slug_character_key, sync_character_to_files
from admin.decorators import admin_required
from admin.forms import CharacterForm
from app.models.user import CharacterRecord
from extensions import db


def _parse_emotion_display(character: CharacterRecord | None) -> dict | None:
    """解析角色情绪状态供管理后台只读展示。"""
    if character is None or not character.emotion_state:
        return None
    try:
        data = json.loads(character.emotion_state)
        if not data:
            return None
        pad = data.get("pad", {})
        from emotion.stage import get_stage_label

        stage = data.get("stage", "stranger")
        stats = data.get("stats", {})
        return {
            "pleasure": round(float(pad.get("pleasure", 0.0)), 2),
            "arousal": round(float(pad.get("arousal", 0.0)), 2),
            "dominance": round(float(pad.get("dominance", 0.0)), 2),
            "stage": stage,
            "stage_label": get_stage_label(stage),
            "total_rounds": int(stats.get("total_rounds", 0)),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _name_exists(name: str, exclude_id: int | None = None) -> bool:
    q = CharacterRecord.query.filter(
        CharacterRecord.display_name == name,
        CharacterRecord.deleted.is_(False),
    )
    if exclude_id:
        q = q.filter(CharacterRecord.id != exclude_id)
    return q.first() is not None


@admin_bp.route("/characters")
@admin_required
def characters_list():
    characters = (
        CharacterRecord.query.filter_by(deleted=False)
        .order_by(CharacterRecord.updated_at.desc())
        .all()
    )
    return render_template("characters_list.html", characters=characters)


@admin_bp.route("/characters/new", methods=["GET", "POST"])
@admin_required
def character_create():
    form = CharacterForm()
    if form.validate_on_submit():
        if _name_exists(form.name.data):
            flash("角色名已存在", "danger")
            return render_template("character_form.html", form=form, title="创建角色"), 400

        character_key = slug_character_key(form.name.data)
        dup = CharacterRecord.query.filter_by(
            user_id=current_user.id,
            character_key=character_key,
            deleted=False,
        ).first()
        if dup:
            flash("角色标识已存在，请更换名称", "danger")
            return render_template("character_form.html", form=form, title="创建角色"), 400

        character = CharacterRecord(
            user_id=current_user.id,
            character_key=character_key,
            display_name=form.name.data,
            role=form.role.data or "",
            description=form.description.data or "",
            system_prompt=form.system_prompt.data or "",
            parameters_json=json.dumps(form.parameters_dict(), ensure_ascii=False),
            deleted=False,
            version=1,
        )
        db.session.add(character)
        db.session.commit()
        sync_character_to_files(character)
        log_admin_action("create_character", character.id, form.name.data)
        flash("角色创建成功", "success")
        return redirect(url_for("admin.characters_list"))

    return render_template("character_form.html", form=form, title="创建角色")


@admin_bp.route("/characters/<int:character_id>/edit", methods=["GET", "POST"])
@admin_required
def character_edit(character_id: int):
    character = CharacterRecord.query.filter_by(
        id=character_id, deleted=False
    ).first_or_404()

    form = CharacterForm()
    if form.validate_on_submit():
        if _name_exists(form.name.data, exclude_id=character.id):
            flash("角色名已存在", "danger")
            return (
                render_template(
                    "character_form.html",
                    form=form,
                    title="编辑角色",
                    character=character,
                ),
                400,
            )

        submitted_version = int(form.version.data or 0)
        if submitted_version != character.version:
            flash("该角色已被他人修改，请刷新后重试", "warning")
            return redirect(url_for("admin.character_edit", character_id=character.id))

        character.display_name = form.name.data
        character.role = form.role.data or ""
        character.description = form.description.data or ""
        character.system_prompt = form.system_prompt.data or ""
        character.parameters_json = json.dumps(
            form.parameters_dict(), ensure_ascii=False
        )
        character.version += 1
        character.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        sync_character_to_files(character)
        log_admin_action("update_character", character.id, form.name.data)
        flash("角色已保存", "success")
        return redirect(url_for("admin.characters_list"))

    form.name.data = character.display_name
    form.role.data = character.role
    form.description.data = character.description
    form.system_prompt.data = character.system_prompt
    form.version.data = character.version
    form.load_parameters(character.parameters_json)
    return render_template(
        "character_form.html",
        form=form,
        title="编辑角色",
        character=character,
        emotion_display=_parse_emotion_display(character),
    )


@admin_bp.route("/characters/<int:character_id>/delete", methods=["POST"])
@admin_required
def character_delete(character_id: int):
    character = CharacterRecord.query.filter_by(
        id=character_id, deleted=False
    ).first_or_404()

    character.deleted = True
    character.version += 1
    character.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    log_admin_action("delete_character", character.id, character.display_name)
    flash("角色已删除（软删除）", "success")
    return redirect(url_for("admin.characters_list"))
