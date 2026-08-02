"""Routes du module CT (Supervision des essais cliniques), en Blueprint Flask."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, ProtocoleEssaiClinique, Personne, Produit, Etablissement
import workflow_ct as wfct
from delais import executer_verifications_delais_ct
from auth import current_user, login_required, roles_required

ct_bp = Blueprint("ct", __name__)
ROLES_CT_INTERNES = ("administrateur_dpml", "agent_dros", "directeur_dpml")


@ct_bp.route("/protocoles")
@login_required
def registre():
    executer_verifications_delais_ct()
    u = current_user()
    q = ProtocoleEssaiClinique.query
    if u.role_systeme == "demandeur_externe":
        q = q.filter_by(promoteur_id=u.id)
    elif u.role_systeme not in ROLES_CT_INTERNES:
        abort(403)
    statut = request.args.get("statut", "")
    if statut:
        q = q.filter_by(statut=statut)
    protocoles = q.order_by(ProtocoleEssaiClinique.date_creation.desc()).all()
    return render_template("essais_cliniques/registre.html", protocoles=protocoles, statut=statut)


@ct_bp.route("/protocoles/nouveau", methods=["GET", "POST"])
@login_required
@roles_required("demandeur_externe", "administrateur_dpml")
def nouveau():
    produits = Produit.query.order_by(Produit.nom_commercial).all()
    etablissements = Etablissement.query.order_by(Etablissement.raison_sociale).all()
    if request.method == "POST":
        u = current_user()
        promoteur = u
        if u.role_systeme == "administrateur_dpml":
            promoteur_id = request.form.get("promoteur_id", type=int)
            if promoteur_id:
                promoteur = Personne.query.get(promoteur_id)
        produit = Produit.query.get(request.form.get("produit_etudie_id", type=int)) \
            if request.form.get("produit_etudie_id") else None
        sites = Etablissement.query.filter(Etablissement.id.in_(request.form.getlist("sites", type=int))).all()
        try:
            p = wfct.deposer(promoteur, request.form.get("titre", ""), produit_etudie=produit, sites=sites,
                              reference_comite_ethique=request.form.get("reference_comite_ethique", ""))
            db.session.commit()
        except wfct.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("essais_cliniques/nouveau.html", produits=produits, etablissements=etablissements,
                                    demandeurs=_liste_promoteurs())
        flash(f"Protocole {p.numero} déposé.", "success")
        return redirect(url_for("ct.fiche", id=p.id))
    return render_template("essais_cliniques/nouveau.html", produits=produits, etablissements=etablissements,
                            demandeurs=_liste_promoteurs())


def _liste_promoteurs():
    return Personne.query.filter_by(role_systeme="demandeur_externe", statut_compte="actif") \
        .order_by(Personne.nom_complet).all()


@ct_bp.route("/protocoles/<int:id>")
@login_required
def fiche(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    u = current_user()
    if u.role_systeme == "demandeur_externe" and p.promoteur_id != u.id:
        abort(403)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="ProtocoleEssaiClinique", entite_id=p.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("essais_cliniques/fiche.html", p=p, audit_events=audit_events,
                            peut_agir=wfct.peut_agir(p, u))


@ct_bp.route("/protocoles/<int:id>/avis-ethique", methods=["POST"])
@login_required
@roles_required("agent_dros", "administrateur_dpml")
def action_avis_ethique(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.mettre_a_jour_avis_ethique(p, current_user(), request.form.get("statut_avis_ethique"),
                                         reference=request.form.get("reference_comite_ethique"))
        db.session.commit()
        flash("Avis du comité d'éthique mis à jour.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/recevabilite", methods=["POST"])
@login_required
@roles_required("agent_dros")
def action_recevabilite(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.marquer_recevabilite(p, current_user(), request.form.get("decision"), request.form.get("motif", ""))
        db.session.commit()
        flash("Décision de recevabilité enregistrée.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/avis", methods=["POST"])
@login_required
@roles_required("agent_dros")
def action_avis(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.formuler_avis(p, current_user(), request.form.get("commentaire", ""))
        db.session.commit()
        flash("Avis consigné.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def action_decision(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    rapports = []
    for i in range(1, 4):
        titre = request.form.get(f"rapport_titre_{i}", "").strip()
        echeance = request.form.get(f"rapport_echeance_{i}", "").strip()
        if titre and echeance:
            rapports.append({"titre": titre, "echeance": echeance})
    try:
        wfct.decider(p, current_user(), request.form.get("decision"), motif=request.form.get("motif", ""),
                      rapports_attendus=rapports)
        db.session.commit()
        flash("Décision enregistrée.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/repondre-complement", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def action_repondre_complement(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.deposer_reponse_complement(p, current_user())
        db.session.commit()
        flash("Réponse au complément déposée.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/amendement", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def action_amendement(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.soumettre_amendement(p, current_user(), request.form.get("description", ""))
        db.session.commit()
        flash("Amendement soumis.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/amendement/decision", methods=["POST"])
@login_required
@roles_required("agent_dros", "directeur_dpml")
def action_amendement_decision(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.decider_amendement(p, current_user(), request.form.get("decision"), motif=request.form.get("motif", ""))
        db.session.commit()
        flash("Décision d'amendement enregistrée.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/rapport-etape", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def action_rapport_etape(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.deposer_rapport_etape(p, current_user(), request.form.get("titre"))
        db.session.commit()
        flash("Rapport d'étape déposé.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))


@ct_bp.route("/protocoles/<int:id>/cloturer", methods=["POST"])
@login_required
@roles_required("agent_dros", "directeur_dpml")
def action_cloturer(id):
    p = ProtocoleEssaiClinique.query.get_or_404(id)
    try:
        wfct.cloturer(p, current_user())
        db.session.commit()
        flash("Protocole clôturé.", "success")
    except wfct.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ct.fiche", id=id))
