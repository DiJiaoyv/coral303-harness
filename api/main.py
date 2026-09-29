"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routes import arc, auth, characters, chat, memories
from database import init_sqlite_schema
from database.models import Base
from database.session import engine, get_database_url


def _init_database() -> None:
    Base.metadata.create_all(bind=engine)
    db_url = get_database_url()
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        if ":memory:" not in db_path:
            init_sqlite_schema(db_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_database()
    yield


app = FastAPI(
    title="Harness REST API",
    description="AI 角色扮演引擎 REST API（供 React 等前端调用）",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(arc.router, prefix="/api")
app.include_router(memories.router, prefix="/api")


@app.get("/api/health")
def health():
    import os
    return {"status": "ok", "version": os.environ.get("HARNESS_VERSION", "1.0.0")}
