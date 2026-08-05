"""
Deux documents distincts au terme du circuit, et une seule pièce opposable.

LE CERTIFICAT D'HOMOLOGATION (généré)
-------------------------------------
Produit automatiquement à la dernière signature. Il récapitule la décision et
le parcours de validation. C'est un SUPPORT INTERNE : il sert de pièce
justificative à la chaîne réglementaire et de base à l'établissement de l'acte
ministériel. Tout agent, à tout échelon, doit pouvoir le consulter — sinon la
signature du ministre s'appuie sur un document que ses services n'ont pas vu.

Il n'est **pas** remis au demandeur. Un certificat généré par le système, sans
signature manuscrite ni sceau, se prête trop bien à un usage abusif : présenté
à un douanier ou à un acheteur, rien ne le distingue d'une autorisation en
bonne et due forme.

L'AMM SIGNÉE (téléversée)
-------------------------
L'acte réel, signé de la main du ministre, scanné et déposé sur la plateforme
par le chef de service. C'est LUI, et lui seul, que le demandeur télécharge.

Son dépôt fixe la durée de validité de l'autorisation : le service saisit la
durée au moment du téléversement, ce qui arme les rappels de renouvellement
(J-180, soit six mois avant l'échéance, puis J-90 et J-30).
"""
from datetime import date, datetime

from audit import enregistrer_audit
from erreurs import ErreurWorkflow
from models import PieceJointe, db
from notifications import notifier

# Type de pièce réservé : c'est la clé qui distingue l'acte opposable de tous
# les autres documents d'un dossier.
TYPE_AMM_SIGNEE = "AMM signée du ministre"

# Qui dépose l'acte signé. Le chef de service reçoit le parapheur retourné du
# cabinet ; c'est à lui qu'incombe la mise en ligne.
ROLES_DEPOT = ("chef_service_amm", "chef_bureau", "administrateur_dpml")

DUREE_DEFAUT_ANNEES = 5          # repli si le paramètre n'est pas initialisé
DUREE_MAX_ANNEES = 15


def duree_par_defaut():
    """Durée proposée à la saisie, tirée du paramètre administrable du module."""
    from delais import get_parametre
    try:
        return int(get_parametre("MA", "duree_validite_amm_annees",
                                 default=DUREE_DEFAUT_ANNEES))
    except (TypeError, ValueError):
        return DUREE_DEFAUT_ANNEES


def piece_signee(dossier):
    """L'AMM signée déposée pour ce dossier, ou None."""
    return (PieceJointe.query
            .filter_by(entite_type="DossierAMM", entite_id=dossier.id,
                       type_document=TYPE_AMM_SIGNEE)
            .order_by(PieceJointe.id.desc()).first())


def est_disponible(dossier):
    """Le demandeur a-t-il quelque chose à télécharger ?"""
    return piece_signee(dossier) is not None


def _echeance(depart, duree_annees):
    """Date d'expiration à durée constante, sans dériver sur les bissextiles."""
    try:
        return depart.replace(year=depart.year + duree_annees)
    except ValueError:                       # 29 février
        return depart.replace(month=2, day=28, year=depart.year + duree_annees)


def deposer(dossier, fichier, acteur, duree_annees, date_signature=None):
    """Dépose l'AMM signée et arme le compte à rebours du renouvellement.

    Le circuit de signature doit être achevé : déposer un acte « signé » sur un
    dossier que le ministre n'a pas encore validé reviendrait à antidater une
    décision.
    """
    import validation_numerique as vn
    from pieces import enregistrer_piece

    if acteur is None or acteur.role_systeme not in ROLES_DEPOT:
        raise ErreurWorkflow(
            "Le dépôt de l'acte signé relève du chef de service.")
    if not vn.circuit_acheve(dossier):
        raise ErreurWorkflow(
            "Le circuit de validation n'est pas achevé : l'acte signé ne peut "
            "pas être déposé avant la signature du ministre.")
    try:
        duree = int(duree_annees)
    except (TypeError, ValueError):
        raise ErreurWorkflow("La durée de validité doit être un nombre d'années.")
    if not 1 <= duree <= DUREE_MAX_ANNEES:
        raise ErreurWorkflow(
            f"La durée de validité doit être comprise entre 1 et "
            f"{DUREE_MAX_ANNEES} ans.")

    signature = date_signature or date.today()
    if signature > date.today():
        raise ErreurWorkflow("La date de signature ne peut pas être future.")

    piece = enregistrer_piece(dossier, fichier, TYPE_AMM_SIGNEE, acteur)

    dossier.date_validite_amm = _echeance(signature, duree)
    if not dossier.date_decision:
        dossier.date_decision = datetime.utcnow()
    # Le produit devient effectivement commercialisable : c'est le dépôt de
    # l'acte, non la signature interne, qui ouvre le marché.
    if dossier.produit is not None:
        dossier.produit.statut_amm_courant = "active"

    enregistrer_audit(
        dossier,
        f"AMM signée du ministre déposée — validité {duree} an(s), "
        f"jusqu'au {dossier.date_validite_amm.strftime('%d/%m/%Y')}",
        acteur, commentaire=piece.nom_fichier)

    if dossier.demandeur:
        notifier(dossier.demandeur, "amm_signee_disponible",
                 f"Votre autorisation de mise sur le marché {dossier.numero}, "
                 f"signée par le ministre, est disponible au téléchargement. "
                 f"Elle est valable jusqu'au "
                 f"{dossier.date_validite_amm.strftime('%d/%m/%Y')} ; un rappel "
                 "de renouvellement vous sera adressé six mois avant "
                 "l'échéance.",
                 lien=f"/industriel/suivi/{dossier.id}")
    return piece


def peut_deposer(dossier, acteur):
    """Le bouton de dépôt doit-il être proposé à cet agent ?"""
    import validation_numerique as vn

    return (acteur is not None
            and acteur.role_systeme in ROLES_DEPOT
            and vn.circuit_acheve(dossier)
            and not est_disponible(dossier))
