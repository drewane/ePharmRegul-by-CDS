"""
Files d'attente des services : financier, homologation, commission, direction.

Orchestration seulement. Le contenu des files vient de `files_attente`, qui le
déduit lui-même de la machine à états ; les boutons viennent de la même source
que sur la fiche du dossier, et les transitions passent par la route unique
`dossier.transition`. Aucune décision métier n'est prise ici.
"""
from flask import (Blueprint, abort, jsonify, redirect, render_template,
                   request, url_for)

import files_attente as fa
from auth import current_user, login_required

bp = Blueprint("files", __name__, url_prefix="/files")


def _file_autorisee(code):
    u = current_user()
    visibles = {f["code"] for f in fa.files_visibles(u)}
    if code not in visibles:
        abort(403)
    return u, fa.FILES_PAR_CODE[code]


@bp.route("/")
@login_required
def accueil():
    """Renvoie sur la file de l'utilisateur, ou sur la synthèse s'il en voit
    plusieurs — un chef de service n'a pas à choisir entre deux files chaque
    matin quand il n'en a qu'une."""
    u = current_user()
    visibles = fa.files_visibles(u)
    if not visibles:
        abort(403)
    if len(visibles) == 1:
        return redirect(url_for("files.file", code=visibles[0]["code"]))
    return render_template("files/synthese.html", u=u,
                           synthese=fa.synthese(u),
                           SEUIL_ALERTE=fa.SEUIL_ALERTE,
                           SEUIL_ATTENTION=fa.SEUIL_ATTENTION)


@bp.route("/<code>")
@login_required
def file(code):
    u, entree = _file_autorisee(code)
    return render_template(
        "files/file.html", u=u, entree=entree,
        lignes=fa.contenu(code, u),
        autres=[f for f in fa.files_visibles(u) if f["code"] != code],
        PALIERS=fa.PALIERS)


@bp.route("/<code>/synthese.json")
@login_required
def synthese_json(code):
    """Compteurs de la file, pour le rafraîchissement sans rechargement."""
    _u, _entree = _file_autorisee(code)
    donnees = fa.compter(code)
    # Signature de l'état de la file : si elle change, la page se recharge.
    donnees["empreinte"] = "|".join(
        f"{l['dossier'].id}:{l['dossier'].statut}"
        for l in fa.contenu(code, None))
    return jsonify(donnees)
