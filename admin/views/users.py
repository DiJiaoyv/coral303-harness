from flask import flash, redirect, render_template, url_for

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from app.models.user import User
from extensions import db


@admin_bp.route("/users")
@admin_required
def users_list():
    users = User.query.order_by(User.created_at.desc()).all()
    log_admin_action("view_users")
    return render_template("users_list.html", users=users)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def user_toggle_active(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("用户不存在", "danger")
        return redirect(url_for("admin.users_list"))

    if user.is_admin and user.is_active:
        flash("不能禁用管理员账户", "warning")
        return redirect(url_for("admin.users_list"))

    user.is_active = not user.is_active
    db.session.commit()
    action = "enable_user" if user.is_active else "disable_user"
    log_admin_action(action, user.id, user.username)
    flash(f"用户 {user.username} 已{'启用' if user.is_active else '禁用'}", "success")
    return redirect(url_for("admin.users_list"))
