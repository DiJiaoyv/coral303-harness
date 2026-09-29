#!/usr/bin/env python3
"""从环境变量创建管理员账户（用于容器首次启动）。"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not username or not password:
        print("[init_admin] 未设置 ADMIN_USERNAME/ADMIN_PASSWORD，跳过")
        return 0

    from app import create_app
    from app.cli import create_admin_account

    app = create_app()
    with app.app_context():
        try:
            create_admin_account(username=username, password=password)
        except SystemExit as exc:
            print(f"[init_admin] 失败: {exc}", file=sys.stderr)
            return 1
    print(f"[init_admin] 管理员 '{username}' 已就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
