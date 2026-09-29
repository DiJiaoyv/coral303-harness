"""审核记录写入 AuditLog 表。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from safety.config import get_config

logger = logging.getLogger(__name__)


def log_audit_record(
    *,
    stage: str,
    level: str,
    matched_word: str | None,
    original_content: str,
    action_taken: str,
    user_id: int | None = None,
    character_id: int | None = None,
) -> None:
    """写入审核日志（仅在有命中或拦截时调用）。"""
    try:
        if _write_via_flask(
            stage=stage,
            level=level,
            matched_word=matched_word,
            original_content=original_content,
            action_taken=action_taken,
            user_id=user_id,
            character_id=character_id,
        ):
            return

        from database.models import AuditLog
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            session.add(
                AuditLog(
                    user_id=user_id,
                    character_id=character_id,
                    stage=stage,
                    level=level,
                    matched_word=matched_word or "***",
                    original_content=original_content,
                    action_taken=action_taken,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            _cleanup_old_logs_sqlalchemy(session)
        finally:
            session.close()
    except Exception:
        logger.exception("写入 AuditLog 失败")


def _write_via_flask(**fields) -> bool:
    try:
        from flask import has_app_context

        if not has_app_context():
            return False
        from app.models.user import AuditLog as FlaskAuditLog
        from extensions import db

        db.session.add(FlaskAuditLog(**fields))
        db.session.commit()
        _cleanup_old_logs_flask()
        return True
    except Exception:
        return False


def _cleanup_old_logs_flask() -> None:
    cfg = get_config()
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.LOG_RETENTION_DAYS)
    try:
        from app.models.user import AuditLog as FlaskAuditLog
        from extensions import db

        FlaskAuditLog.query.filter(FlaskAuditLog.created_at < cutoff).delete()
        db.session.commit()
    except Exception:
        from extensions import db

        db.session.rollback()
        logger.warning("清理过期审核日志失败", exc_info=True)


def _cleanup_old_logs_sqlalchemy(session) -> None:
    cfg = get_config()
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.LOG_RETENTION_DAYS)
    try:
        from database.models import AuditLog

        session.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("清理过期审核日志失败", exc_info=True)
