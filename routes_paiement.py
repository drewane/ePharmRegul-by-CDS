"""
Routes du paiement en ligne sécurisé.

Parcours : /paiements/<id>/payer  (choix du moyen)
        →  /paiements/regler      (page du prestataire — simulateur)
        →  /paiements/notification (webhook signé, vérifié côté serveur)

Le webhook est la SEULE source de vérité : le retour navigateur de l'usager ne
confirme jamais un paiement à lui seul (il est falsifiable).
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import paiement_gateway as passerelle
import paiements as svc
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import Paiement, db

bp = Blueprint("paiement", __name__, url_prefix="/paiements")


def _paiement_ou_404(paiement_id):
    p = db.session.get(Paiement, paiement_id)
    if not p:
        abort(404)
    return p


def _peut_payer(user, paiement):
    """Le payeur légitime est le demandeur rattaché, ou l'administration."""
    from permissions import a_permission
    if a_permission(user, "confirmer_paiement"):
        return True
    demandeur = svc._demandeur(paiement)
    return demandeur is not None and demandeur.id == user.id


@bp.route("/<int:paiement_id>/payer", methods=["GET", "POST"])
@login_required
def payer(paiement_id):
    p = _paiement_ou_404(paiement_id)
    u = current_user()
    if not _peut_payer(u, p):
        abort(403)
    passerelle.expirer_si_besoin(p)
    db.session.commit()

    if p.statut == "confirme":
        flash("Ce paiement a déjà été réglé.", "info")
        return redirect(svc._lien_entite(p) or url_for("dashboard"))

    if request.method == "POST":
        fournisseur = request.form.get("fournisseur", "")
        try:
            session = svc.initier_en_ligne(
                p, fournisseur, url_for("paiement.regler", _external=False), u)
            db.session.commit()
        except ErreurWorkflow as e:
            flash(str(e), "danger")
            return redirect(url_for("paiement.payer", paiement_id=p.id))
        return redirect(session["url_paiement"])

    return render_template("paiement/payer.html", paiement=p,
                           fournisseurs=passerelle.FOURNISSEURS,
                           mode_reel=passerelle.mode_reel(),
                           objet=svc.LIBELLE_OBJET.get(p.entite_type, p.entite_type))


@bp.route("/regler")
@login_required
def regler():
    """Page du prestataire — SIMULATEUR de démonstration.

    En production, cette page est hébergée par le prestataire agréé : l'usager
    y saisit ses identifiants de paiement, que SIREPH ne voit jamais.
    """
    if passerelle.mode_reel():
        abort(404)          # en mode réel, le PSP héberge sa propre page
    ref = request.args.get("ref", "")
    p = Paiement.query.filter_by(reference_marchande=ref).first()
    if not p:
        abort(404)
    if not _peut_payer(current_user(), p):
        abort(403)
    return render_template("paiement/simulateur.html", paiement=p,
                           fournisseur=passerelle.FOURNISSEURS.get(p.fournisseur, "—"))


@bp.route("/simuler", methods=["POST"])
@login_required
def simuler():
    """Déclenche la notification signée du simulateur (succès ou échec).

    Le formulaire ne transmet PAS le résultat en clair depuis le navigateur :
    il demande au serveur de produire une notification signée, qui suit ensuite
    exactement le même chemin de vérification qu'un webhook réel.
    """
    if passerelle.mode_reel():
        abort(404)
    ref = request.form.get("ref", "")
    succes = request.form.get("resultat") == "succes"
    p = Paiement.query.filter_by(reference_marchande=ref).first()
    if not p:
        abort(404)
    if not _peut_payer(current_user(), p):
        abort(403)

    payload = passerelle.construire_notification(p, succes=succes)
    try:
        svc.traiter_notification(p, payload, current_user())
        db.session.commit()
        flash("Paiement confirmé." if succes else "Le paiement n'a pas abouti.",
              "success" if succes else "danger")
    except ErreurWorkflow as e:
        flash(str(e), "danger")
    return redirect(svc._lien_entite(p) or url_for("dashboard"))


@bp.route("/notification", methods=["POST"])
def notification():
    """Webhook du prestataire — endpoint public, protégé par la SIGNATURE seule.

    Aucune session utilisateur ici : c'est le prestataire qui appelle. La
    vérification HMAC + le contrôle du montant tiennent lieu d'authentification.
    """
    payload = request.get_json(silent=True) or {}
    ref = payload.get("reference_marchande")
    p = Paiement.query.filter_by(reference_marchande=ref).first() if ref else None
    if not p:
        # Ne pas révéler si la référence existe : réponse neutre.
        return {"statut": "ignore"}, 202
    try:
        svc.traiter_notification(p, payload, None)
        db.session.commit()
    except ErreurWorkflow as e:
        return {"statut": "refuse", "motif": str(e)}, 400
    return {"statut": "ok", "paiement": p.statut}, 200
