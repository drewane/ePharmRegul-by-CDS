"""
Routes du module LI (Licences établissements), en Blueprint Flask — même
convention que routes_vl.py / routes_ri.py.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, DemandeLicence, Etablissement, Paiement
import workflow_li as wfli
from delais import executer_verifications_delais_li
from auth import current_user, login_required, roles_required
from erreurs import ErreurWorkflow
from pieces import enregistrer_piece, lister_pieces
from paiements import (deposer_preuve, confirmer as confirmer_paiement, rejeter as rejeter_paiement,
                        lister_paiements)

li_bp = Blueprint("li", __name__)

ROLES_LI = ("administrateur_dpml", "agent_licences", "directeur_dpml")


@li_bp.route("/licences")
@login_required
def registre():
    executer_verifications_delais_li()
    u = current_user()
    q = DemandeLicence.query
    if u.role_systeme == "demandeur_externe":
        if not u.etablissement_rattachement_id:
            abort(403)
        q = q.filter_by(etablissement_id=u.etablissement_rattachement_id)
    elif u.role_systeme not in ROLES_LI:
        abort(403)

    statut = request.args.get("statut", "")
    if statut:
        q = q.filter_by(statut=statut)
    demandes = q.order_by(DemandeLicence.date_creation.desc()).all()
    return render_template("licence/registre.html", demandes=demandes, statut=statut)


@li_bp.route("/licences/deposer/<int:etablissement_id>", methods=["POST"])
@login_required
def deposer(etablissement_id):
    etab = Etablissement.query.get_or_404(etablissement_id)
    u = current_user()
    autorise = (u.role_systeme == "administrateur_dpml") or (
        u.role_systeme == "demandeur_externe" and u.etablissement_rattachement_id == etab.id
    )
    if not autorise:
        abort(403)
    try:
        demande = wfli.deposer_demande(etab, u, type_demande=request.form.get("type_demande", "nouvelle"),
                                        pieces_justificatives=request.form.get("pieces_justificatives", ""))
        db.session.commit()
        flash(f"Demande de licence {demande.numero} déposée.", "success")
        return redirect(url_for("li.fiche", id=demande.id))
    except wfli.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("ri.etablissement_fiche", id=etablissement_id))


@li_bp.route("/licences/<int:id>")
@login_required
def fiche(id):
    demande = DemandeLicence.query.get_or_404(id)
    u = current_user()
    if u.role_systeme == "demandeur_externe" and u.etablissement_rattachement_id != demande.etablissement_id:
        abort(403)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="DemandeLicence", entite_id=demande.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("licence/fiche.html", d=demande, audit_events=audit_events,
                            pieces=lister_pieces(demande), paiements=lister_paiements(demande))


@li_bp.route("/licences/<int:id>/documents", methods=["POST"])
@login_required
def televerser_document(id):
    demande = DemandeLicence.query.get_or_404(id)
    u = current_user()
    autorise = (u.role_systeme == "administrateur_dpml") or (
        u.role_systeme == "demandeur_externe" and u.etablissement_rattachement_id == demande.etablissement_id
    )
    if not autorise:
        abort(403)
    try:
        enregistrer_piece(demande, request.files.get("fichier"), request.form.get("type_document", "").strip(), u)
        db.session.commit()
        flash("Document téléversé avec succès.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("li.fiche", id=id))


@li_bp.route("/licences/<int:id>/paiements/<int:paiement_id>/preuve", methods=["POST"])
@login_required
def paiement_preuve(id, paiement_id):
    demande = DemandeLicence.query.get_or_404(id)
    paiement = Paiement.query.get_or_404(paiement_id)
    u = current_user()
    if paiement.entite_type != "DemandeLicence" or paiement.entite_id != demande.id:
        abort(404)
    autorise = (u.role_systeme == "administrateur_dpml") or (
        u.role_systeme == "demandeur_externe" and u.etablissement_rattachement_id == demande.etablissement_id
    )
    if not autorise:
        abort(403)
    try:
        deposer_preuve(paiement, request.files.get("fichier"), u)
        db.session.commit()
        flash("Preuve de paiement déposée. Elle sera vérifiée par la DPML.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("li.fiche", id=id))


@li_bp.route("/licences/<int:id>/paiements/<int:paiement_id>/confirmer", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def paiement_confirmer(id, paiement_id):
    paiement = Paiement.query.get_or_404(paiement_id)
    try:
        confirmer_paiement(paiement, current_user())
        db.session.commit()
        flash("Paiement confirmé.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("li.fiche", id=id))


@li_bp.route("/licences/<int:id>/paiements/<int:paiement_id>/rejeter", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def paiement_rejeter(id, paiement_id):
    paiement = Paiement.query.get_or_404(paiement_id)
    try:
        rejeter_paiement(paiement, current_user(), request.form.get("motif", ""))
        db.session.commit()
        flash("Preuve de paiement rejetée.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("li.fiche", id=id))


@li_bp.route("/licences/<int:id>/instruire", methods=["POST"])
@login_required
@roles_required("agent_licences")
def action_instruire(id):
    demande = DemandeLicence.query.get_or_404(id)
    try:
        wfli.instruire(demande, current_user())
        db.session.commit()
        flash("Demande mise en instruction.", "success")
    except wfli.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("li.fiche", id=id))


@li_bp.route("/licences/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def action_decision(id):
    demande = DemandeLicence.query.get_or_404(id)
    try:
        wfli.decider(demande, current_user(), request.form.get("decision"), motif=request.form.get("motif", ""))
        db.session.commit()
        flash("Décision enregistrée.", "success")
    except wfli.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("li.fiche", id=id))


@li_bp.route("/etablissements/<int:id>/suspendre", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def etablissement_suspendre(id):
    etab = Etablissement.query.get_or_404(id)
    try:
        wfli.suspendre(etab, current_user(), request.form.get("motif", ""),
                        origine_type=request.form.get("origine_type"),
                        origine_numero=request.form.get("origine_numero"))
        db.session.commit()
        flash(f"Licence de {etab.raison_sociale} suspendue.", "success")
    except wfli.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(request.referrer or url_for("ri.etablissement_fiche", id=id))


@li_bp.route("/etablissements/<int:id>/reactiver", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def etablissement_reactiver(id):
    etab = Etablissement.query.get_or_404(id)
    try:
        wfli.lever_suspension(etab, current_user())
        db.session.commit()
        flash(f"Licence de {etab.raison_sociale} réactivée.", "success")
    except wfli.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ri.etablissement_fiche", id=id))


@li_bp.route("/etablissements/<int:id>/revoquer", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def etablissement_revoquer(id):
    etab = Etablissement.query.get_or_404(id)
    try:
        wfli.revoquer(etab, current_user(), request.form.get("motif", ""))
        db.session.commit()
        flash(f"Licence de {etab.raison_sociale} révoquée.", "success")
    except wfli.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ri.etablissement_fiche", id=id))
