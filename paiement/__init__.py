"""
Plateforme de paiement SIREPH — point d'entrée public.

    from paiement import obtenir, disponibles, ErreurPaiement

Les moyens de paiement raccordés sont décrits dans `fournisseurs.py`, le
contrat commun et les primitives de sécurité dans `base.py`.
"""
from .base import (ErreurConfiguration, ErreurPaiement, Fournisseur, Initiation,
                   Resultat, nouvelle_reference, signer, verifier_signature)
from .fournisseurs import (FOURNISSEURS, ORDRE_AFFICHAGE, CarteBancaire,
                           MobileMoney, MtnMomo, OrangeMoney, VirementBancaire,
                           disponibles, obtenir)

__all__ = [
    "ErreurPaiement", "ErreurConfiguration", "Fournisseur", "Initiation", "Resultat",
    "nouvelle_reference", "signer", "verifier_signature",
    "FOURNISSEURS", "ORDRE_AFFICHAGE", "obtenir", "disponibles",
    "VirementBancaire", "CarteBancaire", "MobileMoney", "MtnMomo", "OrangeMoney",
]
