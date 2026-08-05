"""
Instruction des dossiers : recevabilité, évaluation interne, commissions.

Orchestration uniquement — la logique métier vit dans workflow_instruction.py.
"""
from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import workflow_instruction as wfi
import workflow_ma as wf
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import (AssignationEvaluation, AvisCommission, DossierAMM,
                    DossierSession, Personne, SessionCommission, db)

bp = Blueprint("instruction", __name__, url_prefix="/instruction")

# Hiérarchie MIRA : la recevabilité administrative et l'attribution relèvent du
# chef de bureau ; l'arbitrage technique, la commission et le rapport relèvent
# du chef de service.
ROLES_BUREAU = ("chef_bureau", "chef_service_amm", "administrateur_dpml")
ROLES_CHEF = ("chef_service_amm", "administrateur_dpml")


def _bureau():
    """Recevabilité et attribution — chef de bureau."""
    u = current_user()
    if u is None or u.role_systeme not in ROLES_BUREAU:
        abort(403)
    return u


def _chef():
    """Arbitrage technique, commission, rapport — chef de service."""
    u = current_user()
    if u is None or u.role_systeme not in ROLES_CHEF:
        abort(403)
    return u


# ---------------------------------------------------------------------------
# Bureau du chef de service
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def bureau():
    u = _bureau()
    a_examiner = DossierAMM.query.filter_by(statut="soumis").all()
    en_evaluation = DossierAMM.query.filter_by(statut="evaluation_en_cours").all()
    return render_template(
        "instruction/bureau.html", u=u, a_examiner=a_examiner,
        en_evaluation=[(d, wfi.etat_instruction(d)) for d in en_evaluation],
        seances=SessionCommission.query.order_by(
            SessionCommission.id.desc()).limit(10).all(),
        STATUTS=wf.STATUTS)


# ---------------------------------------------------------------------------
# Recevabilité — liste de contrôle
# ---------------------------------------------------------------------------
@bp.route("/dossiers/<int:dossier_id>", methods=["GET", "POST"])
@login_required
def dossier(dossier_id):
    u = _bureau()
    d = db.session.get(DossierAMM, dossier_id) or abort(404)

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "checklist":
                wfi.enregistrer_checklist(d, u, request.form)
                flash("Liste de contrôle enregistrée.", "success")
            elif action == "recevable":
                wfi.enregistrer_checklist(d, u, request.form)
                wfi.prononcer_recevabilite(d, u, True)
                flash("Dossier déclaré recevable — le déposant a été informé.", "success")
            elif action == "irrecevable":
                wfi.prononcer_recevabilite(d, u, False, request.form.get("motif"))
                flash("Dossier déclaré irrecevable.", "info")
            elif action == "assigner":
                ev = db.session.get(Personne, int(request.form.get("evaluateur_id", 0)))
                if ev is None:
                    raise ErreurWorkflow("Évaluateur introuvable.")
                wfi.assigner(d, ev, u, request.form.get("consigne"))
                flash(f"Dossier confié à {ev.nom_complet}.", "success")
            elif action == "rapport":
                _chef()          # le rapport engage le chef de service
                wfi.rediger_rapport(d, u, request.form.get("avis_propose", ""),
                                    request.form.get("synthese"),
                                    request.form.get("motif"))
                flash("Rapport transmis — le circuit de signature est ouvert.", "success")
            db.session.commit()
        except (ErreurWorkflow, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("instruction.dossier", dossier_id=d.id))

    return render_template(
        "instruction/dossier.html", u=u, d=d, etat=wfi.etat_instruction(d),
        checklist=wfi.CHECKLIST_RECEVABILITE, coches=d.checklist_recevabilite or {},
        POINTS_ATTESTES=wfi.POINTS_ATTESTES,
        evaluateurs=wfi.evaluateurs_disponibles(), AVIS=wfi.AVIS,
        seances_ouvertes=SessionCommission.query.filter(
            SessionCommission.statut != "close").all(),
        STATUTS=wf.STATUTS)


# ---------------------------------------------------------------------------
# Espace de l'évaluateur interne
# ---------------------------------------------------------------------------
@bp.route("/mes-evaluations")
@login_required
def mes_evaluations():
    u = current_user()
    if u.role_systeme != "evaluateur_interne":
        abort(403)
    return render_template(
        "instruction/mes_evaluations.html", u=u,
        assignations=AssignationEvaluation.query.filter_by(evaluateur_id=u.id)
        .order_by(AssignationEvaluation.id.desc()).all(), AVIS=wfi.AVIS)


