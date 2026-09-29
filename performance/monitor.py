"""性能数据写入 PerformanceLog 表。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def record_performance(
    user_id: int | None,
    character_id: int | None,
    duration_ms: float,
    gpu_util: float,
    queue_length: int,
    success: bool,
) -> None:
    """记录性能元数据（不含对话内容）。"""
    try:
        from database.models import PerformanceLog
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            session.add(
                PerformanceLog(
                    user_id=user_id,
                    character_id=character_id,
                    duration_ms=float(duration_ms),
                    gpu_util=float(gpu_util),
                    queue_length=int(queue_length),
                    success=bool(success),
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        logger.warning("写入 PerformanceLog 失败: %s", exc)
