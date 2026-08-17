"""
Espace de l'industriel / titulaire d'AMM.

Tout ce qui est affiché ici est CLOISONNÉ à la société du compte connecté
(cf. espace_industriel.py) : un titulaire ne voit jamais le portefeuille d'un
concurrent.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import espace_industriel as esp
import paiements as pmt
import suivi
import workflow_demande_inspection as wfdi
import workflow_ma as wf
from auth import current_user, login_required
from erreurs import ErreurWorkflow
from models import DemandeInspection, DossierAMM, Paiement, Produit, db

bp = Blueprint("industriel", __name__, url_prefix="/industriel")

# Profils autorisés à disposer de cet espace
PROFILS = ("demandeur_externe",)


def _verifier_profil():
    """Espace du titulaire d'AMM : portefeuille, suivi, dossiers."""
    u = current_user()
    if u is None or u.role_systeme not in PROFILS:
        abort(403)
    return u


def _verifier_inspection():
    """Demande d'inspection : ouverte à tout profil que la matrice y admet.

    Un fabricant et un grossiste sollicitent l'inspection de leur site sans
    détenir la moindre AMM. Les enfermer dans `demandeur_externe` faisait
    offrir par le menu ce que la route refusait.
    """
    import matrice_acces

    u = current_user()
    if u is None:
        abort(403)
    if not matrice_acces.acte_concerne(u, "inspection"):
        abort(403)
    return u


def _dossier_de_ma_societe(dossier_id):
    """Garde-fou de cloisonnement : refuse l'accès à un dossier d'une autre société."""
    u = _verifier_profil()
    dossier = db.session.get(DossierAMM, dossier_id)
    if not dossier or dossier.demandeur_id not in esp.personnes_de_la_societe(u):
        abort(404)          # 404 plutôt que 403 : ne révèle pas l'existence du dossier
    return u, dossier


# ---------------------------------------------------------------------------
# Tableau de bord de la société
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def tableau_bord():
    """Tableau de bord composé selon le profil de l'opérateur.

    Ouvert à tous les profils externes, et non au seul titulaire d'AMM : un
    fabricant ou un grossiste n'avait jusqu'ici aucune page d'accueil qui lui
    parle. La composition vient de tableau_de_bord.COMPOSITION ; cette route
    ne fait que l'alimenter.
    """
    import tableau_de_bord as tdb

    u = current_user()
    if u is None or not u.est_externe:
        abort(403)
    fiche = tdb.composition(u)
    if fiche is None:
        abort(403)

    contexte = {
        "u": u, "fiche": fiche,
        "societe": (u.etablissement.raison_sociale if u.etablissement
                    else u.nom_complet),
        "valeurs": tdb.indicateurs(u),
        "a_faire": tdb.a_faire(u),
        "prochaine_action": tdb.prochaine_action,
        "fenetre": tdb.FENETRE_RECENTS_JOURS,
        "STATUTS": wf.STATUTS, "TYPES": wf.TYPES_PROCEDURE,
    }
    # Chaque section n'est alimentée que si le profil la réclame.
    if "recents" in fiche["sections"]:
        contexte["recents"] = tdb.dossiers_recents(u)
    if "echeances" in fiche["sections"]:
        contexte["a_renouveler"] = esp.amm_a_renouveler(u)
    if "agrements" in fiche["sections"]:
        from models import DemandeLicence
        etab = u.etablissement_rattachement_id
        contexte["agrements"] = (
            DemandeLicence.query.filter_by(etablissement_id=etab)
            .order_by(DemandeLicence.id.desc()).limit(5).all() if etab else [])
    if "inspections" in fiche["sections"]:
        contexte["inspections"] = esp.demandes_inspection(u)[:5]
    if "protocoles" in fiche["sections"]:
        from models import ProtocoleEssaiClinique
        contexte["protocoles"] = (
            ProtocoleEssaiClinique.query
            .filter(ProtocoleEssaiClinique.promoteur_id.in_(
                esp.personnes_de_la_societe(u)))
            .order_by(ProtocoleEssaiClinique.id.desc()).limit(5).all())
    if "rappels" in fiche["sections"]:
        from models import SignalementQualite
        contexte["rappels"] = (
            SignalementQualite.query
            .filter(SignalementQualite.statut == "rappel_engage")
            .order_by(SignalementQualite.id.desc()).limit(5).all())
    return render_template("industriel/tableau_bord.html", **contexte)


