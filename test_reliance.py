"""
Tests du volet régional CEEAC.

L'essentiel porte sur la SOUVERAINETÉ : ce qui ne doit jamais sortir du pays
ne sort pas, et ce qui sort sous accord exige un consentement tracé.

Exécution :  venv\\Scripts\\python test_reliance.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import reliance as ctr
import workflow_reliance as wfr
from erreurs import ErreurWorkflow
from models import (AccordPartage, AlerteTransfrontaliere, DecisionPubliee,
                    MessageReliance, PaysCEEAC, Personne, RequeteReliance, db)

_res = []
_a_nettoyer = []

# Certains traitements valident la transaction par conception (réception d'un
# message entrant = webhook). Un simple rollback ne suffit donc pas : on relève
# le dernier identifiant de chaque table avant les tests, et on supprime après
# coup tout ce qui a été créé au-delà. La base retrouve son état initial.
_TABLES_RELIANCE = None


def _max_ids():
    global _TABLES_RELIANCE
    if _TABLES_RELIANCE is None:
        _TABLES_RELIANCE = (RequeteReliance, AlerteTransfrontaliere,
                            AccordPartage, MessageReliance, DecisionPubliee)
    reperes = {}
    for modele in _TABLES_RELIANCE:
        dernier = db.session.query(db.func.max(modele.id)).scalar()
        reperes[modele] = dernier or 0
    return reperes


def _nettoyer(reperes):
    supprimes = 0
    for modele, borne in reperes.items():
        for obj in modele.query.filter(modele.id > borne).all():
            db.session.delete(obj)
            supprimes += 1
    db.session.commit()
    return supprimes


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def leve(fn, motif_attendu=None):
    try:
        fn()
        return False
    except ErreurWorkflow as e:
        return motif_attendu is None or motif_attendu.lower() in str(e).lower()


def test_pays_configurables():
    print("\n[1] Liste des pays — donnée de configuration")
    total = PaysCEEAC.query.count()
    verifier("11 États membres enregistrés", total == 11, f"{total} trouvés")
    verifier("le Rwanda est présent et modifiable",
             PaysCEEAC.query.filter_by(code_iso="RW").first() is not None)
    partenaires = wfr.pays_partenaires()
    verifier("l'instance courante n'est pas sa propre partenaire",
             all(p.code_iso != ctr.pays_instance() for p in partenaires))

    # Un pays retiré sort du réseau, sans toucher au code
    ga = PaysCEEAC.query.filter_by(code_iso="GA").first()
    ancien = ga.statut
    ga.statut = "retire"
    db.session.flush()
    verifier("un pays retiré n'est plus proposé",
             all(p.code_iso != "GA" for p in wfr.pays_partenaires()))
    verifier("échange refusé vers un pays retiré",
             leve(lambda: wfr.creer_requete(
                 Personne.query.first(), "GA", "Test", "clarification"), "reliance"))
    ga.statut = ancien
    db.session.flush()


def test_souverainete_contrat():
    print("\n[2] Souveraineté — appliquée par le contrat lui-même")
    verifier("donnée « national » refusée à la construction",
             leve(lambda: ctr.construire_enveloppe(
                 "requete_reliance", "GA", {"x": 1}, "national"),
                  "ne peut pas quitter le pays"))
    verifier("« sous accord » sans consentement refusé",
             leve(lambda: ctr.construire_enveloppe(
                 "reponse_reliance", "GA", {"x": 1}, "partageable_sous_accord"),
                  "consentement"))
    env = ctr.construire_enveloppe("reponse_reliance", "GA", {"x": 1},
                                   "partageable_sous_accord", "ACC-2026-0001")
    verifier("« sous accord » avec consentement accepté", env["signature"])
    verifier("type de message hors contrat refusé",
             leve(lambda: ctr.construire_enveloppe("exfiltration", "GA", {})))


def test_signature_et_rejeu():
    print("\n[3] Signature des échanges")
    env = ctr.construire_enveloppe("alerte", "REGIONAL", {"produit_nom": "X"})
    verifier("enveloppe signée vérifiable", ctr.verifier_signature(env))

    altere = dict(env)
    altere["payload"] = {"produit_nom": "Y"}
    verifier("altération du contenu détectée", not ctr.verifier_signature(altere))
    verifier("enveloppe altérée rejetée à la réception",
             leve(lambda: ctr.valider_enveloppe_entrante(altere), "signature"))

    perimee = dict(env)
    perimee["version"] = "0.9"
    verifier("version de contrat incompatible refusée",
             leve(lambda: ctr.valider_enveloppe_entrante(perimee), "version"))


def test_consentement_requis_pour_rapport():
    print("\n[4] Réponse à une requête — consentement obligatoire pour un rapport")
    acteur = Personne.query.filter_by(role_systeme="administrateur_dpml").first()
    # Numéro unique par exécution : certains traitements (webhook entrant)
    # valident la transaction, la base n'est donc pas garantie vierge.
    req = RequeteReliance(numero=f"REL-TEST-{uuid.uuid4().hex[:8]}", sens="entrante",
                          pays_partenaire="GA", type_requete="rapport_evaluation",
                          objet="Rapport Amoxidem", statut="recue")
    db.session.add(req)
    db.session.flush()
    _a_nettoyer.append(req)

    verifier("sans consentement : transmission refusée",
             leve(lambda: wfr.repondre_requete(req, acteur, "Rapport complet"),
                  "consentement"))

    accord = wfr.accorder_partage(acteur, "Rapport Amoxidem", "GA", "rapport_evaluation")
    db.session.flush()
    verifier("consentement révoqué : transmission refusée",
             leve(lambda: (setattr(accord, "revoque", True),
                           wfr.repondre_requete(req, acteur, "R", accord))[1], "révoqué"))
    accord.revoque = False

    autre = wfr.accorder_partage(acteur, "Autre", "CD", "rapport_evaluation")
    db.session.flush()
    verifier("consentement visant un autre pays : refusé",
             leve(lambda: wfr.repondre_requete(req, acteur, "R", autre), "refusée"))

    wfr.repondre_requete(req, acteur, "Rapport d'évaluation complet.", accord)
    db.session.flush()
    verifier("avec consentement valide : réponse transmise", req.statut == "repondue")
    msg = MessageReliance.query.filter_by(type_message="reponse_reliance").order_by(
        MessageReliance.id.desc()).first()
    verifier("consentement tracé dans l'enveloppe",
             msg.enveloppe.get("consentement_ref") == accord.numero,
             msg.enveloppe.get("consentement_ref"))
    verifier("confidentialité correctement classée",
             msg.enveloppe.get("confidentialite") == "partageable_sous_accord")


def test_alerte_transfrontaliere():
    print("\n[5] Alerte transfrontalière")
    acteur = Personne.query.filter_by(role_systeme="administrateur_dpml").first()
    a = wfr.emettre_alerte(acteur, "produit_falsifie", "Antipalu-X",
                           "Produit falsifié — retrait immédiat.", "AX-0912", "I")
    db.session.flush()
    verifier("alerte créée et numérotée", a.numero.startswith("ALR-"), a.numero)
    verifier("alerte mise en file vers le réseau",
             MessageReliance.query.filter_by(type_message="alerte",
                                             destinataire="REGIONAL").count() >= 1)
    verifier("alerte signée", bool(a.signature))
    verifier("message d'alerte obligatoire",
             leve(lambda: wfr.emettre_alerte(acteur, "rappel_lot", "P", "")))


def test_reception_idempotente():
    print("\n[6] Réception — idempotence et notification")
    env = ctr.construire_enveloppe("alerte", ctr.pays_instance(), {
        "type_alerte": "rappel_lot", "produit_nom": "Vaxidem",
        "numero_lot": "VX-014", "niveau_risque": "II",
        "message": "Rappel précaution — chaîne du froid."})
    env["emetteur"] = "GA"
    env["signature"] = ctr.signer(env)

    avant = AlerteTransfrontaliere.query.filter_by(sens="recue").count()
    wfr.traiter_message_entrant(env)
    apres = AlerteTransfrontaliere.query.filter_by(sens="recue").count()
    verifier("alerte entrante enregistrée", apres == avant + 1)

    wfr.traiter_message_entrant(env)          # rejeu
    verifier("rejeu du même message ignoré",
             AlerteTransfrontaliere.query.filter_by(sens="recue").count() == apres)


def test_resilience_hub_absent():
    print("\n[7] Résilience — Hub injoignable")
    verifier("Hub non raccordé en l'absence de configuration", not ctr.hub_raccorde())
    r = wfr.synchroniser()
    verifier("synchronisation sans exception", isinstance(r, dict))
    verifier("messages conservés en file", r.get("hub_raccorde") is False)
    verifier("aucune transmission prétendue", r.get("transmis") == [])


def test_appariement_produit():
    print("\n[8] Appariement « même produit » entre pays")
    a = ctr.cle_pivot("Amoxicilline", "Comprimé", "500 mg")
    b = ctr.cle_pivot("  amoxicilline ", "COMPRIMÉ", "500 MG")
    verifier("clé pivot insensible casse/accents/espaces", a == b, f"{a} vs {b}")
    verifier("produits différents → clés différentes",
             a != ctr.cle_pivot("Amoxicilline", "Comprimé", "250 mg"))


def main():
    print("=" * 70)
    print("Volet régional CEEAC — tests")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_pays_configurables, test_souverainete_contrat,
                  test_signature_et_rejeu, test_consentement_requis_pour_rapport,
                  test_alerte_transfrontaliere, test_reception_idempotente,
                  test_resilience_hub_absent, test_appariement_produit):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False, f"{type(e).__name__}: {e}")
        db.session.rollback()
        _nettoyer(reperes)

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
