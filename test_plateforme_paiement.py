"""
Tests de la plateforme de paiement multi-fournisseurs.

Exécution :  venv\\Scripts\\python test_plateforme_paiement.py
"""
import sys
from datetime import datetime, timedelta

# Console Windows en cp1252 : éviter les erreurs d'encodage sur les symboles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import paiement as pf
from paiement.base import TOLERANCE_NOTIFICATION_SECONDES, signer


class FauxPaiement:
    def __init__(self, montant=500000, devise="XAF", statut="en_attente"):
        self.numero = "PAY-TEST-0001"
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


CONTEXTE = {"url_retour": "/retour", "url_notification": "/notification",
            "url_simulateur": "/simulateur", "numero_payeur": "699000000"}

_res = []


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail and not cond else ""))


def _initier(code, paiement=None, contexte=None):
    p = paiement or FauxPaiement()
    f = pf.obtenir(code)
    p.reference_marchande = pf.nouvelle_reference(getattr(f, "prefixe_ref", "MRC"))
    p.fournisseur = code
    init = f.initier(p, contexte or CONTEXTE)
    p.reference_marchande = init.reference_marchande
    return p, f, init


def test_catalogue():
    print("\n[1] Catalogue des moyens de paiement")
    codes = {f.code for f in pf.disponibles()}
    verifier("4 moyens disponibles", len(codes) == 4, str(codes))
    for attendu in ("mtn_momo", "orange_money", "carte", "virement"):
        verifier(f"« {attendu} » présent", attendu in codes)
    verifier("moyen inconnu rejeté",
             _leve(lambda: pf.obtenir("bitcoin"), pf.ErreurPaiement))
    familles = {f.famille for f in pf.disponibles()}
    verifier("3 familles (mobile, carte, virement)",
             familles == {"mobile", "carte", "virement"}, str(familles))


def _leve(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True


def test_flux_carte():
    print("\n[2] Carte bancaire — flux par redirection")
    p, f, init = _initier("carte")
    verifier("flux = redirection", init.flux == "redirection")
    verifier("URL de redirection fournie", bool(init.url_redirection))
    verifier("marqué comme simulation (non raccordé)", init.simulation)
    verifier("frais opérateur calculés", f.frais(500000) > 0)

    notif = f.notification_simulee(p, succes=True)
    r = f.traiter_notification(notif, p)
    verifier("notification valide confirmée", r.etat == "confirme")
    verifier("référence de transaction retournée", bool(r.reference_transaction))


def test_flux_mobile():
    print("\n[3] Mobile money — flux push")
    p, f, init = _initier("mtn_momo")
    verifier("flux = push", init.flux == "push")
    verifier("consigne affichée au payeur", "consigne" in init.instructions)

    # Numéro invalide refusé
    q = FauxPaiement()
    q.reference_marchande = pf.nouvelle_reference("MTN")
    verifier("numéro invalide refusé",
             _leve(lambda: pf.obtenir("mtn_momo").initier(q, {**CONTEXTE, "numero_payeur": "12"}),
                   pf.ErreurPaiement))

    verifier("statut en_cours tant que non confirmé",
             pf.obtenir("mtn_momo").interroger(p).etat == "en_cours")
    r = f.traiter_notification(f.notification_simulee(p, succes=False), p)
    verifier("refus opérateur pris en compte", r.etat == "echoue")


def test_flux_virement():
    print("\n[4] Virement bancaire — flux hors ligne + rapprochement")
    p, f, init = _initier("virement")
    verifier("flux = hors_ligne", init.flux == "hors_ligne")
    for champ in ("iban", "bic", "banque", "libelle_obligatoire"):
        verifier(f"instruction « {champ} » fournie", champ in init.instructions)
    verifier("référence à rappeler = référence marchande",
             init.instructions["libelle_obligatoire"] == p.reference_marchande)
    verifier("délai de virement long (≥ 7 jours)",
             (init.expire_le - datetime.utcnow()).days >= 7)

    # Rapprochement conforme
    ligne = {"reference": p.reference_marchande, "montant": p.montant,
             "devise": p.devise, "date": "2026-08-02", "reference_bancaire": "OP-99"}
    verifier("rapprochement conforme accepté", f.rapprocher(p, ligne).etat == "confirme")

    # Virement partiel refusé
    p2, f2, _ = _initier("virement")
    partiel = {**ligne, "reference": p2.reference_marchande, "montant": 100}
    verifier("virement partiel refusé", _leve(lambda: f2.rapprocher(p2, partiel),
                                              pf.ErreurPaiement))
    # Mauvaise référence refusée
    verifier("référence inconnue refusée",
             _leve(lambda: f2.rapprocher(p2, {**ligne, "reference": "VIR-AUTRE"}),
                   pf.ErreurPaiement))


def test_securite_commune():
    print("\n[5] Sécurité commune à tous les fournisseurs")
    for code in ("carte", "mtn_momo", "orange_money"):
        p, f, _ = _initier(code)
        notif = f.notification_simulee(p, succes=True)

        # Signature falsifiée
        falsifie = dict(notif); falsifie["montant"] = 1
        verifier(f"[{code}] montant falsifié détecté",
                 _leve(lambda: f.traiter_notification(falsifie, p), pf.ErreurPaiement))

        # Montant divergent mais correctement resigné
        triche = dict(notif); triche["montant"] = 100
        triche["signature"] = signer(triche, f.code)
        verifier(f"[{code}] montant divergent resigné refusé",
                 _leve(lambda: f.traiter_notification(triche, p), pf.ErreurPaiement))

        # Rejeu hors fenêtre
        vieux = dict(notif)
        vieux["horodatage"] = (datetime.utcnow() -
                               timedelta(seconds=TOLERANCE_NOTIFICATION_SECONDES + 60)).isoformat()
        vieux["signature"] = signer(vieux, f.code)
        verifier(f"[{code}] notification périmée refusée",
                 _leve(lambda: f.traiter_notification(vieux, p), pf.ErreurPaiement))


def test_cloisonnement_fournisseurs():
    print("\n[6] Cloisonnement : un secret par fournisseur")
    p, carte, _ = _initier("carte")
    notif = carte.notification_simulee(p, succes=True)
    mtn = pf.obtenir("mtn_momo")
    # Une notification signée par le PSP carte ne doit pas être acceptée par MTN.
    verifier("notification d'un autre fournisseur refusée",
             _leve(lambda: mtn.traiter_notification(notif, p), pf.ErreurPaiement))


def test_idempotence():
    print("\n[7] Idempotence — aucun double encaissement")
    p, f, _ = _initier("carte")
    notif = f.notification_simulee(p, succes=True)
    verifier("1er passage confirme", f.traiter_notification(notif, p).etat == "confirme")
    p.statut = "confirme"          # tel que persisté par la couche métier
    verifier("rejeu neutralisé", f.traiter_notification(notif, p).etat == "deja_confirme")

    # Référence croisée entre deux créances
    a, fa, _ = _initier("carte")
    b, _fb, _ = _initier("carte")
    verifier("référence croisée refusée",
             _leve(lambda: fa.traiter_notification(fa.notification_simulee(a), b),
                   pf.ErreurPaiement))


def test_aucune_donnee_sensible():
    print("\n[8] Aucune donnée de paiement sensible")
    for code in ("carte", "mtn_momo", "virement"):
        p, f, init = _initier(code)
        empreinte = (" ".join(str(v) for v in vars(p).values()) + " " +
                     str(init.instructions)).lower()
        for interdit in ("cvv", "pan", "card_number", "numero_carte", "pin", "code_secret"):
            verifier(f"[{code}] aucun « {interdit} »", interdit not in empreinte)
        verifier(f"[{code}] non raccordé → simulation assumée", not f.configure()
                 or code == "virement")


def main():
    print("=" * 66)
    print("Plateforme de paiement SIREPH — tests")
    print("=" * 66)
    for t in (test_catalogue, test_flux_carte, test_flux_mobile, test_flux_virement,
              test_securite_commune, test_cloisonnement_fournisseurs, test_idempotence,
              test_aucune_donnee_sensible):
        t()
    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 66)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + ", ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
