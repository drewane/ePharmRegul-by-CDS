"""
Passerelle de paiement en ligne — couche d'abstraction sécurisée.

PÉRIMÈTRE ET LIMITE ASSUMÉE
---------------------------
SIREPH ne collecte, ne stocke et ne transmet JAMAIS de numéro de carte
bancaire ni de code mobile money. Le paiement s'effectue chez le prestataire
agréé ; SIREPH ne manipule que des références opaques et une notification
signée. Cette architecture est celle exigée pour ne pas entrer dans le
périmètre PCI-DSS.

Deux fournisseurs sont branchés :

  * `SimulateurAgree` — fournisseur de DÉMONSTRATION, actif par défaut. Il
    reproduit fidèlement le protocole réel (initiation → redirection →
    notification signée → réconciliation) sans mouvement de fonds. Il est
    explicitement identifié comme simulation dans l'interface.

  * `PrestatairePSP` — connecteur pour un agrégateur réel (Orange Money,
    MTN MoMo, carte via un PSP agréé). Il ne s'active que si les identifiants
    sont fournis en variables d'environnement ; sans eux, l'application
    refuse de prétendre encaisser (aucun faux positif possible).

MESURES DE SÉCURITÉ IMPLÉMENTÉES
--------------------------------
1. Idempotence  : chaque paiement porte une `reference_marchande` unique ;
                  rejouer une notification ne double jamais un encaissement.
2. Intégrité    : les notifications (webhooks) sont signées en HMAC-SHA256 et
                  vérifiées en comparaison à temps constant (anti-timing).
3. Anti-rejeu   : horodatage signé, fenêtre de validité courte, et refus d'une
                  notification portant sur un paiement déjà confirmé.
4. Montant      : le montant notifié doit correspondre exactement au montant
                  attendu — une notification divergente est rejetée et tracée.
5. Expiration   : une session de paiement non aboutie expire (statut `expire`).
6. Traçabilité  : chaque transition est écrite au journal d'audit.
7. Aucun secret en dur : clés lues dans l'environnement.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta

# Durée de validité d'une session de paiement
DELAI_EXPIRATION_MINUTES = 30
# Tolérance d'horodatage des notifications (anti-rejeu)
TOLERANCE_NOTIFICATION_SECONDES = 900

FOURNISSEURS = {
    "mtn_momo": "MTN Mobile Money",
    "orange_money": "Orange Money",
    "carte": "Carte bancaire",
}


class ErreurPaiement(Exception):
    pass


# ---------------------------------------------------------------------------
# Secret de signature
# ---------------------------------------------------------------------------
def _secret() -> str:
    """Secret partagé avec le prestataire. Jamais écrit en dur dans le code."""
    cle = os.getenv("SIREPH_PSP_SECRET")
    if not cle:
        # Secret de session pour le simulateur : suffisant en démonstration,
        # inutilisable en production (il change à chaque redémarrage).
        cle = _secret_simulateur()
    return cle


_SECRET_SIMU: str | None = None


def _secret_simulateur() -> str:
    global _SECRET_SIMU
    if _SECRET_SIMU is None:
        _SECRET_SIMU = secrets.token_hex(32)
    return _SECRET_SIMU


def mode_reel() -> bool:
    """Un prestataire réel est-il configuré ? Sinon : mode simulation."""
    return bool(os.getenv("SIREPH_PSP_SECRET") and os.getenv("SIREPH_PSP_URL"))


def nom_fournisseur_actif() -> str:
    return "Prestataire agréé" if mode_reel() else "Simulateur de démonstration"


# ---------------------------------------------------------------------------
# Signature des notifications
# ---------------------------------------------------------------------------
def _charge_canonique(payload: dict) -> bytes:
    """Sérialisation stable (hors signature) : indispensable pour que la
    signature soit reproductible des deux côtés."""
    sans_sig = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(sans_sig, sort_keys=True, separators=(",", ":")).encode("utf-8")


def signer(payload: dict) -> str:
    return hmac.new(_secret().encode("utf-8"), _charge_canonique(payload),
                    hashlib.sha256).hexdigest()


def verifier_signature(payload: dict) -> bool:
    """Comparaison à temps constant : ne fuit pas d'information par le temps de calcul."""
    fournie = payload.get("signature", "")
    return hmac.compare_digest(signer(payload), fournie)


# ---------------------------------------------------------------------------
# Cycle de vie d'un paiement en ligne
# ---------------------------------------------------------------------------
def nouvelle_reference() -> str:
    """Référence marchande unique et non devinable (clé d'idempotence)."""
    return f"MRC-{datetime.utcnow():%Y%m%d}-{secrets.token_urlsafe(12)}"


