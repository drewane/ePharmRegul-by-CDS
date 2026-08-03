"""
Volet régional CEEAC — contrat d'échange et service de reliance.

SOUVERAINETÉ (exigence non négociable)
--------------------------------------
Trois niveaux de confidentialité, appliqués par le contrat lui-même :

    publiable                 décision, statut d'AMM, alerte — circule librement
    partageable_sous_accord   rapport d'évaluation — exige un consentement tracé
    national                  pièces de dossier, ICC — NE CIRCULE JAMAIS

Une enveloppe classée « national » est refusée à la construction : le blocage
est structurel, pas déclaratif. Une donnée « partageable sous accord » sans
référence de consentement est refusée de la même manière.

RÉSILIENCE
----------
L'instance nationale ne dépend jamais du Hub pour fonctionner. Tout message
part d'abord dans une file locale ; si le Hub est injoignable, les messages y
restent et sont rejoués au rétablissement (idempotence par message_id).

RACCORDEMENT
------------
    SIREPH_HUB_URL      URL du Hub régional
    SIREPH_PAYS_CODE    code ISO de cette instance (défaut : CM)
    SIREPH_HUB_SECRET   secret de signature partagé avec le Hub

Sans SIREPH_HUB_URL, la reliance fonctionne en mode local : les messages
s'empilent dans la file et la consultation régionale interroge le registre
local. Rien n'est jamais prétendu transmis.
"""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime

from erreurs import ErreurWorkflow

CONTRAT_VERSION = "1.0"

TYPES_MESSAGE = ("consultation_regionale", "requete_reliance", "reponse_reliance",
                 "decision_publiee", "alerte")

NIVEAUX_CONFIDENTIALITE = ("publiable", "partageable_sous_accord", "national")

PORTEES_ACCORD = {
    "rapport_evaluation": "Rapport d'évaluation",
    "decision_seule": "Décision seule (sans rapport)",
    "dossier_complet": "Dossier complet",
}

TYPES_REQUETE = {
    "rapport_evaluation": "Demande de rapport d'évaluation",
    "clarification": "Demande de clarification",
    "statut_produit": "Vérification du statut d'un produit",
}

TYPES_ALERTE = {
    "rappel_lot": "Rappel de lot",
    "produit_falsifie": "Produit falsifié",
    "signal_vigilance": "Signal de pharmacovigilance",
    "retrait_amm": "Retrait d'AMM",
}

_SECRET_SESSION = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def pays_instance():
    return os.getenv("SIREPH_PAYS_CODE", "CM")


def url_hub():
    return (os.getenv("SIREPH_HUB_URL") or "").rstrip("/")


def hub_raccorde():
    return bool(url_hub())


def _secret():
    """Secret partagé avec le Hub. À défaut, secret de session (démonstration)."""
    global _SECRET_SESSION
    cle = os.getenv("SIREPH_HUB_SECRET")
    if cle:
        return cle
    if _SECRET_SESSION is None:
        _SECRET_SESSION = secrets.token_hex(32)
    return _SECRET_SESSION


# ---------------------------------------------------------------------------
# Contrat d'échange : construction et vérification des enveloppes signées
# ---------------------------------------------------------------------------
def _canonique(env):
    sans_sig = {k: v for k, v in env.items() if k != "signature"}
    return json.dumps(sans_sig, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def signer(env):
    return hmac.new(_secret().encode("utf-8"), _canonique(env), hashlib.sha256).hexdigest()


def verifier_signature(env):
    return hmac.compare_digest(signer(env), env.get("signature", ""))


def construire_enveloppe(type_message, destinataire, payload,
                          confidentialite="publiable", consentement_ref=None):
    """Construit et signe une enveloppe conforme au contrat.

    Refuse à la source tout envoi contraire à la souveraineté nationale.
    """
    if type_message not in TYPES_MESSAGE:
        raise ErreurWorkflow(f"Type de message hors contrat : {type_message}")
    if confidentialite not in NIVEAUX_CONFIDENTIALITE:
        raise ErreurWorkflow(f"Niveau de confidentialité inconnu : {confidentialite}")

    if confidentialite == "national":
        raise ErreurWorkflow(
            "Refus : une donnée classée « national » ne peut pas quitter le pays. "
            "Reclassez-la ou établissez un accord de partage.")
    if confidentialite == "partageable_sous_accord" and not consentement_ref:
        raise ErreurWorkflow(
            "Refus : un consentement explicite et tracé (accord de partage) est "
            "requis pour transmettre une donnée partageable sous accord.")

    env = {
        "version": CONTRAT_VERSION,
        "message_id": f"{pays_instance()}-{secrets.token_urlsafe(16)}",
        "type": type_message,
        "emetteur": pays_instance(),
        "destinataire": destinataire,
        "horodatage": datetime.utcnow().isoformat(),
        "confidentialite": confidentialite,
        "consentement_ref": consentement_ref,
        "payload": payload,
    }
    env["signature"] = signer(env)
    return env


def valider_enveloppe_entrante(env):
    """Contrôle une enveloppe reçue avant tout traitement."""
    for champ in ("version", "type", "emetteur", "destinataire", "horodatage",
                  "confidentialite", "payload", "signature"):
        if champ not in env:
            raise ErreurWorkflow(f"Enveloppe incomplète : champ « {champ} » manquant.")
    if env["version"] != CONTRAT_VERSION:
        raise ErreurWorkflow(
            f"Version de contrat non supportée : {env['version']} "
            f"(cette instance parle la version {CONTRAT_VERSION}).")
    if env["type"] not in TYPES_MESSAGE:
        raise ErreurWorkflow(f"Type de message hors contrat : {env['type']}")
    if not verifier_signature(env):
        raise ErreurWorkflow("Signature invalide — enveloppe rejetée.")
    if env["confidentialite"] == "national":
        raise ErreurWorkflow(
            "Enveloppe rejetée : une donnée « national » n'a pas à circuler.")
    return True


def cle_pivot(dci, forme=None, dosage=None):
    """Clé d'appariement « même produit » d'un pays à l'autre (esprit ISO IDMP).

    Normalisée pour résister aux écarts de casse, d'accents et d'espaces.
    """
    import unicodedata

    def norm(v):
        v = (v or "").strip().upper()
        v = unicodedata.normalize("NFD", v)
        v = "".join(c for c in v if unicodedata.category(c) != "Mn")
        return " ".join(v.split())

    return "|".join(x for x in (norm(dci), norm(forme), norm(dosage)) if x)
