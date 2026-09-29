"""为管理后台升级现有 SQLite 表结构（添加 is_admin、角色扩展字段等）。"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "harness.db")

USER_COLUMNS = [
    ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("is_active", "INTEGER NOT NULL DEFAULT 1"),
]

CHARACTER_COLUMNS = [
    ("description", "TEXT DEFAULT ''"),
    ("system_prompt", "TEXT DEFAULT ''"),
    ("parameters_json", "TEXT DEFAULT '{}'"),
    ("emotion_state", "TEXT DEFAULT '{}'"),
    ("deleted", "INTEGER NOT NULL DEFAULT 0"),
    ("version", "INTEGER NOT NULL DEFAULT 1"),
    ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
]

ARC_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS arcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL UNIQUE,
    current_stage TEXT NOT NULL DEFAULT 'stranger',
    stages TEXT NOT NULL DEFAULT '["stranger","acquaintance","trust","intimate"]',
    goals TEXT NOT NULL DEFAULT '[]',
    progress REAL NOT NULL DEFAULT 0.0,
    auto_advance INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_arcs_character_id ON arcs(character_id);
CREATE TABLE IF NOT EXISTS arc_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_arc_logs_character_id ON arc_logs(character_id);
CREATE INDEX IF NOT EXISTS idx_arc_logs_created_at ON arc_logs(created_at);
"""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def migrate_admin_schema(db_path: str | None = None) -> None:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with sqlite3.connect(path) as conn:
        for col, typedef in USER_COLUMNS:
            if col not in _existing_columns(conn, "users"):
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
        for col, typedef in CHARACTER_COLUMNS:
            if col not in _existing_columns(conn, "characters"):
                conn.execute(f"ALTER TABLE characters ADD COLUMN {col} {typedef}")
        if not _table_exists(conn, "arcs"):
            conn.executescript(ARC_TABLES_SQL)
        conn.commit()


if __name__ == "__main__":
    migrate_admin_schema()
    print("管理后台 schema 迁移完成。")
