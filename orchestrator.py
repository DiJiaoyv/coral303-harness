"""编排层（Orchestration）—— 所有对话入口的唯一函数。

合并前（重复逻辑散落三处）：

    api/routes/chat.py    → generate_response()        → engine.process_message()
    app/routes/data_routes.py → engine.process_message()           （自己写 Conversation + score_and_persist）
    harness_core.generate_response_stream()                     （自己写 Conversation + score_and_persist）

合并后（统一一个入口）：

    api/routes/chat.py           → orchestrate_turn()
    app/routes/data_routes.py    → orchestrate_turn() / _stream()
    harness_core.generate_response/_stream → 薄包装，调 orchestrate_turn()/_stream()

核心流程（engine.process_message 内部已实现，本模块只做编排 + 持久化）：

    1. 加载/缓存用户引擎（_get_engine_for_user）
    2. 切换到目标角色
    3. context_builder.build()             ← engine.build_prompt()
    4. LLM.generate(candidate)              ← engine.chat_ollama
    5. HarnessEvaluator.evaluate() 循环    ← engine._generate_with_diagnosis()
       （≤ max_regen_attempts 次重生成，失败候选不进 Memory）
    6. memory_writer.write(final_response) ← engine._finalize_turn()
    7. 写 Evaluation Log + Observability   ← scoring.engine.score_and_persist()
    8. 写 Conversation                     ← 本模块负责

关键约束（来自用户）：
    - 所有对外暴露的对话接口最终必须走到本模块的 orchestrate_turn() 或
      orchestrate_turn_stream()。
    - 绝对不允许任何路径绕过 Context Builder 或 Memory Writer。
    - 失败候选不进 Memory（engine 内部已保证；本模块只读 final_response）。
"""
from __future__ import annotations

from typing import Any, Iterator

from harness_core import (
    TurnResult,
    _get_engine_for_user,
)


# ==============================================================
# 内部辅助：加载 character_meta + 切换角色
# ==============================================================
def _resolve_character(
    user_id: int,
    character_id: int,
) -> tuple[Any, dict]:
    """查询 character 元数据并切换到该角色。

    返回 (character_meta, character_meta_dict)：
        - character_meta[0] 是 ORM 对象（含 character_key / display_name 等）
        - character_meta[1] 是给 scoring 用的 dict
    """
    from database.models import Character
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        char = (
            db.query(Character)
            .filter(
                Character.id == character_id,
                Character.user_id == user_id,
                Character.deleted.is_(False),
            )
            .first()
        )
        if not char:
            raise ValueError(f"角色不存在或无权访问: character_id={character_id}")
        character_key = char.character_key
        character_meta = {
            "display_name": char.display_name,
            "role": char.role or "",
            "description": char.description or "",
            "system_prompt": char.system_prompt or "",
            "character_key": char.character_key,
        }
    finally:
        db.close()

    engine = _get_engine_for_user(user_id)
    if engine.get_active_character() != character_key:
        engine.switch_character(character_key)

    return engine, character_meta


def _persist_conversation(
    user_id: int,
    character_key: str,
    user_message: str,
    assistant_reply: str,
) -> int | None:
    """把 (user, assistant) 一对消息写入 conversations 表，返回 assistant 行 id。"""
    from database.models import Conversation
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        user_conv = Conversation(
            user_id=user_id,
            character_key=character_key,
            role="user",
            content=user_message,
        )
        db.add(user_conv)
        db.flush()
        assistant_conv = Conversation(
            user_id=user_id,
            character_key=character_key,
            role="assistant",
            content=assistant_reply,
        )
        db.add(assistant_conv)
        db.commit()
        return assistant_conv.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _persist_score_log(
    *,
    user_id: int,
    character_id: int,
    conversation_id: int | None,
    user_message: str,
    reply: str,
    character_meta: dict,
    turn_result: TurnResult | None,
) -> None:
    """调 score_and_persist 记录评估日志（quality improvement data，不进 Memory）。"""
    from scoring.engine import score_and_persist

    diagnosis_dict = None
    if turn_result is not None and getattr(turn_result, "diagnosis", None):
        diagnosis_dict = turn_result.diagnosis

    score_and_persist(
        user_message,
        reply,
        character_meta,
        user_id=user_id,
        character_id=character_id,
        conversation_id=conversation_id,
        diagnosis=diagnosis_dict,
    )


