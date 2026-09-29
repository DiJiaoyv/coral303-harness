"""内容安全网关：供 harness_core 调用的统一审核入口。"""
from __future__ import annotations

from safety.auditor import log_audit_record
from safety.input_filter import filter_input, input_blocked_message
from safety.output_filter import filter_output, output_blocked_message


def check_user_input(
    text: str,
    *,
    user_id: int | None = None,
    character_id: int | None = None,
) -> str | None:
    """
    审核用户输入。

    Returns:
        None 表示放行；非 None 为应返回给用户的拦截提示。
    """
    result = filter_input(text)
    if not result.hit:
        return None

    log_audit_record(
        stage="input",
        level=result.level or "monitor",
        matched_word=result.matched_word,
        original_content=text,
        action_taken=result.action,
        user_id=user_id,
        character_id=character_id,
    )
    if result.action == "blocked":
        return input_blocked_message()
    return None


def sanitize_model_output(
    text: str,
    *,
    user_id: int | None = None,
    character_id: int | None = None,
) -> str:
    """审核模型输出，禁止级命中则替换为统一提示。"""
    result = filter_output(text)
    if not result.hit:
        return text

    log_audit_record(
        stage="output",
        level=result.level or "monitor",
        matched_word=result.matched_word,
        original_content=text,
        action_taken=result.action,
        user_id=user_id,
        character_id=character_id,
    )
    if result.action == "blocked":
        return output_blocked_message()
    return text
