"""用户前台：创建角色向导（归属当前用户）。"""
from __future__ import annotations

import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from admin.character_wizard import (
    create_character_record,
    get_template_by_id,
    load_character_templates,
    load_worlds,
)
from admin.forms.character_create import (
    PreviewForm,
    Step1Form,
    Step2Form,
    Step3Form,
    Step4Form,
)

_admin_templates = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "admin",
    "templates",
)
character_wizard_bp = Blueprint(
    "character_wizard",
    __name__,
    template_folder=_admin_templates,
)

SESSION_NS = "user_character_wizard"


def _get_data():
    return dict(session.get(SESSION_NS) or {})


def _save_data(data: dict) -> None:
    session[SESSION_NS] = data
    session.modified = True


def _merge(step_key: str, payload: dict) -> dict:
    data = _get_data()
    data[step_key] = payload
    _save_data(data)
    return data


def _clear() -> None:
    session.pop(SESSION_NS, None)
    session.modified = True


def _ctx(**extra):
    ctx = {
        "wizard_data": _get_data(),
        "is_admin_view": False,
        "step1_endpoint": "character_wizard.user_step1",
        "step2_endpoint": "character_wizard.user_step2",
        "step3_endpoint": "character_wizard.user_step3",
        "step4_endpoint": "character_wizard.user_step4",
        "preview_endpoint": "character_wizard.user_preview",
        "cancel_endpoint": "data.index",
    }
    ctx.update(extra)
    return ctx


@character_wizard_bp.route("/characters/create", methods=["GET", "POST"])
@login_required
def user_step1():
    form = Step1Form()
    templates = load_character_templates()
    if request.method == "GET" and request.args.get("reset") == "1":
        _clear()

    if form.validate_on_submit():
        payload = {
            "name": form.name.data.strip(),
            "description": (form.description.data or "").strip(),
            "avatar_url": (form.avatar_url.data or "").strip(),
            "template_id": (form.template_id.data or "").strip(),
        }
        _merge("step1", payload)
        tmpl = get_template_by_id(payload["template_id"])
        if tmpl:
            data = _get_data()
            data["step2"] = {
                "system_prompt": tmpl.get("system_prompt", ""),
                "style_tags": tmpl.get("style_tags", ""),
            }
            data["step3"] = {
                "temperature": tmpl.get("temperature", 0.7),
                "max_tokens": tmpl.get("max_tokens", 2048),
                "top_p": tmpl.get("top_p", 0.9),
            }
            data["step4"] = {
                "world_id": tmpl.get("world_id", ""),
                "owner_user_id": current_user.id,
            }
            _save_data(data)
        return redirect(url_for("character_wizard.user_step2"))

    existing = _get_data().get("step1") or {}
    if request.method == "GET" and existing:
        form.name.data = existing.get("name", "")
        form.description.data = existing.get("description", "")
        form.avatar_url.data = existing.get("avatar_url", "")
        form.template_id.data = existing.get("template_id", "")

    return render_template(
        "character_create_step1.html",
        form=form,
        templates=templates,
        current_step=1,
        **_ctx(),
    )


@character_wizard_bp.route("/characters/create/2", methods=["GET", "POST"])
@login_required
def user_step2():
    if not _get_data().get("step1"):
        flash("请先完成基本信息", "warning")
        return redirect(url_for("character_wizard.user_step1"))

    form = Step2Form()
    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("character_wizard.user_step1"))
    if form.validate_on_submit():
        _merge(
            "step2",
            {
                "system_prompt": form.system_prompt.data.strip(),
                "style_tags": (form.style_tags.data or "").strip(),
            },
        )
        return redirect(url_for("character_wizard.user_step3"))

    existing = _get_data().get("step2") or {}
    if request.method == "GET" and existing:
        form.system_prompt.data = existing.get("system_prompt", "")
        form.style_tags.data = existing.get("style_tags", "")

    return render_template(
        "character_create_step2.html",
        form=form,
        current_step=2,
        **_ctx(),
    )


@character_wizard_bp.route("/characters/create/3", methods=["GET", "POST"])
@login_required
def user_step3():
    data = _get_data()
    if not data.get("step2"):
        flash("请按顺序完成前面的步骤", "warning")
        return redirect(url_for("character_wizard.user_step1"))

    form = Step3Form()
    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("character_wizard.user_step2"))
    if form.validate_on_submit():
        _merge(
            "step3",
            {
                "temperature": float(form.temperature.data),
                "max_tokens": int(form.max_tokens.data),
                "top_p": float(form.top_p.data),
            },
        )
        return redirect(url_for("character_wizard.user_step4"))

    existing = data.get("step3") or {}
    if request.method == "GET":
        form.temperature.data = existing.get("temperature", 0.7)
        form.max_tokens.data = existing.get("max_tokens", 2048)
        form.top_p.data = existing.get("top_p", 0.9)

    return render_template(
        "character_create_step3.html",
        form=form,
        current_step=3,
        **_ctx(),
    )


@character_wizard_bp.route("/characters/create/4", methods=["GET", "POST"])
@login_required
def user_step4():
    data = _get_data()
    if not data.get("step3"):
        flash("请按顺序完成前面的步骤", "warning")
        return redirect(url_for("character_wizard.user_step1"))

    worlds = load_worlds()
    form = Step4Form()
    form.world_id.choices = [(w["id"], w["name"]) for w in worlds]
    form.owner_user_id.choices = [(current_user.id, current_user.username)]

    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("character_wizard.user_step3"))
    if form.validate_on_submit():
        _merge(
            "step4",
            {
                "world_id": form.world_id.data or "",
                "owner_user_id": current_user.id,
            },
        )
        return redirect(url_for("character_wizard.user_preview"))

    existing = data.get("step4") or {}
    if request.method == "GET":
        form.world_id.data = existing.get("world_id", "")
        form.owner_user_id.data = current_user.id

    return render_template(
        "character_create_step4.html",
        form=form,
        worlds=worlds,
        current_step=4,
        **_ctx(),
    )


@character_wizard_bp.route("/characters/create/preview", methods=["GET", "POST"])
@login_required
def user_preview():
    data = _get_data()
    if not all(k in data for k in ("step1", "step2", "step3", "step4")):
        flash("请完成全部步骤后再预览", "warning")
        return redirect(url_for("character_wizard.user_step1"))

    form = PreviewForm()
    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("character_wizard.user_step4"))
    if form.validate_on_submit():
        try:
            character = create_character_record(
                owner_user_id=current_user.id,
                wizard_data=data,
                operator=f"user:{current_user.username}",
                is_admin=False,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("character_wizard.user_step1"))

        _clear()
        flash(f"角色「{character.display_name}」创建成功", "success")
        return redirect(url_for("data.character_detail", character_id=character.id))

    world_name = "无"
    for w in load_worlds():
        if w["id"] == data["step4"].get("world_id"):
            world_name = w["name"]
            break

    return render_template(
        "character_create_preview.html",
        form=form,
        current_step=5,
        world_name=world_name,
        **_ctx(),
    )
