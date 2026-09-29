import os

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from admin.forms import MemoryEditForm
from app.models.user import CharacterRecord
from memory.config import IMPORTANCE_LABELS, PER_PAGE, SOURCE_LABELS
from memory.reader import get_character_memories_by_id
from memory.search import search_memories_by_character_id
from memory.writer import (
    MemoryNotFoundError,
    MemoryValidationError,
    batch_delete_memories,
    delete_memory,
    get_raw_memory,
    update_memory,
)

_admin_templates = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "admin", "templates"
)
memory_bp = Blueprint(
    "memory",
    __name__,
    template_folder=_admin_templates,
)


def _user_characters():
    return (
        CharacterRecord.query.filter_by(
            user_id=current_user.id, deleted=False
        )
        .order_by(CharacterRecord.id)
        .all()
    )


def _query_params():
    return {
        "page": request.args.get("page", 1, type=int),
        "per_page": PER_PAGE,
        "keyword": request.args.get("q", ""),
        "importance_filter": request.args.get("importance", "") or None,
        "date_from": request.args.get("from", "") or None,
        "date_to": request.args.get("to", "") or None,
        "source": request.args.get("source", "") or None,
    }


def _filters_ctx(params, **extra):
    filters = {
        "q": params["keyword"] or "",
        "importance": params["importance_filter"] or "",
        "from": params["date_from"] or "",
        "to": params["date_to"] or "",
        "source": params.get("source") or "",
        "show_deleted": False,
    }
    filters.update(extra)
    return {"filters": filters}


def _render_memory_page(**kwargs):
    defaults = {
        "importance_labels": IMPORTANCE_LABELS,
        "source_labels": SOURCE_LABELS,
        "is_admin_view": False,
        "pagination_endpoint": "memory.memory_page",
    }
    defaults.update(kwargs)
    return render_template("memory_list.html", **defaults)


def _require_owned_character(character_id: int) -> CharacterRecord:
    char = CharacterRecord.query.filter_by(
        id=character_id, user_id=current_user.id, deleted=False
    ).first()
    if not char:
        abort(404)
    return char


@memory_bp.route("/memory")
@login_required
def memory_page():
    characters = _user_characters()
    empty_stats = {
        "total": 0,
        "high_count": 0,
        "filtered_total": 0,
        "trend_labels": [],
        "trend_values": [],
    }
    if not characters:
        return _render_memory_page(
            memories=[],
            stats=empty_stats,
            total=0,
            page=1,
            pages=0,
            characters=[],
            character_id=None,
            character_name="",
            filters={"q": "", "importance": "", "from": "", "to": "", "source": "", "show_deleted": False},
        )

    character_id = request.args.get("character_id", type=int) or characters[0].id
    _require_owned_character(character_id)

    params = _query_params()
    try:
        items, total, stats, _owner, char_name = get_character_memories_by_id(
            character_id,
            user_id=current_user.id,
            **params,
        )
    except (LookupError, PermissionError):
        abort(404)

    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return _render_memory_page(
        memories=items,
        stats=stats,
        total=total,
        page=params["page"],
        pages=pages,
        characters=characters,
        character_id=character_id,
        character_name=char_name,
        **_filters_ctx(params),
    )


@memory_bp.route("/memory/manage/<int:character_id>", methods=["GET", "POST"])
@login_required
def memory_manage(character_id: int):
    _require_owned_character(character_id)
    params = _query_params()
    operator = f"user:{current_user.username}"

    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "delete":
                delete_memory(
                    current_user.id,
                    character_id,
                    request.form.get("memory_id", ""),
                    operator=operator,
                    require_owner=True,
                )
                flash("记忆已删除", "success")
            elif action == "batch_delete":
                count = batch_delete_memories(
                    current_user.id,
                    character_id,
                    request.form.getlist("memory_ids"),
                    operator=operator,
                    require_owner=True,
                )
                flash(f"已删除 {count} 条记忆", "success")
        except (MemoryNotFoundError, MemoryValidationError) as exc:
            flash(str(exc), "danger")
        return redirect(url_for("memory.memory_manage", character_id=character_id))

    try:
        items, total, stats, _, char_name = search_memories_by_character_id(
            character_id,
            user_id=current_user.id,
            keyword=params["keyword"],
            importance=params["importance_filter"],
            date_from=params["date_from"],
            date_to=params["date_to"],
            source=params["source"],
            page=params["page"],
            per_page=params["per_page"],
            require_owner=True,
        )
    except (LookupError, PermissionError):
        abort(404)

    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template(
        "memories_list.html",
        memories=items,
        stats=stats,
        total=total,
        page=params["page"],
        pages=pages,
        characters=_user_characters(),
        character_id=character_id,
        character_name=char_name,
        is_admin_view=False,
        manage_mode=True,
        pagination_endpoint="memory.memory_manage",
        edit_endpoint="memory.memory_edit",
        list_endpoint="memory.memory_manage",
        importance_labels=IMPORTANCE_LABELS,
        source_labels=SOURCE_LABELS,
        **_filters_ctx(params),
    )


@memory_bp.route("/memory/manage/<int:character_id>/<memory_id>/edit", methods=["GET", "POST"])
@login_required
def memory_edit(character_id: int, memory_id: str):
    character = _require_owned_character(character_id)
    form = MemoryEditForm()
    operator = f"user:{current_user.username}"

    try:
        memory = get_raw_memory(
            current_user.id,
            character_id,
            memory_id,
            require_owner=True,
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
                require_owner=True,
            )
            flash("记忆已更新", "success")
            return redirect(url_for("memory.memory_manage", character_id=character_id))
        except MemoryValidationError as exc:
            flash(str(exc), "danger")

    if request.method == "GET":
        form.content.data = memory["content"]
        form.importance.data = str(memory["importance_raw"])

    return render_template(
        "memory_edit.html",
        form=form,
        memory=memory,
        character=character,
        character_id=character_id,
        is_admin_view=False,
        list_endpoint="memory.memory_manage",
    )
