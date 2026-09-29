"""
将现有单用户数据迁移到默认管理员账户。

用法:
    set SECRET_KEY=your-secret-key
    python migrate_existing_data.py

默认账户: admin / Admin123456
迁移后请尽快修改密码。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "Admin123456"


def _copy_tree(src: str, dst: str) -> None:
    if not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


def _copy_file(src: str, dst: str) -> None:
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)


def migrate() -> None:
    if not os.environ.get("SECRET_KEY", "").strip():
        print("错误: 请先设置环境变量 SECRET_KEY（可在 .env 中配置）", file=sys.stderr)
        sys.exit(1)

    from app import create_app
    from app.models.user import CharacterRecord
    from app.services.auth_service import register_user
    from extensions import db

    app = create_app()

    with app.app_context():
        from app.models.user import User

        user = User.query.filter_by(username=DEFAULT_USERNAME).first()
        if user:
            print(f"用户 '{DEFAULT_USERNAME}' 已存在 (id={user.id})，跳过创建。")
        else:
            user = register_user(DEFAULT_USERNAME, DEFAULT_PASSWORD)
            print(f"已创建默认用户 '{DEFAULT_USERNAME}' (id={user.id})")

        user_root = os.path.join(BASE_DIR, "users", str(user.id))
        os.makedirs(user_root, exist_ok=True)

        # 复制角色目录与注册表
        _copy_tree(os.path.join(BASE_DIR, "characters"), os.path.join(user_root, "characters"))
        _copy_file(
            os.path.join(BASE_DIR, "characters.json"),
            os.path.join(user_root, "characters.json"),
        )
        _copy_tree(os.path.join(BASE_DIR, "logs"), os.path.join(user_root, "logs"))

        for fname in ("emotion_state.json", "memory_state.json", "soul_state.json"):
            _copy_file(os.path.join(BASE_DIR, fname), os.path.join(user_root, fname))

        # 同步角色元数据到 DB（带 user_id，便于导出/查询隔离）
        registry_path = os.path.join(user_root, "characters.json")
        if os.path.isfile(registry_path):
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for key, meta in registry.get("characters", {}).items():
                existing = CharacterRecord.query.filter_by(
                    user_id=user.id, character_key=key
                ).first()
                display_name = meta.get("name", key)
                role = meta.get("role", "")
                if existing:
                    existing.display_name = display_name
                    existing.role = role
                else:
                    db.session.add(
                        CharacterRecord(
                            user_id=user.id,
                            character_key=key,
                            display_name=display_name,
                            role=role,
                        )
                    )
            db.session.commit()

        print(f"数据已迁移至: {user_root}")
        print(f"请使用 {DEFAULT_USERNAME} / {DEFAULT_PASSWORD} 登录，并尽快修改密码。")


if __name__ == "__main__":
    migrate()
