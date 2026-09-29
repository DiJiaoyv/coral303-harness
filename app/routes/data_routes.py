import os
import time

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context
from flask_login import current_user, login_required

from app.models.user import CharacterRecord, Conversation
from extensions import db
from harness_core import HarnessEngine, TurnResult
from performance.config import get_config
from performance.monitor import record_performance
from performance.queue_manager import get_request_queue
from performance.runtime import run_inference
from streaming.cancel_manager import get_cancel_manager, stream_token_for_user
from streaming.sse import sse_generator, sse_pack

data_bp = Blueprint("data", __name__)

_engines: dict[int, HarnessEngine] = {}


def user_data_root(user_id: int) -> str:
    return os.path.join("users", str(user_id))


def get_user_engine(user_id: int) -> HarnessEngine:
    if user_id not in _engines:
        root = user_data_root(user_id)
        os.makedirs(root, exist_ok=True)
        _engines[user_id] = HarnessEngine(
            config_path="config.json",
            user_id=user_id,
            user_data_root=root,
        )
        _sync_characters_to_db(user_id, _engines[user_id])
    return _engines[user_id]


def _sync_characters_to_db(user_id: int, engine: HarnessEngine) -> None:
    """将文件系统中的角色同步到 DB（带 user_id）。"""
    chars_meta = engine.character_manager.registry.get("characters", {})
    for key in engine.list_characters():
        meta = chars_meta.get(key, {})
        display_name = meta.get("name", key)
        role = meta.get("role", "")
        existing = CharacterRecord.query.filter_by(
            user_id=user_id, character_key=key, deleted=False
        ).first()
        if existing:
            existing.display_name = display_name
            existing.role = role
        else:
            db.session.add(
                CharacterRecord(
                    user_id=user_id,
                    character_key=key,
                    display_name=display_name,
                    role=role,
                )
            )
    db.session.commit()


@data_bp.route("/")
@login_required
def index():
    engine = get_user_engine(current_user.id)
    char_rec = CharacterRecord.query.filter_by(
        user_id=current_user.id,
        character_key=engine.get_active_character(),
        deleted=False,
    ).first()
    arc_card_html = ""
    if char_rec:
        from arc.manager import get_arc
        from arc.renderer import render_arc_card

        arc_state = get_arc(char_rec.id)
        arc_card_html = render_arc_card(arc_state, readonly=True)

    return render_template(
        "index.html",
        username=current_user.username,
        character_name=engine.soul.name,
        character_role=engine.soul.role,
        characters=engine.list_characters(),
        active_character=engine.get_active_character(),
        status=engine.format_status_text(),
        arc_card_html=arc_card_html,
        active_character_id=char_rec.id if char_rec else None,
    )


@data_bp.route("/character/<int:character_id>")
@login_required
def character_detail(character_id: int):
    """用户角色详情页（弧光只读）。"""
    character = CharacterRecord.query.filter_by(
        id=character_id,
        user_id=current_user.id,
        deleted=False,
    ).first_or_404()

    from arc.manager import get_arc
    from arc.renderer import render_arc_card

    arc_state = get_arc(character.id)
    arc_card_html = render_arc_card(arc_state, readonly=True)

    return render_template(
        "character_detail.html",
        character=character,
        arc_card_html=arc_card_html,
        arc_state=arc_state,
    )


@data_bp.route("/characters", methods=["GET"])
@login_required
def list_characters():
    records = CharacterRecord.query.filter_by(
        user_id=current_user.id,
        deleted=False,
    ).all()
    return jsonify([
        {
            "character_key": r.character_key,
            "display_name": r.display_name,
            "role": r.role,
        }
        for r in records
    ])


@data_bp.route("/characters/switch", methods=["POST"])
@login_required
def switch_character():
    data = request.get_json(silent=True) or {}
    name = data.get("character_key") or request.form.get("character_key")
    if not name:
        return jsonify({"error": "缺少 character_key"}), 400

    owned = CharacterRecord.query.filter_by(
        user_id=current_user.id, character_key=name, deleted=False
    ).first()
    if not owned:
        return jsonify({"error": "无权访问该角色"}), 403

    engine = get_user_engine(current_user.id)
    msg = engine.switch_character(name)
    return jsonify({"message": msg})


@data_bp.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    # 角色存在性校验（保留 Flask 层校验，避免无 character_id 时 404）
    engine = get_user_engine(current_user.id)
    char_rec = CharacterRecord.query.filter_by(
        user_id=current_user.id,
        character_key=engine.get_active_character(),
        deleted=False,
    ).first()
    if not char_rec:
        return jsonify({"error": "未选择角色或角色不存在"}), 400
    character_id = char_rec.id

    # 统一编排入口：Conversation + score_log + memory 全部由 orchestrator 落盘
    from orchestrator import orchestrate_turn

    try:
        result = orchestrate_turn(
            current_user.id,
            character_id,
            message,
        )
    except ValueError:
        return jsonify({"error": "角色不存在或无权访问"}), 404
    except Exception as exc:
        return jsonify({"error": f"生成回复失败: {exc}"}), 500

    response_text = result.response
    new_facts = result.new_facts
    arc_changes = result.arc_changes
    error = result.error

    return jsonify({
        "response": response_text,
        "new_facts": new_facts,
        "arc_changes": arc_changes,
        "error": error,
        "status": engine.format_status_text(),
    })


