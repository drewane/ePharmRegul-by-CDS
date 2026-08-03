"""
Espace de l'industriel / titulaire d'AMM.

CLOISONNEMENT PAR SOCIÉTÉ
-------------------------
Un industriel ne voit QUE ce qui relève de sa propre société. Le périmètre
n'est pas l'utilisateur mais l'établissement : deux collaborateurs d'UPSA
voient le même portefeuille, et jamais celui d'un concurrent.

Le rattachement se fait par `Personne.etablissement_rattachement_id`. À défaut
d'établissement (compte isolé), le périmètre se réduit à l'utilisateur lui-même
— jamais à l'ensemble des dossiers.
"""
from datetime import date, timedelta

from models import (DemandeInspection, DossierAMM, Personne, Produit, db)

# Un renouvellement s'anticipe : on alerte le titulaire dans ce délai.
PREAVIS_RENOUVELLEMENT_JOURS = 180


def personnes_de_la_societe(user):
    """Identifiants des comptes rattachés au même établissement."""
    if user is None:
        return []
    if not user.etablissement_rattachement_id:
        return [user.id]
    return [p.id for p in Personne.query.filter_by(
        etablissement_rattachement_id=user.etablissement_rattachement_id).all()]


def dossiers_de_la_societe(user):
    """Requête des dossiers d'AMM de la société — socle de tout l'espace."""
    return DossierAMM.query.filter(
        DossierAMM.demandeur_id.in_(personnes_de_la_societe(user)))


def produits_de_la_societe(user):
    """Produits dont la société est titulaire, ou sur lesquels elle a déposé."""
    q = dossiers_de_la_societe(user)
    ids = {d.produit_id for d in q.all() if d.produit_id}
    if user is not None and user.etablissement_rattachement_id:
        ids |= {p.id for p in Produit.query.filter_by(
            titulaire_amm_id=user.etablissement_rattachement_id).all()}
    return Produit.query.filter(Produit.id.in_(ids or [-1])).all()


def amm_a_renouveler(user, preavis_jours=PREAVIS_RENOUVELLEMENT_JOURS):
    """AMM en vigueur dont l'échéance approche, ou déjà dépassée.

    Renvoie une liste de (dossier, jours restants) triée par urgence : un
    nombre négatif signale une AMM expirée.
    """
    limite = date.today() + timedelta(days=preavis_jours)
    dossiers = (dossiers_de_la_societe(user)
                .filter(DossierAMM.statut == "approuve",
                        DossierAMM.date_validite_amm.isnot(None),
                        DossierAMM.date_validite_amm <= limite)
                .order_by(DossierAMM.date_validite_amm).all())
    aujourdhui = date.today()
    return [(d, (d.date_validite_amm - aujourdhui).days) for d in dossiers]


def synthese(user):
    """Chiffres du tableau de bord, strictement limités à la société."""
    q = dossiers_de_la_societe(user)
    tous = q.all()

    def compte(*statuts):
        return sum(1 for d in tous if d.statut in statuts)

    en_cours = compte("soumis", "recevable", "evaluation_en_cours", "complement_requis")
    a_renouveler = amm_a_renouveler(user)

    return {
        "total": len(tous),
        "brouillons": compte("brouillon"),
        "en_cours": en_cours,
        "complement_requis": compte("complement_requis"),
        "approuves": compte("approuve"),
        "rejetes": compte("rejete", "irrecevable"),
        "clotures": compte("cloture_delai_depasse"),
        "a_renouveler": len(a_renouveler),
        "expirees": sum(1 for _d, j in a_renouveler if j < 0),
        "par_type": {
            t: sum(1 for d in tous if d.type_procedure == t)
            for t in ("nouvelle_demande", "renouvellement", "variation", "retrait")
        },
    }


def demandes_inspection(user):
    return (DemandeInspection.query
            .filter(DemandeInspection.demandeur_id.in_(personnes_de_la_societe(user)))
            .order_by(DemandeInspection.id.desc()).all())


def dossiers_recents(user, limite=10):
    return (dossiers_de_la_societe(user)
            .order_by(DossierAMM.date_maj.desc()).limit(limite).all())
