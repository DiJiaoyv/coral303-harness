#!/usr/bin/env python3
"""
演示脚本：记忆如何影响模型回复（端到端）。

自动执行两段对话剧本，真实读写 users/999/characters/demo/memory_state.json。
不修改现有代码，不调用 Ollama。
"""
from __future__ import annotations

import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_SCRIPT_DIR)
os.environ.setdefault("SECRET_KEY", "demo-memory-impact-secret-key")
_local_db = os.path.join(_SCRIPT_DIR, "harness.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_local_db.replace(chr(92), '/')}"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 隔离测试数据，避免污染真实用户
USER_ID = 999
CHARACTER_ID = 999
CHARACTER_KEY = "demo"

DEFAULT_MEMORY_STATE = {
    "max_messages": 20,
    "short_term": [],
    "long_term": [],
    "use_vector": True,
}

# 剧本： (用户输入, 是否首轮记名场景)
SCRIPT = [
    ("我叫美猪猪", True),
    ("我饿了", False),
]


def _ensure_db_character() -> None:
    from app import create_app
    from app.models.user import CharacterRecord, User
    from extensions import db

    app = create_app()
    with app.app_context():
        user = db.session.get(User, USER_ID)
        if user is None:
            user = User(
                id=USER_ID,
                username="demo_memory_user",
                password_hash="demo-no-login",
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
                display_name="记忆影响演示",
                role="演示角色",
            )
            db.session.add(char)
        else:
            char.user_id = USER_ID
            char.character_key = CHARACTER_KEY
            char.deleted = False

        db.session.commit()


def ensure_memory_file() -> str:
    from memory.io import memory_file_path

    path = memory_file_path(USER_ID, CHARACTER_KEY)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        # 每次演示从干净状态开始
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_MEMORY_STATE, f, ensure_ascii=False, indent=2)
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_MEMORY_STATE, f, ensure_ascii=False, indent=2)
    return path


def extract_name_from_input(text: str) -> str | None:
    """从「我叫 XXX」类输入中提取名字。"""
    m = re.search(r"我叫\s*(.+?)\s*$", text.strip())
    if m:
        return m.group(1).strip()
    return None


def score_user_input(text: str, name: str | None) -> tuple[int, str]:
    """简单规则：包含个人信息则重要性 5。"""
    if name:
        return 5, "包含个人信息"
    if any(k in text for k in ("喜欢", "讨厌", "秘密", "住在", "工作")):
        return 4, "包含偏好或个人信息"
    return 3, "普通对话"


def extract_name_from_memories(memories: list[dict]) -> str | None:
    """从已有记忆中解析用户名字。"""
    patterns = [
        re.compile(r"用户名叫[「\"'](.+?)[」\"']"),
        re.compile(r"名叫[「\"'](.+?)[」\"']"),
        re.compile(r"用户名字是\s*(.+?)\s*$"),
        re.compile(r"我叫\s*(.+?)\s*$"),
    ]
    for item in memories:
        content = item.get("content", "")
        for pat in patterns:
            m = pat.search(content)
            if m:
                return m.group(1).strip()
    return None


def search_all_memories() -> list[dict]:
    from memory.search import search_memories

    items, _ = search_memories(USER_ID, CHARACTER_KEY, per_page=500)
    return items


def generate_reply(user_input: str, memories: list[dict]) -> str:
    """根据记忆生成个性化回复（规则引擎，非 LLM）。"""
    name = extract_name_from_memories(memories)

    if "饿" in user_input and name:
        return f"{name}饿了呀，推荐你去吃火锅！"

    if name:
        return f"好的{name}，我记住了：{user_input}"

    if "饿" in user_input:
        return "你饿了呀，推荐你去吃点东西！"

    return f"收到：{user_input}"


def run_demo() -> str:
    from memory.io import memory_file_path
    from memory.writer import add_memory

    _ensure_db_character()
    memory_path = ensure_memory_file()
    print("[INIT] 创建测试角色完成")

    for user_input, is_intro in SCRIPT:
        print(f"[INPUT] 用户说：{user_input}")

        if is_intro:
            name = extract_name_from_input(user_input)
            importance, reason = score_user_input(user_input, name)
            print(f"[SCORE] 重要性评分：{importance}（{reason}）")

            fact = f'用户名叫"{name}"' if name else f"用户说：{user_input}"
            add_memory(
                USER_ID,
                CHARACTER_ID,
                fact,
                importance=importance,
                source="user",
                operator="demo_memory_impact",
            )
            print(f'[MEMORY] 写入记忆：{fact}（重要性 {importance}）')
            continue

        # 第二轮：先检索，再生成回复，再写入
        all_memories = search_all_memories()
        name = extract_name_from_memories(all_memories)

        if name:
            matched = [
                m for m in all_memories if name in m.get("content", "")
            ]
            if matched:
                summary = matched[0].get("content", "")[:40]
                print(
                    f"[MEMORY] 检索到 {len(matched)} 条相关记忆：{summary}"
                )
            else:
                print(f"[MEMORY] 检索到名字相关记忆：用户名叫\"{name}\"")
        else:
            print("[MEMORY] 检索到 0 条相关记忆")

        reply = generate_reply(user_input, all_memories)
        print(f"[OUTPUT] {reply}")

        bot_fact = f"模型回复：{reply}"
        add_memory(
            USER_ID,
            CHARACTER_ID,
            bot_fact,
            importance=3,
            source="model",
            operator="demo_memory_impact",
        )
        print("[MEMORY] 写入记忆：模型回复（重要性 3）")

    rel_path = f"users/{USER_ID}/characters/{CHARACTER_KEY}/memory_state.json"
    print(f"演示完成。记忆文件路径：{rel_path}")
    return memory_file_path(USER_ID, CHARACTER_KEY)


def main() -> int:
    try:
        run_demo()
        return 0
    except Exception as exc:
        print(f"[ERROR] 演示失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
