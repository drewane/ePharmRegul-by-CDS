"""
Routes de la plateforme de paiement.

Parcours selon le flux du moyen choisi :

  redirection (carte)   /payer → PSP (3-D Secure) → /retour + webhook signé
  push (mobile money)   /payer → /attente (interrogation périodique du statut)
  hors_ligne (virement) /payer → /virement (avis de paiement + référence)

Le webhook `/paiements/notification` est la source de vérité : le retour
navigateur ne confirme jamais un encaissement à lui seul, car il est falsifiable.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

import paiement as plateforme
import paiements as svc
from auth import current_user, login_required, permission_requise
from erreurs import ErreurWorkflow
from models import Paiement, db

bp = Blueprint("paiement", __name__, url_prefix="/paiements")


def _paiement_ou_404(paiement_id):
    p = db.session.get(Paiement, paiement_id)
    if not p:
        abort(404)
    return p


def _peut_payer(user, paiement):
    """Payeur légitime : le redevable rattaché, ou l'administration."""
    from permissions import a_permission
    if a_permission(user, "confirmer_paiement"):
        return True
    redevable = svc._demandeur(paiement)
    return redevable is not None and redevable.id == user.id


def _contexte(paiement):
    """URL techniques transmises au prestataire."""
    return {
        "url_retour": url_for("paiement.retour", paiement_id=paiement.id, _external=True),
        "url_notification": url_for("paiement.notification", _external=True),
        "url_simulateur": url_for("paiement.simulateur", paiement_id=paiement.id),
    }


# ---------------------------------------------------------------------------
# Choix du moyen de paiement
# ---------------------------------------------------------------------------
@bp.route("/<int:paiement_id>/payer", methods=["GET", "POST"])
@login_required
def payer(paiement_id):
    p = _paiement_ou_404(paiement_id)
    if not _peut_payer(current_user(), p):
        abort(403)
    svc.purger_sessions_expirees()

    if p.statut == "confirme":
        flash("Ce paiement a déjà été réglé.", "info")
        return redirect(svc._lien_entite(p) or url_for("dashboard"))

    if request.method == "POST":
        code = request.form.get("fournisseur", "")
        contexte = _contexte(p)
        contexte["numero_payeur"] = request.form.get("numero_payeur", "")
        try:
            initiation = svc.initier_en_ligne(p, code, contexte, current_user())
            db.session.commit()
        except ErreurWorkflow as e:
            flash(str(e), "danger")
            return redirect(url_for("paiement.payer", paiement_id=p.id))

        if initiation.flux == "redirection":
            return redirect(initiation.url_redirection)
        if initiation.flux == "push":
            return redirect(url_for("paiement.attente", paiement_id=p.id))
        return redirect(url_for("paiement.virement", paiement_id=p.id))

    return render_template(
        "paiement/payer.html", paiement=p, fournisseurs=plateforme.disponibles(),
        objet=svc.LIBELLE_OBJET.get(p.entite_type, p.entite_type))


# ---------------------------------------------------------------------------
# Flux « hors ligne » — virement bancaire
# ---------------------------------------------------------------------------
@bp.route("/<int:paiement_id>/virement")
@login_required
def virement(paiement_id):
    p = _paiement_ou_404(paiement_id)
    if not _peut_payer(current_user(), p):
        abort(403)
    f = plateforme.obtenir("virement")
    return render_template("paiement/virement.html", paiement=p,
                           coordonnees=f.coordonnees(), fournisseur=f,
                           objet=svc.LIBELLE_OBJET.get(p.entite_type, p.entite_type))


# ---------------------------------------------------------------------------
# Flux « push » — mobile money : attente de la confirmation du payeur
# ---------------------------------------------------------------------------
@bp.route("/<int:paiement_id>/attente")
@login_required
def attente(paiement_id):
    p = _paiement_ou_404(paiement_id)
    if not _peut_payer(current_user(), p):
        abort(403)
    f = plateforme.FOURNISSEURS.get(p.fournisseur)
    return render_template("paiement/attente.html", paiement=p, fournisseur=f,
                           objet=svc.LIBELLE_OBJET.get(p.entite_type, p.entite_type))


@bp.route("/<int:paiement_id>/statut")
@login_required
def statut(paiement_id):
    """Interrogation appelée périodiquement par la page d'attente (JSON)."""
    p = _paiement_ou_404(paiement_id)
    if not _peut_payer(current_user(), p):
        abort(403)
    try:
        svc.interroger_statut(p, current_user())
        db.session.commit()
    except ErreurWorkflow as e:
        return jsonify({"statut": p.statut, "erreur": str(e)})
    return jsonify({"statut": p.statut,
                    "redirection": svc._lien_entite(p) if p.statut == "confirme" else None})


