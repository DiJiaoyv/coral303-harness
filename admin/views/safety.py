from datetime import datetime, timedelta, timezone

from flask import abort, render_template, request
from sqlalchemy import func

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from app.models.user import AuditLog
from extensions import db
from safety.loader import reload_word_lists


@admin_bp.route("/safety")
@admin_required
def safety_dashboard():
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_blocked = AuditLog.query.filter(
        AuditLog.created_at >= today_start,
        AuditLog.action_taken == "blocked",
    ).count()

    trend_labels = []
    trend_blocked = []
    trend_total = []
    for i in range(6, -1, -1):
        day = today_start - timedelta(days=i)
        next_day = day + timedelta(days=1)
        trend_labels.append(day.strftime("%m-%d"))
        blocked = AuditLog.query.filter(
            AuditLog.created_at >= day,
            AuditLog.created_at < next_day,
            AuditLog.action_taken == "blocked",
        ).count()
        total = AuditLog.query.filter(
            AuditLog.created_at >= day,
            AuditLog.created_at < next_day,
        ).count()
        trend_blocked.append(blocked)
        trend_total.append(total)

    recent_logs = (
        AuditLog.query.order_by(AuditLog.created_at.desc()).limit(50).all()
    )

    level_stats = dict(
        db.session.query(AuditLog.level, func.count(AuditLog.id))
        .group_by(AuditLog.level)
        .all()
    )

    log_admin_action("view_safety_dashboard")
    return render_template(
        "safety_dashboard.html",
        today_blocked=today_blocked,
        trend_labels=trend_labels,
        trend_blocked=trend_blocked,
        trend_total=trend_total,
        recent_logs=recent_logs,
        level_stats=level_stats,
    )


@admin_bp.route("/safety/reload", methods=["POST"])
@admin_required
def safety_reload_words():
    reload_word_lists()
    log_admin_action("reload_safety_word_lists")
    from flask import flash, redirect, url_for

    flash("敏感词库已重新加载", "success")
    return redirect(url_for("admin.safety_dashboard"))


@admin_bp.route("/safety/<int:log_id>")
@admin_required
def safety_detail(log_id: int):
    record = db.session.get(AuditLog, log_id)
    if not record:
        abort(404)
    reveal = request.args.get("reveal") == "1"
    if reveal:
        log_admin_action(
            "view_audit_original",
            target_id=log_id,
            details=f"stage={record.stage}",
        )
    log_admin_action("view_audit_detail", target_id=log_id)
    return render_template(
        "audit_log_detail.html",
        record=record,
        reveal=reveal,
    )


@admin_bp.route("/safety/<int:log_id>/reveal", methods=["POST"])
@admin_required
def safety_reveal(log_id: int):
    record = db.session.get(AuditLog, log_id)
    if not record:
        abort(404)
    log_admin_action(
        "view_audit_original",
        target_id=log_id,
        details=f"stage={record.stage}",
    )
    from flask import redirect, url_for

    return redirect(url_for("admin.safety_detail", log_id=log_id, reveal=1))
