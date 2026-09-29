"""弧光管理器：读取/更新弧光状态，记录日志，联动情绪基线。"""
from __future__ import annotations

import logging
import re
from typing import Callable

from arc.config import (
    AUTO_ADVANCE_RULES,
    DEFAULT_STAGE,
    DEFAULT_STAGES,
    MAX_GOAL_DESC_LEN,
    MAX_GOAL_TITLE_LEN,
    MAX_STAGE_LEN,
    SOUL_TO_ARC_STAGE,
    STAGE_NAME_PATTERN,
)
from arc.logger import log_arc_action
from arc.models import ArcState, GoalItem

logger = logging.getLogger(__name__)


class ArcValidationError(ValueError):
    pass


class ArcNotFoundError(LookupError):
    pass


def _clamp_progress(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def validate_stage_name(stage: str) -> str:
    stage = (stage or "").strip()
    if not stage or len(stage) > MAX_STAGE_LEN:
        raise ArcValidationError(f"阶段名称无效（长度 1~{MAX_STAGE_LEN}）")
    if not re.fullmatch(STAGE_NAME_PATTERN, stage):
        raise ArcValidationError("阶段名称仅允许字母、数字、下划线")
    return stage


def validate_goal_title(title: str) -> str:
    title = (title or "").strip()
    if not title or len(title) > MAX_GOAL_TITLE_LEN:
        raise ArcValidationError(f"目标标题无效（长度 1~{MAX_GOAL_TITLE_LEN}）")
    return title


def validate_goal_description(description: str) -> str:
    description = (description or "").strip()
    if len(description) > MAX_GOAL_DESC_LEN:
        raise ArcValidationError(f"目标描述过长（最多 {MAX_GOAL_DESC_LEN} 字符）")
    return description


def _use_flask() -> bool:
    try:
        from flask import has_app_context

        return has_app_context()
    except Exception:
        return False


def get_or_create_arc(character_id: int) -> ArcState:
    """获取角色弧光状态，不存在则创建默认记录。"""
    if _use_flask():
        from app.models.user import ArcRecord
        from extensions import db

        row = ArcRecord.query.filter_by(character_id=character_id).first()
        if row is None:
            row = ArcRecord(
                character_id=character_id,
                current_stage=DEFAULT_STAGE,
                stages=list(DEFAULT_STAGES),
                goals=[],
                progress=0.0,
                auto_advance=True,
            )
            db.session.add(row)
            db.session.commit()
            log_arc_action(
                character_id,
                "create",
                {"stage": DEFAULT_STAGE},
                operator="system",
            )
        state = ArcState.from_db_row(row)
        state.progress = state.compute_progress()
        return state

    from database.models import Arc
    from database.session import SessionLocal

    session = SessionLocal()
    try:
        row = session.query(Arc).filter_by(character_id=character_id).first()
        if row is None:
            row = Arc(
                character_id=character_id,
                current_stage=DEFAULT_STAGE,
                stages=list(DEFAULT_STAGES),
                goals=[],
                progress=0.0,
                auto_advance=True,
            )
            session.add(row)
            session.commit()
            log_arc_action(
                character_id,
                "create",
                {"stage": DEFAULT_STAGE},
                operator="system",
            )
        state = ArcState.from_db_row(row)
        state.progress = state.compute_progress()
        return state
    finally:
        session.close()


def get_arc(character_id: int) -> ArcState:
    return get_or_create_arc(character_id)


def _save_arc_state(state: ArcState) -> None:
    state.progress = _clamp_progress(state.compute_progress())

    if _use_flask():
        from app.models.user import ArcRecord
        from extensions import db

        row = ArcRecord.query.filter_by(character_id=state.character_id).first()
        if row is None:
            raise ArcNotFoundError(f"弧光记录不存在: character_id={state.character_id}")
        row.current_stage = state.current_stage
        row.stages = list(state.stages)
        row.goals = [g.to_dict() for g in state.goals]
        row.progress = state.progress
        row.auto_advance = state.auto_advance
        db.session.commit()
        return

    from database.models import Arc
    from database.session import SessionLocal

    session = SessionLocal()
    try:
        row = session.query(Arc).filter_by(character_id=state.character_id).first()
        if row is None:
            raise ArcNotFoundError(f"弧光记录不存在: character_id={state.character_id}")
        row.current_stage = state.current_stage
        row.stages = list(state.stages)
        row.goals = [g.to_dict() for g in state.goals]
        row.progress = state.progress
        row.auto_advance = state.auto_advance
        session.commit()
    finally:
        session.close()


def _sync_emotion_baseline(character_id: int, new_stage: str) -> None:
    """弧光阶段变化时，将情绪 PAD 向新阶段基线轻推（可选联动）。"""
    try:
        from emotion.models import EmotionRuntimeState, PADState
        from emotion.stage import get_stage_baseline

        baseline = get_stage_baseline(new_stage)

        try:
            from flask import has_app_context

            if has_app_context():
                from app.models.user import CharacterRecord
                from extensions import db

                char = CharacterRecord.query.get(character_id)
                if not char or not char.emotion_state:
                    return
                import json

                data = json.loads(char.emotion_state)
                runtime = EmotionRuntimeState.from_dict(data)
                runtime.pad.decay_toward(baseline, 0.2)
                runtime.stage = new_stage
                char.emotion_state = json.dumps(
                    runtime.to_dict(), ensure_ascii=False
                )
                db.session.commit()
                return
        except Exception:
            pass

        from database.models import Character
        from database.session import SessionLocal
        import json

        session = SessionLocal()
        try:
            char = session.query(Character).filter_by(id=character_id).first()
            if not char or not char.emotion_state:
                return
            data = json.loads(char.emotion_state or "{}")
            runtime = EmotionRuntimeState.from_dict(data)
            runtime.pad.decay_toward(baseline, 0.2)
            runtime.stage = new_stage
            char.emotion_state = json.dumps(runtime.to_dict(), ensure_ascii=False)
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        logger.debug("情绪基线联动跳过: %s", exc)


def update_stage(
    character_id: int,
    new_stage: str,
    operator: str = "system",
    *,
    user_id: int | None = None,
    sync_emotion: bool = True,
) -> ArcState:
    new_stage = validate_stage_name(new_stage)
    state = get_arc(character_id)

    if new_stage not in state.stages:
        raise ArcValidationError(f"阶段 {new_stage} 不在阶段列表中")

    old_stage = state.current_stage
    if old_stage == new_stage:
        return state

    state.current_stage = new_stage
    state.progress = state.compute_progress()
    _save_arc_state(state)

    log_arc_action(
        character_id,
        "update_stage",
        {"old_stage": old_stage, "new_stage": new_stage},
        operator=operator,
        user_id=user_id,
    )

    if sync_emotion:
        _sync_emotion_baseline(character_id, new_stage)

    return state


def set_auto_advance(
    character_id: int,
    enabled: bool,
    operator: str,
    *,
    user_id: int | None = None,
) -> ArcState:
    state = get_arc(character_id)
    state.auto_advance = bool(enabled)
    _save_arc_state(state)
    log_arc_action(
        character_id,
        "set_auto_advance",
        {"auto_advance": enabled},
        operator=operator,
        user_id=user_id,
    )
    return state


def add_goal(
    character_id: int,
    title: str,
    description: str = "",
    operator: str = "system",
    *,
    user_id: int | None = None,
) -> ArcState:
    title = validate_goal_title(title)
    description = validate_goal_description(description)
    state = get_arc(character_id)
    goal = GoalItem.create(title, description)
    state.goals.append(goal)
    state.progress = state.compute_progress()
    _save_arc_state(state)

    log_arc_action(
        character_id,
        "add_goal",
        {"goal_id": goal.id, "title": title},
        operator=operator,
        user_id=user_id,
    )
    return state


def update_goal(
    character_id: int,
    goal_id: str,
    title: str,
    description: str = "",
    operator: str = "system",
    *,
    user_id: int | None = None,
) -> ArcState:
    title = validate_goal_title(title)
    description = validate_goal_description(description)
    state = get_arc(character_id)
    goal = _find_goal(state, goal_id)
    old = {"title": goal.title, "description": goal.description}
    goal.title = title
    goal.description = description
    _save_arc_state(state)

    log_arc_action(
        character_id,
        "update_goal",
        {"goal_id": goal_id, "old": old, "new": {"title": title, "description": description}},
        operator=operator,
        user_id=user_id,
    )
    return state


def complete_goal(
    character_id: int,
    goal_id: str,
    completed: bool = True,
    operator: str = "system",
    *,
    user_id: int | None = None,
) -> ArcState:
    state = get_arc(character_id)
    goal = _find_goal(state, goal_id)
    goal.completed = bool(completed)
    state.progress = state.compute_progress()
    _save_arc_state(state)

    log_arc_action(
        character_id,
        "complete_goal" if completed else "uncomplete_goal",
        {"goal_id": goal_id, "title": goal.title, "completed": completed},
        operator=operator,
        user_id=user_id,
    )
    return state


def delete_goal(
    character_id: int,
    goal_id: str,
    operator: str = "system",
    *,
    user_id: int | None = None,
) -> ArcState:
    state = get_arc(character_id)
    goal = _find_goal(state, goal_id)
    state.goals = [g for g in state.goals if g.id != goal_id]
    state.progress = state.compute_progress()
    _save_arc_state(state)

    log_arc_action(
        character_id,
        "delete_goal",
        {"goal_id": goal_id, "title": goal.title},
        operator=operator,
        user_id=user_id,
    )
    return state


def _find_goal(state: ArcState, goal_id: str) -> GoalItem:
    for goal in state.goals:
        if goal.id == goal_id:
            return goal
    raise ArcNotFoundError(f"目标不存在: {goal_id}")


def get_recent_logs(character_id: int, limit: int = 20) -> list[dict]:
    if _use_flask():
        from app.models.user import ArcLogRecord

        rows = (
            ArcLogRecord.query.filter_by(character_id=character_id)
            .order_by(ArcLogRecord.created_at.desc())
            .limit(limit)
            .all()
        )
    else:
        from database.models import ArcLog
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            rows = (
                session.query(ArcLog)
                .filter_by(character_id=character_id)
                .order_by(ArcLog.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    return [
        {
            "id": r.id,
            "action": r.action,
            "details": r.details,
            "operator": r.operator,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


def try_auto_advance(
    character_id: int,
    total_rounds: int,
    operator: str = "system",
) -> ArcState | None:
    """根据配置条件尝试自动推进阶段（auto_advance 关闭时跳过）。"""
    state = get_arc(character_id)
    if not state.auto_advance:
        return None

    completed = state.completed_goal_count()
    best = state.current_stage
    stage_rank = {s: i for i, s in enumerate(state.stages)}

    for stage, rules in AUTO_ADVANCE_RULES.items():
        if stage not in state.stages:
            continue
        if stage_rank.get(stage, 0) <= stage_rank.get(best, 0):
            continue
        if total_rounds < rules.get("min_rounds", 0):
            continue
        if completed < rules.get("min_goals_completed", 0):
            continue
        best = stage

    if best == state.current_stage:
        return None

    return update_stage(character_id, best, operator=operator, sync_emotion=True)


def on_engine_arc_update(
    character_id: int | None,
    *,
    soul_arc_stage: str | None = None,
    current_goal: str | None = None,
    reason: str = "",
    total_rounds: int = 0,
    operator: str = "system",
) -> ArcState | None:
    """
    引擎弧光自动推进后同步到 Arc 表。

    - 映射 Soul 阶段到产品阶段
    - 尝试按轮次/目标条件自动推进
    - 将新目标写入 goals（若不存在同标题）
    """
    if not character_id:
        return None

    try:
        state = get_arc(character_id)
        changed = False

        if soul_arc_stage:
            mapped = SOUL_TO_ARC_STAGE.get(soul_arc_stage)
            if (
                mapped
                and state.auto_advance
                and mapped in state.stages
                and mapped != state.current_stage
            ):
                idx_old = state.stages.index(state.current_stage)
                idx_new = state.stages.index(mapped)
                if idx_new > idx_old:
                    update_stage(
                        character_id,
                        mapped,
                        operator=operator,
                        sync_emotion=True,
                    )
                    changed = True
                    state = get_arc(character_id)

        advanced = try_auto_advance(character_id, total_rounds, operator=operator)
        if advanced:
            state = advanced
            changed = True

        if current_goal and current_goal.strip():
            title = current_goal.strip()[:MAX_GOAL_TITLE_LEN]
            exists = any(g.title == title for g in state.goals)
            if not exists:
                add_goal(
                    character_id,
                    title,
                    description=reason[:MAX_GOAL_DESC_LEN] if reason else "",
                    operator=operator,
                )
                changed = True
                state = get_arc(character_id)

        if changed:
            log_arc_action(
                character_id,
                "engine_sync",
                {
                    "soul_arc_stage": soul_arc_stage,
                    "current_goal": current_goal,
                    "reason": reason,
                    "rounds": total_rounds,
                },
                operator=operator,
            )

        return state
    except Exception as exc:
        logger.warning("引擎弧光同步失败（fail-open）: %s", exc)
        return None