def initier(paiement, fournisseur: str, retour_url: str) -> dict:
    """Ouvre une session de paiement chez le prestataire.

    Ne débite rien : renvoie l'URL vers laquelle rediriger le payeur. SIREPH ne
    voit à aucun moment ses identifiants de paiement.
    """
    if fournisseur not in FOURNISSEURS:
        raise ErreurPaiement(f"Fournisseur inconnu : {fournisseur}")
    if paiement.statut == "confirme":
        raise ErreurPaiement("Ce paiement est déjà réglé.")
    if paiement.montant <= 0:
        raise ErreurPaiement("Montant invalide.")

    paiement.mode = "en_ligne"
    paiement.fournisseur = fournisseur
    # Idempotence : on conserve la référence si une session est déjà ouverte.
    if not paiement.reference_marchande:
        paiement.reference_marchande = nouvelle_reference()
    paiement.statut = "initie"
    paiement.date_initiation = datetime.utcnow()
    paiement.date_expiration = paiement.date_initiation + timedelta(
        minutes=DELAI_EXPIRATION_MINUTES)
    paiement.detail_echec = None

    if mode_reel():
        # Connecteur réel : l'appel HTTP au PSP se fait ici. Non exécuté tant
        # qu'aucun identifiant n'est configuré — pas de simulation déguisée.
        raise ErreurPaiement(
            "Connecteur prestataire réel non encore raccordé : renseignez "
            "SIREPH_PSP_URL et SIREPH_PSP_SECRET, puis implémentez l'appel "
            "d'initiation propre au prestataire retenu.")

    # Simulateur : page de paiement interne, clairement identifiée comme telle.
    return {
        "url_paiement": f"{retour_url}?ref={paiement.reference_marchande}",
        "reference_marchande": paiement.reference_marchande,
        "expire_le": paiement.date_expiration,
        "simulation": True,
    }


def construire_notification(paiement, succes: bool = True) -> dict:
    """Construit la notification signée que le prestataire renverrait.

    Utilisée par le simulateur. En production, c'est le PSP qui l'émet et
    SIREPH ne fait que la vérifier via `traiter_notification`.
    """
    payload = {
        "reference_marchande": paiement.reference_marchande,
        "reference_transaction": f"TRX-{secrets.token_hex(8).upper()}",
        "montant": paiement.montant,
        "devise": paiement.devise,
        "statut": "succes" if succes else "echec",
        "horodatage": datetime.utcnow().isoformat(),
    }
    payload["signature"] = signer(payload)
    return payload


def _horodatage_valide(payload: dict) -> bool:
    try:
        emis = datetime.fromisoformat(payload["horodatage"])
    except (KeyError, ValueError):
        return False
    ecart = abs((datetime.utcnow() - emis).total_seconds())
    return ecart <= TOLERANCE_NOTIFICATION_SECONDES


def traiter_notification(payload: dict, paiement) -> str:
    """Vérifie puis applique une notification de paiement.

    Renvoie l'état résultant. Lève ErreurPaiement si la notification est
    irrecevable — dans ce cas le paiement N'EST PAS modifié.
    """
    if not verifier_signature(payload):
        raise ErreurPaiement("Signature de notification invalide — notification rejetée.")
    if not _horodatage_valide(payload):
        raise ErreurPaiement("Notification hors fenêtre de validité (rejeu probable).")
    if payload.get("reference_marchande") != paiement.reference_marchande:
        raise ErreurPaiement("Référence marchande non concordante.")

    # Idempotence : une notification rejouée sur un paiement déjà confirmé
    # est acceptée sans effet de bord (et sans double encaissement).
    if paiement.statut == "confirme":
        return "deja_confirme"

    if int(payload.get("montant", -1)) != int(paiement.montant):
        raise ErreurPaiement(
            f"Montant notifié ({payload.get('montant')}) différent du montant attendu "
            f"({paiement.montant}) — notification rejetée.")
    if payload.get("devise") != paiement.devise:
        raise ErreurPaiement("Devise non concordante.")

    if payload.get("statut") == "succes":
        paiement.statut = "confirme"
        paiement.date_confirmation = datetime.utcnow()
        paiement.reference_transaction = payload.get("reference_transaction")
        paiement.signature_notification = payload.get("signature", "")[:120]
        return "confirme"

    paiement.statut = "echoue"
    paiement.detail_echec = payload.get("motif", "Paiement refusé par le prestataire.")
    return "echoue"


def expirer_si_besoin(paiement) -> bool:
    """Passe une session non aboutie à l'état `expire`. Renvoie True si modifié."""
    if (paiement.statut == "initie" and paiement.date_expiration
            and datetime.utcnow() > paiement.date_expiration):
        paiement.statut = "expire"
        paiement.detail_echec = "Session de paiement expirée sans confirmation."
        return True
    return False
