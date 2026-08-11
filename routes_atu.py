"""
Autorisations temporaires d'utilisation : dépôt, instruction, suivi.

Le registre est visible de tout agent ; le dépôt est ouvert aux profils qui
peuvent légitimement demander un accès anticipé — l'industriel pour une
cohorte, mais aussi le pharmacien, qui relaie la demande d'un prescripteur.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import workflow_atu as wfa
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import AutorisationTemporaire, db

bp = Blueprint("atu", __name__, url_prefix="/atu")

# Une ATU nominative part du soignant : le pharmacien d'officine et le
# laboratoire hospitalier sont des relais légitimes, au même titre que
# l'industriel qui demande une cohorte.
PROFILS_DEPOSANTS = ("demandeur_externe", "pharmacien", "laboratoire_prive",
                     "promoteur_essai", "administrateur_dpml")


def _peut_deposer(u):
    return u is not None and u.role_systeme in PROFILS_DEPOSANTS


def _mienne(atu, u):
    """Le déposant ne voit que ses demandes ; l'administration les voit toutes."""
    from permissions import a_niveau

    if a_niveau(u, 1):
        return True
    import espace_industriel as esp
    return atu.demandeur_id in esp.personnes_de_la_societe(u)


@bp.route("/")
@login_required
def registre():
    u = current_user()
    from permissions import a_niveau

    # L'échéance passée doit se voir : sans cela une ATU expirée resterait
    # affichée « en cours » et le caractère temporaire deviendrait une fiction.
    wfa.expirer_echues()

    q = AutorisationTemporaire.query
    if not a_niveau(u, 1):
        import espace_industriel as esp
        q = q.filter(AutorisationTemporaire.demandeur_id.in_(
            esp.personnes_de_la_societe(u)))
    statut = request.args.get("statut", "").strip()
    if statut:
        q = q.filter(AutorisationTemporaire.statut == statut)

    demandes = q.order_by(AutorisationTemporaire.id.desc()).all()
    return render_template("atu/registre.html", u=u, demandes=demandes,
                           etats={a.id: wfa.etat(a) for a in demandes},
                           STATUTS=wfa.STATUTS, TYPES=wfa.TYPES, statut=statut,
                           peut_deposer=_peut_deposer(u),
                           agent=a_niveau(u, 1))


@bp.route("/nouvelle", methods=["GET", "POST"])
@login_required
def nouvelle():
    u = current_user()
    if not _peut_deposer(u):
        abort(403)
    type_atu = request.args.get("type", "nominative")
    if type_atu not in wfa.TYPES:
        type_atu = "nominative"

    if request.method == "POST":
        donnees = dict(request.form)
        donnees["engagement_amm"] = bool(request.form.get("engagement_amm"))
        try:
            atu = wfa.deposer(u, donnees)
            db.session.commit()
            flash(f"Demande d'ATU {atu.numero} déposée. Elle est instruite en "
                  "priorité — un patient est en attente.", "success")
            return redirect(url_for("atu.fiche", id=atu.id))
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("atu/nouvelle.html", u=u, type_atu=type_atu,
                           TYPES=wfa.TYPES, CONDITIONS=wfa.CONDITIONS,
                           valeurs=request.form)


@bp.route("/<int:id>")
@login_required
def fiche(id):
    u = current_user()
    atu = db.session.get(AutorisationTemporaire, id) or abort(404)
    if not _mienne(atu, u):
        abort(404)
    from permissions import a_niveau
    return render_template("atu/fiche.html", u=u, atu=atu, e=wfa.etat(atu),
                           STATUTS=wfa.STATUTS, TYPES=wfa.TYPES,
                           CONDITIONS=wfa.CONDITIONS,
                           rapports=atu.rapports(),
                           instructeur=(u.role_systeme in wfa.ROLES_INSTRUCTION),
                           agent=a_niveau(u, 1))


@bp.route("/<int:id>/action", methods=["POST"])
@login_required
def action(id):
    u = current_user()
    atu = db.session.get(AutorisationTemporaire, id) or abort(404)
    if not _mienne(atu, u):
        abort(404)
    quoi = request.form.get("action")
    try:
        if quoi == "instruire":
            wfa.prendre_en_instruction(atu, u)
            flash("Demande prise en instruction.", "success")
        elif quoi == "complement":
            wfa.demander_complement(atu, u, request.form.get("question", ""))
            flash("Complément demandé au demandeur.", "info")
        elif quoi == "accorder":
            conditions = {code: bool(request.form.get(code))
                          for code, _l in wfa.CONDITIONS}
            wfa.prononcer_decision(atu, u, True, conditions,
                                   request.form.get("duree_mois"),
                                   request.form.get("motif"))
            flash(f"ATU accordée jusqu'au "
                  f"{atu.date_echeance.strftime('%d/%m/%Y')}.", "success")
        elif quoi == "refuser":
            wfa.prononcer_decision(atu, u, False,
                                   motif=request.form.get("motif"))
            flash("ATU refusée. Le demandeur est informé.", "info")
        elif quoi == "renouveler":
            wfa.renouveler(atu, u, request.form.get("duree_mois"),
                           request.form.get("justification", ""))
            flash(f"ATU renouvelée jusqu'au "
                  f"{atu.date_echeance.strftime('%d/%m/%Y')}.", "success")
        elif quoi == "suspendre":
            wfa.suspendre(atu, u, request.form.get("motif", ""))
            flash("ATU suspendue.", "warning")
        elif quoi == "rapport":
            wfa.remettre_rapport(atu, u, request.form.get("periode", ""),
                                 request.form.get("contenu", ""),
                                 request.form.get("effets_indesirables", 0))
            flash("Rapport de suivi enregistré.", "success")
        else:
            abort(400)
        db.session.commit()
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("atu.fiche", id=atu.id))