@bp.route("/assignations/<int:assignation_id>", methods=["GET", "POST"])
@login_required
def assignation(assignation_id):
    u = current_user()
    a = db.session.get(AssignationEvaluation, assignation_id) or abort(404)
    if a.evaluateur_id != u.id and u.role_systeme not in ROLES_CHEF:
        abort(403)

    if request.method == "POST":
        try:
            wfi.remettre_evaluation(a, u, request.form.get("rapport", ""),
                                    request.form.get("conclusion", ""))
            db.session.commit()
            flash("Évaluation remise au chef de service.", "success")
            return redirect(url_for("instruction.mes_evaluations"))
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("instruction/assignation.html", u=u, a=a, AVIS=wfi.AVIS)


# ---------------------------------------------------------------------------
# Commissions
# ---------------------------------------------------------------------------
@bp.route("/commissions", methods=["GET", "POST"])
@login_required
def commissions():
    u = current_user()
    if request.method == "POST":
        _chef()
        try:
            date_seance = None
            if request.form.get("date_seance"):
                date_seance = datetime.strptime(request.form["date_seance"], "%Y-%m-%d")
            wfi.convoquer_commission(u, request.form.get("intitule", ""),
                                     request.form.get("type_commission", "specialisee"),
                                     date_seance, request.form.get("lieu"))
            db.session.commit()
            flash("Commission convoquée — les membres ont été prévenus.", "success")
        except (ErreurWorkflow, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("instruction.commissions"))

    toutes = SessionCommission.query.order_by(SessionCommission.id.desc()).all()
    # Un membre ne voit que les séances de sa propre commission.
    if u.role_systeme in ("membre_commission_specialisee", "membre_commission_nationale"):
        toutes = [s for s in toutes if s.role_membre == u.role_systeme]
    elif u.role_systeme not in ROLES_CHEF:
        abort(403)
    return render_template("instruction/commissions.html", u=u, seances=toutes,
                           est_chef=u.role_systeme in ROLES_CHEF)


@bp.route("/commissions/<int:session_id>", methods=["GET", "POST"])
@login_required
def seance(session_id):
    u = current_user()
    s = db.session.get(SessionCommission, session_id) or abort(404)
    est_chef = u.role_systeme in ROLES_CHEF
    est_membre = u.role_systeme == s.role_membre
    if not (est_chef or est_membre):
        abort(403)

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "inscrire":
                _chef()
                d = db.session.get(DossierAMM, int(request.form.get("dossier_id", 0)))
                if d is None:
                    raise ErreurWorkflow("Dossier introuvable.")
                wfi.inscrire_dossier(s, d, u)
                flash(f"Dossier {d.numero} inscrit à l'ordre du jour.", "success")
            elif action == "clore":
                _chef()
                wfi.clore_seance(s, u)
                flash("Séance close — les avis ont été synthétisés.", "success")
            db.session.commit()
        except (ErreurWorkflow, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("instruction.seance", session_id=s.id))

    # Avis déjà saisis par ce membre, pour pré-remplir la grille
    mes_avis = {}
    if est_membre:
        for ds in s.inscriptions:
            a = AvisCommission.query.filter_by(dossier_session_id=ds.id,
                                               membre_id=u.id).first()
            if a:
                mes_avis[ds.id] = a
    return render_template(
        "instruction/seance.html", u=u, s=s, est_chef=est_chef, est_membre=est_membre,
        grille=wfi.GRILLE_COMMISSION, AVIS=wfi.AVIS, mes_avis=mes_avis,
        disponibles=DossierAMM.query.filter_by(statut="evaluation_en_cours").all())


@bp.route("/seances/<int:ds_id>/avis", methods=["POST"])
@login_required
def saisir_avis(ds_id):
    """Saisie de l'avis d'un membre — pensée pour un usage sur tablette en séance."""
    u = current_user()
    ds = db.session.get(DossierSession, ds_id) or abort(404)
    reponses = {code: request.form.get(f"q_{code}", "")
                for code, _libelle in wfi.GRILLE_COMMISSION}
    try:
        wfi.saisir_avis(ds, u, reponses, request.form.get("avis", ""),
                        request.form.get("motif"))
        db.session.commit()
        flash("Votre avis a été enregistré.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("instruction.seance", session_id=ds.session_id))
