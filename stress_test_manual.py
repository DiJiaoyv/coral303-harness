#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Harness 手动压力测试：最多 50 轮，显示评分与性能数据。

用法:
  python stress_test_manual.py

固定测试用户/角色 ID=8888（自动创建）。输入 exit 退出。
结束后打印汇总，不清除数据（可在管理后台查看）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# 保证项目根在 path 上
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

# 压测仅跑对话模型：禁用合并分析/向量嵌入，避免 CPU 双模型加载导致 300s 超时
os.environ["HARNESS_STRESS_MODE"] = "1"
os.environ.setdefault("TIMEOUT_SECONDS", "600")

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# 压力测试始终使用项目根目录的 harness.db（忽略 Docker 用的 /app/data 路径）
_local_db = os.path.join(ROOT, "harness.db")
_db_url = os.environ.get("DATABASE_URL", "")
if (not _db_url) or "/app/" in _db_url.replace("\\", "/"):
    os.environ["DATABASE_URL"] = f"sqlite:///{_local_db}"

from api.utils.security import hash_password
from database.models import Character, PerformanceLog, ScoreLog, User
import database.session as db_session
from database.session import create_db_engine
from sqlalchemy.orm import sessionmaker
from harness_core import generate_response, init_database

# 重建并回写会话工厂，确保评分/性能写入同一本地库
_engine = create_db_engine(os.environ["DATABASE_URL"])
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
db_session.engine = _engine
db_session.SessionLocal = SessionLocal

USER_ID = 8888
CHARACTER_ID = 8888
MAX_ROUNDS = 50
CHARACTER_KEY = "喵小星"
USERNAME = "stress8888"
PASSWORD = "Stress8888"
CHARACTER_JSON = os.path.join(ROOT, "characters", "喵小星.json")


def _load_character_profile() -> dict:
    """从 characters/喵小星.json 读取展示信息与 system_prompt。"""
    defaults = {
        "name": "喵小星",
        "role": "低重力星球的小猫",
        "description": "一只生活在低重力星球的小猫。",
        "system_prompt": "你是喵小星，一只生活在低重力星球的小猫。",
        "temperature": 1.0,
        "max_tokens": 1024,
    }
    if not os.path.isfile(CHARACTER_JSON):
        return defaults
    import json

    with open(CHARACTER_JSON, encoding="utf-8") as f:
        data = json.load(f)
    defaults.update({
        "name": data.get("name") or defaults["name"],
        "role": data.get("role") or defaults["role"],
        "description": data.get("description") or defaults["description"],
        "system_prompt": data.get("system_prompt") or defaults["system_prompt"],
        "temperature": data.get("temperature", defaults["temperature"]),
        "max_tokens": data.get("max_tokens", defaults["max_tokens"]),
    })
    return defaults


