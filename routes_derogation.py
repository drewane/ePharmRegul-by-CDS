"""
Routes du module Dérogations spéciales, en Blueprint Flask — même convention
que routes_vl.py / routes_li.py.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, DemandeDerogation, DossierAMM
import workflow_derogation as wfd
from auth import current_user, login_required, roles_required

derogation_bp = Blueprint("derogation", __name__)

ROLES_INTERNES = ("administrateur_dpml", "directeur_dpml")


@derogation_bp.route("/derogations")
@login_required
def registre():
    u = current_user()
    q = DemandeDerogation.query
    if u.role_systeme == "demandeur_externe":
        q = q.filter_by(demandeur_id=u.id)
    elif u.role_systeme not in ROLES_INTERNES:
        abort(403)

    statut = request.args.get("statut", "")
    if statut:
        q = q.filter_by(statut=statut)
    demandes = q.order_by(DemandeDerogation.date_creation.desc()).all()
    return render_template("derogation/registre.html", demandes=demandes, statut=statut)


@derogation_bp.route("/derogations/nouvelle", methods=["GET", "POST"])
@login_required
@roles_required("demandeur_externe")
def nouvelle():
    u = current_user()
    dossiers = DossierAMM.query.filter_by(demandeur_id=u.id).order_by(DossierAMM.date_creation.desc()).all()
    if request.method == "POST":
        dossier_id = request.form.get("dossier_amm_id", type=int)
        dossier = DossierAMM.query.get(dossier_id) if dossier_id else None
        if dossier and dossier.demandeur_id != u.id:
            abort(403)
        try:
            demande = wfd.deposer(u, request.form.get("objet", ""), request.form.get("motif", ""), dossier)
            db.session.commit()
            flash(f"Demande de dérogation {demande.numero} déposée.", "success")
            return redirect(url_for("derogation.fiche", id=demande.id))
        except wfd.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
    return render_template("derogation/nouvelle.html", dossiers=dossiers)


@derogation_bp.route("/derogations/<int:id>")
@login_required
def fiche(id):
    demande = DemandeDerogation.query.get_or_404(id)
    u = current_user()
    if u.role_systeme == "demandeur_externe" and demande.demandeur_id != u.id:
        abort(403)
    elif u.role_systeme not in ("demandeur_externe",) + ROLES_INTERNES:
        abort(403)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="DemandeDerogation", entite_id=demande.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("derogation/fiche.html", d=demande, audit_events=audit_events)


@derogation_bp.route("/derogations/<int:id>/instruire", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def action_instruire(id):
    demande = DemandeDerogation.query.get_or_404(id)
    try:
        wfd.instruire(demande, current_user())
        db.session.commit()
        flash("Demande mise en instruction.", "success")
    except wfd.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("derogation.fiche", id=id))


@derogation_bp.route("/derogations/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def action_decision(id):
    demande = DemandeDerogation.query.get_or_404(id)
    try:
        wfd.decider(demande, current_user(), request.form.get("decision"), motif=request.form.get("motif", ""))
        db.session.commit()
        flash("Décision enregistrée.", "success")
    except wfd.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("derogation.fiche", id=id))