# Tris proposés : (clé, libellé, expression). Déclarés ici pour que l'écran
# n'invente pas de colonne triable qui n'existe pas côté requête.
TRIS = {
    "recent": ("Mouvement le plus récent", DossierAMM.date_maj.desc()),
    "ancien": ("Mouvement le plus ancien", DossierAMM.date_maj.asc()),
    "reference": ("Référence", DossierAMM.numero.asc()),
    "statut": ("Statut", DossierAMM.statut.asc()),
}


@bp.route("/portefeuille")
@login_required
def portefeuille():
    """Tous les dossiers valides de la société, avec leur statut courant.

    « Valide » exclut les brouillons : un dossier jamais soumis n'est pas une
    pièce du portefeuille réglementaire, c'est une saisie en cours. Une case
    permet de les réintégrer, parce que leur auteur, lui, veut les retrouver.
    """
    import matrice_acces
    import tableau_de_bord as tdb

    u = current_user()
    if u is None or not u.est_externe:
        abort(403)

    # Le portefeuille d'un fabricant ou d'un grossiste n'est pas fait de
    # dossiers d'AMM mais d'agréments : leur servir une liste d'AMM
    # invariablement vide serait pire que ne rien leur montrer.
    if not matrice_acces.acte_concerne(u, "homologation"):
        return _portefeuille_agrements(u)

    statut = request.args.get("statut", "").strip()
    type_proc = request.args.get("type", "").strip()
    recherche = request.args.get("q", "").strip()
    tri = request.args.get("tri", "recent")
    if tri not in TRIS:
        tri = "recent"
    avec_brouillons = request.args.get("brouillons") == "1"

    q = esp.dossiers_de_la_societe(u)
    if statut:
        q = q.filter(DossierAMM.statut == statut)
    elif not avec_brouillons:
        q = q.filter(DossierAMM.statut != "brouillon")
    if type_proc:
        q = q.filter(DossierAMM.type_procedure == type_proc)
    if recherche:
        motif = f"%{recherche}%"
        q = (q.outerjoin(Produit, DossierAMM.produit_id == Produit.id)
             .filter(db.or_(DossierAMM.numero.ilike(motif),
                            DossierAMM.numero_suivi.ilike(motif),
                            Produit.nom_commercial.ilike(motif),
                            Produit.denomination_commune_internationale
                            .ilike(motif))))

    dossiers = q.order_by(TRIS[tri][1]).all()
    return render_template(
        "industriel/portefeuille.html", u=u, dossiers=dossiers,
        statut=statut, type_proc=type_proc, recherche=recherche, tri=tri,
        avec_brouillons=avec_brouillons, TRIS=TRIS,
        prochaine_action=tdb.prochaine_action,
        STATUTS=wf.STATUTS, TYPES=wf.TYPES_PROCEDURE)


def _portefeuille_agrements(u):
    """Portefeuille des profils dont l'objet réglementaire est l'agrément."""
    from models import DemandeLicence
    import workflow_agrement as wfa
    import workflow_li as wfli

    etab = u.etablissement_rattachement_id
    recherche = request.args.get("q", "").strip()
    statut = request.args.get("statut", "").strip()

    q = DemandeLicence.query.filter(DemandeLicence.etablissement_id == etab)         if etab else DemandeLicence.query.filter(db.text("0"))
    if statut:
        q = q.filter(DemandeLicence.statut == statut)
    if recherche:
        q = q.filter(DemandeLicence.numero.ilike(f"%{recherche}%"))
    demandes = q.order_by(DemandeLicence.id.desc()).all()

    return render_template(
        "industriel/portefeuille_agrements.html", u=u, demandes=demandes,
        etablissement=u.etablissement, statut=statut, recherche=recherche,
        intitule=wfa.intitule, STATUTS=wfli.STATUTS_DEMANDE)


