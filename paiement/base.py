"""
Socle de la plateforme de paiement : contrat commun à tous les fournisseurs,
primitives de sécurité et types de retour.

PRINCIPE D'ARCHITECTURE
-----------------------
Chaque moyen de paiement (virement, carte, mobile money) est un `Fournisseur`
qui implémente le même contrat. Le reste de l'application ne connaît que ce
contrat : ajouter un opérateur (Wave, Moov, un nouveau PSP carte) revient à
écrire une classe, sans toucher aux routes ni aux workflows.

TROIS FAMILLES DE FLUX
----------------------
* `redirection`  — carte bancaire : l'usager part sur la page 3-D Secure du
                   PSP, revient, et c'est le webhook qui fait foi.
* `push`         — mobile money : une demande de paiement est poussée sur le
                   téléphone (USSD/appli), puis on interroge le statut.
* `hors_ligne`   — virement bancaire : coordonnées + référence à rappeler,
                   encaissement constaté a posteriori par rapprochement.

SÉCURITÉ (commune à tous les fournisseurs)
------------------------------------------
1. Idempotence par référence marchande unique.
2. Notifications signées, vérifiées en comparaison à temps constant.
3. Contrôle strict montant + devise avant toute confirmation.
4. Anti-rejeu par horodatage signé.
5. Aucune donnée de carte ou de compte mobile stockée par SIREPH.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

TOLERANCE_NOTIFICATION_SECONDES = 900


class ErreurPaiement(Exception):
    """Erreur fonctionnelle de paiement (montant, signature, état incohérent)."""


class ErreurConfiguration(ErreurPaiement):
    """Le fournisseur n'est pas configuré : identifiants marchands manquants."""


# ---------------------------------------------------------------------------
# Types de retour
# ---------------------------------------------------------------------------
@dataclass
class Initiation:
    """Résultat de l'ouverture d'une session de paiement."""
    flux: str                      # redirection | push | hors_ligne
    reference_marchande: str
    expire_le: datetime
    url_redirection: str | None = None      # flux `redirection`
    instructions: dict = field(default_factory=dict)  # flux `hors_ligne` / `push`
    simulation: bool = False


@dataclass
class Resultat:
    """Issue d'une notification ou d'une interrogation de statut."""
    etat: str                      # confirme | echoue | en_cours | deja_confirme
    reference_transaction: str | None = None
    detail: str | None = None


# ---------------------------------------------------------------------------
# Primitives de sécurité
# ---------------------------------------------------------------------------
_SECRETS_SIMULATION: dict[str, str] = {}


def secret_fournisseur(code: str) -> str:
    """Secret de signature du fournisseur.

    Lu dans l'environnement (`SIREPH_PSP_<CODE>_SECRET`). À défaut, un secret
    de session est généré : suffisant pour la simulation, inutilisable en
    production puisqu'il change à chaque redémarrage.
    """
    cle = os.getenv(f"SIREPH_PSP_{code.upper()}_SECRET")
    if cle:
        return cle
    if code not in _SECRETS_SIMULATION:
        _SECRETS_SIMULATION[code] = secrets.token_hex(32)
    return _SECRETS_SIMULATION[code]


