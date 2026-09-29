from datetime import datetime, timedelta, timezone

from flask import render_template, request
from sqlalchemy import func

from admin.blueprint import admin_bp
from admin.decorators import admin_required
from app.models.user import ScoreLog
from extensions import db
from scoring.config import LOW_SCORE_THRESHOLD


@admin_bp.route("/scores")
@admin_required
def scores_dashboard():
    sort = request.args.get("sort", "created_at")
    order = request.args.get("order", "desc")
    method_filter = request.args.get("method", "")

    allowed_sort = {
        "created_at": ScoreLog.created_at,
        "total_score": ScoreLog.total_score,
        "relevance_score": ScoreLog.relevance_score,
    }
    sort_col = allowed_sort.get(sort, ScoreLog.created_at)
    query = ScoreLog.query
    if method_filter in ("rule", "model"):
        query = query.filter(ScoreLog.scoring_method == method_filter)

    if order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    recent_scores = query.limit(100).all()

    now = datetime.now(timezone.utc)
    trend_labels = []
    trend_values = []
    for i in range(6, -1, -1):
        day_start = (now - timedelta(days=i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)
        trend_labels.append(day_start.strftime("%m-%d"))
        avg = (
            db.session.query(func.avg(ScoreLog.total_score))
            .filter(
                ScoreLog.created_at >= day_start,
                ScoreLog.created_at < day_end,
            )
            .scalar()
        )
        trend_values.append(round(float(avg or 0), 2))

    dim_avgs = db.session.query(
        func.avg(ScoreLog.relevance_score),
        func.avg(ScoreLog.consistency_score),
        func.avg(ScoreLog.fluency_score),
        func.avg(ScoreLog.safety_score),
    ).one()
    radar_values = [
        round(float(dim_avgs[0] or 0), 2),
        round(float(dim_avgs[1] or 0), 2),
        round(float(dim_avgs[2] or 0), 2),
        round(float(dim_avgs[3] or 0), 2),
    ]

    return render_template(
        "scores_dashboard.html",
        recent_scores=recent_scores,
        trend_labels=trend_labels,
        trend_values=trend_values,
        radar_values=radar_values,
        low_threshold=LOW_SCORE_THRESHOLD,
        sort=sort,
        order=order,
        method_filter=method_filter,
    )
