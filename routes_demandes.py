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

import dossier_essai_clinique as dec
import espace_industriel as esp
import modules_ctd as ctd
import taxonomie_demandes as tax
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
    """Profils admis sur « Demande », lus dans la matrice d'accès.

    Recopier ici la liste des profils la ferait diverger du menu : c'est
    exactement ce qui s'était produit — le fabricant voyait l'onglet et
    recevait un 403 en cliquant.
    """
    import matrice_acces

    u = current_user()
    admis = matrice_acces.profils_admis("demande")
    if u is None or (u.role_systeme not in admis
                     and u.role_systeme != "administrateur_dpml"):
        abort(403)
    return u


def _acte_ouvert(u, code_acte):
    """Refuse une famille de démarche qui ne relève pas du profil.

    Le grisage du menu est une politesse ; ce contrôle-ci est la garantie.
    """
    import matrice_acces

    if not matrice_acces.acte_concerne(u, code_acte):
        abort(403)


def _cartes(u, chemin):
    """Sous-rubriques de la page, chacune marquée accessible ou grisée.

    La page reprend le parti du menu : on montre ce qui existe, on grise ce
    qui ne concerne pas le profil, et on dit pourquoi.
    """
    import matrice_acces

    racine = chemin[0] if chemin else None
    cartes = []
    for enfant in tax.enfants_avec_liens(chemin):
        code_acte = racine or enfant["code"]
        ok = matrice_acces.acte_concerne(u, code_acte)
        cartes.append({**enfant, "accessible": ok,
                       "motif": None if ok
                       else matrice_acces.motif_indisponible(u)})
    return cartes


# ---------------------------------------------------------------------------
# Accueil et navigation dans l'arborescence
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def accueil():
    u = _industriel()
    return render_template("demandes/rubrique.html", u=u,
                           titre="Déposer une demande",
                           description="Choisissez la nature de votre démarche. "
                                       "Chaque dépôt donne lieu à un accusé de "
                                       "réception immédiat, puis à un suivi dans "
                                       "votre portefeuille.",
                           enfants=_cartes(u, []), fil=[])


@bp.route("/rubrique/<path:chemin>")
@login_required
def rubrique(chemin):
    """Un niveau quelconque de l'arborescence, décrit une seule fois ailleurs."""
    u = _industriel()
    segments = [c for c in chemin.split("/") if c]
    n = tax.noeud(segments)
    if n is None:
        abort(404)
    _acte_ouvert(u, segments[0])
    if not n.get("enfants"):
        return redirect(n["lien"])
    return render_template("demandes/rubrique.html", u=u, titre=n["libelle"],
                           description=n["description"],
                           enfants=_cartes(u, segments),
                           fil=tax.fil_ariane(segments))


# ---------------------------------------------------------------------------
# Essais cliniques — besoin documentaire par phase
# ---------------------------------------------------------------------------
@bp.route("/essai-clinique/<phase>")
@login_required
def essai_clinique(phase):
    u = _industriel()
    _acte_ouvert(u, "essai_clinique")
    if phase not in dec.PHASES:
        abort(404)
    obligatoires, total = dec.compte(phase)
    return render_template("demandes/essai_clinique.html", u=u, phase=phase,
                           infos=dec.PHASES[phase],
                           exigences=dec.exigences(phase),
                           obligatoires=obligatoires, total=total,
                           fil=tax.fil_ariane(["essai_clinique", phase]))


# ---------------------------------------------------------------------------
# Agréments d'établissement — domaine × catégorie × acte
# ---------------------------------------------------------------------------
@bp.route("/agrements/<domaine>/<categorie>/<acte>", methods=["GET", "POST"])
@login_required
def agrement(domaine, categorie, acte):
    """Douze démarches d'agrément, servies par une seule page.

    Le domaine (distribution / fabrication) et la catégorie (médicaments /
    dispositifs médicaux) qualifient l'agrément ; l'acte dit ce qu'on en fait.
    """
    import workflow_agrement as wfa

    u = _industriel()
    _acte_ouvert(u, "agrements")
    if (domaine not in tax.DOMAINES_AGREMENT
            or categorie not in tax.CATEGORIES_AGREMENT
            or acte not in tax.ACTES_AGREMENT):
        abort(404)

    etablissement = u.etablissement
    if request.method == "POST":
        try:
            demande = wfa.deposer(etablissement, u, domaine, categorie, acte,
                                  request.form.get("motif", ""),
                                  request.form.get("pieces", ""))
            db.session.commit()
            flash(f"Demande {demande.numero} déposée. Un accusé de réception "
                  "vous a été adressé.", "success")
            return redirect(url_for("li.fiche", id=demande.id))
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")

    libelle_acte, description = tax.ACTES_AGREMENT[acte]
    return render_template(
        "demandes/agrement.html", u=u, domaine=domaine, categorie=categorie,
        acte=acte, libelle_acte=libelle_acte, description=description,
        libelle_domaine=tax.DOMAINES_AGREMENT[domaine],
        libelle_categorie=tax.CATEGORIES_AGREMENT[categorie],
        etablissement=etablissement,
        pieces_attendues=wfa.pieces_attendues(domaine, categorie, acte),
        en_cours=wfa.demandes_en_cours(etablissement),
        motif_requis=wfa.MOTIF_REQUIS.get(acte, False),
        fil=tax.fil_ariane(["agrements", domaine, categorie, acte]))


# ---------------------------------------------------------------------------
# AMM — les quatre types de procédure
# ---------------------------------------------------------------------------
@bp.route("/amm")
@login_required
def amm():
    u = _industriel()
    _acte_ouvert(u, "homologation")
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
    _acte_ouvert(u, "homologation")
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
