"""
Routes du module VL (Pharmacovigilance), en Blueprint Flask — premier module à
suivre ce découpage (cf. README.md : app.py reste en un seul fichier pour MA/RS,
mais tout module supplémentaire est un blueprint séparé, enregistré dans app.py).
Orchestration uniquement ; la logique métier vit dans workflow_vl.py.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, NotificationVigilance, Produit
import workflow_vl as wfvl
from delais import executer_verifications_delais_vl, cas_vigilance_en_retard
from auth import current_user, login_required, roles_required

vl_bp = Blueprint("vl", __name__, url_prefix="/vigilance")

ROLES_VL = ("administrateur_dpml", "agent_vigilance", "directeur_dpml")


# ---------------------------------------------------------------------------
# Formulaire public de notification — aucune authentification requise
# (critère d'acceptation VL : un notificateur externe peut créer un cas sans
# compte utilisateur et reçoit un numéro de suivi).
# ---------------------------------------------------------------------------
@vl_bp.route("/notifier", methods=["GET", "POST"])
def notifier():
    produits = Produit.query.order_by(Produit.nom_commercial).all()
    if request.method == "POST":
        donnees = {
            "description_effet": request.form.get("description_effet", ""),
            "gravite": request.form.get("gravite"),
            "source": request.form.get("source"),
            "produit_id": request.form.get("produit_id", type=int),
            "numero_lot": request.form.get("numero_lot", ""),
            "patient_age": request.form.get("patient_age", type=int),
            "patient_sexe": request.form.get("patient_sexe", ""),
            "notificateur_nom": request.form.get("notificateur_nom", ""),
            "notificateur_contact": request.form.get("notificateur_contact", ""),
        }
        acteur = current_user()  # un agent DPML peut aussi saisir un cas pour un tiers
        try:
            cas = wfvl.creer_notification(donnees, acteur)
            db.session.commit()
        except wfvl.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("vigilance/notifier.html", produits=produits)
        return render_template("vigilance/accuse.html", cas=cas)
    return render_template("vigilance/notifier.html", produits=produits)


# ---------------------------------------------------------------------------
# Registre et fiche de cas — usage interne
# ---------------------------------------------------------------------------
@vl_bp.route("/cas")
@login_required
@roles_required(*ROLES_VL)
def registre():
    executer_verifications_delais_vl()
    q = NotificationVigilance.query
    statut = request.args.get("statut", "")
    gravite = request.args.get("gravite", "")
    produit_id = request.args.get("produit_id", type=int)
    if statut:
        q = q.filter_by(statut=statut)
    if gravite:
        q = q.filter_by(gravite=gravite)
    if produit_id:
        q = q.filter_by(produit_id=produit_id)
    cas_liste = q.order_by(NotificationVigilance.date_notification.desc()).all()
    return render_template("vigilance/registre.html", cas_liste=cas_liste, statut=statut, gravite=gravite,
                            produit_id=produit_id, produits=Produit.query.order_by(Produit.nom_commercial).all(),
                            en_retard=cas_vigilance_en_retard)


@vl_bp.route("/cas/<int:id>")
@login_required
@roles_required(*ROLES_VL)
def fiche(id):
    cas = NotificationVigilance.query.get_or_404(id)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="NotificationVigilance", entite_id=cas.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("vigilance/fiche.html", cas=cas, audit_events=audit_events,
                            peut_agir=wfvl.peut_agir(cas, current_user()),
                            produits=Produit.query.order_by(Produit.nom_commercial).all())


@vl_bp.route("/cas/<int:id>/prendre-en-charge", methods=["POST"])
@login_required
@roles_required("agent_vigilance")
def action_prendre_en_charge(id):
    cas = NotificationVigilance.query.get_or_404(id)
    try:
        wfvl.prendre_en_charge(cas, current_user())
        db.session.commit()
        flash("Cas pris en charge.", "success")
    except wfvl.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("vl.fiche", id=id))


@vl_bp.route("/cas/<int:id>/modifier", methods=["POST"])
@login_required
@roles_required("agent_vigilance")
def action_modifier(id):
    cas = NotificationVigilance.query.get_or_404(id)
    try:
        wfvl.modifier_cas(cas, current_user(), {
            "produit_id": request.form.get("produit_id", type=int),
            "numero_lot": request.form.get("numero_lot", ""),
            "description_effet": request.form.get("description_effet", ""),
            "gravite": request.form.get("gravite", ""),
            "evaluation_causalite": request.form.get("evaluation_causalite", ""),
        })
        db.session.commit()
        flash("Cas mis à jour.", "success")
    except wfvl.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("vl.fiche", id=id))


@vl_bp.route("/cas/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("agent_vigilance")
def action_decision(id):
    cas = NotificationVigilance.query.get_or_404(id)
    try:
        wfvl.decider_suivi(cas, current_user(), request.form.get("decision"), request.form.get("commentaire", ""))
        db.session.commit()
        flash("Décision de suivi enregistrée.", "success")
    except wfvl.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("vl.fiche", id=id))


@vl_bp.route("/cas/<int:id>/arbitrage", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def action_arbitrage(id):
    cas = NotificationVigilance.query.get_or_404(id)
    try:
        wfvl.arbitrer_signal(cas, current_user(), request.form.get("decision"),
                              motif=request.form.get("motif", ""), type_mesure=request.form.get("type_mesure"))
        db.session.commit()
        flash("Arbitrage enregistré.", "success")
    except wfvl.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("vl.fiche", id=id))


@vl_bp.route("/cas/<int:id>/cloturer-mesure", methods=["POST"])
@login_required
@roles_required("agent_vigilance")
def action_cloturer_mesure(id):
    cas = NotificationVigilance.query.get_or_404(id)
    try:
        wfvl.cloturer_mesure(cas, current_user())
        db.session.commit()
        flash("Cas clôturé.", "success")
    except wfvl.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("vl.fiche", id=id))


@vl_bp.route("/cas/<int:id>/transmettre", methods=["POST"])
@login_required
@roles_required("agent_vigilance", "administrateur_dpml")
def action_transmettre(id):
    cas = NotificationVigilance.query.get_or_404(id)
    try:
        wfvl.transmettre_vigiflow(cas, current_user())
        db.session.commit()
        flash(f"Cas transmis à VigiFlow (référence {cas.reference_e2b}).", "success")
    except wfvl.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("vl.fiche", id=id))


# ---------------------------------------------------------------------------
# Tableau de signaux — regroupement des cas par produit (simplification assumée,
# documentée dans README : le regroupement par "type d'effet" en texte libre
# n'est pas fiabilisé dans ce périmètre, le regroupement se fait par produit).
# ---------------------------------------------------------------------------
@vl_bp.route("/signaux")
@login_required
@roles_required(*ROLES_VL)
def signaux():
    produits_avec_cas = db.session.query(NotificationVigilance.produit_id, db.func.count(NotificationVigilance.id)) \
        .filter(NotificationVigilance.produit_id.isnot(None)) \
        .group_by(NotificationVigilance.produit_id).having(db.func.count(NotificationVigilance.id) >= 1).all()
    groupes = []
    for produit_id, total in produits_avec_cas:
        produit = Produit.query.get(produit_id)
        cas_produit = NotificationVigilance.query.filter_by(produit_id=produit_id) \
            .order_by(NotificationVigilance.date_notification.desc()).all()
        groupes.append({"produit": produit, "total": total, "cas": cas_produit,
                         "graves": sum(1 for c in cas_produit if c.gravite in ("grave", "fatal"))})
    groupes.sort(key=lambda g: g["total"], reverse=True)
    return render_template("vigilance/signaux.html", groupes=groupes)
