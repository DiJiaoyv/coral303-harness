#!/usr/bin/env python3
"""初始化数据库 schema（容器启动时调用）。"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    data_dir = os.environ.get("HARNESS_DATA_DIR", "/app/data")
    os.makedirs(data_dir, exist_ok=True)
    db_url = os.environ.get("DATABASE_URL", f"sqlite:///{data_dir}/harness.db")
    db_path = db_url.replace("sqlite:///", "", 1) if db_url.startswith("sqlite:///") else os.path.join(data_dir, "harness.db")

    from app import create_app

    create_app()
    print(f"[init_db] 数据库已初始化: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
