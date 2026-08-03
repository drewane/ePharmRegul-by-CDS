"""
Routes du volet régional CEEAC.

Orchestration uniquement : la logique métier vit dans workflow_reliance.py et
le contrat d'échange dans reliance.py (convention du projet, cf. README).
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import reliance as ctr
import workflow_reliance as wfr
from auth import current_user, login_required, permission_requise
from erreurs import ErreurWorkflow
from models import (AccordPartage, AlerteTransfrontaliere, DecisionPubliee,
                    DossierAMM, MessageReliance, PaysCEEAC, Produit,
                    RequeteReliance, db)

bp = Blueprint("reliance", __name__, url_prefix="/reliance")


@bp.route("/")
@login_required
@permission_requise("consulter_reliance")
def tableau_bord():
    """Vue d'ensemble du volet régional."""
    file_attente = MessageReliance.query.filter_by(sens="sortant", statut="en_file").count()
    alertes_non_traitees = AlerteTransfrontaliere.query.filter_by(
        sens="recue", traitee=False).count()
    requetes_entrantes = RequeteReliance.query.filter_by(
        sens="entrante", statut="recue").count()
    return render_template(
        "reliance/tableau_bord.html",
        pays_instance=ctr.pays_instance(), hub_raccorde=ctr.hub_raccorde(),
        url_hub=ctr.url_hub(), contrat=ctr.CONTRAT_VERSION,
        partenaires=wfr.pays_partenaires(),
        file_attente=file_attente, alertes_non_traitees=alertes_non_traitees,
        requetes_entrantes=requetes_entrantes,
        decisions_regionales=DecisionPubliee.query.filter(
            DecisionPubliee.pays_origine != ctr.pays_instance()).count(),
        decisions_publiees=DecisionPubliee.query.filter_by(
            pays_origine=ctr.pays_instance()).count())


# ---------------------------------------------------------------------------
# Consultation régionale
# ---------------------------------------------------------------------------
@bp.route("/consultation")
@login_required
@permission_requise("consulter_reliance")
def consultation():
    dci = request.args.get("dci", "").strip()
    produit = request.args.get("produit", "").strip()
    pays = request.args.get("pays", "").strip() or None
    resultats = wfr.consulter_registre(dci=dci or None, produit=produit or None,
                                       pays=pays) if (dci or produit or pays) else []
    return render_template("reliance/consultation.html", resultats=resultats,
                           dci=dci, produit=produit, pays=pays,
                           partenaires=wfr.pays_partenaires(),
                           recherche_lancee=bool(dci or produit or pays))


# ---------------------------------------------------------------------------
# Consentements de partage (ICC)
# ---------------------------------------------------------------------------
@bp.route("/accords", methods=["GET", "POST"])
@login_required
@permission_requise("gerer_reliance")
def accords():
    if request.method == "POST":
        try:
            dossier = None
            if request.form.get("dossier_id"):
                dossier = db.session.get(DossierAMM, int(request.form["dossier_id"]))
            wfr.accorder_partage(
                current_user(), request.form.get("objet", ""),
                request.form.get("pays_destinataire", ""),
                request.form.get("portee", "rapport_evaluation"), dossier)
            db.session.commit()
            flash("Consentement de partage enregistré.", "success")
        except (ErreurWorkflow, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("reliance.accords"))

    return render_template(
        "reliance/accords.html",
        accords=AccordPartage.query.order_by(AccordPartage.id.desc()).all(),
        partenaires=wfr.pays_partenaires(), portees=ctr.PORTEES_ACCORD)


