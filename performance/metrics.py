"""性能指标聚合（供管理后台查询）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def get_recent_metrics(minutes: int = 60) -> dict:
    """聚合最近 N 分钟的性能指标。"""
    from performance.gpu_check import detect_gpu
    from performance.queue_manager import get_request_queue

    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = _fetch_performance_logs(since)

    durations = [r.duration_ms for r in rows if r.duration_ms is not None]
    gpu_utils = [r.gpu_util for r in rows if r.gpu_util is not None]
    queue_lens = [r.queue_length for r in rows if r.queue_length is not None]

    avg_duration = sum(durations) / len(durations) if durations else 0.0
    p95_duration = _percentile(durations, 95) if durations else 0.0
    avg_gpu = sum(gpu_utils) / len(gpu_utils) if gpu_utils else 0.0
    avg_queue = sum(queue_lens) / len(queue_lens) if queue_lens else 0.0
    success_rate = (
        sum(1 for r in rows if r.success) / len(rows) * 100 if rows else 100.0
    )

    recent_100 = rows[:100]
    recent_20 = rows[:20]

    chart_labels = [
        r.created_at.strftime("%H:%M:%S") if r.created_at else ""
        for r in reversed(recent_100)
    ]
    chart_durations = [round(r.duration_ms, 1) for r in reversed(recent_100)]
    chart_queue = [r.queue_length for r in reversed(recent_100)]

    gpu_info = detect_gpu(force_refresh=True)
    current_gpu = (
        float(gpu_info.get("utilization_pct") or 0.0)
        if gpu_info.get("available")
        else 0.0
    )

    return {
        "minutes": minutes,
        "count": len(rows),
        "avg_duration_ms": round(avg_duration, 1),
        "p95_duration_ms": round(p95_duration, 1),
        "avg_gpu_util": round(avg_gpu, 1),
        "current_gpu_util": round(current_gpu, 1),
        "avg_queue_length": round(avg_queue, 2),
        "current_queue_length": get_request_queue().queue_length,
        "success_rate": round(success_rate, 1),
        "gpu_info": gpu_info,
        "chart_labels": chart_labels,
        "chart_durations": chart_durations,
        "chart_queue": chart_queue,
        "recent_logs": recent_20,
    }


def _fetch_performance_logs(since):
    try:
        from flask import has_app_context

        if has_app_context():
            from app.models.user import PerformanceLog

            return (
                PerformanceLog.query.filter(PerformanceLog.created_at >= since)
                .order_by(PerformanceLog.created_at.desc())
                .all()
            )
    except Exception:
        pass

    from database.models import PerformanceLog
    from database.session import SessionLocal

    session = SessionLocal()
    try:
        return (
            session.query(PerformanceLog)
            .filter(PerformanceLog.created_at >= since)
            .order_by(PerformanceLog.created_at.desc())
            .all()
        )
    finally:
        session.close()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return float(ordered[f])
    return float(ordered[f] + (ordered[c] - ordered[f]) * (k - f))
