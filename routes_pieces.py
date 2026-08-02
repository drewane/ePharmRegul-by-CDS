"""
Téléchargement de pièces jointes — route générique, avec contrôle d'accès
dérivé du type d'entité parente : le demandeur ne peut télécharger que les
pièces de ses propres dossiers ; le personnel DPML concerné par ce module
peut tout voir.
"""
from flask import Blueprint, abort, send_from_directory

from models import DossierAMM, DemandeLicence, Paiement, PieceJointe
from auth import current_user, login_required
from pieces import DOCUMENTS_DIR

pieces_bp = Blueprint("pieces", __name__)

ROLES_INTERNES_PAR_ENTITE = {
    "DossierAMM": ("administrateur_dpml", "evaluateur_amm", "directeur_dpml"),
    "DemandeLicence": ("administrateur_dpml", "agent_licences", "directeur_dpml"),
}


def _verifier_acces_entite(entite_type, entite_id, u):
    """Une preuve de paiement (entite_type == "Paiement") emprunte les droits
    d'accès de son entité parente (DossierAMM/DemandeLicence) : administrateur_dpml
    valide tous les paiements, quel que soit le module."""
    if entite_type == "Paiement":
        paiement = Paiement.query.get(entite_id)
        if not paiement:
            abort(403)
        if u.role_systeme == "administrateur_dpml":
            return
        entite_type, entite_id = paiement.entite_type, paiement.entite_id

    if u.role_systeme in ROLES_INTERNES_PAR_ENTITE.get(entite_type, ()):
        return
    if u.role_systeme == "demandeur_externe":
        if entite_type == "DossierAMM":
            dossier = DossierAMM.query.get(entite_id)
            if dossier and dossier.demandeur_id == u.id:
                return
        elif entite_type == "DemandeLicence":
            demande = DemandeLicence.query.get(entite_id)
            if demande and u.etablissement_rattachement_id and demande.etablissement_id == u.etablissement_rattachement_id:
                return
    abort(403)


@pieces_bp.route("/documents/<int:piece_id>/telecharger")
@login_required
def telecharger(piece_id):
    piece = PieceJointe.query.get_or_404(piece_id)
    _verifier_acces_entite(piece.entite_type, piece.entite_id, current_user())
    return send_from_directory(DOCUMENTS_DIR, piece.chemin_fichier,
                                as_attachment=True, download_name=piece.nom_fichier)
