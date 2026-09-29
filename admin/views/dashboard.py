from datetime import datetime, timedelta, timezone

from flask import render_template

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from app.models.user import CharacterRecord, Conversation, User


@admin_bp.route("/")
@admin_required
def dashboard():
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    total_characters = CharacterRecord.query.filter_by(deleted=False).count()
    total_users = User.query.count()
    today_conversations = Conversation.query.filter(
        Conversation.created_at >= today_start
    ).count()

    chart_labels = []
    chart_values = []
    for i in range(6, -1, -1):
        day = today_start - timedelta(days=i)
        next_day = day + timedelta(days=1)
        chart_labels.append(day.strftime("%m-%d"))
        count = Conversation.query.filter(
            Conversation.created_at >= day,
            Conversation.created_at < next_day,
        ).count()
        chart_values.append(count)

    log_admin_action("view_dashboard")
    return render_template(
        "dashboard.html",
        total_characters=total_characters,
        total_users=total_users,
        today_conversations=today_conversations,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )
