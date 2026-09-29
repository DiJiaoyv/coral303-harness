"""弧光操作日志写入 arc_logs 表。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def log_arc_action(
    character_id: int,
    action: str,
    details: dict | str,
    operator: str = "system",
    *,
    user_id: int | None = None,
) -> None:
    """记录弧光变更（手动或自动）。"""
    if isinstance(details, dict):
        details_str = json.dumps(details, ensure_ascii=False)
    else:
        details_str = str(details)

    fields = {
        "character_id": character_id,
        "user_id": user_id,
        "action": action[:64],
        "details": details_str,
        "operator": operator[:64],
        "created_at": datetime.now(timezone.utc),
    }

    try:
        if _write_via_flask(**fields):
            return

        from database.models import ArcLog
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            session.add(ArcLog(**fields))
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.exception("写入 ArcLog 失败")


def _write_via_flask(**fields) -> bool:
    try:
        from flask import has_app_context

        if not has_app_context():
            return False
        from app.models.user import ArcLogRecord
        from extensions import db

        db.session.add(ArcLogRecord(**fields))
        db.session.commit()
        return True
    except Exception:
        return False