def ensure_test_fixtures() -> None:
    """确保 harness.db 中存在 user_id=8888、character_id=8888。"""
    init_database(_local_db)
    profile = _load_character_profile()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == USER_ID).first()
        if user is None:
            user = User(
                id=USER_ID,
                username=USERNAME,
                password_hash=hash_password(PASSWORD),
                is_admin=False,
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.flush()
            print(f"[初始化] 已创建测试用户 id={USER_ID} ({USERNAME})")
        else:
            print(f"[初始化] 复用测试用户 id={USER_ID} ({user.username})")

        char = db.query(Character).filter(Character.id == CHARACTER_ID).first()
        if char is None:
            char = Character(
                id=CHARACTER_ID,
                user_id=USER_ID,
                character_key=CHARACTER_KEY,
                display_name=profile["name"],
                role=profile["role"],
                description=profile["description"],
                system_prompt=profile["system_prompt"],
                deleted=False,
                version=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(char)
            db.flush()
            print(f"[初始化] 已创建测试角色 id={CHARACTER_ID} ({CHARACTER_KEY})")
        else:
            # 同步为喵小星（覆盖旧的 stress_ghost 等）
            char.user_id = USER_ID
            char.character_key = CHARACTER_KEY
            char.display_name = profile["name"]
            char.role = profile["role"]
            char.description = profile["description"]
            char.system_prompt = profile["system_prompt"]
            char.deleted = False
            char.updated_at = datetime.now(timezone.utc)
            print(f"[初始化] 已同步测试角色 id={CHARACTER_ID} ({char.character_key})")

        db.commit()

        # 同步用户侧角色注册表，供 HarnessEngine.switch_character 使用
        _ensure_user_character_registry(profile)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_user_character_registry(profile: dict) -> None:
    """在 users/8888/characters.json 注册喵小星，并确保角色目录存在。"""
    import json

    user_root = os.path.join(ROOT, "users", str(USER_ID))
    os.makedirs(user_root, exist_ok=True)
    registry_path = os.path.join(user_root, "characters.json")
    if os.path.isfile(registry_path):
        with open(registry_path, encoding="utf-8") as f:
            registry = json.load(f)
    else:
        registry = {"active": CHARACTER_KEY, "base_dir": "characters", "characters": {}}

    registry.setdefault("characters", {})
    registry["characters"][CHARACTER_KEY] = {
        "name": profile["name"],
        "role": profile["role"],
        "core_traits": ["轻盈", "好奇", "懵懂"],
        "core_drive": profile["system_prompt"],
        "fear": "被关进没有浮力的沉重世界。",
        "catchphrases": ["喵？", "像羽毛一样轻呀～"],
        "vocabulary": ["漂浮", "爪子", "天花板", "轻"],
        "arc_stage": "起点",
        "current_goal": "找更多漂浮玩具一起玩。",
        "system_prompt": profile["system_prompt"],
    }
    registry["active"] = CHARACTER_KEY
    registry["base_dir"] = "characters"
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    # 清除引擎缓存，下次 generate_response 会重新加载注册表
    try:
        from harness_core import _engine_cache

        _engine_cache.pop(USER_ID, None)
    except Exception:
        pass

    print(f"[初始化] 已注册角色到 {registry_path}")


def fetch_latest_score(after_id: int | None = None) -> ScoreLog | None:
    db = SessionLocal()
    try:
        q = (
            db.query(ScoreLog)
            .filter(ScoreLog.user_id == USER_ID)
            .order_by(ScoreLog.id.desc())
        )
        if after_id is not None:
            q = q.filter(ScoreLog.id > after_id)
        return q.first()
    finally:
        db.close()


def fetch_latest_perf(after_id: int | None = None) -> PerformanceLog | None:
    db = SessionLocal()
    try:
        q = (
            db.query(PerformanceLog)
            .filter(PerformanceLog.user_id == USER_ID)
            .order_by(PerformanceLog.id.desc())
        )
        if after_id is not None:
            q = q.filter(PerformanceLog.id > after_id)
        return q.first()
    finally:
        db.close()


def latest_ids() -> tuple[int, int]:
    """返回当前最大 score_id / perf_id，用于定位本轮新增记录。"""
    db = SessionLocal()
    try:
        score_row = (
            db.query(ScoreLog.id)
            .filter(ScoreLog.user_id == USER_ID)
            .order_by(ScoreLog.id.desc())
            .first()
        )
        perf_row = (
            db.query(PerformanceLog.id)
            .filter(PerformanceLog.user_id == USER_ID)
            .order_by(PerformanceLog.id.desc())
            .first()
        )
        return (
            int(score_row[0]) if score_row else 0,
            int(perf_row[0]) if perf_row else 0,
        )
    finally:
        db.close()


def print_score(score: ScoreLog | None) -> None:
    print("━━━ 评分 ━━━")
    if score is None:
        print("暂无数据")
        return
    print(
        f"相关性: {score.relevance_score:.1f} | "
        f"角色一致性: {score.consistency_score:.1f} | "
        f"流畅度: {score.fluency_score:.1f} | "
        f"安全性: {score.safety_score:.1f}"
    )
    print(f"总分: {score.total_score:.1f}  (method={score.scoring_method})")


def print_perf(perf: PerformanceLog | None) -> None:
    print("━━━ 性能 ━━━")
    if perf is None:
        print("暂无数据")
        return
    ok = "成功" if perf.success else "失败"
    print(
        f"耗时: {perf.duration_ms:.0f}ms | "
        f"队列长度: {perf.queue_length} | "
        f"GPU: {perf.gpu_util:.1f}% | {ok}"
    )


def print_summary(scores: list[float], durations: list[float]) -> None:
    print("\n" + "=" * 50)
    print("=== 测试汇总 ===")
    print(f"完成轮次: {len(scores)} / {MAX_ROUNDS}")
    if scores:
        print(
            f"评分 — 平均: {sum(scores)/len(scores):.2f} | "
            f"最高: {max(scores):.2f} | 最低: {min(scores):.2f}"
        )
    else:
        print("评分 — 暂无数据")
    if durations:
        print(
            f"耗时 — 平均: {sum(durations)/len(durations):.0f}ms | "
            f"最长: {max(durations):.0f}ms | 最短: {min(durations):.0f}ms"
        )
    else:
        print("耗时 — 暂无数据")
    print(f"数据保留在 user_id={USER_ID} / character_id={CHARACTER_ID}，可在管理后台查看。")
    print("=" * 50)


def main() -> None:
    print("=== Harness 压力测试（手动模式）===")
    print(f"用户 ID: {USER_ID} | 角色 ID: {CHARACTER_ID}")
    print(f"输入 'exit' 退出，最多 {MAX_ROUNDS} 轮\n")

    try:
        ensure_test_fixtures()
    except Exception as exc:
        print(f"[错误] 初始化测试用户/角色失败: {exc}")
        sys.exit(1)

    score_totals: list[float] = []
    durations_ms: list[float] = []

    for round_no in range(1, MAX_ROUNDS + 1):
        print(f"\n第 {round_no}/{MAX_ROUNDS} 轮")
        try:
            user_input = input("你的输入: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[系统] 中断，结束测试。")
            break

        if not user_input:
            print("[跳过] 空输入")
            continue
        if user_input.lower() in ("exit", "quit", "/exit"):
            print("[系统] 退出。")
            break

        prev_score_id, prev_perf_id = latest_ids()

        try:
            reply = generate_response(USER_ID, CHARACTER_ID, user_input)
        except Exception as exc:
            print(f"[错误] 模型调用失败: {exc}")
            print("继续下一轮…")
            continue

        print(f"模型回复: {reply}")

        score = fetch_latest_score(after_id=prev_score_id)
        perf = fetch_latest_perf(after_id=prev_perf_id)
        print_score(score)
        print_perf(perf)

        if score is not None:
            score_totals.append(float(score.total_score))
        if perf is not None:
            durations_ms.append(float(perf.duration_ms))

    print_summary(score_totals, durations_ms)


if __name__ == "__main__":
    main()
