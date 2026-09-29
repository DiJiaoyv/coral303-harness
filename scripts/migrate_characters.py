"""
将 characters/ 目录下的 JSON 角色文件迁移到数据库 Character 表。

用法:
    python scripts/migrate_characters.py [--user-id 1]

特性:
    - 迁移前自动备份 characters/ 到 characters_backup_YYYYMMDD/
    - 使用事务：全部成功才提交，出错回滚
    - 不依赖 Flask 应用上下文（直接使用 SQLAlchemy）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTERS_DIR = os.path.join(BASE_DIR, "characters")
LOG_PATH = os.path.join(BASE_DIR, "migrate_characters.log")

SKIP_FILENAMES = frozenset({
    "soul_state.json",
    "memory_state.json",
    "emotion_state.json",
})

DANGEROUS_NAME_PATTERN = re.compile(r"(\.\.|[\\/<>|:\"*?])")
NAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff]{1,64}$", re.UNICODE)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


def _setup_path() -> None:
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)


def _backup_characters_dir() -> str | None:
    if not os.path.isdir(CHARACTERS_DIR):
        logger.warning("characters/ 目录不存在，跳过备份")
        return None
    stamp = datetime.now().strftime("%Y%m%d")
    backup_dir = os.path.join(BASE_DIR, f"characters_backup_{stamp}")
    if os.path.exists(backup_dir):
        suffix = datetime.now().strftime("%H%M%S")
        backup_dir = os.path.join(BASE_DIR, f"characters_backup_{stamp}_{suffix}")
    shutil.copytree(CHARACTERS_DIR, backup_dir)
    print(f"已备份 characters/ → {backup_dir}")
    logger.info("Backed up characters to %s", backup_dir)
    return backup_dir


def _iter_character_json_files() -> list[str]:
    if not os.path.isdir(CHARACTERS_DIR):
        return []
    files: list[str] = []
    for root, _dirs, filenames in os.walk(CHARACTERS_DIR):
        for filename in filenames:
            if not filename.lower().endswith(".json"):
                continue
            if filename in SKIP_FILENAMES:
                continue
            files.append(os.path.join(root, filename))
    return sorted(files)


def _validate_name(name: str, filepath: str) -> str | None:
    if not name or len(name) > 64:
        logger.error("角色名无效（长度）: %s (%s)", name, filepath)
        return None
    if DANGEROUS_NAME_PATTERN.search(name):
        logger.error("角色名含危险字符，拒绝导入: %s (%s)", name, filepath)
        return None
    if not NAME_PATTERN.match(name):
        logger.error("角色名格式不合法: %s (%s)", name, filepath)
        return None
    return name


def _slug_key(name: str) -> str:
    key = re.sub(r"[^\w]", "_", name.strip(), flags=re.UNICODE)
    key = re.sub(r"_+", "_", key).strip("_")
    return (key[:32] or "character")


def _parse_character_file(filepath: str) -> dict | None:
    name = os.path.splitext(os.path.basename(filepath))[0]
    name = _validate_name(name, filepath)
    if not name:
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("非法 JSON，跳过: %s (%s)", filepath, exc)
        return None
    except OSError as exc:
        logger.error("无法读取文件，跳过: %s (%s)", filepath, exc)
        return None

    if not isinstance(data, dict):
        logger.error("JSON 根节点须为对象，跳过: %s", filepath)
        return None

    json_name = data.get("name")
    if json_name:
        validated = _validate_name(str(json_name), filepath)
        if validated:
            name = validated

    temperature = data.get("temperature", 0.7)
    max_tokens = data.get("max_tokens", 2048)
    try:
        temperature = float(temperature)
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        logger.error("参数格式无效，跳过: %s", filepath)
        return None

    return {
        "display_name": name,
        "character_key": _slug_key(name),
        "role": str(data.get("role", "") or "")[:128],
        "description": str(data.get("description", "") or "")[:1024],
        "system_prompt": str(data.get("system_prompt", "") or "")[:8192],
        "parameters_json": json.dumps(
            {"temperature": temperature, "max_tokens": max_tokens},
            ensure_ascii=False,
        ),
    }


def migrate_characters(user_id: int = 1) -> tuple[int, int]:
    _setup_path()

    from database.migrate_admin_schema import migrate_admin_schema
    from database.models import Character, User
    from database.session import SessionLocal, get_database_url

    db_url = get_database_url()
    if db_url.startswith("sqlite:///"):
        migrate_admin_schema(db_url.replace("sqlite:///", "", 1))

    _backup_characters_dir()
    json_files = _iter_character_json_files()
    if not json_files:
        print("未在 characters/ 下找到可导入的 JSON 角色文件。")
        return 0, 0

    session = SessionLocal()
    imported = 0
    skipped = 0

    try:
        user = session.get(User, user_id)
        if not user:
            raise RuntimeError(f"用户 id={user_id} 不存在，请先创建用户。")

        pending: list[Character] = []
        seen_names: set[str] = set()

        for filepath in json_files:
            parsed = _parse_character_file(filepath)
            if not parsed:
                skipped += 1
                continue

            display_name = parsed["display_name"]
            if display_name in seen_names:
                skipped += 1
                logger.info("本次运行内重复，跳过: %s", display_name)
                continue
            seen_names.add(display_name)

            existing = (
                session.query(Character)
                .filter(
                    Character.user_id == user_id,
                    Character.display_name == display_name,
                    Character.deleted.is_(False),
                )
                .first()
            )
            if existing:
                skipped += 1
                logger.info("数据库已存在同名角色，跳过: %s", display_name)
                continue

            key_dup = (
                session.query(Character)
                .filter(
                    Character.user_id == user_id,
                    Character.character_key == parsed["character_key"],
                    Character.deleted.is_(False),
                )
                .first()
            )
            if key_dup:
                skipped += 1
                logger.info("数据库已存在相同 character_key，跳过: %s", parsed["character_key"])
                continue

            pending.append(
                Character(
                    user_id=user_id,
                    character_key=parsed["character_key"],
                    display_name=parsed["display_name"],
                    role=parsed["role"],
                    description=parsed["description"],
                    system_prompt=parsed["system_prompt"],
                    parameters_json=parsed["parameters_json"],
                    deleted=False,
                    version=1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            imported += 1

        for row in pending:
            session.add(row)
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.exception("迁移失败，已回滚: %s", exc)
        raise
    finally:
        session.close()

    return imported, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 characters/ JSON 到数据库")
    parser.add_argument("--user-id", type=int, default=1, help="角色归属用户 ID")
    args = parser.parse_args()

    try:
        imported, skipped = migrate_characters(user_id=args.user_id)
    except Exception as exc:
        print(f"迁移失败: {exc}", file=sys.stderr)
        print(f"详情请查看日志: {LOG_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"成功导入 {imported} 个角色，跳过 {skipped} 个重复/无效角色")
    print(f"日志文件: {LOG_PATH}")


if __name__ == "__main__":
    main()
