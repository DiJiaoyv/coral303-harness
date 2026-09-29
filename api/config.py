"""FastAPI 专用配置（SECRET_KEY 必须从环境变量读取）。"""
import os
import sys

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "harness.db")


class ApiSettings(BaseSettings):
    SECRET_KEY: str
    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_PATH}"
    JWT_EXPIRE_MINUTES: int = 30
    CORS_ORIGINS: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("SECRET_KEY 未设置")
        return v.strip()

    def cors_origins_list(self) -> list[str]:
        raw = self.CORS_ORIGINS.strip()
        if not raw:
            return ["http://localhost:3000"]
        if raw.startswith("["):
            import json
            return json.loads(raw)
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


def get_settings() -> ApiSettings:
    try:
        return ApiSettings()
    except Exception:
        print(
            "错误: 未设置环境变量 SECRET_KEY。\n"
            "请创建 .env 文件并设置 SECRET_KEY=你的随机密钥",
            file=sys.stderr,
        )
        sys.exit(1)


settings = get_settings()