def _canonique(payload: dict) -> bytes:
    sans_sig = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(sans_sig, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def signer(payload: dict, code_fournisseur: str) -> str:
    return hmac.new(secret_fournisseur(code_fournisseur).encode("utf-8"),
                    _canonique(payload), hashlib.sha256).hexdigest()


def verifier_signature(payload: dict, code_fournisseur: str) -> bool:
    """Comparaison à temps constant : ne fuit rien par le temps de calcul."""
    return hmac.compare_digest(signer(payload, code_fournisseur),
                               payload.get("signature", ""))


def horodatage_valide(payload: dict) -> bool:
    try:
        emis = datetime.fromisoformat(payload["horodatage"])
    except (KeyError, ValueError, TypeError):
        return False
    return abs((datetime.utcnow() - emis).total_seconds()) <= TOLERANCE_NOTIFICATION_SECONDES


def nouvelle_reference(prefixe: str = "MRC") -> str:
    """Référence marchande unique et non devinable (clé d'idempotence)."""
    return f"{prefixe}-{datetime.utcnow():%Y%m%d}-{secrets.token_urlsafe(10)}"


def controler_montant(payload: dict, paiement) -> None:
    """Refuse toute notification dont le montant ou la devise diverge."""
    try:
        montant = int(payload.get("montant", -1))
    except (TypeError, ValueError):
        raise ErreurPaiement("Montant notifié illisible.")
    if montant != int(paiement.montant):
        raise ErreurPaiement(
            f"Montant notifié ({montant}) différent du montant attendu "
            f"({paiement.montant}) — notification rejetée.")
    if payload.get("devise") != paiement.devise:
        raise ErreurPaiement("Devise non concordante — notification rejetée.")


# ---------------------------------------------------------------------------
# Contrat commun
# ---------------------------------------------------------------------------
class Fournisseur:
    """Contrat que doit respecter tout moyen de paiement."""

    code: str = ""
    libelle: str = ""
    famille: str = ""          # carte | mobile | virement
    flux: str = ""             # redirection | push | hors_ligne
    icone: str = "bi-credit-card"
    # Préfixe de la référence marchande : rend le moyen de paiement lisible
    # d'un coup d'œil sur un relevé ou dans le journal d'audit.
    prefixe_ref: str = "MRC"
    delai_expiration_minutes: int = 30
    # Frais de service éventuels appliqués par l'opérateur, en pour mille.
    frais_pour_mille: int = 0

    # -- Configuration ------------------------------------------------------
    def configure(self) -> bool:
        """Des identifiants marchands réels sont-ils disponibles ?"""
        return False

    def etat_configuration(self) -> str:
        return "Prestataire raccordé" if self.configure() else "Simulation (non raccordé)"

    # -- Cycle de vie -------------------------------------------------------
    def initier(self, paiement, contexte: dict) -> Initiation:
        raise NotImplementedError

    def interroger(self, paiement) -> Resultat:
        """Interroge le statut auprès du prestataire (flux `push` surtout)."""
        return Resultat(etat="en_cours")

    def traiter_notification(self, payload: dict, paiement) -> Resultat:
        """Vérifie et interprète une notification. Ne persiste rien."""
        if not verifier_signature(payload, self.code):
            raise ErreurPaiement("Signature de notification invalide — rejetée.")
        if not horodatage_valide(payload):
            raise ErreurPaiement("Notification hors fenêtre de validité (rejeu probable).")
        if payload.get("reference_marchande") != paiement.reference_marchande:
            raise ErreurPaiement("Référence marchande non concordante.")
        if paiement.statut == "confirme":
            return Resultat(etat="deja_confirme")
        controler_montant(payload, paiement)
        if payload.get("statut") == "succes":
            return Resultat(etat="confirme",
                            reference_transaction=payload.get("reference_transaction"))
        return Resultat(etat="echoue",
                        detail=payload.get("motif", "Paiement refusé par le prestataire."))

    # -- Simulation ---------------------------------------------------------
    def notification_simulee(self, paiement, succes: bool = True) -> dict:
        """Construit la notification signée qu'émettrait le prestataire."""
        payload = {
            "reference_marchande": paiement.reference_marchande,
            "reference_transaction": f"{self.code.upper()}-{secrets.token_hex(6).upper()}",
            "montant": paiement.montant,
            "devise": paiement.devise,
            "statut": "succes" if succes else "echec",
            "horodatage": datetime.utcnow().isoformat(),
        }
        if not succes:
            payload["motif"] = "Solde insuffisant (simulation)."
        payload["signature"] = signer(payload, self.code)
        return payload

    # -- Utilitaires --------------------------------------------------------
    def expiration(self) -> datetime:
        return datetime.utcnow() + timedelta(minutes=self.delai_expiration_minutes)

    def frais(self, montant: int) -> int:
        return round(montant * self.frais_pour_mille / 1000)
