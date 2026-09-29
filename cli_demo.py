#!/usr/bin/env python3
"""
Harness 引擎 Input->Output 全流程演示（CLI）。

真实读写 users/{user_id}/characters/{character_key}/memory_state.json，
不调用 Ollama，用回声模拟模型回复。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# 确保从项目根目录运行，并满足 create_app 所需环境变量
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_SCRIPT_DIR)
os.environ.setdefault("SECRET_KEY", "cli-demo-secret-key-for-local-test")
# 避免 .env 中 Docker 路径 (/app/data/...) 导致本地无法打开数据库
_local_db = os.path.join(_SCRIPT_DIR, "harness.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_local_db.replace(chr(92), '/')}"

# Windows 终端尽量使用 UTF-8，避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 固定测试身份（与 users/1/characters/1/memory_state.json 对应）
USER_ID = 1
CHARACTER_ID = 1
CHARACTER_KEY = "1"

DEFAULT_MEMORY_STATE = {
    "max_messages": 20,
    "short_term": [],
    "long_term": [],
    "use_vector": True,
}


def _ensure_db_character() -> None:
    """确保数据库中存在 user_id=1、character_id=1、character_key='1' 的记录。"""
    from app import create_app
    from app.models.user import CharacterRecord, User
    from extensions import db

    app = create_app()
    with app.app_context():
        user = db.session.get(User, USER_ID)
        if user is None:
            user = User(
                id=USER_ID,
                username="cli_demo_user",
                password_hash="cli-demo-no-login",
                is_admin=False,
                is_active=True,
            )
            db.session.add(user)
            db.session.flush()

        char = db.session.get(CharacterRecord, CHARACTER_ID)
        if char is None:
            char = CharacterRecord(
                id=CHARACTER_ID,
                user_id=USER_ID,
                character_key=CHARACTER_KEY,
                display_name="CLI Demo",
                role="演示角色",
            )
            db.session.add(char)
        else:
            char.user_id = USER_ID
            char.character_key = CHARACTER_KEY
            char.deleted = False

        db.session.commit()


def ensure_memory_file(user_id: int, character_key: str) -> str:
    """创建目录与初始 memory_state.json（若不存在）。"""
    from memory.io import memory_file_path

    path = memory_file_path(user_id, character_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_MEMORY_STATE, f, ensure_ascii=False, indent=2)
        print(f"[SETUP] 已创建初始记忆文件 -> {path}")
    return path


def log_write(path: str, content: str) -> None:
    preview = content if len(content) <= 60 else content[:57] + "..."
    print(f'[MEMORY WRITE] 写入记忆: "{preview}" -> {path}')


def log_search(keyword: str, items: list, total: int) -> None:
    print(f'[MEMORY SEARCH] 关键词 "{keyword}" 检索到 {total} 条相关记忆')
    for i, item in enumerate(items[:5], 1):
        summary = item.get("summary") or item.get("content", "")[:50]
        print(f"  #{i} [{item.get('importance_raw', '?')}] {summary}")
    if total > 5:
        print(f"  ... 另有 {total - 5} 条未显示")


def simulate_model_reply(user_input: str) -> str:
    return f"收到你的消息：{user_input}"


def process_turn(user_input: str, memory_path: str) -> None:
    from memory.search import search_memories
    from memory.writer import MemoryValidationError, add_memory

    # 1) 检索（写入前先查已有相关记忆）
    items, total = search_memories(
        USER_ID,
        CHARACTER_KEY,
        keyword=user_input,
        per_page=10,
    )
    log_search(user_input, items, total)

    # 2) 写入用户输入
    user_fact = f"用户说：{user_input}"
    add_memory(
        USER_ID,
        CHARACTER_ID,
        user_fact,
        importance=3,
        source="user",
        operator="cli_demo",
    )
    log_write(memory_path, user_fact)

    # 3) 模拟模型回复
    reply = simulate_model_reply(user_input)
    print(f'[MODEL REPLY] 模型回复: "{reply}"')

    # 4) 写入模型回复
    bot_fact = f"模型回复：{reply}"
    add_memory(
        USER_ID,
        CHARACTER_ID,
        bot_fact,
        importance=3,
        source="model",
        operator="cli_demo",
    )
    log_write(memory_path, bot_fact)

    # 5) 再次检索，展示本轮后的记忆池
    items_after, total_after = search_memories(
        USER_ID,
        CHARACTER_KEY,
        keyword=user_input,
        per_page=10,
    )
    print(
        f"[MEMORY SEARCH] 本轮后关键词 \"{user_input}\" 共 {total_after} 条相关记忆"
    )


def main() -> int:
    print("=" * 60)
    print("Harness CLI Demo - Input->Output + Memory Read/Write")
    print(f"用户 ID: {USER_ID}  角色 ID: {CHARACTER_ID}  角色 Key: {CHARACTER_KEY}")
    print("输入 exit 退出")
    print("=" * 60)

    try:
        _ensure_db_character()
        memory_path = ensure_memory_file(USER_ID, CHARACTER_KEY)
        print(f"[SETUP] 记忆文件路径: {os.path.abspath(memory_path)}")
        print(f"[SETUP] 启动时间: {datetime.now(timezone.utc).isoformat()}")
    except Exception as exc:
        print(f"[ERROR] 初始化失败: {exc}", file=sys.stderr)
        return 1

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[EXIT] 再见。")
            break

        if not user_input:
            print("[HINT] 请输入内容，或输入 exit 退出。")
            continue

        if user_input.lower() == "exit":
            print("[EXIT] 再见。")
            break

        try:
            process_turn(user_input, memory_path)
        except MemoryValidationError as exc:
            print(f"[ERROR] 记忆校验失败: {exc}")
        except Exception as exc:
            print(f"[ERROR] 本轮处理异常: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
