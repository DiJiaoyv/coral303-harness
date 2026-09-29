"""管理后台记忆读写管理。"""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from admin.forms import MemoryEditForm
from app.models.user import CharacterRecord
from extensions import db
from memory.config import IMPORTANCE_LABELS, PER_PAGE, SOURCE_LABELS
from memory.search import search_memories_by_character_id
from memory.writer import (
    MemoryNotFoundError,
    MemoryValidationError,
    batch_delete_memories,
    delete_memory,
    get_raw_memory,
    restore_memory,
    update_memory,
)


def _query_params():
    return {
        "page": request.args.get("page", 1, type=int),
        "per_page": PER_PAGE,
        "keyword": request.args.get("q", ""),
        "importance": request.args.get("importance", "") or None,
        "date_from": request.args.get("from", "") or None,
        "date_to": request.args.get("to", "") or None,
        "source": request.args.get("source", "") or None,
        "show_deleted": request.args.get("show_deleted", "") == "1",
    }


def _list_context(character_id: int, params: dict) -> dict:
    try:
        items, total, stats, owner_id, char_name = search_memories_by_character_id(
            character_id,
            keyword=params["keyword"],
            importance=params["importance"],
            date_from=params["date_from"],
            date_to=params["date_to"],
            source=params["source"],
            page=params["page"],
            per_page=params["per_page"],
            include_deleted=params["show_deleted"],
        )
    except LookupError:
        abort(404)

    characters = (
        CharacterRecord.query.filter_by(deleted=False)
        .order_by(CharacterRecord.id)
        .all()
    )
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    return {
        "memories": items,
        "stats": stats,
        "total": total,
        "page": params["page"],
        "pages": pages,
        "characters": characters,
        "character_id": character_id,
        "character_name": char_name,
        "is_admin_view": True,
        "manage_mode": True,
        "pagination_endpoint": "admin.memories_list",
        "edit_endpoint": "admin.memory_edit",
        "list_endpoint": "admin.memories_list",
        "importance_labels": IMPORTANCE_LABELS,
        "source_labels": SOURCE_LABELS,
        "filters": {
            "q": params["keyword"] or "",
            "importance": params["importance"] or "",
            "from": params["date_from"] or "",
            "to": params["date_to"] or "",
            "source": params["source"] or "",
            "show_deleted": params["show_deleted"],
        },
    }


@admin_bp.route("/memories")
@admin_required
def memories_index():
    characters = (
        CharacterRecord.query.filter_by(deleted=False)
        .order_by(CharacterRecord.id)
        .all()
    )
    if not characters:
        abort(404, "暂无角色")
    return redirect(url_for("admin.memories_list", character_id=characters[0].id))


@admin_bp.route("/memories/<int:character_id>", methods=["GET", "POST"])
@admin_required
def memories_list(character_id: int):
    params = _query_params()
    operator = f"admin:{current_user.username}"

    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "delete":
                memory_id = request.form.get("memory_id", "")
                delete_memory(
                    current_user.id,
                    character_id,
                    memory_id,
                    operator=operator,
                    require_owner=False,
                )
                flash("记忆已软删除", "success")
                log_admin_action("memory_delete", character_id, memory_id)

            elif action == "restore":
                memory_id = request.form.get("memory_id", "")
                restore_memory(
                    current_user.id,
                    character_id,
                    memory_id,
                    operator=operator,
                    require_owner=False,
                )
                flash("记忆已恢复", "success")
                log_admin_action("memory_restore", character_id, memory_id)

            elif action == "batch_delete":
                ids = request.form.getlist("memory_ids")
                count = batch_delete_memories(
                    current_user.id,
                    character_id,
                    ids,
                    operator=operator,
                    require_owner=False,
                )
                flash(f"已软删除 {count} 条记忆", "success")
                log_admin_action("memory_batch_delete", character_id, f"count={count}")

        except (MemoryNotFoundError, MemoryValidationError) as exc:
            flash(str(exc), "danger")

        return redirect(
            url_for(
                "admin.memories_list",
                character_id=character_id,
                page=params["page"],
                q=params["keyword"],
                importance=params["importance"],
                **{"from": params["date_from"], "to": params["date_to"]},
                source=params["source"],
            )
        )

    ctx = _list_context(character_id, params)
    log_admin_action("view_memories_manage", character_id)
    return render_template("memories_list.html", **ctx)


@admin_bp.route(
    "/memories/<int:character_id>/<memory_id>/edit",
    methods=["GET", "POST"],
)
@admin_required
def memory_edit(character_id: int, memory_id: str):
    form = MemoryEditForm()
    operator = f"admin:{current_user.username}"

    try:
        memory = get_raw_memory(
            current_user.id,
            character_id,
            memory_id,
            require_owner=False,
        )
    except MemoryNotFoundError:
        abort(404)

    if form.validate_on_submit():
        try:
            update_memory(
                current_user.id,
                character_id,
                memory_id,
                content=form.content.data,
                importance=int(form.importance.data),
                operator=operator,
                require_owner=False,
            )
            flash("记忆已更新", "success")
            log_admin_action("memory_edit", character_id, memory_id)
            return redirect(url_for("admin.memories_list", character_id=character_id))
        except MemoryValidationError as exc:
            flash(str(exc), "danger")

    if request.method == "GET":
        form.content.data = memory["content"]
        form.importance.data = str(memory["importance_raw"])

    character = CharacterRecord.query.get(character_id)
    return render_template(
        "memory_edit.html",
        form=form,
        memory=memory,
        character=character,
        character_id=character_id,
        is_admin_view=True,
        list_endpoint="admin.memories_list",
    )