# ==============================================================
# 唯一编排入口：同步
# ==============================================================
def orchestrate_turn(
    user_id: int,
    character_id: int,
    user_message: str,
    *,
    persist_conversation: bool = True,
    persist_score: bool = True,
) -> TurnResult:
    """所有对话入口的唯一编排函数（同步版）。

    流程：
        1. 解析 character_meta + 切换角色
        2. engine.process_message()
           （内部已做：safety 检查 → context_builder.build() →
            LLM.generate → diagnose 循环 → _finalize_turn(memory_writer.write)）
        3. 持久化 Conversation（user + assistant 两条）
        4. 持久化 score_log（含 diagnosis，不进 Memory）
        5. 经 performance.run_inference 排队 + 监控

    Args:
        user_id: 当前用户 id
        character_id: 目标角色 id
        user_message: 用户消息文本
        persist_conversation: 是否写 Conversation 表（默认 True）
        persist_score: 是否写 score_logs（默认 True）

    Returns:
        TurnResult：含 response / new_facts / arc_changes / diagnosis / error
    """
    from performance import run_inference

    def _task() -> TurnResult:
        engine, character_meta = _resolve_character(user_id, character_id)
        result = engine.process_message(
            user_message,
            stream=False,
            character_id=character_id,
        )

        reply = result.response
        if persist_conversation and reply:
            conv_id = _persist_conversation(
                user_id,
                character_meta["character_key"],
                user_message,
                reply,
            )
            if persist_score:
                _persist_score_log(
                    user_id=user_id,
                    character_id=character_id,
                    conversation_id=conv_id,
                    user_message=user_message,
                    reply=reply,
                    character_meta=character_meta,
                    turn_result=result,
                )

        return result

    return run_inference(
        _task,
        user_id=user_id,
        character_id=character_id,
    )


# ==============================================================
# 唯一编排入口：流式
# ==============================================================
def orchestrate_turn_stream(
    user_id: int,
    character_id: int,
    user_message: str,
    *,
    cancel_event=None,
    timeout_seconds: float | None = None,
    persist_conversation: bool = True,
    persist_score: bool = True,
) -> Iterator[tuple[str, Any]]:
    """所有对话入口的唯一编排函数（流式版）。

    流程完全等同 orchestrate_turn()，只是 token 用 yield 推送。

    Yields:
        ("token", str)     — 增量 token
        ("done", TurnResult) — 最终结果
        ("cancelled", TurnResult) — 被取消，含已生成部分
        ("error", str)     — 错误信息
    """
    engine, character_meta = _resolve_character(user_id, character_id)

    turn_result: TurnResult | None = None
    accumulated = ""
    cancelled = False

    stream_kwargs: dict[str, Any] = {"cancel_event": cancel_event}
    if timeout_seconds is not None:
        stream_kwargs["timeout_seconds"] = timeout_seconds

    for event, payload in engine.process_message_stream(
        user_message,
        character_id=character_id,
        **stream_kwargs,
    ):
        if event == "token":
            accumulated += payload
            yield "token", payload
        elif event == "cancelled":
            cancelled = True
            turn_result = payload
            yield "cancelled", payload
        elif event == "done":
            turn_result = payload
            yield "done", payload
        elif event == "error":
            yield "error", payload
            return

    reply = ""
    if turn_result is not None:
        reply = turn_result.response
    elif accumulated:
        reply = accumulated

    if persist_conversation and reply and not cancelled:
        conv_id = _persist_conversation(
            user_id,
            character_meta["character_key"],
            user_message,
            reply,
        )
        if persist_score:
            _persist_score_log(
                user_id=user_id,
                character_id=character_id,
                conversation_id=conv_id,
                user_message=user_message,
                reply=reply,
                character_meta=character_meta,
                turn_result=turn_result,
            )


__all__ = [
    "orchestrate_turn",
    "orchestrate_turn_stream",
]
