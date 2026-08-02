"""
Routes du module Visas techniques, en Blueprint Flask — même convention que
routes_vl.py / routes_li.py.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, VisaTechnique, Produit, DossierAMM
import workflow_visas as wfv
from auth import current_user, login_required, roles_required

visas_bp = Blueprint("visas", __name__)


@visas_bp.route("/visas")
@login_required
def registre():
    u = current_user()
    q = VisaTechnique.query
    if u.role_systeme == "demandeur_externe":
        q = q.filter_by(demandeur_id=u.id)
    elif u.role_systeme not in ("administrateur_dpml", "directeur_dpml"):
        abort(403)

    statut = request.args.get("statut", "")
    if statut:
        q = q.filter_by(statut=statut)
    visas = q.order_by(VisaTechnique.date_creation.desc()).all()
    return render_template("visas/registre.html", visas=visas, statut=statut)


@visas_bp.route("/visas/nouvelle", methods=["GET", "POST"])
@login_required
@roles_required("demandeur_externe")
def nouvelle():
    u = current_user()
    produits = (Produit.query.join(DossierAMM, DossierAMM.produit_id == Produit.id)
                .filter(DossierAMM.demandeur_id == u.id, Produit.statut_amm_courant == "active")
                .distinct().order_by(Produit.nom_commercial).all())
    if request.method == "POST":
        produit_id = request.form.get("produit_id", type=int)
        produit = Produit.query.get(produit_id) if produit_id else None
        if not produit:
            flash("Veuillez sélectionner un produit.", "danger")
            return render_template("visas/nouvelle.html", produits=produits)
        try:
            visa = wfv.demander(u, produit, request.form.get("description", ""))
            db.session.commit()
            flash(f"Demande de visa technique {visa.numero} déposée.", "success")
            return redirect(url_for("visas.fiche", id=visa.id))
        except wfv.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
    return render_template("visas/nouvelle.html", produits=produits)


@visas_bp.route("/visas/<int:id>")
@login_required
def fiche(id):
    visa = VisaTechnique.query.get_or_404(id)
    u = current_user()
    if u.role_systeme == "demandeur_externe" and visa.demandeur_id != u.id:
        abort(403)
    elif u.role_systeme not in ("demandeur_externe", "administrateur_dpml", "directeur_dpml"):
        abort(403)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="VisaTechnique", entite_id=visa.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("visas/fiche.html", d=visa, audit_events=audit_events)


@visas_bp.route("/visas/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def action_decision(id):
    visa = VisaTechnique.query.get_or_404(id)
    try:
        wfv.decider(visa, current_user(), request.form.get("decision"), motif=request.form.get("motif", ""))
        db.session.commit()
        flash("Décision enregistrée.", "success")
    except wfv.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("visas.fiche", id=id))