@bp.route("/accords/<int:accord_id>/revoquer", methods=["POST"])
@login_required
@permission_requise("gerer_reliance")
def revoquer_accord(accord_id):
    accord = db.session.get(AccordPartage, accord_id) or abort(404)
    try:
        wfr.revoquer_partage(accord, current_user(), request.form.get("motif", ""))
        db.session.commit()
        flash(f"Consentement {accord.numero} révoqué.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("reliance.accords"))


# ---------------------------------------------------------------------------
# Requêtes de reliance
# ---------------------------------------------------------------------------
@bp.route("/requetes", methods=["GET", "POST"])
@login_required
@permission_requise("consulter_reliance")
def requetes():
    if request.method == "POST":
        from permissions import a_permission
        if not a_permission(current_user(), "gerer_reliance"):
            abort(403)
        try:
            produit = None
            if request.form.get("produit_id"):
                produit = db.session.get(Produit, int(request.form["produit_id"]))
            req = wfr.creer_requete(
                current_user(), request.form.get("pays_partenaire", ""),
                request.form.get("objet", ""),
                request.form.get("type_requete", "rapport_evaluation"), produit)
            if request.form.get("transmettre"):
                wfr.transmettre_requete(req, current_user())
            db.session.commit()
            flash(f"Requête {req.numero} enregistrée.", "success")
        except (ErreurWorkflow, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("reliance.requetes"))

    toutes = RequeteReliance.query.order_by(RequeteReliance.id.desc()).all()
    return render_template(
        "reliance/requetes.html",
        sortantes=[r for r in toutes if r.sens == "sortante"],
        entrantes=[r for r in toutes if r.sens == "entrante"],
        partenaires=wfr.pays_partenaires(), types=ctr.TYPES_REQUETE,
        accords_actifs=AccordPartage.query.filter_by(revoque=False).all())


@bp.route("/requetes/<int:requete_id>/<action>", methods=["POST"])
@login_required
@permission_requise("gerer_reliance")
def agir_requete(requete_id, action):
    req = db.session.get(RequeteReliance, requete_id) or abort(404)
    try:
        if action == "transmettre":
            wfr.transmettre_requete(req, current_user())
            flash(f"Requête {req.numero} mise en file de transmission.", "success")
        elif action == "repondre":
            accord = None
            if request.form.get("accord_id"):
                accord = db.session.get(AccordPartage, int(request.form["accord_id"]))
            wfr.repondre_requete(req, current_user(),
                                 request.form.get("contenu", ""), accord)
            flash(f"Réponse à {req.numero} mise en file.", "success")
        elif action == "refuser":
            wfr.refuser_requete(req, current_user(), request.form.get("motif", ""))
            flash(f"Requête {req.numero} refusée.", "info")
        else:
            abort(404)
        db.session.commit()
    except (ErreurWorkflow, ValueError) as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("reliance.requetes"))


# ---------------------------------------------------------------------------
# Registre régional : publication d'une décision nationale
# ---------------------------------------------------------------------------
@bp.route("/publications", methods=["GET", "POST"])
@login_required
@permission_requise("gerer_reliance")
def publications():
    if request.method == "POST":
        try:
            dossier = db.session.get(DossierAMM, int(request.form["dossier_id"]))
            if not dossier:
                raise ErreurWorkflow("Dossier introuvable.")
            wfr.publier_decision(dossier, current_user(),
                                 request.form.get("resume", ""),
                                 bool(request.form.get("rapport_partageable")))
            db.session.commit()
            flash("Décision publiée au registre régional.", "success")
        except (ErreurWorkflow, ValueError, KeyError) as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("reliance.publications"))

    publiables = (DossierAMM.query
                  .filter(DossierAMM.statut.in_(("amm_octroyee", "octroye", "autorise")))
                  .order_by(DossierAMM.id.desc()).limit(100).all())
    deja = {d.dossier_amm_id for d in DecisionPubliee.query.filter_by(
        pays_origine=ctr.pays_instance()).all() if d.dossier_amm_id}
    return render_template(
        "reliance/publications.html",
        publiables=[d for d in publiables if d.id not in deja],
        publiees=DecisionPubliee.query.filter_by(
            pays_origine=ctr.pays_instance()).order_by(
            DecisionPubliee.id.desc()).all())


