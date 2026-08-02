"""
Routes du module RI (Inspection réglementaire), en Blueprint Flask — même
convention que routes_vl.py. Comprend aussi le registre/fiche Établissement
(entité du socle commun, mais sans écran dédié avant ce module).
"""
from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify

from models import db, Inspection, Etablissement, Personne, DemandeLicence
import workflow_ri as wfri
from delais import executer_verifications_delais_ri, plan_action_en_retard
from auth import current_user, login_required, roles_required

ri_bp = Blueprint("ri", __name__)

ROLES_RI = ("administrateur_dpml", "inspecteur_igspl", "directeur_dpml")


# ---------------------------------------------------------------------------
# Back-office : registre, planification, fiche, suivi des plans d'action
# ---------------------------------------------------------------------------
@ri_bp.route("/inspections")
@login_required
@roles_required(*ROLES_RI)
def registre():
    executer_verifications_delais_ri()
    q = Inspection.query
    statut = request.args.get("statut", "")
    type_insp = request.args.get("type", "")
    if statut:
        q = q.filter_by(statut=statut)
    if type_insp:
        q = q.filter_by(type=type_insp)
    inspections = q.order_by(Inspection.date_creation.desc()).all()
    return render_template("inspection/registre.html", inspections=inspections, statut=statut, type_insp=type_insp)


@ri_bp.route("/inspections/planifier", methods=["GET", "POST"])
@login_required
@roles_required("administrateur_dpml")
def planifier():
    etablissements = Etablissement.query.order_by(Etablissement.raison_sociale).all()
    inspecteurs = Personne.query.filter_by(role_systeme="inspecteur_igspl", statut_compte="actif") \
        .order_by(Personne.nom_complet).all()
    if request.method == "POST":
        etablissement = Etablissement.query.get(request.form.get("etablissement_id", type=int))
        inspecteur = Personne.query.get(request.form.get("inspecteur_id", type=int))
        date_planifiee = request.form.get("date_planifiee")
        try:
            date_planifiee = datetime.strptime(date_planifiee, "%Y-%m-%d").date() if date_planifiee else None
            insp = wfri.planifier(etablissement, inspecteur, current_user(),
                                   type_insp=request.form.get("type", "routine"), date_planifiee=date_planifiee)
            db.session.commit()
        except (wfri.ErreurWorkflow, AttributeError, ValueError) as e:
            db.session.rollback()
            flash(str(e) if isinstance(e, wfri.ErreurWorkflow) else "Établissement et inspecteur sont obligatoires.",
                  "danger")
            return render_template("inspection/planifier.html", etablissements=etablissements, inspecteurs=inspecteurs)
        flash(f"Inspection {insp.numero} planifiée.", "success")
        return redirect(url_for("ri.fiche", id=insp.id))
    return render_template("inspection/planifier.html", etablissements=etablissements, inspecteurs=inspecteurs)


@ri_bp.route("/inspections/<int:id>")
@login_required
@roles_required(*ROLES_RI)
def fiche(id):
    insp = Inspection.query.get_or_404(id)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="Inspection", entite_id=insp.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    inspecteurs = Personne.query.filter_by(role_systeme="inspecteur_igspl", statut_compte="actif") \
        .order_by(Personne.nom_complet).all()
    return render_template("inspection/fiche.html", insp=insp, audit_events=audit_events,
                            peut_agir=wfri.peut_agir(insp, current_user()), inspecteurs=inspecteurs,
                            en_retard=plan_action_en_retard(insp))


@ri_bp.route("/inspections/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("inspecteur_igspl", "administrateur_dpml")
def action_decision(id):
    insp = Inspection.query.get_or_404(id)
    try:
        wfri.decider_conformite(insp, current_user(), request.form.get("decision"),
                                 non_conforme_grave=bool(request.form.get("non_conforme_grave")))
        db.session.commit()
        flash("Décision de conformité enregistrée.", "success")
    except wfri.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ri.fiche", id=id))


@ri_bp.route("/inspections/<int:id>/plan-action", methods=["POST"])
@login_required
@roles_required("inspecteur_igspl", "administrateur_dpml")
def action_plan_action(id):
    insp = Inspection.query.get_or_404(id)
    date_echeance = request.form.get("date_echeance")
    try:
        date_echeance = datetime.strptime(date_echeance, "%Y-%m-%d").date() if date_echeance else None
        wfri.soumettre_plan_action(insp, current_user(), request.form.get("plan_action", ""), date_echeance)
        db.session.commit()
        flash("Plan d'action correctif enregistré.", "success")
    except wfri.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ri.fiche", id=id))


@ri_bp.route("/inspections/<int:id>/cloturer-plan-action", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def action_cloturer_plan_action(id):
    insp = Inspection.query.get_or_404(id)
    try:
        wfri.cloturer_plan_action(insp, current_user())
        db.session.commit()
        flash("Inspection clôturée.", "success")
    except wfri.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("ri.fiche", id=id))


@ri_bp.route("/inspections/<int:id>/suivi", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def action_suivi(id):
    insp = Inspection.query.get_or_404(id)
    inspecteur = Personne.query.get(request.form.get("inspecteur_id", type=int))
    try:
        nouvelle = wfri.initier_suivi(insp, current_user(), inspecteur)
        db.session.commit()
        flash(f"Inspection de suivi {nouvelle.numero} programmée.", "success")
        return redirect(url_for("ri.fiche", id=nouvelle.id))
    except wfri.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("ri.fiche", id=id))


@ri_bp.route("/inspections/plans-action")
@login_required
@roles_required(*ROLES_RI)
def plans_action():
    executer_verifications_delais_ri()
    inspections = Inspection.query.filter_by(statut="plan_action_en_cours") \
        .order_by(Inspection.date_echeance_plan_action.asc()).all()
    return render_template("inspection/plans_action.html", inspections=inspections, en_retard=plan_action_en_retard)


# ---------------------------------------------------------------------------
# Établissements — registre et fiche (entité du socle, écran introduit par RI)
# ---------------------------------------------------------------------------
@ri_bp.route("/etablissements")
def etablissements_registre():
    # Registre public en lecture pour les seuls établissements agréés (licence active),
    # conformément au spec LI §6 ; vue interne complète (tous statuts) pour les comptes
    # connectés.
    q = Etablissement.query
    texte = request.args.get("q", "").strip()
    type_etab = request.args.get("type", "")
    statut = request.args.get("statut", "")
    vue_publique = current_user() is None
    if vue_publique:
        q = q.filter_by(statut_licence="active")
        statut = "active"
    if texte:
        q = q.filter(Etablissement.raison_sociale.ilike(f"%{texte}%"))
    if type_etab:
        q = q.filter_by(type=type_etab)
    if statut and not vue_publique:
        q = q.filter_by(statut_licence=statut)
    etablissements = q.order_by(Etablissement.raison_sociale).all()
    return render_template("inspection/etablissements_registre.html", etablissements=etablissements,
                            q=texte, type_etab=type_etab, statut=statut, vue_publique=vue_publique)


@ri_bp.route("/etablissements/<int:id>")
@login_required
def etablissement_fiche(id):
    etab = Etablissement.query.get_or_404(id)
    inspections = Inspection.query.filter_by(etablissement_id=etab.id) \
        .order_by(Inspection.date_creation.desc()).all()
    demandes_licence = DemandeLicence.query.filter_by(etablissement_id=etab.id) \
        .order_by(DemandeLicence.date_creation.desc()).all()
    peut_gerer_licence = current_user().role_systeme == "administrateur_dpml" or (
        current_user().role_systeme == "demandeur_externe" and current_user().etablissement_rattachement_id == etab.id
    )
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="Etablissement", entite_id=etab.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("inspection/etablissement_fiche.html", etab=etab, inspections=inspections,
                            demandes_licence=demandes_licence, peut_gerer_licence=peut_gerer_licence,
                            audit_events=audit_events)


# ---------------------------------------------------------------------------
# Mobile (terrain) — fonctionne hors connexion une fois la grille chargée.
# Voir templates/inspection/grille.html pour la logique JS (localStorage + sync).
# ---------------------------------------------------------------------------
@ri_bp.route("/inspections/mobile")
@login_required
@roles_required("inspecteur_igspl")
def mobile_liste():
    inspections = Inspection.query.filter_by(inspecteur_id=current_user().id) \
        .filter(Inspection.statut.in_(("planifiee", "en_cours"))) \
        .order_by(Inspection.date_planifiee.asc()).all()
    return render_template("inspection/mobile_liste.html", inspections=inspections)


@ri_bp.route("/inspections/<int:id>/demarrer", methods=["POST"])
@login_required
@roles_required("inspecteur_igspl")
def action_demarrer(id):
    insp = Inspection.query.get_or_404(id)
    try:
        wfri.demarrer(insp, current_user())
        db.session.commit()
    except wfri.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("ri.mobile_liste"))
    return redirect(url_for("ri.grille", id=id))


@ri_bp.route("/inspections/<int:id>/grille")
@login_required
@roles_required("inspecteur_igspl")
def grille(id):
    insp = Inspection.query.get_or_404(id)
    if insp.inspecteur_id != current_user().id:
        abort(403)
    return render_template("inspection/grille.html", insp=insp)


@ri_bp.route("/inspections/<int:id>/sync", methods=["POST"])
@login_required
@roles_required("inspecteur_igspl")
def sync(id):
    """API JSON appelée par le JS de grille.html — dès qu'une connexion est disponible,
    que ce soit pour une simple sauvegarde intermédiaire ou pour la clôture finale."""
    insp = Inspection.query.get_or_404(id)
    payload = request.get_json(force=True, silent=True) or {}
    grille_donnees = payload.get("grille", [])
    action = payload.get("action", "sync")
    try:
        if action == "cloturer":
            wfri.cloturer_visite(insp, current_user(), grille_donnees,
                                  confirmation_items_manquants=bool(payload.get("confirmation_items_manquants")))
        else:
            wfri.synchroniser_grille(insp, current_user(), grille_donnees)
        db.session.commit()
        return jsonify({"ok": True, "statut": insp.statut, "score": insp.score_conformite})
    except wfri.ErreurWorkflow as e:
        db.session.rollback()
        return jsonify({"ok": False, "erreur": str(e)}), 400
