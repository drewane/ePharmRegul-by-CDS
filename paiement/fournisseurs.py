"""
Fournisseurs de paiement raccordés à la plateforme SIREPH.

Chaque classe décrit un moyen de paiement réel, avec son flux propre. Les
connecteurs vers les API des prestataires sont écrits ; ils s'activent dès que
les identifiants marchands correspondants sont présents dans l'environnement.
Sans identifiants, le fournisseur bascule en simulation — jamais en silence :
l'interface l'indique et aucun encaissement n'est prétendu.

VARIABLES D'ENVIRONNEMENT ATTENDUES (production)
------------------------------------------------
Carte bancaire
    SIREPH_PSP_CARTE_URL, SIREPH_PSP_CARTE_CLE, SIREPH_PSP_CARTE_SECRET
MTN Mobile Money (API Collections)
    SIREPH_PSP_MTN_URL, SIREPH_PSP_MTN_CLE, SIREPH_PSP_MTN_ABONNEMENT,
    SIREPH_PSP_MTN_SECRET
Orange Money (Web Payment)
    SIREPH_PSP_ORANGE_URL, SIREPH_PSP_ORANGE_CLE, SIREPH_PSP_ORANGE_SECRET
Virement bancaire (pas d'API : coordonnées du compte de recette publique)
    SIREPH_BANQUE_NOM, SIREPH_BANQUE_IBAN, SIREPH_BANQUE_BIC,
    SIREPH_BANQUE_TITULAIRE
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from .base import (ErreurConfiguration, ErreurPaiement, Fournisseur, Initiation,
                   Resultat, nouvelle_reference)


def _env(*cles) -> bool:
    return all(os.getenv(c) for c in cles)


# ===========================================================================
# 1. VIREMENT BANCAIRE — flux hors ligne, réconciliation a posteriori
# ===========================================================================
class VirementBancaire(Fournisseur):
    """Virement sur le compte de recette de la DPML.

    Aucun appel API : la plateforme délivre un avis de paiement portant une
    RÉFÉRENCE UNIQUE que le payeur doit rappeler dans le libellé du virement.
    L'encaissement est constaté ensuite, soit par import du relevé bancaire
    (rapprochement automatique sur la référence), soit par confirmation
    manuelle d'un agent habilité.

    C'est le seul mode réellement opérationnel sans contrat prestataire.
    """

    code = "virement"
    libelle = "Virement bancaire"
    famille = "virement"
    flux = "hors_ligne"
    icone = "bi-bank"
    prefixe_ref = "VIR"
    delai_expiration_minutes = 60 * 24 * 15      # 15 jours pour virer

    def configure(self) -> bool:
        return _env("SIREPH_BANQUE_IBAN", "SIREPH_BANQUE_NOM")

    def etat_configuration(self) -> str:
        return ("Coordonnées bancaires officielles"
                if self.configure() else "Coordonnées de démonstration")

    def coordonnees(self) -> dict:
        return {
            "banque": os.getenv("SIREPH_BANQUE_NOM", "BANQUE DE DÉMONSTRATION"),
            "titulaire": os.getenv("SIREPH_BANQUE_TITULAIRE",
                                   "DPML — Recettes réglementaires"),
            "iban": os.getenv("SIREPH_BANQUE_IBAN", "CM21 1000 1000 0000 0000 0000 000"),
            "bic": os.getenv("SIREPH_BANQUE_BIC", "DEMOCMCX"),
        }

    def initier(self, paiement, contexte: dict) -> Initiation:
        ref = paiement.reference_marchande or nouvelle_reference("VIR")
        return Initiation(
            flux=self.flux, reference_marchande=ref,
            expire_le=self.expiration(),
            instructions={
                **self.coordonnees(),
                "montant": paiement.montant,
                "devise": paiement.devise,
                "libelle_obligatoire": ref,
                "consigne": ("Reportez EXACTEMENT cette référence dans le libellé du "
                             "virement : sans elle, le rapprochement automatique est "
                             "impossible et le traitement de votre dossier sera retardé."),
            },
            simulation=not self.configure())

    def rapprocher(self, paiement, ligne_releve: dict) -> Resultat:
        """Rapproche une ligne de relevé bancaire avec ce paiement.

        `ligne_releve` : {reference, montant, devise, date, emetteur}
        Le contrôle du montant est strict : un virement partiel n'acquitte pas
        la créance et doit être traité manuellement.
        """
        if ligne_releve.get("reference") != paiement.reference_marchande:
            raise ErreurPaiement("Référence de virement non concordante.")
        if int(ligne_releve.get("montant", -1)) != int(paiement.montant):
            raise ErreurPaiement(
                f"Montant viré ({ligne_releve.get('montant')}) différent du montant "
                f"attendu ({paiement.montant}) — rapprochement refusé.")
        if ligne_releve.get("devise", paiement.devise) != paiement.devise:
            raise ErreurPaiement("Devise du virement non concordante.")
        if paiement.statut == "confirme":
            return Resultat(etat="deja_confirme")
        return Resultat(etat="confirme",
                        reference_transaction=ligne_releve.get("reference_bancaire")
                        or f"VIR-{ligne_releve.get('date', '')}")


# ===========================================================================
# 2. CARTE BANCAIRE — flux par redirection (page hébergée + 3-D Secure)
# ===========================================================================
class CarteBancaire(Fournisseur):
    """Carte bancaire via un PSP agréé, en page hébergée.

    SIREPH ne voit jamais le numéro de carte : l'usager est redirigé vers la
    page du prestataire (authentification 3-D Secure incluse), puis ramené.
    Le retour navigateur ne vaut PAS confirmation — seul le webhook signé fait
    foi, car l'URL de retour est falsifiable.
    """

    code = "carte"
    libelle = "Carte bancaire (Visa / Mastercard)"
    famille = "carte"
    flux = "redirection"
    icone = "bi-credit-card-2-front"
    prefixe_ref = "CB"
    delai_expiration_minutes = 20
    frais_pour_mille = 18            # ordre de grandeur d'une commission carte

    def configure(self) -> bool:
        return _env("SIREPH_PSP_CARTE_URL", "SIREPH_PSP_CARTE_CLE",
                    "SIREPH_PSP_CARTE_SECRET")

    def initier(self, paiement, contexte: dict) -> Initiation:
        ref = paiement.reference_marchande or nouvelle_reference("CB")
        if not self.configure():
            return Initiation(flux=self.flux, reference_marchande=ref,
                              expire_le=self.expiration(),
                              url_redirection=contexte["url_simulateur"],
                              simulation=True)

        # --- Connecteur réel -------------------------------------------------
        import requests           # dépendance chargée seulement si raccordé
        reponse = requests.post(
            f"{os.environ['SIREPH_PSP_CARTE_URL'].rstrip('/')}/sessions",
            json={
                "montant": paiement.montant,
                "devise": paiement.devise,
                "reference_marchande": ref,
                "description": f"SIREPH {paiement.numero}",
                "url_retour": contexte["url_retour"],
                "url_notification": contexte["url_notification"],
                "3ds": "obligatoire",
            },
            headers={"Authorization": f"Bearer {os.environ['SIREPH_PSP_CARTE_CLE']}",
                     "Idempotency-Key": ref},
            timeout=20)
        if reponse.status_code >= 300:
            raise ErreurPaiement(
                f"Le prestataire carte a refusé l'ouverture de session "
                f"(HTTP {reponse.status_code}).")
        data = reponse.json()
        return Initiation(flux=self.flux, reference_marchande=ref,
                          expire_le=self.expiration(),
                          url_redirection=data["url_paiement"], simulation=False)


# ===========================================================================
# 3. MOBILE MONEY — flux « push » : demande envoyée sur le téléphone
# ===========================================================================
class MobileMoney(Fournisseur):
    """Base commune aux opérateurs de mobile money.

    Le payeur saisit son numéro ; l'opérateur pousse une demande de
    confirmation (USSD ou notification applicative) sur son téléphone. Le
    code confidentiel est saisi sur le mobile — jamais dans SIREPH.
    """

    famille = "mobile"
    flux = "push"
    icone = "bi-phone"
    delai_expiration_minutes = 15
    prefixe_ref = "MOB"
    indicatif = "+237"

    def numero_valide(self, numero: str) -> bool:
        chiffres = "".join(c for c in (numero or "") if c.isdigit())
        return 8 <= len(chiffres) <= 15

    def initier(self, paiement, contexte: dict) -> Initiation:
        numero = (contexte.get("numero_payeur") or "").strip()
        if not self.numero_valide(numero):
            raise ErreurPaiement(
                "Numéro de téléphone invalide : indiquez le numéro du compte "
                f"{self.libelle} à débiter.")
        ref = paiement.reference_marchande or nouvelle_reference(self.prefixe_ref)

        if not self.configure():
            return Initiation(
                flux=self.flux, reference_marchande=ref, expire_le=self.expiration(),
                instructions={"numero": numero, "operateur": self.libelle,
                              "consigne": "Une demande de confirmation serait envoyée "
                                          "sur ce téléphone."},
                simulation=True)

        return self._collecter(paiement, numero, ref, contexte)

    def _collecter(self, paiement, numero, ref, contexte) -> Initiation:
        raise NotImplementedError


class MtnMomo(MobileMoney):
    """MTN Mobile Money — API Collections (RequestToPay)."""

    code = "mtn_momo"
    libelle = "MTN Mobile Money"
    prefixe_ref = "MTN"
    frais_pour_mille = 15

    def configure(self) -> bool:
        return _env("SIREPH_PSP_MTN_URL", "SIREPH_PSP_MTN_CLE",
                    "SIREPH_PSP_MTN_ABONNEMENT", "SIREPH_PSP_MTN_SECRET")

    def _collecter(self, paiement, numero, ref, contexte) -> Initiation:
        import requests
        reponse = requests.post(
            f"{os.environ['SIREPH_PSP_MTN_URL'].rstrip('/')}/collection/v1_0/requesttopay",
            json={
                "amount": str(paiement.montant),
                "currency": paiement.devise,
                "externalId": ref,
                "payer": {"partyIdType": "MSISDN",
                          "partyId": "".join(c for c in numero if c.isdigit())},
                "payerMessage": f"SIREPH {paiement.numero}",
                "payeeNote": "Redevance reglementaire DPML",
            },
            headers={
                "Authorization": f"Bearer {os.environ['SIREPH_PSP_MTN_CLE']}",
                "X-Reference-Id": ref,
                "X-Target-Environment": os.getenv("SIREPH_PSP_MTN_ENV", "mtncameroon"),
                "Ocp-Apim-Subscription-Key": os.environ["SIREPH_PSP_MTN_ABONNEMENT"],
                "X-Callback-Url": contexte["url_notification"],
            },
            timeout=20)
        if reponse.status_code not in (200, 202):
            raise ErreurPaiement(
                f"MTN MoMo a refusé la demande de paiement (HTTP {reponse.status_code}).")
        return Initiation(flux=self.flux, reference_marchande=ref,
                          expire_le=self.expiration(),
                          instructions={"numero": numero, "operateur": self.libelle,
                                        "consigne": "Confirmez la demande sur votre "
                                                    "téléphone (composez *126# si besoin)."},
                          simulation=False)

    def interroger(self, paiement) -> Resultat:
        if not self.configure():
            return Resultat(etat="en_cours")
        import requests
        r = requests.get(
            f"{os.environ['SIREPH_PSP_MTN_URL'].rstrip('/')}"
            f"/collection/v1_0/requesttopay/{paiement.reference_marchande}",
            headers={"Authorization": f"Bearer {os.environ['SIREPH_PSP_MTN_CLE']}",
                     "X-Target-Environment": os.getenv("SIREPH_PSP_MTN_ENV", "mtncameroon"),
                     "Ocp-Apim-Subscription-Key": os.environ["SIREPH_PSP_MTN_ABONNEMENT"]},
            timeout=15)
        if r.status_code >= 300:
            return Resultat(etat="en_cours")
        data = r.json()
        statut = (data.get("status") or "").upper()
        if statut == "SUCCESSFUL":
            if int(data.get("amount", paiement.montant)) != int(paiement.montant):
                raise ErreurPaiement("Montant encaissé divergent — à vérifier manuellement.")
            return Resultat(etat="confirme",
                            reference_transaction=data.get("financialTransactionId"))
        if statut == "FAILED":
            return Resultat(etat="echoue",
                            detail=(data.get("reason") or "Paiement refusé par MTN."))
        return Resultat(etat="en_cours")


class OrangeMoney(MobileMoney):
    """Orange Money — Web Payment (initiation puis notification)."""

    code = "orange_money"
    libelle = "Orange Money"
    prefixe_ref = "OM"
    frais_pour_mille = 15

    def configure(self) -> bool:
        return _env("SIREPH_PSP_ORANGE_URL", "SIREPH_PSP_ORANGE_CLE",
                    "SIREPH_PSP_ORANGE_SECRET")

    def _collecter(self, paiement, numero, ref, contexte) -> Initiation:
        import requests
        reponse = requests.post(
            f"{os.environ['SIREPH_PSP_ORANGE_URL'].rstrip('/')}/webpayment",
            json={
                "merchant_key": os.environ["SIREPH_PSP_ORANGE_CLE"],
                "currency": paiement.devise,
                "order_id": ref,
                "amount": paiement.montant,
                "return_url": contexte["url_retour"],
                "cancel_url": contexte["url_retour"],
                "notif_url": contexte["url_notification"],
                "reference": f"SIREPH {paiement.numero}",
                "msisdn": "".join(c for c in numero if c.isdigit()),
            },
            headers={"Authorization": f"Bearer {os.environ['SIREPH_PSP_ORANGE_SECRET']}"},
            timeout=20)
        if reponse.status_code >= 300:
            raise ErreurPaiement(
                f"Orange Money a refusé la demande (HTTP {reponse.status_code}).")
        data = reponse.json()
        # Orange renvoie une URL de paiement : on redirige plutôt que d'attendre.
        return Initiation(flux="redirection", reference_marchande=ref,
                          expire_le=self.expiration(),
                          url_redirection=data.get("payment_url"),
                          instructions={"numero": numero, "operateur": self.libelle},
                          simulation=False)


# ===========================================================================
# Registre
# ===========================================================================
FOURNISSEURS: dict[str, Fournisseur] = {
    f.code: f for f in (VirementBancaire(), CarteBancaire(), MtnMomo(), OrangeMoney())
}

ORDRE_AFFICHAGE = ["mtn_momo", "orange_money", "carte", "virement"]


def obtenir(code: str) -> Fournisseur:
    if code not in FOURNISSEURS:
        raise ErreurPaiement(f"Moyen de paiement inconnu : {code}")
    return FOURNISSEURS[code]


def disponibles() -> list[Fournisseur]:
    return [FOURNISSEURS[c] for c in ORDRE_AFFICHAGE if c in FOURNISSEURS]