# ---------------------------------------------------------------------------
# Alertes transfrontalières
# ---------------------------------------------------------------------------
@bp.route("/alertes", methods=["GET", "POST"])
@login_required
@permission_requise("consulter_reliance")
def alertes():
    if request.method == "POST":
        from permissions import a_permission
        if not a_permission(current_user(), "gerer_reliance"):
            abort(403)
        try:
            wfr.emettre_alerte(
                current_user(), request.form.get("type_alerte", "rappel_lot"),
                request.form.get("produit_nom", ""), request.form.get("message", ""),
                request.form.get("numero_lot"), request.form.get("niveau_risque") or None)
            db.session.commit()
            flash("Alerte transfrontalière mise en file de diffusion.", "success")
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
        return redirect(url_for("reliance.alertes"))

    toutes = AlerteTransfrontaliere.query.order_by(
        AlerteTransfrontaliere.id.desc()).all()
    return render_template(
        "reliance/alertes.html",
        emises=[a for a in toutes if a.sens == "emise"],
        recues=[a for a in toutes if a.sens == "recue"],
        types=ctr.TYPES_ALERTE)


@bp.route("/alertes/<int:alerte_id>/<action>", methods=["POST"])
@login_required
@permission_requise("consulter_reliance")
def agir_alerte(alerte_id, action):
    alerte = db.session.get(AlerteTransfrontaliere, alerte_id) or abort(404)
    try:
        if action == "accuser":
            wfr.accuser_reception_alerte(alerte, current_user())
        elif action == "traiter":
            wfr.marquer_alerte_traitee(alerte, current_user())
        else:
            abort(404)
        db.session.commit()
        flash("Alerte mise à jour.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("reliance.alertes"))


# ---------------------------------------------------------------------------
# File d'échange et synchronisation
# ---------------------------------------------------------------------------
@bp.route("/file")
@login_required
@permission_requise("gerer_reliance")
def file_echange():
    return render_template(
        "reliance/file.html",
        messages=MessageReliance.query.order_by(MessageReliance.id.desc()).limit(100).all(),
        hub_raccorde=ctr.hub_raccorde(), url_hub=ctr.url_hub())


@bp.route("/synchroniser", methods=["POST"])
@login_required
@permission_requise("gerer_reliance")
def synchroniser():
    r = wfr.synchroniser(current_user())
    if not r.get("hub_raccorde"):
        flash(f"Hub régional non raccordé : {len(r['en_attente'])} message(s) "
              "conservé(s) en file. L'instance reste pleinement opérationnelle.",
              "warning")
    else:
        flash(f"{len(r['transmis'])} message(s) transmis, "
              f"{len(r['en_attente'])} en attente, {len(r['erreurs'])} en erreur.",
              "info")
    return redirect(url_for("reliance.file_echange"))


# ---------------------------------------------------------------------------
# Point d'entrée des messages venant du Hub (authentifié par la signature)
# ---------------------------------------------------------------------------
@bp.route("/entrant", methods=["POST"])
def entrant():
    env = request.get_json(silent=True) or {}
    try:
        wfr.traiter_message_entrant(env)
    except ErreurWorkflow as e:
        return {"statut": "refuse", "motif": str(e)}, 400
    return {"statut": "ok"}, 200


# ---------------------------------------------------------------------------
# Administration : liste des pays (configurable, jamais codée en dur)
# ---------------------------------------------------------------------------
@bp.route("/pays", methods=["GET", "POST"])
@login_required
@permission_requise("gerer_reliance")
def pays():
    if request.method == "POST":
        p = db.session.get(PaysCEEAC, int(request.form.get("pays_id", 0)))
        if p:
            p.statut = request.form.get("statut", p.statut)
            p.dans_reliance = bool(request.form.get("dans_reliance"))
            p.url_instance = request.form.get("url_instance", "").strip() or None
            db.session.commit()
            flash(f"{p.nom} mis à jour.", "success")
        return redirect(url_for("reliance.pays"))
    return render_template("reliance/pays.html",
                           pays=PaysCEEAC.query.order_by(PaysCEEAC.nom).all(),
                           pays_instance=ctr.pays_instance())
