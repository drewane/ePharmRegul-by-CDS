"""
Auth partagée entre app.py (module MA + RS) et les blueprints des modules
suivants (routes_vl.py, ...). Extraite dans son propre fichier pour éviter un
import circulaire entre app.py et les blueprints de module.
"""
from functools import wraps

from flask import session, redirect, url_for, request, abort

from models import db, Personne


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(Personne, uid)


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


def roles_required(*roles):
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            u = current_user()
            if not u or u.role_systeme not in roles:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco
