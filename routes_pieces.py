"""
Téléchargement de pièces jointes — route générique, avec contrôle d'accès
dérivé du type d'entité parente.

RÈGLE D'ACCÈS
-------------
* Tout agent de l'administration (niveau ≥ 1) lit les pièces d'un dossier.
  C'est la condition d'une validation objective : un sous-directeur, un
  inspecteur général ou le ministre signent au vu du dossier, non d'un résumé.
  La liste nominative de rôles qui figurait ici excluait de fait tous les
  échelons de la chaîne au-dessus de l'évaluateur.
* Un opérateur externe ne lit que les pièces de SA société — le cloisonnement
  porte sur l'établissement, pas sur la seule personne qui a déposé.
"""
from flask import Blueprint, abort, send_from_directory

from auth import current_user, login_required
from models import DemandeLicence, DossierAMM, Paiement, PieceJointe, db
from pieces import DOCUMENTS_DIR

pieces_bp = Blueprint("pieces", __name__)


def _acces_externe(entite_type, entite_id, u):
    """L'opérateur externe accède-t-il à cette entité au titre de sa société ?"""
    import espace_industriel as esp

    if entite_type == "DossierAMM":
        dossier = db.session.get(DossierAMM, entite_id)
        return (dossier is not None
                and dossier.demandeur_id in esp.personnes_de_la_societe(u))
    if entite_type == "DemandeLicence":
        demande = db.session.get(DemandeLicence, entite_id)
        return (demande is not None
                and u.etablissement_rattachement_id is not None
                and demande.etablissement_id == u.etablissement_rattachement_id)
    return False


def _verifier_acces_entite(entite_type, entite_id, u):
    """Une preuve de paiement (entite_type == "Paiement") emprunte les droits
    d'accès de son entité parente (DossierAMM/DemandeLicence)."""
    from permissions import a_niveau

    if entite_type == "Paiement":
        paiement = db.session.get(Paiement, entite_id)
        if not paiement:
            abort(404)
        entite_type, entite_id = paiement.entite_type, paiement.entite_id

    if a_niveau(u, 1):                       # tout agent de l'administration
        return
    if _acces_externe(entite_type, entite_id, u):
        return
    abort(404)      # 404 plutôt que 403 : ne révèle pas l'existence de la pièce


@pieces_bp.route("/documents/<int:piece_id>/telecharger")
@login_required
def telecharger(piece_id):
    piece = PieceJointe.query.get_or_404(piece_id)
    _verifier_acces_entite(piece.entite_type, piece.entite_id, current_user())
    return send_from_directory(DOCUMENTS_DIR, piece.chemin_fichier,
                                as_attachment=True, download_name=piece.nom_fichier)
