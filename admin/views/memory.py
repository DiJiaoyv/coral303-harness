from flask import abort, redirect, render_template, request, url_for

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from app.models.user import CharacterRecord
from extensions import db
from memory.config import IMPORTANCE_LABELS, PER_PAGE, SOURCE_LABELS
from memory.reader import get_character_memories_by_id


def _query_params():
    return {
        "page": request.args.get("page", 1, type=int),
        "per_page": PER_PAGE,
        "keyword": request.args.get("q", ""),
        "importance_filter": request.args.get("importance", "") or None,
        "date_from": request.args.get("from", "") or None,
        "date_to": request.args.get("to", "") or None,
    }


@admin_bp.route("/memory")
@admin_required
def memory_index():
    characters = (
        CharacterRecord.query.filter_by(deleted=False)
        .order_by(CharacterRecord.id)
        .all()
    )
    if not characters:
        return render_template(
            "memory_list.html",
            memories=[],
            stats={"total": 0, "high_count": 0, "filtered_total": 0, "trend_labels": [], "trend_values": []},
            total=0,
            page=1,
            pages=0,
            characters=[],
            character_id=None,
            character_name="",
            is_admin_view=True,
            pagination_endpoint="admin.memory_view",
            importance_labels=IMPORTANCE_LABELS,
            source_labels=SOURCE_LABELS,
            filters={"q": "", "importance": "", "from": "", "to": ""},
        )
    first_id = characters[0].id
    return redirect(url_for("admin.memory_view", character_id=first_id))


@admin_bp.route("/memory/<int:character_id>")
@admin_required
def memory_view(character_id: int):
    params = _query_params()
    try:
        items, total, stats, owner_id, char_name = get_character_memories_by_id(
            character_id, **params
        )
    except LookupError:
        abort(404)
    except PermissionError:
        abort(403)

    characters = (
        CharacterRecord.query.filter_by(deleted=False)
        .order_by(CharacterRecord.id)
        .all()
    )
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    log_admin_action("view_memory", character_id, f"user_id={owner_id}")

    return render_template(
        "memory_list.html",
        memories=items,
        stats=stats,
        total=total,
        page=params["page"],
        pages=pages,
        characters=characters,
        character_id=character_id,
        character_name=char_name,
        is_admin_view=True,
        pagination_endpoint="admin.memory_view",
        importance_labels=IMPORTANCE_LABELS,
        source_labels=SOURCE_LABELS,
        filters={
            "q": params["keyword"] or "",
            "importance": params["importance_filter"] or "",
            "from": params["date_from"] or "",
            "to": params["date_to"] or "",
        },
    )