# ---------------------------------------------------------------------------
# Retour navigateur (informatif) — ne confirme jamais à lui seul
# ---------------------------------------------------------------------------
@bp.route("/<int:paiement_id>/retour")
@login_required
def retour(paiement_id):
    p = _paiement_ou_404(paiement_id)
    if not _peut_payer(current_user(), p):
        abort(403)
    if p.statut == "confirme":
        flash("Paiement confirmé. Merci.", "success")
    else:
        flash("Retour du prestataire enregistré. La confirmation définitive "
              "intervient dès réception de la notification bancaire.", "info")
    return redirect(svc._lien_entite(p) or url_for("dashboard"))


# ---------------------------------------------------------------------------
# Simulateur — actif uniquement pour un fournisseur non raccordé
# ---------------------------------------------------------------------------
@bp.route("/<int:paiement_id>/simulateur")
@login_required
def simulateur(paiement_id):
    p = _paiement_ou_404(paiement_id)
    if not _peut_payer(current_user(), p):
        abort(403)
    f = plateforme.FOURNISSEURS.get(p.fournisseur)
    if f is None or f.configure():
        abort(404)          # en mode raccordé, la page appartient au prestataire
    return render_template("paiement/simulateur.html", paiement=p, fournisseur=f,
                           objet=svc.LIBELLE_OBJET.get(p.entite_type, p.entite_type))


@bp.route("/simuler", methods=["POST"])
@login_required
def simuler():
    """Fait produire au serveur une notification signée, traitée comme un vrai webhook."""
    p = _paiement_ou_404(int(request.form.get("paiement_id", 0)))
    if not _peut_payer(current_user(), p):
        abort(403)
    f = plateforme.FOURNISSEURS.get(p.fournisseur)
    if f is None or f.configure():
        abort(404)
    succes = request.form.get("resultat") == "succes"
    try:
        svc.traiter_notification(p, f.notification_simulee(p, succes=succes), current_user())
        db.session.commit()
        flash("Paiement confirmé." if succes else "Le paiement n'a pas abouti.",
              "success" if succes else "danger")
    except ErreurWorkflow as e:
        flash(str(e), "danger")
    return redirect(svc._lien_entite(p) or url_for("dashboard"))


# ---------------------------------------------------------------------------
# Webhook prestataire — authentifié par la SIGNATURE, pas par une session
# ---------------------------------------------------------------------------
@bp.route("/notification", methods=["POST"])
def notification():
    payload = request.get_json(silent=True) or {}
    ref = payload.get("reference_marchande")
    p = Paiement.query.filter_by(reference_marchande=ref).first() if ref else None
    if not p:
        # Réponse neutre : ne pas révéler si la référence existe.
        return {"statut": "ignore"}, 202
    try:
        svc.traiter_notification(p, payload, None)
        db.session.commit()
    except ErreurWorkflow as e:
        return {"statut": "refuse", "motif": str(e)}, 400
    return {"statut": "ok", "paiement": p.statut}, 200


# ---------------------------------------------------------------------------
# Console de rapprochement bancaire (agents habilités)
# ---------------------------------------------------------------------------
@bp.route("/rapprochement", methods=["GET", "POST"])
@login_required
@permission_requise("confirmer_paiement")
def rapprochement():
    """Rapproche les virements annoncés avec les créances en attente."""
    if request.method == "POST":
        ref = request.form.get("reference", "").strip()
        montant = request.form.get("montant", "0").strip()
        p = Paiement.query.filter_by(reference_marchande=ref).first()
        if not p:
            flash(f"Aucune créance ne porte la référence « {ref} ».", "danger")
        else:
            try:
                svc.rapprocher_virement(
                    p, {"reference": ref, "montant": int(montant or 0),
                        "devise": p.devise,
                        "date": request.form.get("date", ""),
                        "reference_bancaire": request.form.get("reference_bancaire", "")},
                    current_user())
                db.session.commit()
                flash(f"Virement rapproché : {p.numero} réglé.", "success")
            except (ErreurWorkflow, ValueError) as e:
                flash(str(e), "danger")
        return redirect(url_for("paiement.rapprochement"))

    attendus = (Paiement.query
                .filter(Paiement.fournisseur == "virement",
                        Paiement.statut.in_(("initie", "en_attente")))
                .order_by(Paiement.date_creation.desc()).all())
    return render_template("paiement/rapprochement.html", attendus=attendus,
                           libelle_objet=svc.LIBELLE_OBJET)
