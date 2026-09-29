"""管理后台操作日志。"""
import os
from datetime import datetime, timezone

from flask_login import current_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(BASE_DIR, "admin_actions.log")


def log_admin_action(action: str, target_id: int | None = None, details: str = "") -> None:
    username = current_user.username if current_user.is_authenticated else "anonymous"
    line = (
        f"{datetime.now(timezone.utc).isoformat()} | "
        f"{username} | {action} | target={target_id} | {details}\n"
    )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
