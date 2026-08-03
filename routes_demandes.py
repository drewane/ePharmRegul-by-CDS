"""
Point d'entrée des démarches de l'industriel : AMM, dérogation, visa technique.

Chaque type de demande a sa propre page. Une nouvelle demande se saisit
entièrement ; un renouvellement, une variation ou un retrait partent d'une AMM
existante, dont les informations produit sont reprises automatiquement — le
déposant ne ressaisit pas ce que l'administration connaît déjà.

Les essais cliniques relèvent d'un espace distinct (routes_ct.py) : un même
laboratoire ne mélange pas ses démarches d'homologation et ses protocoles.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import espace_industriel as esp
import modules_ctd as ctd
import workflow_ma as wf
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import DossierAMM, db

bp = Blueprint("demandes", __name__, url_prefix="/demandes")

# Type de procédure → (libellé, description, part d'une AMM existante ?)
TYPES_AMM = {
    "nouvelle_demande": (
        "Nouvelle demande d'AMM",
        "Faire homologuer un produit qui n'a pas encore d'autorisation au Cameroun.",
        False),
    "renouvellement": (
        "Renouvellement d'AMM",
        "Prolonger une autorisation existante avant son échéance.", True),
    "variation": (
        "Variation",
        "Déclarer une modification sur un produit déjà autorisé : formule, site de "
        "fabrication, conditionnement, notice…", True),
    "retrait": (
        "Retrait d'AMM",
        "Demander le retrait volontaire d'une autorisation en vigueur.", True),
}


def _industriel():
    u = current_user()
    if u is None or u.role_systeme not in ("demandeur_externe", "administrateur_dpml"):
        abort(403)
    return u


# ---------------------------------------------------------------------------
# Accueil : les trois familles de démarche
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def accueil():
    u = _industriel()
    return render_template("demandes/accueil.html", u=u)


# ---------------------------------------------------------------------------
# AMM — les quatre types de procédure
# ---------------------------------------------------------------------------
@bp.route("/amm")
@login_required
def amm():
    u = _industriel()
    return render_template("demandes/amm.html", u=u, types=TYPES_AMM,
                           amm_en_vigueur=_amm_en_vigueur(u))


def _amm_en_vigueur(u):
    """AMM approuvées de la société — support des renouvellements et variations."""
    return (esp.dossiers_de_la_societe(u)
            .filter(DossierAMM.statut == "approuve")
            .order_by(DossierAMM.numero).all())


@bp.route("/amm/<type_procedure>", methods=["GET", "POST"])
@login_required
def amm_type(type_procedure):
    """Page propre à chaque type de procédure."""
    u = _industriel()
    if type_procedure not in TYPES_AMM:
        abort(404)
    libelle, description, part_existante = TYPES_AMM[type_procedure]

    # Une nouvelle demande se saisit entièrement : on renvoie au formulaire complet.
    if not part_existante:
        return redirect(url_for("dossier_nouveau", type=type_procedure))

    existantes = _amm_en_vigueur(u)

    if request.method == "POST":
        source = db.session.get(DossierAMM, int(request.form.get("dossier_source", 0)))
        if source is None or source.demandeur_id not in esp.personnes_de_la_societe(u):
            flash("Sélectionnez une AMM de votre portefeuille.", "danger")
            return redirect(url_for("demandes.amm_type", type_procedure=type_procedure))
        try:
            nouveau = wf.creer_dossier_procedure(source.produit, u, type_procedure)
            db.session.commit()
            flash(f"{libelle} ouvert{'e' if type_procedure == 'variation' else ''} "
                  f"pour {source.produit.libelle}. Complétez le dossier technique.",
                  "success")
            return redirect(url_for("ctd.sommaire", dossier_id=nouveau.id))
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")

    # Détail du produit sélectionné, pour l'affichage immédiat
    apercus = {
        d.id: {
            "produit": d.produit.libelle if d.produit else "—",
            "dci": (d.produit.denomination_commune_internationale
                    if d.produit else "") or "—",
            "forme": (d.produit.forme_pharmaceutique if d.produit else "") or "—",
            "dosage": (d.produit.dosage if d.produit else "") or "—",
            "titulaire": (d.produit.titulaire_amm.raison_sociale
                          if d.produit and d.produit.titulaire_amm else "—"),
            "nature": ctd.NATURES_PRODUIT[ctd.nature_du_produit(d.produit)]["libelle"],
            "validite": (d.date_validite_amm.strftime("%d/%m/%Y")
                         if d.date_validite_amm else "—"),
            "modules": ctd.modules_obligatoires(
                ctd.nature_du_produit(d.produit), type_procedure),
        } for d in existantes
    }
    return render_template("demandes/amm_existante.html", u=u,
                           type_procedure=type_procedure, libelle=libelle,
                           description=description, existantes=existantes,
                           apercus=apercus)
