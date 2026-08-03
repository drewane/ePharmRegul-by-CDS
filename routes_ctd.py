"""
Constitution du dossier technique (CTD), module par module.

Le déposant renseigne les modules exigés dans l'ordre, charge les pièces
justificatives à la fin de chacun, puis passe au paiement des frais. Une fois
le paiement réglé, il télécharge son reçu et le verse au dossier comme preuve.

Les modules exigés dépendent de la nature du produit ET du type de demande
(cf. modules_ctd.py) : un renouvellement de générique n'appelle pas le même
dossier qu'une nouvelle demande de biosimilaire.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import modules_ctd as ctd
import paiements as svc_paiement
import workflow_ma as wf
from audit import enregistrer_audit
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import DossierAMM, db
from pieces import enregistrer_piece, lister_pieces


def _pieces_du_type(dossier, type_document):
    """Pièces d'un type donné — `lister_pieces` ne filtre pas, on filtre ici."""
    return [p for p in lister_pieces(dossier) if p.type_document == type_document]

bp = Blueprint("ctd", __name__, url_prefix="/dossiers")


def _dossier_modifiable(dossier_id):
    """Le dossier doit appartenir au déposant et rester modifiable."""
    u = current_user()
    d = db.session.get(DossierAMM, dossier_id) or abort(404)
    if u.role_systeme == "demandeur_externe":
        import espace_industriel as esp
        if d.demandeur_id not in esp.personnes_de_la_societe(u):
            abort(404)
    elif u.role_systeme != "administrateur_dpml":
        abort(403)
    if d.statut not in ("brouillon", "complement_requis"):
        raise ErreurWorkflow(
            f"Ce dossier n'est plus modifiable (statut : "
            f"{wf.STATUTS.get(d.statut, d.statut)}).")
    return u, d


# ---------------------------------------------------------------------------
# Vue d'ensemble du dossier technique
# ---------------------------------------------------------------------------
@bp.route("/<int:dossier_id>/technique")
@login_required
def sommaire(dossier_id):
    u = current_user()
    d = db.session.get(DossierAMM, dossier_id) or abort(404)
    exiges = ctd.modules_du_dossier(d)
    faits, total = ctd.progression(d)
    return render_template(
        "ctd/sommaire.html", d=d, u=u, exiges=exiges, MODULES=ctd.MODULES,
        nature=ctd.nature_du_produit(d.produit), NATURES=ctd.NATURES_PRODUIT,
        faits=faits, total=total, complet=ctd.dossier_technique_complet(d),
        suivant=ctd.module_suivant(d), TYPES=wf.TYPES_PROCEDURE,
        est_complet=lambda n: ctd.module_complet(d, n),
        pieces_par_module={n: _pieces_du_type(d, f"module_ctd_{n}") for n in exiges})


# ---------------------------------------------------------------------------
# Saisie d'un module
# ---------------------------------------------------------------------------
@bp.route("/<int:dossier_id>/technique/module/<int:numero>", methods=["GET", "POST"])
@login_required
def module(dossier_id, numero):
    if numero not in ctd.MODULES:
        abort(404)
    try:
        u, d = _dossier_modifiable(dossier_id)
    except ErreurWorkflow as e:
        flash(str(e), "warning")
        return redirect(url_for("ctd.sommaire", dossier_id=dossier_id))

    exiges = ctd.modules_du_dossier(d)
    if numero not in exiges:
        flash(f"Le module {numero} n'est pas exigé pour cette demande.", "info")
        return redirect(url_for("ctd.sommaire", dossier_id=d.id))

    if request.method == "POST":
        donnees = {code: (request.form.get(code) or "").strip()
                   for code, _l, _t in ctd.champs(numero)}
        ctd.ecrire_module(d, numero, donnees)

        fichier = request.files.get("piece")
        if fichier and fichier.filename:
            try:
                enregistrer_piece(d, fichier, f"module_ctd_{numero}", u)
            except Exception as e:                        # noqa: BLE001
                flash(f"Pièce non enregistrée : {e}", "warning")

        enregistrer_audit(d, f"Module CTD {numero} renseigné ({ctd.titre(numero)})", u)
        db.session.commit()

        if not ctd.module_complet(d, numero):
            flash(f"Module {numero} enregistré — des champs restent à compléter.",
                  "warning")
            return redirect(url_for("ctd.module", dossier_id=d.id, numero=numero))

        suivant = ctd.module_suivant(d, apres=numero)
        if suivant:
            flash(f"Module {numero} complété. Passons au module {suivant}.", "success")
            return redirect(url_for("ctd.module", dossier_id=d.id, numero=suivant))
        flash("Dossier technique complet.", "success")
        return redirect(url_for("ctd.sommaire", dossier_id=d.id))

    position = exiges.index(numero) + 1
    return render_template(
        "ctd/module.html", d=d, u=u, numero=numero, meta=ctd.MODULES[numero],
        valeurs=ctd.lire_module(d, numero), exiges=exiges, position=position,
        options=ctd.options_liste,
        pieces=_pieces_du_type(d, f"module_ctd_{numero}"),
        precedent=exiges[position - 2] if position > 1 else None,
        suivant_liste=exiges[position] if position < len(exiges) else None)


