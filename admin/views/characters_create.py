"""创建角色向导（管理后台）。"""
from __future__ import annotations

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from admin.blueprint import admin_bp
from admin.character_wizard import (
    clear_wizard_data,
    create_character_record,
    get_template_by_id,
    get_wizard_data,
    load_character_templates,
    load_worlds,
    merge_step,
)
from admin.decorators import admin_required
from admin.forms.character_create import (
    PreviewForm,
    Step1Form,
    Step2Form,
    Step3Form,
    Step4Form,
)
from app.models.user import User


def _wizard_ctx(**extra):
    data = get_wizard_data(session)
    ctx = {
        "wizard_data": data,
        "is_admin_view": True,
        "wizard_base": "admin.wizard_step1",
        "step1_endpoint": "admin.wizard_step1",
        "step2_endpoint": "admin.wizard_step2",
        "step3_endpoint": "admin.wizard_step3",
        "step4_endpoint": "admin.wizard_step4",
        "preview_endpoint": "admin.wizard_preview",
        "cancel_endpoint": "admin.characters_list",
    }
    ctx.update(extra)
    return ctx


@admin_bp.route("/characters/create", methods=["GET", "POST"])
@admin_required
def wizard_step1():
    form = Step1Form()
    templates = load_character_templates()

    if request.method == "GET" and request.args.get("reset") == "1":
        clear_wizard_data(session)

    if form.validate_on_submit():
        payload = {
            "name": form.name.data.strip(),
            "description": (form.description.data or "").strip(),
            "avatar_url": (form.avatar_url.data or "").strip(),
            "template_id": (form.template_id.data or "").strip(),
        }
        merge_step(session, "step1", payload)

        # 选择模板时预填后续步骤
        tmpl = get_template_by_id(payload["template_id"])
        if tmpl:
            data = get_wizard_data(session)
            data["step2"] = {
                "system_prompt": tmpl.get("system_prompt", ""),
                "style_tags": tmpl.get("style_tags", ""),
            }
            data["step3"] = {
                "temperature": tmpl.get("temperature", 0.7),
                "max_tokens": tmpl.get("max_tokens", 2048),
                "top_p": tmpl.get("top_p", 0.9),
            }
            data["step4"] = {"world_id": tmpl.get("world_id", ""), "owner_user_id": current_user.id}
            from admin.character_wizard import save_wizard_data

            save_wizard_data(session, data)

        return redirect(url_for("admin.wizard_step2"))

    # 回填
    existing = get_wizard_data(session).get("step1") or {}
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
        **_wizard_ctx(),
    )


@admin_bp.route("/characters/create/2", methods=["GET", "POST"])
@admin_required
def wizard_step2():
    if not get_wizard_data(session).get("step1"):
        flash("请先完成基本信息", "warning")
        return redirect(url_for("admin.wizard_step1"))

    form = Step2Form()
    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("admin.wizard_step1"))
    if form.validate_on_submit():
        merge_step(
            session,
            "step2",
            {
                "system_prompt": form.system_prompt.data.strip(),
                "style_tags": (form.style_tags.data or "").strip(),
            },
        )
        return redirect(url_for("admin.wizard_step3"))

    existing = get_wizard_data(session).get("step2") or {}
    if request.method == "GET" and existing:
        form.system_prompt.data = existing.get("system_prompt", "")
        form.style_tags.data = existing.get("style_tags", "")

    return render_template(
        "character_create_step2.html",
        form=form,
        current_step=2,
        **_wizard_ctx(),
    )


@admin_bp.route("/characters/create/3", methods=["GET", "POST"])
@admin_required
def wizard_step3():
    data = get_wizard_data(session)
    if not data.get("step1") or not data.get("step2"):
        flash("请按顺序完成前面的步骤", "warning")
        return redirect(url_for("admin.wizard_step1"))

    form = Step3Form()
    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("admin.wizard_step2"))
    if form.validate_on_submit():
        merge_step(
            session,
            "step3",
            {
                "temperature": float(form.temperature.data),
                "max_tokens": int(form.max_tokens.data),
                "top_p": float(form.top_p.data),
            },
        )
        return redirect(url_for("admin.wizard_step4"))

    existing = data.get("step3") or {}
    if request.method == "GET":
        form.temperature.data = existing.get("temperature", 0.7)
        form.max_tokens.data = existing.get("max_tokens", 2048)
        form.top_p.data = existing.get("top_p", 0.9)

    return render_template(
        "character_create_step3.html",
        form=form,
        current_step=3,
        **_wizard_ctx(),
    )


@admin_bp.route("/characters/create/4", methods=["GET", "POST"])
@admin_required
def wizard_step4():
    data = get_wizard_data(session)
    if not data.get("step3"):
        flash("请按顺序完成前面的步骤", "warning")
        return redirect(url_for("admin.wizard_step1"))

    worlds = load_worlds()
    users = User.query.filter_by(is_active=True).order_by(User.id).all()
    form = Step4Form()
    form.world_id.choices = [(w["id"], w["name"]) for w in worlds]
    form.owner_user_id.choices = [(u.id, f"{u.username} (#{u.id})") for u in users]

    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("admin.wizard_step3"))
    if form.validate_on_submit():
        owner_id = form.owner_user_id.data or current_user.id
        merge_step(
            session,
            "step4",
            {
                "world_id": form.world_id.data or "",
                "owner_user_id": int(owner_id),
            },
        )
        return redirect(url_for("admin.wizard_preview"))

    existing = data.get("step4") or {}
    if request.method == "GET":
        form.world_id.data = existing.get("world_id", "")
        form.owner_user_id.data = existing.get("owner_user_id", current_user.id)

    return render_template(
        "character_create_step4.html",
        form=form,
        worlds=worlds,
        current_step=4,
        **_wizard_ctx(),
    )


@admin_bp.route("/characters/create/preview", methods=["GET", "POST"])
@admin_required
def wizard_preview():
    data = get_wizard_data(session)
    if not all(k in data for k in ("step1", "step2", "step3", "step4")):
        flash("请完成全部步骤后再预览", "warning")
        return redirect(url_for("admin.wizard_step1"))

    form = PreviewForm()
    if request.method == "POST" and form.back_btn.data:
        return redirect(url_for("admin.wizard_step4"))
    if form.validate_on_submit():
        owner_id = int(data["step4"].get("owner_user_id") or current_user.id)
        try:
            character = create_character_record(
                owner_user_id=owner_id,
                wizard_data=data,
                operator=f"admin:{current_user.username}",
                is_admin=True,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin.wizard_step1"))

        clear_wizard_data(session)
        flash(f"角色「{character.display_name}」创建成功", "success")
        return redirect(url_for("admin.characters_list"))

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
        **_wizard_ctx(),
    )
