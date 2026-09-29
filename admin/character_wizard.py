"""创建角色向导：模板加载、世界观、落库与文件同步。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from admin.character_sync import slug_character_key, sync_character_to_files

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "characters", "templates")
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")
USER_ACTIONS_LOG = os.path.join(BASE_DIR, "user_actions.log")

SESSION_KEY = "character_wizard"


def load_character_templates() -> list[dict]:
    """从 characters/templates/*.json 读取预置模板（仅数据，无可执行代码）。"""
    items: list[dict] = []
    if not os.path.isdir(TEMPLATES_DIR):
        return items
    for name in sorted(os.listdir(TEMPLATES_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(TEMPLATES_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            tid = data.get("id") or name[:-5]
            items.append(
                {
                    "id": tid,
                    "name": data.get("name", tid),
                    "description": data.get("description", ""),
                    "system_prompt": data.get("system_prompt", ""),
                    "style_tags": data.get("style_tags", ""),
                    "role": data.get("role", ""),
                    "temperature": float(data.get("temperature", 0.7)),
                    "max_tokens": int(data.get("max_tokens", 2048)),
                    "top_p": float(data.get("top_p", 0.9)),
                    "world_id": data.get("world_id", ""),
                    "avatar_url": data.get("avatar_url", ""),
                }
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return items


def get_template_by_id(template_id: str | None) -> dict | None:
    if not template_id:
        return None
    for item in load_character_templates():
        if item["id"] == template_id:
            return item
    return None


def load_worlds() -> list[dict]:
    """从 worlds/*.json 读取世界观列表。"""
    items: list[dict] = [{"id": "", "name": "无", "summary": ""}]
    if not os.path.isdir(WORLDS_DIR):
        return items
    for name in sorted(os.listdir(WORLDS_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(WORLDS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            wid = data.get("id") or name[:-5]
            items.append(
                {
                    "id": wid,
                    "name": data.get("name", wid),
                    "summary": data.get("summary", "")[:120],
                }
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return items


def get_wizard_data(session) -> dict:
    return dict(session.get(SESSION_KEY) or {})


def save_wizard_data(session, data: dict) -> None:
    session[SESSION_KEY] = data
    session.modified = True


def clear_wizard_data(session) -> None:
    session.pop(SESSION_KEY, None)
    session.modified = True


def merge_step(session, step_key: str, payload: dict) -> dict:
    data = get_wizard_data(session)
    data[step_key] = payload
    save_wizard_data(session, data)
    return data


def name_exists_for_user(user_id: int, name: str) -> bool:
    from app.models.user import CharacterRecord

    return (
        CharacterRecord.query.filter_by(
            user_id=user_id,
            display_name=name,
            deleted=False,
        ).first()
        is not None
    )


def create_character_record(
    *,
    owner_user_id: int,
    wizard_data: dict,
    operator: str,
    is_admin: bool = False,
):
    """根据向导数据创建 CharacterRecord 并同步文件。"""
    from app.models.user import CharacterRecord
    from extensions import db

    step1 = wizard_data.get("step1") or {}
    step2 = wizard_data.get("step2") or {}
    step3 = wizard_data.get("step3") or {}
    step4 = wizard_data.get("step4") or {}

    name = (step1.get("name") or "").strip()
    if not name:
        raise ValueError("角色名称不能为空")
    if name_exists_for_user(owner_user_id, name):
        raise ValueError("角色名已存在")

    character_key = slug_character_key(name)
    dup = CharacterRecord.query.filter_by(
        user_id=owner_user_id,
        character_key=character_key,
        deleted=False,
    ).first()
    if dup:
        raise ValueError("角色标识已存在，请更换名称")

    params = {
        "temperature": float(step3.get("temperature", 0.7)),
        "max_tokens": int(step3.get("max_tokens", 2048)),
        "top_p": float(step3.get("top_p", 0.9)),
        "avatar_url": (step1.get("avatar_url") or "").strip(),
        "style_tags": (step2.get("style_tags") or "").strip(),
        "world_id": (step4.get("world_id") or "").strip(),
        "template_id": (step1.get("template_id") or "").strip(),
    }

    character = CharacterRecord(
        user_id=owner_user_id,
        character_key=character_key,
        display_name=name,
        role=(step2.get("style_tags") or step1.get("description") or "")[:128],
        description=(step1.get("description") or "")[:500],
        system_prompt=step2.get("system_prompt") or "",
        parameters_json=json.dumps(params, ensure_ascii=False),
        deleted=False,
        version=1,
    )
    db.session.add(character)
    db.session.commit()
    sync_character_to_files(character)

    if is_admin:
        try:
            from admin.audit_log import log_admin_action

            log_admin_action("create_character_wizard", character.id, name)
        except Exception:
            _log_user_action(operator, "create_character_wizard", character.id, name)
    else:
        _log_user_action(operator, "create_character", character.id, name)

    return character


def _log_user_action(username: str, action: str, target_id: int, details: str) -> None:
    line = (
        f"{datetime.now(timezone.utc).isoformat()} | "
        f"{username} | {action} | target={target_id} | {details}\n"
    )
    with open(USER_ACTIONS_LOG, "a", encoding="utf-8") as f:
        f.write(line)