# ---------------------------------------------------------------------------
# Suivi unifié — « où en est mon dossier ? »
# ---------------------------------------------------------------------------
@bp.route("/suivi")
@login_required
def suivi_liste():
    """Vue transversale : l'état de chaque dossier et son délai d'instruction."""
    u = _verifier_profil()
    lignes = []
    for d in esp.dossiers_de_la_societe(u).order_by(DossierAMM.date_maj.desc()).all():
        lignes.append({
            "dossier": d,
            "etat": suivi.etat_visible(d),
            "delai": suivi.etat_delai(d, suivi.delai_legal(d)),
            "legal": suivi.delai_legal(d),
        })
    return render_template(
        "industriel/suivi.html", u=u, lignes=lignes,
        LIBELLE_ETAT=suivi.LIBELLE_ETAT, TYPES=wf.TYPES_PROCEDURE,
        en_retard=sum(1 for l in lignes if l["delai"]["depasse"]),
        suspendus=sum(1 for l in lignes if l["delai"]["suspendu"]))


@bp.route("/suivi/<int:dossier_id>")
@login_required
def suivi_dossier(dossier_id):
    """Parcours détaillé d'un dossier : étapes franchies, délai, historique."""
    import amm_signee

    u, d = _dossier_de_ma_societe(dossier_id)
    legal = suivi.delai_legal(d)
    paiements = (Paiement.query
                 .filter_by(entite_type="DossierAMM", entite_id=d.id)
                 .order_by(Paiement.id.desc()).all())
    return render_template(
        "industriel/suivi_dossier.html", u=u, d=d,
        amm_signee=amm_signee.piece_signee(d),
        etapes=suivi.etapes_parcours(d), etat=suivi.etat_visible(d),
        delai=suivi.etat_delai(d, legal), legal=legal,
        fonction=suivi.LIBELLE_FONCTION[suivi.fonction_du_dossier(d)],
        jalons=suivi.jalons_publics(d), paiements=paiements,
        LIBELLE_ETAT=suivi.LIBELLE_ETAT, LIBELLE_PAIEMENT=pmt.LIBELLE_STATUT,
        TYPES=wf.TYPES_PROCEDURE, STATUTS=wf.STATUTS)


# ---------------------------------------------------------------------------
# Déposer une demande
# ---------------------------------------------------------------------------
@bp.route("/nouvelle-demande")
@login_required
def nouvelle_demande():
    """Ancien point d'entrée, conservé en redirection.

    Il existait ici un second écran de dépôt, concurrent de « Demande »
    (/demandes/). Deux portes vers la même démarche finissent toujours par
    diverger — celle-ci court-circuitait déjà les pages par type de procédure
    et leur préremplissage. Une seule porte subsiste ; l'URL reste valide pour
    ne casser aucun signet.
    """
    _verifier_profil()
    return redirect(url_for("demandes.accueil"))


# ---------------------------------------------------------------------------
# Demandes d'inspection (site national ou à l'étranger)
# ---------------------------------------------------------------------------
@bp.route("/inspections", methods=["GET", "POST"])
@login_required
def inspections():
    u = _verifier_inspection()
    if request.method == "POST":
        try:
            d = wfdi.deposer(
                u, request.form.get("site_nom", ""), request.form.get("site_pays", ""),
                request.form.get("motif", ""), request.form.get("site_adresse", ""),
                request.form.get("site_contact", ""),
                request.form.get("produits_concernes", ""),
                request.form.get("periode_souhaitee", ""))
            db.session.commit()
            flash(f"Demande d'inspection {d.numero} déposée. Un accusé de réception "
                  "vous a été adressé.", "success")
            return redirect(url_for("industriel.inspections"))
        except ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("industriel/inspections.html", u=u,
                           demandes=esp.demandes_inspection(u), STATUTS=wfdi.STATUTS)


@bp.route("/inspections/<int:demande_id>")
@login_required
def detail_inspection(demande_id):
    u = _verifier_inspection()
    d = db.session.get(DemandeInspection, demande_id)
    if not d or d.demandeur_id not in esp.personnes_de_la_societe(u):
        abort(404)
    return render_template("industriel/detail_inspection.html", u=u, d=d,
                           STATUTS=wfdi.STATUTS)
