"""Routes du module MC (Surveillance et contrôle du marché), en Blueprint Flask."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, SignalementQualite, Produit, RappelStatutEtablissement
import workflow_mc as wfmc
from delais import executer_verifications_delais_mc
from auth import current_user, login_required, roles_required

mc_bp = Blueprint("mc", __name__)
ROLES_MC = ("administrateur_dpml", "agent_surveillance_marche", "directeur_dpml")


@mc_bp.route("/signalements")
@login_required
@roles_required(*ROLES_MC)
def registre():
    executer_verifications_delais_mc()
    q = SignalementQualite.query
    statut = request.args.get("statut", "")
    niveau = request.args.get("niveau", "")
    if statut:
        q = q.filter_by(statut=statut)
    if niveau:
        q = q.filter_by(niveau_risque=niveau)
    signalements = q.order_by(SignalementQualite.date_creation.desc()).all()
    return render_template("marche/registre.html", signalements=signalements, statut=statut, niveau=niveau)


@mc_bp.route("/signalements/nouveau", methods=["GET", "POST"])
@login_required
def nouveau():
    produits = Produit.query.order_by(Produit.nom_commercial).all()
    if request.method == "POST":
        produit = Produit.query.get(request.form.get("produit_id", type=int))
        if not produit:
            flash("Le produit est obligatoire.", "danger")
            return render_template("marche/nouveau.html", produits=produits)
        numeros_lots = [x.strip() for x in request.form.get("numeros_lots", "").split(",") if x.strip()]
        try:
            sig = wfmc.signaler(produit, current_user(), request.form.get("description", ""),
                                 origine="titulaire_amm", numeros_lots=numeros_lots)
            db.session.commit()
        except wfmc.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("marche/nouveau.html", produits=produits)
        flash(f"Signalement {sig.numero} enregistré.", "success")
        return redirect(url_for("mc.fiche", id=sig.id))
    return render_template("marche/nouveau.html", produits=produits)


@mc_bp.route("/signalements/public", methods=["GET", "POST"])
def public():
    produits = Produit.query.order_by(Produit.nom_commercial).all()
    if request.method == "POST":
        produit = Produit.query.get(request.form.get("produit_id", type=int))
        if not produit:
            flash("Le produit est obligatoire.", "danger")
            return render_template("marche/public.html", produits=produits)
        numeros_lots = [x.strip() for x in request.form.get("numeros_lots", "").split(",") if x.strip()]
        try:
            sig = wfmc.signaler(produit, None, request.form.get("description", ""),
                                 origine="signalement_public", numeros_lots=numeros_lots)
            db.session.commit()
        except wfmc.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("marche/public.html", produits=produits)
        return render_template("marche/accuse.html", sig=sig)
    return render_template("marche/public.html", produits=produits)


@mc_bp.route("/signalements/<int:id>")
@login_required
@roles_required(*ROLES_MC)
def fiche(id):
    sig = SignalementQualite.query.get_or_404(id)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="SignalementQualite", entite_id=sig.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("marche/fiche.html", sig=sig, audit_events=audit_events,
                            peut_agir=wfmc.peut_agir(sig, current_user()))


@mc_bp.route("/signalements/<int:id>/evaluer", methods=["POST"])
@login_required
@roles_required("agent_surveillance_marche")
def action_evaluer(id):
    sig = SignalementQualite.query.get_or_404(id)
    try:
        wfmc.evaluer(sig, current_user(), request.form.get("niveau_risque"))
        db.session.commit()
        flash("Signalement évalué.", "success")
    except wfmc.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("mc.fiche", id=id))


@mc_bp.route("/signalements/<int:id>/rappel", methods=["POST"])
@login_required
@roles_required("agent_surveillance_marche", "directeur_dpml")
def action_rappel(id):
    sig = SignalementQualite.query.get_or_404(id)
    try:
        wfmc.engager_rappel(sig, current_user())
        db.session.commit()
        flash(f"Rappel engagé pour {sig.numero}.", "success")
    except wfmc.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("mc.fiche", id=id))


@mc_bp.route("/signalements/<int:id>/quarantaine", methods=["POST"])
@login_required
@roles_required("agent_surveillance_marche")
def action_quarantaine(id):
    sig = SignalementQualite.query.get_or_404(id)
    try:
        wfmc.mettre_en_quarantaine(sig, current_user())
        db.session.commit()
        flash("Lots mis en quarantaine.", "success")
    except wfmc.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("mc.fiche", id=id))


@mc_bp.route("/signalements/<int:id>/sans-suite", methods=["POST"])
@login_required
@roles_required("agent_surveillance_marche")
def action_sans_suite(id):
    sig = SignalementQualite.query.get_or_404(id)
    try:
        wfmc.classer_sans_suite(sig, current_user(), request.form.get("motif", ""))
        db.session.commit()
        flash("Signalement classé sans suite.", "success")
    except wfmc.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("mc.fiche", id=id))


@mc_bp.route("/signalements/<int:id>/cloturer", methods=["POST"])
@login_required
@roles_required("agent_surveillance_marche")
def action_cloturer(id):
    sig = SignalementQualite.query.get_or_404(id)
    try:
        wfmc.cloturer_manuellement(sig, current_user())
        db.session.commit()
        flash("Signalement clôturé.", "success")
    except wfmc.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("mc.fiche", id=id))


@mc_bp.route("/rappels/<int:id>/confirmer", methods=["POST"])
@login_required
@roles_required("agent_surveillance_marche")
def action_confirmer(id):
    rappel = RappelStatutEtablissement.query.get_or_404(id)
    try:
        wfmc.confirmer_retrait(rappel, current_user())
        db.session.commit()
        flash(f"Retrait confirmé pour {rappel.etablissement.raison_sociale}.", "success")
    except wfmc.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("mc.fiche", id=rappel.signalement_id))


@mc_bp.route("/rappels-public")
def rappels_public():
    signalements = SignalementQualite.query.filter(
        SignalementQualite.statut.in_(("rappel_engage", "notifie", "suivi", "cloture"))
    ).order_by(SignalementQualite.date_creation.desc()).all()
    return render_template("marche/rappels_public.html", signalements=signalements)


@mc_bp.route("/mitm", methods=["GET", "POST"])
@login_required
def mitm():
    u = current_user()
    if request.method == "POST":
        produit = Produit.query.get(request.form.get("produit_id", type=int))
        action = request.form.get("action")
        if action == "marquer" and u.role_systeme == "administrateur_dpml":
            produit.est_mitm = not produit.est_mitm
            db.session.commit()
        elif action == "declarer" and u.role_systeme == "demandeur_externe":
            try:
                wfmc.declarer_disponibilite_mitm(produit, u, request.form.get("disponibilite"))
                db.session.commit()
            except wfmc.ErreurWorkflow as e:
                flash(str(e), "danger")
        return redirect(url_for("mc.mitm"))
    produits = Produit.query.order_by(Produit.nom_commercial).all()
    mitm_produits = [p for p in produits if p.est_mitm]
    return render_template("marche/mitm.html", produits=produits, mitm_produits=mitm_produits)
