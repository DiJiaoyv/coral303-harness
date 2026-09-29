# config.py - Flask 应用配置（SECRET_KEY 必须从环境变量读取）
import os
import sys
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("HARNESS_DATA_DIR", BASE_DIR)
DATABASE_PATH = os.environ.get(
    "DATABASE_PATH", os.path.join(DATA_DIR, "harness.db")
)


def _require_secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if not key or not key.strip():
        print(
            "错误: 未设置环境变量 SECRET_KEY。\n"
            "请创建 .env 文件并设置 SECRET_KEY=你的随机密钥",
            file=sys.stderr,
        )
        sys.exit(1)
    return key.strip()


class Config:
    SECRET_KEY = _require_secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATABASE_PATH}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    REMEMBER_COOKIE_DURATION = timedelta(hours=24)

    WTF_CSRF_ENABLED = True
    HARNESS_CONFIG_JSON = os.path.join(BASE_DIR, "config.json")
