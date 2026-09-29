"""管理后台：系统配置（热生效）。"""
from __future__ import annotations

import json

from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from admin.audit_log import log_admin_action
from admin.blueprint import admin_bp
from admin.decorators import admin_required
from config_manager.backup import create_backup, list_backups, restore_backup, set_backup_pinned
from config_manager.loader import export_dict, get_config_version, load_grouped
from config_manager.registry import MASK, UNDO_WINDOW_SEC, get_item, get_max_backups, iter_items
from config_manager.writer import import_configs, save_configs, undo_last


def _version_conflict_response():
    msg = "配置已被其他管理员修改，请刷新后重试"
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": False, "message": msg, "errors": {"_version": msg}}), 409
    flash(msg, "danger")
    return redirect(url_for("admin.config_dashboard"))


@admin_bp.route("/config", methods=["GET"])
@admin_required
def config_dashboard():
    groups = load_grouped(mask_sensitive=True)
    log_admin_action("view_config")
    return render_template(
        "config_index.html",
        groups=groups,
        mask=MASK,
        undo_window_sec=UNDO_WINDOW_SEC,
        config_version=get_config_version(),
    )


@admin_bp.route("/config/save", methods=["POST"])
@admin_required
def config_save():
    """AJAX / 表单保存。"""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        updates = payload.get("updates") or payload
        version = payload.get("version")
    else:
        updates = {}
        version = request.form.get("version")
        for key, value in request.form.items():
            if key.startswith("cfg_"):
                updates[key[4:]] = value
            elif key not in ("csrf_token", "confirm", "version"):
                updates[key] = value

    ok, message, errors = save_configs(updates if isinstance(updates, dict) else {}, version=version)
    details = json.dumps(
        {"updates": {k: ("***" if v == MASK else v) for k, v in (updates or {}).items()},
         "ok": ok, "errors": errors},
        ensure_ascii=False,
    )
    log_admin_action("update_config", details=details[:2000])

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if errors and errors.get("_version"):
            return jsonify({"ok": False, "message": message, "errors": errors}), 409
        status = 200 if ok else 400
        return jsonify({"ok": ok, "message": message, "errors": errors}), status

    if errors and errors.get("_version"):
        return _version_conflict_response()

    if ok:
        flash(message or "配置已更新", "success")
    else:
        flash(message or "保存失败", "danger")
        for k, err in (errors or {}).items():
            if k != "_version":
                flash(f"{k}: {err}", "warning")
    return redirect(url_for("admin.config_dashboard"))


@admin_bp.route("/config/reset", methods=["POST"])
@admin_required
def config_reset():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys")
    version = data.get("version")

    if keys is None:
        updates = {item["key"]: item["default"] for _g, _l, item in iter_items()}
    else:
        updates = {}
        for key in keys:
            item = get_item(key)
            if item is None:
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"ok": False, "message": f"未知配置项: {key}"}), 400
                flash(f"未知配置项: {key}", "danger")
                return redirect(url_for("admin.config_dashboard"))
            updates[key] = item["default"]

    ok, message, errors = save_configs(updates, version=version)
    log_admin_action(
        "reset_config",
        details=json.dumps({"keys": keys or "ALL", "ok": ok}, ensure_ascii=False),
    )
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if errors and errors.get("_version"):
            return jsonify({"ok": False, "message": message, "errors": errors}), 409
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)
    if errors and errors.get("_version"):
        return _version_conflict_response()
    flash(message, "success" if ok else "danger")
    return redirect(url_for("admin.config_dashboard"))


@admin_bp.route("/config/undo", methods=["POST"])
@admin_required
def config_undo():
    ok, message = undo_last()
    log_admin_action("undo_config", details=message)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)
    flash(message, "success" if ok else "warning")
    return redirect(url_for("admin.config_dashboard"))