# ---------------------------------------------------------------------------
# Passage au paiement, puis dépôt de la preuve
# ---------------------------------------------------------------------------
@bp.route("/<int:dossier_id>/technique/continuer", methods=["POST"])
@login_required
def continuer(dossier_id):
    """Clôt la constitution du dossier et ouvre le règlement des frais."""
    try:
        _u, d = _dossier_modifiable(dossier_id)
    except ErreurWorkflow as e:
        flash(str(e), "warning")
        return redirect(url_for("ctd.sommaire", dossier_id=dossier_id))

    if not ctd.dossier_technique_complet(d):
        faits, total = ctd.progression(d)
        flash(f"Dossier technique incomplet ({faits}/{total} modules). "
              "Complétez les modules exigés avant de poursuivre.", "danger")
        return redirect(url_for("ctd.sommaire", dossier_id=d.id))

    paiement = svc_paiement.creer_paiement_bareme(d)
    db.session.commit()
    if paiement is None:
        flash("Aucun frais n'est exigible pour cette demande.", "info")
        return redirect(url_for("ctd.sommaire", dossier_id=d.id))
    return redirect(url_for("paiement.payer", paiement_id=paiement.id))


@bp.route("/<int:dossier_id>/technique/preuve", methods=["GET", "POST"])
@login_required
def preuve(dossier_id):
    """Dépôt du reçu de paiement, puis soumission effective du dossier."""
    u = current_user()
    d = db.session.get(DossierAMM, dossier_id) or abort(404)
    if u.role_systeme == "demandeur_externe":
        import espace_industriel as esp
        if d.demandeur_id not in esp.personnes_de_la_societe(u):
            abort(404)

    paiements = svc_paiement.lister_paiements(d)
    regle = next((p for p in paiements if p.statut == "confirme"), None)

    if request.method == "POST":
        fichier = request.files.get("preuve")
        if fichier and fichier.filename:
            try:
                enregistrer_piece(d, fichier, "preuve_paiement", u)
                enregistrer_audit(d, "Preuve de paiement versée au dossier", u)
                db.session.commit()
                flash("Preuve de paiement enregistrée.", "success")
            except Exception as e:                        # noqa: BLE001
                db.session.rollback()
                flash(f"Pièce non enregistrée : {e}", "danger")
        elif not regle:
            flash("Réglez les frais ou versez une preuve de paiement.", "warning")

        if request.form.get("soumettre"):
            try:
                wf.soumettre(d, u)
                db.session.commit()
                flash(f"Dossier {d.numero} soumis à la DPML. Vous recevrez un accusé "
                      "de réception.", "success")
                return redirect(url_for("industriel.portefeuille"))
            except ErreurWorkflow as e:
                db.session.rollback()
                flash(str(e), "danger")
        return redirect(url_for("ctd.preuve", dossier_id=d.id))

    return render_template(
        "ctd/preuve.html", d=d, u=u, paiements=paiements, regle=regle,
        preuves=_pieces_du_type(d, "preuve_paiement"),
        complet=ctd.dossier_technique_complet(d))


# ---------------------------------------------------------------------------
# Référentiel public : quels modules pour quelle demande ?
# ---------------------------------------------------------------------------
@bp.route("/exigences-ctd")
@login_required
def exigences():
    return render_template("ctd/exigences.html", matrice=ctd.apercu_matrice(),
                           MODULES=ctd.MODULES, TYPES=wf.TYPES_PROCEDURE,
                           NATURES=ctd.NATURES_PRODUIT)
