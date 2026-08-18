"""
Parcours d'un dossier : état, actions ouvertes, historique.

UNE SEULE ROUTE POUR TOUTES LES TRANSITIONS
-------------------------------------------
Il n'y a pas une route « déclarer recevable », une route « rejeter », une route
« valider ». Il y en a **une**, qui reçoit le nom de l'action et laisse la
machine à états décider. Ajouter une transition, c'est ajouter une ligne dans
`machine_etats.TRANSITIONS` — pas une route, pas un bouton, pas un décorateur.

C'est aussi ce qui rend la garantie tenable : le contrôle des droits est fait
une fois, dans `appliquer_transition`, et non répété — donc oublié — à chaque
vue. Le décorateur `@login_required` ne dit ici que « il faut être connecté » ;
qui peut faire quoi relève du modèle.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect,
                   render_template, request, send_file, url_for)

import actes
import machine_etats as me
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import DossierAMM, db

bp = Blueprint("dossier", __name__, url_prefix="/dossiers")


def _dossier_visible(dossier_id):
    """Le dossier, si l'utilisateur a le droit de le voir.

    Le déposant ne voit que les siens ; l'administration voit tout ce qui
    relève de son périmètre de consultation.
    """
    import permissions as perm

    u = current_user()
    d = db.session.get(DossierAMM, dossier_id) or abort(404)
    if u.est_externe:
        meme_etablissement = (
            u.etablissement_rattachement_id is not None
            and d.demandeur is not None
            and d.demandeur.etablissement_rattachement_id
            == u.etablissement_rattachement_id)
        if d.demandeur_id != u.id and not meme_etablissement:
            abort(403)
    elif not perm.a_permission(u, "voir_tous_dossiers_ma"):
        abort(403)
    return u, d


@bp.route("/<int:dossier_id>/parcours")
@login_required
def parcours(dossier_id):
    u, d = _dossier_visible(dossier_id)
    return render_template(
        "dossiers/parcours.html", u=u, d=d,
        etapes=me.etapes(d),
        actions=me.transitions_autorisees(d, u.role_systeme),
        historique=me.historique(d),
        actes_delivres=actes.resume(d),
        me=me)


@bp.route("/<int:dossier_id>/actes/<code>")
@login_required
def acte(dossier_id, code):
    """Gabarit imprimable de l'acte — en-tête bilingue, prêt pour le papier."""
    from datetime import datetime

    u, d = _dossier_visible(dossier_id)
    if code not in actes.ACTES:
        abort(404)
    if not actes.existe(d, code):
        abort(404)
    if not actes.peut_consulter(d, u):
        abort(403)

    contexte = actes.contexte(d, code)
    titres = {"certificat": "CERTIFICAT D'HOMOLOGATION",
              "amm": "AUTORISATION DE MISE SUR LE MARCHÉ"}
    return render_template(
        contexte["acte"]["gabarit"], u=u, now=datetime.utcnow(),
        titre_fr=titres[code],
        peut_telecharger=actes.peut_telecharger(d, u),
        motif_refus=actes.motif_refus_telechargement(d, u),
        autres_actes=[(c, a) for c, a in actes.actes_disponibles(d)
                      if c != code],
        **contexte)


@bp.route("/<int:dossier_id>/actes/<code>.pdf")
@login_required
def acte_pdf(dossier_id, code):
    """Le PDF de l'acte. Régénéré à la demande : ainsi une AMM devient
    définitive dès le dépôt de l'exemplaire signé, sans purge de cache."""
    u, d = _dossier_visible(dossier_id)
    if code not in actes.ACTES or not actes.existe(d, code):
        abort(404)
    if not actes.peut_telecharger(d, u):
        abort(403)

    chemin = actes.ecrire_pdf(d, code, base_url=request.url_root.rstrip("/"))
    return send_file(chemin, mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"{actes.numero(d, code)}.pdf")


@bp.route("/<int:dossier_id>/etat.json")
@login_required
def etat(dossier_id):
    """État courant du dossier, pour le suivi sans rechargement.

    La page interroge ce point périodiquement et ne se recharge que si
    `empreinte` a changé. On évite ainsi de reconstruire un écran identique
    toutes les vingt secondes — et de faire sauter le formulaire que le
    déposant est peut-être en train de remplir.
    """
    _u, d = _dossier_visible(dossier_id)
    dernier = me.historique(d)
    return jsonify({
        "statut": me.statut_canonique(d),
        "libelle": me.libelle(d),
        "couleur": me.couleur(d),
        "termine": me.est_terminal(d),
        "attendu_de": me.acteurs_attendus_lisibles(d),
        "empreinte": f"{d.statut}:{len(dernier)}",
        "maj": (dernier[-1].horodatage.isoformat() if dernier else None),
    })


@bp.route("/<int:dossier_id>/transition", methods=["POST"])
@login_required
def transition(dossier_id):
    """Applique l'action demandée. Le moteur seul décide si elle est permise."""
    u, d = _dossier_visible(dossier_id)
    action = (request.form.get("action") or "").strip()
    commentaire = request.form.get("commentaire")

    try:
        t = me.appliquer_transition(d, action, u, commentaire)
        db.session.commit()
        flash(f"{t['libelle']} — le dossier est désormais "
              f"« {me.libelle(t['vers'])} ».", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")

    retour = request.form.get("retour")
    return redirect(retour or url_for("dossier.parcours", dossier_id=d.id))