@admin_bp.route("/config/backup", methods=["GET"])
@admin_required
def config_backup_page():
    backups = list_backups()
    log_admin_action("view_config_backups")
    return render_template(
        "config_backup.html",
        backups=backups,
        max_backups=get_max_backups(),
    )


@admin_bp.route("/config/backup/create", methods=["POST"])
@admin_required
def config_backup_create():
    pinned = False
    if request.is_json:
        body = request.get_json(silent=True) or {}
        note = body.get("note") or ""
        pinned = bool(body.get("pinned"))
    else:
        note = request.form.get("note") or ""
        pinned = request.form.get("pinned") in ("1", "on", "true", "yes")
    ts = create_backup(note=note or "manual", redact=True, pinned=pinned)
    log_admin_action("create_config_backup", details=ts)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "timestamp": ts, "message": f"已创建备份 {ts}"})
    flash(f"已创建备份 {ts}", "success")
    return redirect(url_for("admin.config_backup_page"))


@admin_bp.route("/config/backup/pin/<timestamp>", methods=["POST"])
@admin_required
def config_backup_pin(timestamp: str):
    if request.is_json:
        pinned = bool((request.get_json(silent=True) or {}).get("pinned", True))
    else:
        pinned = request.form.get("pinned", "1") in ("1", "on", "true", "yes")
    ok, message = set_backup_pinned(timestamp, pinned)
    log_admin_action(
        "pin_config_backup",
        details=json.dumps({"timestamp": timestamp, "pinned": pinned, "ok": ok}),
    )
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("admin.config_backup_page"))


@admin_bp.route("/config/backup/restore/<timestamp>", methods=["POST"])
@admin_required
def config_backup_restore(timestamp: str):
    ok, message = restore_backup(timestamp)
    log_admin_action(
        "restore_config_backup",
        details=json.dumps({"timestamp": timestamp, "ok": ok, "message": message}),
    )
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("admin.config_backup_page"))


@admin_bp.route("/config/export", methods=["GET"])
@admin_required
def config_export():
    include_sensitive = request.args.get("include_sensitive", "0") in ("1", "true", "yes")
    data = export_dict(include_sensitive=include_sensitive)
    log_admin_action(
        "export_config",
        details=f"include_sensitive={include_sensitive}",
    )
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        body,
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment; filename=harness_config_export.json",
        },
    )


@admin_bp.route("/config/import", methods=["POST"])
@admin_required
def config_import():
    version = None
    payload = None
    if request.files.get("file"):
        raw = request.files["file"].read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            flash("导入文件不是有效 JSON", "danger")
            return redirect(url_for("admin.config_dashboard"))
        version = request.form.get("version")
    elif request.is_json:
        body = request.get_json(silent=True) or {}
        version = body.pop("version", None) if isinstance(body, dict) else None
        payload = body
    else:
        version = request.form.get("version")
        raw = request.form.get("json")
        if raw:
            try:
                payload = json.loads(raw)
            except Exception:
                flash("JSON 解析失败", "danger")
                return redirect(url_for("admin.config_dashboard"))

    if not isinstance(payload, dict):
        if request.is_json:
            return jsonify({"ok": False, "message": "需要 JSON 对象"}), 400
        flash("需要 JSON 对象", "danger")
        return redirect(url_for("admin.config_dashboard"))

    ok, message, errors = import_configs(payload, version=version)
    log_admin_action(
        "import_config",
        details=json.dumps({"ok": ok, "keys": list(payload.keys())[:50]}, ensure_ascii=False),
    )
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if errors and errors.get("_version"):
            return jsonify({"ok": False, "message": message, "errors": errors}), 409
        return jsonify({"ok": ok, "message": message, "errors": errors}), (200 if ok else 400)
    if errors and errors.get("_version"):
        return _version_conflict_response()
    flash(message, "success" if ok else "danger")
    for k, err in (errors or {}).items():
        if k != "_version":
            flash(f"{k}: {err}", "warning")
    return redirect(url_for("admin.config_dashboard"))
