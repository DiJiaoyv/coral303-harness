from flask import render_template, request

from admin.blueprint import admin_bp
from admin.decorators import admin_required
from performance.metrics import get_recent_metrics


@admin_bp.route("/performance")
@admin_required
def performance_dashboard():
    minutes = request.args.get("minutes", 60, type=int)
    minutes = max(5, min(minutes, 24 * 60))
    metrics = get_recent_metrics(minutes=minutes)
    return render_template(
        "performance_dashboard.html",
        metrics=metrics,
        minutes=minutes,
    )