def _stream_chat_events(
    *,
    user_id: int,
    message: str,
    character_id: int | None,
    cancel_event,
):
    """内部生成器：产出 (event_type, data) 供 SSE 包装。

    重构后：对话生成 + Conversation 写入 + score_log 全部委托给
    orchestrator.orchestrate_turn_stream()，本函数只保留 Flask Web 层
    关注点（队列槽 / cancel token / performance record）。
    """
    from performance.gpu_check import current_gpu_utilization

    queue_mgr = get_request_queue()
    cfg = get_config()
    queue_len = queue_mgr.queue_length
    started = time.perf_counter()
    success = False
    slot_held = False
    token = stream_token_for_user(user_id)
    cancel_mgr = get_cancel_manager()

    if not queue_mgr.try_begin_stream():
        yield "error", {"message": cfg.BUSY_MESSAGE}
        cancel_mgr.clear(token)
        return
    slot_held = True

    # 用于在 cancel 时调用 engine.chat_ollama.cancel_ollama_request()，
    # 因此需要拿到 engine 引用（orchestrator 内部也用同一 engine）
    engine = get_user_engine(user_id)

    def _release_resources() -> None:
        """取消或结束时：释放队列槽 + 中断 Ollama 连接。"""
        nonlocal slot_held
        if slot_held:
            slot_held = False
            try:
                queue_mgr.end_stream()
            except Exception:
                pass
        try:
            engine.chat_ollama.cancel_ollama_request()
        except Exception:
            pass

    # POST /cancel → set_cancel 时立即释槽，避免频繁取消占满队列
    cancel_mgr.set_release(token, _release_resources)

    try:
        if character_id is None:
            char_rec = CharacterRecord.query.filter_by(
                user_id=user_id,
                character_key=engine.get_active_character(),
                deleted=False,
            ).first()
            if char_rec is None:
                yield "error", {"message": "角色不存在或无权访问"}
                return
            character_id = char_rec.id

        # 统一编排入口（流式版）：内部完成
        #   engine.process_message_stream → Conversation → score_log
        from orchestrator import orchestrate_turn_stream

        for event, payload in orchestrate_turn_stream(
            user_id,
            character_id,
            message,
            cancel_event=cancel_event,
            timeout_seconds=cfg.TIMEOUT_SECONDS,
        ):
            if event == "token":
                yield "message", {"token": payload}
            elif event == "cancelled":
                # payload: TurnResult
                accumulated = (
                    payload.response if isinstance(payload, TurnResult) else ""
                )
                yield "cancelled", {
                    "message": "生成已取消",
                    "response": accumulated,
                }
            elif event == "done":
                # payload: TurnResult
                yield "done", {
                    "response": payload.response,
                    "new_facts": payload.new_facts,
                    "arc_changes": payload.arc_changes,
                    "error": payload.error,
                    "status": engine.format_status_text(),
                }
                success = True
            elif event == "error":
                yield "error", {"message": str(payload)}
                return
    finally:
        # 若取消时已释放则 no-op
        cancel_mgr.release(token)
        if slot_held:
            try:
                queue_mgr.end_stream()
            except Exception:
                pass
            slot_held = False
        duration_ms = (time.perf_counter() - started) * 1000.0
        record_performance(
            user_id=user_id,
            character_id=character_id,
            duration_ms=duration_ms,
            gpu_util=current_gpu_utilization(),
            queue_length=queue_len,
            success=success,
        )
        cancel_mgr.clear(token)


@data_bp.route("/stream/chat", methods=["GET"])
@login_required
def stream_chat():
    """SSE 流式对话：参数 message、character_id（可选）。"""
    message = (request.args.get("message") or "").strip()
    if not message:
        return Response(
            sse_pack("error", {"message": "消息不能为空"}),
            mimetype="text/event-stream",
            status=400,
        )

    character_id_raw = request.args.get("character_id")
    character_id = None
    if character_id_raw:
        try:
            character_id = int(character_id_raw)
        except ValueError:
            return Response(
                sse_pack("error", {"message": "character_id 无效"}),
                mimetype="text/event-stream",
                status=400,
            )

    user_id = current_user.id
    token = stream_token_for_user(user_id)
    cancel_mgr = get_cancel_manager()
    # 新请求自动取消同一用户的旧流
    cancel_event = cancel_mgr.begin(token)

    @stream_with_context
    def _generate():
        source = _stream_chat_events(
            user_id=user_id,
            message=message,
            character_id=character_id,
            cancel_event=cancel_event,
        )
        yield from sse_generator(
            source,
            cancel_event=cancel_event,
        )

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers=headers,
    )


@data_bp.route("/cancel", methods=["POST"])
@login_required
def cancel_generation():
    """取消当前用户正在进行的生成（仅本人 session）。"""
    data = request.get_json(silent=True) or {}
    claimed = data.get("session_id") or data.get("token")
    token = stream_token_for_user(current_user.id)
    if claimed and claimed != token and claimed != str(current_user.id):
        return jsonify({"ok": False, "error": "无权取消他人生成"}), 403

    # set_cancel 会立即触发释放回调（end_stream + Ollama abort）
    ok = get_cancel_manager().set_cancel(token)

    # 额外保险：直接中断本用户引擎上的 Ollama 流
    try:
        get_user_engine(current_user.id).chat_ollama.cancel_ollama_request()
    except Exception:
        pass

    # 记录用户取消事件（部分文本评分在流结束 cancelled 分支以 method=partial 写入）
    try:
        from datetime import datetime, timezone

        log_path = os.path.join("admin_actions.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now(timezone.utc).isoformat()} | "
                f"{current_user.username} | user_cancel_generation | "
                f"target={current_user.id} | cancelled={ok}\n"
            )
    except Exception:
        pass

    return jsonify({"ok": True, "cancelled": ok})
