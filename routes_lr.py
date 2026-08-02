"""Routes du module LR (Libération des lots), en Blueprint Flask."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, LiberationLot, Produit, Lot
import workflow_lr as wflr
from auth import current_user, login_required, roles_required

lr_bp = Blueprint("lr", __name__)
ROLES_LR = ("administrateur_dpml", "agent_laboratoire", "responsable_qualite_labo", "directeur_dpml")


@lr_bp.route("/liberations")
@login_required
@roles_required(*ROLES_LR)
def registre():
    q = LiberationLot.query
    statut = request.args.get("statut", "")
    if statut:
        q = q.filter_by(statut=statut)
    liberations = q.order_by(LiberationLot.date_reception.desc()).all()
    return render_template("liberation/registre.html", liberations=liberations, statut=statut)


@lr_bp.route("/liberations/nouveau", methods=["GET", "POST"])
@login_required
@roles_required("administrateur_dpml", "agent_laboratoire")
def nouveau():
    produits = Produit.query.filter(Produit.categorie.in_(wflr.CATEGORIES_APPLICABLES)) \
        .order_by(Produit.nom_commercial).all()
    if request.method == "POST":
        produit = Produit.query.get(request.form.get("produit_id", type=int))
        numero_lot = request.form.get("numero_lot", "").strip()
        if not produit or not numero_lot:
            flash("Le produit et le numéro de lot sont obligatoires.", "danger")
            return render_template("liberation/nouveau.html", produits=produits)
        lot = Lot.query.filter_by(produit_id=produit.id, numero_lot=numero_lot).first()
        if not lot:
            lot = Lot(produit_id=produit.id, numero_lot=numero_lot, fabricant_id=produit.fabricant_id,
                       statut="en_circulation")
            db.session.add(lot)
            db.session.flush()
        try:
            liberation = wflr.recevoir_dossier_lot(produit, lot, current_user(),
                                                    dossier_fabricant=request.form.get("dossier_fabricant", ""))
            db.session.commit()
        except wflr.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("liberation/nouveau.html", produits=produits)
        flash(f"Dossier de lot {liberation.numero} enregistré.", "success")
        return redirect(url_for("lr.fiche", id=liberation.id))
    return render_template("liberation/nouveau.html", produits=produits)


@lr_bp.route("/liberations/<int:id>")
@login_required
@roles_required(*ROLES_LR)
def fiche(id):
    liberation = LiberationLot.query.get_or_404(id)
    from models import EvenementAudit, NotificationVigilance
    audit_events = EvenementAudit.query.filter_by(entite_type="LiberationLot", entite_id=liberation.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    vigilance_recente = NotificationVigilance.query.filter_by(produit_id=liberation.produit_id) \
        .order_by(NotificationVigilance.date_notification.desc()).limit(5).all()
    return render_template("liberation/fiche.html", l=liberation, audit_events=audit_events,
                            peut_agir=wflr.peut_agir(liberation, current_user()), vigilance_recente=vigilance_recente)


@lr_bp.route("/liberations/<int:id>/controle-documentaire", methods=["POST"])
@login_required
@roles_required("agent_laboratoire", "administrateur_dpml")
def action_controle_documentaire(id):
    liberation = LiberationLot.query.get_or_404(id)
    try:
        wflr.controler_documentaire(liberation, current_user(), request.form.get("decision"),
                                     motif=request.form.get("motif", ""))
        db.session.commit()
        flash("Décision de contrôle documentaire enregistrée.", "success")
    except wflr.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lr.fiche", id=id))


@lr_bp.route("/liberations/<int:id>/controle-laboratoire", methods=["POST"])
@login_required
@roles_required("agent_laboratoire", "administrateur_dpml")
def action_controle_laboratoire(id):
    liberation = LiberationLot.query.get_or_404(id)
    try:
        wflr.lancer_controle_laboratoire(liberation, current_user())
        db.session.commit()
        flash("Contrôle de laboratoire lancé.", "success")
    except wflr.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lr.fiche", id=id))


@lr_bp.route("/liberations/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def action_decision(id):
    liberation = LiberationLot.query.get_or_404(id)
    try:
        wflr.decider_liberation(liberation, current_user(), request.form.get("decision"),
                                 motif=request.form.get("motif", ""),
                                 deja_distribue=bool(request.form.get("deja_distribue")))
        db.session.commit()
        flash("Décision de libération enregistrée.", "success")
    except wflr.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lr.fiche", id=id))


@lr_bp.route("/pev")
@login_required
@roles_required(*ROLES_LR)
def pev():
    liberations = LiberationLot.query.filter_by(statut="libere").order_by(LiberationLot.date_liberation.desc()).all()
    return render_template("liberation/pev.html", liberations=liberations)
