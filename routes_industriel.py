"""
Espace de l'industriel / titulaire d'AMM.

Tout ce qui est affiché ici est CLOISONNÉ à la société du compte connecté
(cf. espace_industriel.py) : un titulaire ne voit jamais le portefeuille d'un
concurrent.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import espace_industriel as esp
import workflow_demande_inspection as wfdi
import workflow_ma as wf
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import DemandeInspection, DossierAMM, db

bp = Blueprint("industriel", __name__, url_prefix="/industriel")

# Profils autorisés à disposer de cet espace
PROFILS = ("demandeur_externe",)


def _verifier_profil():
    u = current_user()
    if u is None or u.role_systeme not in PROFILS:
        abort(403)
    return u


def _dossier_de_ma_societe(dossier_id):
    """Garde-fou de cloisonnement : refuse l'accès à un dossier d'une autre société."""
    u = _verifier_profil()
    dossier = db.session.get(DossierAMM, dossier_id)
    if not dossier or dossier.demandeur_id not in esp.personnes_de_la_societe(u):
        abort(404)          # 404 plutôt que 403 : ne révèle pas l'existence du dossier
    return u, dossier


# ---------------------------------------------------------------------------
# Tableau de bord de la société
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def tableau_bord():
    u = _verifier_profil()
    return render_template(
        "industriel/tableau_bord.html", u=u,
        societe=u.etablissement.raison_sociale if u.etablissement else u.nom_complet,
        s=esp.synthese(u), recents=esp.dossiers_recents(u),
        a_renouveler=esp.amm_a_renouveler(u),
        demandes_inspection=esp.demandes_inspection(u)[:5],
        STATUTS=wf.STATUTS, TYPES=wf.TYPES_PROCEDURE)


@bp.route("/portefeuille")
@login_required
def portefeuille():
    """Tous les dossiers de la société, filtrables."""
    u = _verifier_profil()
    statut = request.args.get("statut", "").strip()
    type_proc = request.args.get("type", "").strip()
    q = esp.dossiers_de_la_societe(u)
    if statut:
        q = q.filter(DossierAMM.statut == statut)
    if type_proc:
        q = q.filter(DossierAMM.type_procedure == type_proc)
    return render_template(
        "industriel/portefeuille.html", u=u,
        dossiers=q.order_by(DossierAMM.date_maj.desc()).all(),
        statut=statut, type_proc=type_proc,
        STATUTS=wf.STATUTS, TYPES=wf.TYPES_PROCEDURE)


# ---------------------------------------------------------------------------
# Espace de travail : déposer une nouvelle demande
# ---------------------------------------------------------------------------
@bp.route("/nouvelle-demande")
@login_required
def nouvelle_demande():
    """Point de départ unique de toutes les démarches de l'industriel."""
    u = _verifier_profil()
    return render_template("industriel/nouvelle_demande.html", u=u,
                           amm_en_vigueur=esp.dossiers_de_la_societe(u).filter(
                               DossierAMM.statut == "approuve").all())


# ---------------------------------------------------------------------------
# Demandes d'inspection (site national ou à l'étranger)
# ---------------------------------------------------------------------------
@bp.route("/inspections", methods=["GET", "POST"])
@login_required
def inspections():
    u = _verifier_profil()
    if request.method == "POST":
        try:
            d = wfdi.deposer(
                u, request.form.get("site_nom", ""), request.form.get("site_pays", ""),
                request.form.get("motif", ""), request.form.get("site_adresse", ""),
                request.form.get("site_contact", ""),
                request.form.get("produits_concernes", ""),
                request.form.get("periode_souhaitee", ""))
            db.session.commit()
            flash(f"Demande d'inspection {d.numero} déposée. Un accusé de réception "
                  "vous a été adressé.", "success")
            return redirect(url_for("industriel.inspections"))
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("industriel/inspections.html", u=u,
                           demandes=esp.demandes_inspection(u), STATUTS=wfdi.STATUTS)


@bp.route("/inspections/<int:demande_id>")
@login_required
def detail_inspection(demande_id):
    u = _verifier_profil()
    d = db.session.get(DemandeInspection, demande_id)
    if not d or d.demandeur_id not in esp.personnes_de_la_societe(u):
        abort(404)
    return render_template("industriel/detail_inspection.html", u=u, d=d,
                           STATUTS=wfdi.STATUTS)
