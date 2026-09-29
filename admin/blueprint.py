"""管理后台 Flask Blueprint。"""
from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
    static_folder="static",
)

from admin.views import arc, characters, characters_create, config, dashboard, memories, memory, performance, safety, scores, soul, users  # noqa: E402, F401
