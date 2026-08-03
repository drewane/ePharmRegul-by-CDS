"""
Suivi des courriels sortants (administration).

Permet de vérifier ce qui a été adressé — ou, en démonstration, ce qui
l'aurait été. Sans configuration SMTP, rien n'est envoyé et cela s'affiche
clairement : personne ne doit croire à tort qu'un message est parti.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

import courriel
from auth import login_required, permission_requise
from models import CourrielSortant

bp = Blueprint("courriel", __name__, url_prefix="/administration/courriels")


@bp.route("/")
@login_required
@permission_requise("gerer_utilisateurs")
def liste():
    statut = request.args.get("statut", "").strip()
    q = CourrielSortant.query
    if statut:
        q = q.filter(CourrielSortant.statut == statut)
    messages = q.order_by(CourrielSortant.id.desc()).limit(200).all()
    compteurs = {}
    for s in ("journalise", "envoye", "echec", "en_attente", "rejoue"):
        compteurs[s] = CourrielSortant.query.filter_by(statut=s).count()
    return render_template("admin/courriels.html", messages=messages,
                           etat=courriel.etat(), compteurs=compteurs, statut=statut)


@bp.route("/rejouer", methods=["POST"])
@login_required
@permission_requise("gerer_utilisateurs")
def rejouer():
    r = courriel.rejouer_echecs()
    if not r["smtp_configure"]:
        flash("Aucun serveur de messagerie configuré : rien ne peut être réexpédié.",
              "warning")
    else:
        flash(f"{r['rejoues']} courriel(s) réexpédié(s).", "success")
    return redirect(url_for("courriel.liste"))
