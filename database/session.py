"""SQLAlchemy 引擎与会话工厂。"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "harness.db")


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")


def create_db_engine(database_url: str | None = None):
    url = database_url or get_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
