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


def niveau_requis(minimum):
    """Réserve une vue aux agents dont le NIVEAU DE RESPONSABILITÉ atteint le seuil.

    Complète roles_required : au lieu d'énumérer des rôles, on exprime l'exigence
    hiérarchique (2 = responsable de service, 3 = direction, 4 = administration).
    Ajouter un nouveau rôle régulateur ne demande alors aucune modification ici.
    """
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            from permissions import a_niveau
            u = current_user()
            if not u or not a_niveau(u, minimum):
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


def permission_requise(cle):
    """Réserve une vue aux titulaires d'une fonctionnalité (permissions.utilisateur_peut).

    Le décorateur est inchangé ; c'est ce qu'il résout qui change. `cle` peut
    être un code du catalogue (ex. recevabilite.decider) ou une clé historique
    encore gérée par le repli de utilisateur_peut.
    """
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            from permissions import utilisateur_peut
            if not utilisateur_peut(current_user(), cle):
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco
