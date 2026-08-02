"""
Tests de sécurité de la passerelle de paiement.

Exécution :  venv\\Scripts\\python test_paiement_securise.py
(pas de pytest requis sur ce projet — exécution directe, sortie lisible)
"""
import sys
from datetime import datetime, timedelta

import paiement_gateway as pg


class FauxPaiement:
    """Double de test : mêmes attributs que le modèle Paiement."""

    def __init__(self, montant=500000, devise="XAF", statut="en_attente"):
        self.montant = montant
        self.devise = devise
        self.statut = statut
        self.mode = "preuve_manuelle"
        self.fournisseur = None
        self.reference_marchande = None
        self.reference_transaction = None
        self.date_initiation = None
        self.date_expiration = None
        self.signature_notification = None
        self.detail_echec = None


_resultats = []


def verifier(nom, condition, detail=""):
    _resultats.append((nom, bool(condition), detail))
    print(f"  {'OK  ' if condition else 'ECHEC'}  {nom}" + (f" — {detail}" if detail and not condition else ""))


def test_initiation():
    print("\n[1] Initiation d'une session de paiement")
    p = FauxPaiement()
    s = pg.initier(p, "mtn_momo", "/paiements/regler")
    verifier("statut passé à 'initie'", p.statut == "initie")
    verifier("référence marchande générée", bool(p.reference_marchande))
    verifier("expiration positionnée", p.date_expiration is not None)
    verifier("URL de paiement fournie", "ref=" in s["url_paiement"])

    # Idempotence de l'initiation : relancer ne change pas la référence
    ref1 = p.reference_marchande
    pg.initier(p, "orange_money", "/paiements/regler")
    verifier("référence stable si on relance", p.reference_marchande == ref1)

    try:
        pg.initier(p, "bitcoin", "/x")
        verifier("fournisseur inconnu refusé", False)
    except pg.ErreurPaiement:
        verifier("fournisseur inconnu refusé", True)


def test_signature():
    print("\n[2] Intégrité : signature HMAC")
    p = FauxPaiement()
    pg.initier(p, "carte", "/paiements/regler")
    notif = pg.construire_notification(p, succes=True)
    verifier("signature valide acceptée", pg.verifier_signature(notif))

    # Altération du montant → signature invalide
    falsifie = dict(notif)
    falsifie["montant"] = 1
    verifier("montant falsifié détecté", not pg.verifier_signature(falsifie))

    # Signature absente
    sans = {k: v for k, v in notif.items() if k != "signature"}
    verifier("signature absente refusée", not pg.verifier_signature(sans))


def test_confirmation():
    print("\n[3] Confirmation d'un paiement")
    p = FauxPaiement()
    pg.initier(p, "mtn_momo", "/x")
    notif = pg.construire_notification(p, succes=True)
    etat = pg.traiter_notification(notif, p)
    verifier("paiement confirmé", etat == "confirme" and p.statut == "confirme")
    verifier("référence de transaction enregistrée", bool(p.reference_transaction))

    # Rejeu de la même notification → pas de double encaissement
    etat2 = pg.traiter_notification(notif, p)
    verifier("rejeu neutralisé (idempotence)", etat2 == "deja_confirme")


def test_montant_divergent():
    print("\n[4] Contrôle du montant")
    p = FauxPaiement(montant=500000)
    pg.initier(p, "carte", "/x")
    notif = pg.construire_notification(p, succes=True)
    # Un attaquant qui contrôlerait le PSP tenterait de payer moins :
    notif["montant"] = 100
    notif["signature"] = pg.signer(notif)      # il resigne correctement
    try:
        pg.traiter_notification(notif, p)
        verifier("montant divergent refusé", False)
    except pg.ErreurPaiement as e:
        verifier("montant divergent refusé", "Montant" in str(e))
    verifier("paiement resté non confirmé", p.statut != "confirme")


def test_antirejeu():
    print("\n[5] Anti-rejeu : horodatage")
    p = FauxPaiement()
    pg.initier(p, "carte", "/x")
    notif = pg.construire_notification(p, succes=True)
    vieux = datetime.utcnow() - timedelta(seconds=pg.TOLERANCE_NOTIFICATION_SECONDES + 60)
    notif["horodatage"] = vieux.isoformat()
    notif["signature"] = pg.signer(notif)
    try:
        pg.traiter_notification(notif, p)
        verifier("notification périmée refusée", False)
    except pg.ErreurPaiement as e:
        verifier("notification périmée refusée", "validité" in str(e))


def test_reference_non_concordante():
    print("\n[6] Référence marchande non concordante")
    p1, p2 = FauxPaiement(), FauxPaiement()
    pg.initier(p1, "carte", "/x")
    pg.initier(p2, "carte", "/x")
    notif = pg.construire_notification(p1, succes=True)
    try:
        pg.traiter_notification(notif, p2)   # notification de p1 appliquée à p2
        verifier("référence croisée refusée", False)
    except pg.ErreurPaiement as e:
        verifier("référence croisée refusée", "concordante" in str(e))


def test_echec_et_expiration():
    print("\n[7] Échec et expiration")
    p = FauxPaiement()
    pg.initier(p, "mtn_momo", "/x")
    notif = pg.construire_notification(p, succes=False)
    pg.traiter_notification(notif, p)
    verifier("échec enregistré", p.statut == "echoue")

    q = FauxPaiement()
    pg.initier(q, "carte", "/x")
    q.date_expiration = datetime.utcnow() - timedelta(minutes=1)
    verifier("session expirée détectée", pg.expirer_si_besoin(q) and q.statut == "expire")

    r = FauxPaiement()
    pg.initier(r, "carte", "/x")
    verifier("session valide non expirée", not pg.expirer_si_besoin(r))


def test_pas_de_donnees_sensibles():
    print("\n[8] Aucune donnée de paiement sensible stockée")
    p = FauxPaiement()
    pg.initier(p, "carte", "/x")
    notif = pg.construire_notification(p, succes=True)
    pg.traiter_notification(notif, p)
    champs = " ".join(str(v) for v in vars(p).values()).lower()
    for interdit in ("cvv", "pan", "numero_carte", "card_number", "pin"):
        verifier(f"aucun champ « {interdit} »", interdit not in champs)
    verifier("mode réel désactivé sans identifiants", not pg.mode_reel())


def main():
    print("=" * 62)
    print("Tests de sécurité — passerelle de paiement SIREPH")
    print("=" * 62)
    for t in (test_initiation, test_signature, test_confirmation, test_montant_divergent,
              test_antirejeu, test_reference_non_concordante, test_echec_et_expiration,
              test_pas_de_donnees_sensibles):
        t()
    total = len(_resultats)
    reussis = sum(1 for _, ok, _ in _resultats if ok)
    print("\n" + "=" * 62)
    print(f"Résultat : {reussis}/{total} vérifications réussies")
    echecs = [n for n, ok, _ in _resultats if not ok]
    if echecs:
        print("Échecs : " + ", ".join(echecs))
    return 0 if reussis == total else 1


if __name__ == "__main__":
    sys.exit(main())
