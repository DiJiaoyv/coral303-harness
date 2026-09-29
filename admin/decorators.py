from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def admin_required(view):
    """要求已登录且 is_admin=True，否则 403。"""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped
