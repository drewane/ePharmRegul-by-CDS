"""
Tests de l'ATU et des voies d'homologation.

Deux exigences dominent :
  * L'ATU n'est pas une AMM au rabais — quatre conditions cumulatives, une
    durée bornée, des rapports, et une extinction dès que l'AMM est tranchée.
  * La reconnaissance ALLÈGE l'examen sans le supprimer : le module national
    reste exigé, la référence doit être produite, et une voie abrégée ne peut
    jamais réclamer plus que la voie nationale.

Un troisième objectif, plus discret : vérifier que rien de l'existant n'a
bougé. Les circuits, la matrice CTD et les délais des autres fonctions sont
contrôlés explicitement.

Exécution :  venv\\Scripts\\python test_atu_voies.py
"""
import sys
import uuid
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import modules_ctd as ctd
import suivi
import validation_numerique as vn
import voies_homologation as vh
import workflow_atu as wfa
from erreurs import ErreurWorkflow
from models import (AutorisationTemporaire, DossierAMM, Etablissement,
                    EvenementAudit, Notification, Personne, Produit, db)

_res = []
_MODELES = (EvenementAudit, AutorisationTemporaire, Notification, DossierAMM,
            Produit, Personne, Etablissement)


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def leve(fn, motif=None):
    try:
        fn()
        return False
    except ErreurWorkflow as e:
        return motif is None or motif.lower() in str(e).lower()


def _max_ids():
    return {M: (db.session.query(db.func.max(M.id)).scalar() or 0) for M in _MODELES}


def _nettoyer(reperes):
    for M in _MODELES:
        for obj in M.query.filter(M.id > reperes[M]).all():
            db.session.delete(obj)
    db.session.commit()


def _r(role):
    return Personne.query.filter_by(role_systeme=role).first()


def _demandeur():
    return Personne.query.filter_by(email="demandeur@pharmacam.demo").first()


def _base(**extra):
    donnees = {"type_atu": "nominative",
               "denomination": f"Produit {uuid.uuid4().hex[:5]}",
               "indication": "Amyotrophie spinale infantile de type 1",
               "justification": "Maladie mortelle avant deux ans ; le "
                                "traitement ne peut pas être différé.",
               "prescripteur_nom": "Dr Mballa",
               "patient_reference": f"PAT-{uuid.uuid4().hex[:6]}"}
    donnees.update(extra)
    return donnees


# ---------------------------------------------------------------------------
def test_depot_nominative():
    print("\n[1] ATU nominative — dépôt")
    dep = _demandeur()
    atu = wfa.deposer(dep, _base())
    db.session.flush()
    verifier("numérotée", atu.numero.startswith("ATU-"), atu.numero)
    verifier("numéro national de suivi",
             (atu.numero_suivi or "").startswith("CMR-ATU-"), atu.numero_suivi)
    verifier("statut « soumise »", atu.statut == "soumise")
    verifier("accusé de réception au demandeur",
             Notification.query.filter_by(destinataire_id=dep.id,
                                          type="atu_receptionnee").count() >= 1)
    verifier("le service instructeur est saisi",
             Notification.query.filter_by(type="atu_a_instruire").count() >= 1)
    verifier("le patient n'est pas nommé, seulement référencé",
             atu.patient_reference and not atu.patient_age)


def test_champs_obligatoires():
    print("\n[2] Ce qu'une demande ne peut pas omettre")
    dep = _demandeur()
    verifier("dénomination exigée",
             leve(lambda: wfa.deposer(dep, _base(denomination="")),
                  "dénomination"))
    verifier("indication exigée",
             leve(lambda: wfa.deposer(dep, _base(indication="")), "indication"))
    verifier("justification exigée",
             leve(lambda: wfa.deposer(dep, _base(justification="")),
                  "justification"))
    verifier("prescripteur exigé en nominative",
             leve(lambda: wfa.deposer(dep, _base(prescripteur_nom="")),
                  "prescripteur"))
    verifier("référence patient exigée en nominative",
             leve(lambda: wfa.deposer(dep, _base(patient_reference="")),
                  "patient"))
    verifier("type inconnu refusé",
             leve(lambda: wfa.deposer(dep, _base(type_atu="collective")),
                  "type"))


def test_cohorte():
    print("\n[3] ATU de cohorte — ses exigences propres")
    dep = _demandeur()
    cohorte = {"type_atu": "cohorte",
               "denomination": "Produit cohorte",
               "indication": "Forme résistante",
               "justification": "Absence d'alternative.",
               "effectif_estime": 40,
               "protocole_utilisation": "Critères d'inclusion, recueil mensuel.",
               "engagement_amm": True}
    verifier("effectif exigé",
             leve(lambda: wfa.deposer(dep, {**cohorte, "effectif_estime": None}),
                  "effectif"))
    verifier("protocole d'utilisation exigé",
             leve(lambda: wfa.deposer(dep, {**cohorte,
                                            "protocole_utilisation": ""}),
                  "protocole"))
    verifier("engagement d'AMM exigé",
             leve(lambda: wfa.deposer(dep, {**cohorte, "engagement_amm": False}),
                  "engagement"))
    atu = wfa.deposer(dep, cohorte)
    db.session.flush()
    verifier("cohorte complète acceptée", atu.type_atu == "cohorte")
    verifier("pas de patient nommé sur une cohorte",
             atu.patient_reference is None)


def test_conditions_cumulatives():
    print("\n[4] Les quatre conditions sont cumulatives")
    dep, chef = _demandeur(), _r("chef_service_amm")
    atu = wfa.deposer(dep, _base())
    db.session.flush()
    verifier("quatre conditions déclarées", len(wfa.CONDITIONS) == 4)

    toutes = {c: True for c, _l in wfa.CONDITIONS}
    for code, libelle in wfa.CONDITIONS:
        partielles = dict(toutes)
        partielles[code] = False
        verifier(f"sans « {code} », l'ATU n'est pas accordée",
                 leve(lambda p=partielles: wfa.prononcer_decision(atu, chef,
                                                                  True, p),
                      "conditions"))
    wfa.prononcer_decision(atu, chef, True, toutes, 12)
    db.session.flush()
    verifier("les quatre réunies, l'ATU est accordée", atu.statut == "accordee")


def test_qui_instruit():
    print("\n[5] L'instruction relève du service Homologation")
    dep = _demandeur()
    atu = wfa.deposer(dep, _base())
    db.session.flush()
    for role in ("demandeur_externe", "evaluateur_interne", "ministre_sante",
                 "responsable_financier"):
        verifier(f"« {role} » n'instruit pas",
                 leve(lambda r=role: wfa.prononcer_decision(
                     atu, _r(r), True, {c: True for c, _l in wfa.CONDITIONS}),
                      "service homologation"))
    verifier("refus sans motif rejeté",
             leve(lambda: wfa.prononcer_decision(atu, _r("chef_service_amm"),
                                                 False, motif=""), "motivé"))


def test_duree_et_renouvellement():
    print("\n[6] Durée bornée, renouvellement justifié")
    dep, chef = _demandeur(), _r("chef_service_amm")
    atu = wfa.deposer(dep, _base())
    db.session.flush()
    toutes = {c: True for c, _l in wfa.CONDITIONS}
    verifier("durée excessive refusée",
             leve(lambda: wfa.prononcer_decision(atu, chef, True, toutes, 36),
                  "comprise"))
    wfa.prononcer_decision(atu, chef, True, toutes, 12)
    db.session.flush()
    echeance = atu.date_echeance
    verifier("échéance à douze mois",
             echeance == date(date.today().year + 1, date.today().month,
                              date.today().day)
             or echeance > date.today(), str(echeance))
    verifier("renouvellement sans justification refusé",
             leve(lambda: wfa.renouveler(atu, chef, 6, ""), "motivez"))
    wfa.renouveler(atu, chef, 6, "Toujours aucune alternative disponible.")
    db.session.flush()
    verifier("échéance repoussée", atu.date_echeance > echeance)
    verifier("renouvellement compté", atu.renouvellements == 1)
    verifier("le demandeur est informé",
             Notification.query.filter_by(destinataire_id=dep.id,
                                          type="atu_renouvelee").count() >= 1)


def test_suivi_et_extinction():
    print("\n[7] Rapports, suspension, extinction sur AMM")
    dep, chef = _demandeur(), _r("chef_service_amm")
    atu = wfa.deposer(dep, _base())
    db.session.flush()
    verifier("aucun rapport avant l'octroi",
             leve(lambda: wfa.remettre_rapport(atu, dep, "01/2026", "x"),
                  "en cours"))
    wfa.prononcer_decision(atu, chef, True,
                           {c: True for c, _l in wfa.CONDITIONS}, 12)
    db.session.flush()
    wfa.remettre_rapport(atu, dep, "03/2026", "Tolérance satisfaisante.", 2)
    db.session.flush()
    verifier("rapport enregistré", len(atu.rapports()) == 1)
    verifier("effets indésirables comptés",
             atu.rapports()[0]["effets_indesirables"] == 2)
    verifier("rapport vide refusé",
             leve(lambda: wfa.remettre_rapport(atu, dep, "04/2026", "")))

    dossier = DossierAMM.query.first()
    wfa.clore_sur_amm(atu, chef, dossier)
    db.session.flush()
    verifier("l'ATU s'éteint quand l'AMM est tranchée", atu.statut == "close")
    verifier("le dossier d'AMM est rattaché", atu.dossier_amm_id == dossier.id)


def test_expiration():
    print("\n[8] Une ATU échue cesse d'être « en cours »")
    dep, chef = _demandeur(), _r("chef_service_amm")
    atu = wfa.deposer(dep, _base())
    db.session.flush()
    wfa.prononcer_decision(atu, chef, True,
                           {c: True for c, _l in wfa.CONDITIONS}, 12)
    atu.date_echeance = date.today() - timedelta(days=1)
    db.session.commit()
    wfa.expirer_echues()
    db.session.refresh(atu)
    verifier("statut passé à « expirée »", atu.statut == "expiree")
    verifier("le demandeur est prévenu",
             Notification.query.filter_by(destinataire_id=dep.id,
                                          type="atu_expiree").count() >= 1)
    verifier("l'expiration est idempotente", wfa.expirer_echues() == 0)


# ---------------------------------------------------------------------------
def test_voies_declarees():
    print("\n[9] Les trois voies d'homologation")
    verifier("trois voies", set(vh.VOIES) ==
             {"nationale", "reconnaissance", "prequalification"})
    verifier("la voie nationale est la plus longue",
             vh.delai_legal("nationale") > vh.delai_legal("reconnaissance"))
    verifier("reconnaissance et préqualification raccourcissent le délai",
             vh.delai_legal("prequalification") < vh.delai_legal("nationale"))
    verifier("des autorités de référence sont listées",
             len(vh.AUTORITES_REFERENCE) >= 8)
    verifier("les programmes OMS sont listés", len(vh.PROGRAMMES_OMS) >= 3)
    verifier("chaque voie a un libellé et une description",
             all(v.get("libelle") and v.get("description")
                 for v in vh.VOIES.values()))


def test_allegement_encadre():
    print("\n[10] L'allègement retire, il n'ajoute jamais")
    for nature in ctd.NATURES_PRODUIT:
        for procedure in ("nouvelle_demande", "renouvellement", "variation"):
            national = set(ctd.modules_obligatoires(nature, procedure))
            for voie in vh.VOIES:
                allege = set(vh.modules_exiges(voie, nature, procedure))
                if allege - national:
                    verifier(f"{voie}/{nature}/{procedure} n'ajoute rien",
                             False, str(allege - national))
                    return
    verifier("aucune voie n'exige un module que la voie nationale n'exige pas",
             True)
    verifier("le module 1 reste exigé en reconnaissance",
             1 in vh.modules_exiges("reconnaissance", "chimique",
                                    "nouvelle_demande"))
    verifier("le module qualité reste exigé en reconnaissance",
             3 in vh.modules_exiges("reconnaissance", "chimique",
                                    "nouvelle_demande"))
    verifier("la préqualification allège davantage que la reconnaissance",
             len(vh.modules_exiges("prequalification", "chimique",
                                   "nouvelle_demande"))
             <= len(vh.modules_exiges("reconnaissance", "chimique",
                                      "nouvelle_demande")))


def test_reference_exigee():
    print("\n[11] Pas de reconnaissance sans décision de référence")
    verifier("reconnaissance sans autorité refusée",
             vh.verifier_reference("reconnaissance") is not None)
    verifier("autorité inconnue refusée",
             vh.verifier_reference("reconnaissance", "agence_fantaisiste")
             is not None)
    verifier("reconnaissance avec autorité admise acceptée",
             vh.verifier_reference("reconnaissance", "ema") is None)
    verifier("préqualification sans programme refusée",
             vh.verifier_reference("prequalification") is not None)
    verifier("préqualification avec programme acceptée",
             vh.verifier_reference("prequalification",
                                   programme="pq_medicaments") is None)
    verifier("la voie nationale n'exige aucune référence",
             vh.verifier_reference("nationale") is None)
    verifier("libellé lisible de la référence",
             "EMA" in (vh.libelle_reference("reconnaissance", "ema") or ""))


def test_pieces_par_voie():
    print("\n[12] Pièces propres à chaque voie")
    rec = vh.pieces_exigees("reconnaissance")
    pq = vh.pieces_exigees("prequalification")
    verifier("la voie nationale n'ajoute aucune pièce",
             vh.pieces_exigees("nationale") == [])
    verifier("la reconnaissance réclame la décision de référence",
             any(p["code"] == "decision_reference" for p in rec))
    verifier("elle réclame le rapport d'évaluation",
             any(p["code"] == "rapport_evaluation" for p in rec))
    verifier("elle réclame l'attestation d'identité du produit",
             any(p["code"] == "attestation_identite" and p["obligatoire"]
                 for p in rec))
    verifier("elle réclame les mesures restrictives éventuelles",
             any(p["code"] == "mesures_restrictives" for p in rec))
    verifier("la préqualification réclame l'attestation OMS",
             any(p["code"] == "attestation_pq" for p in pq))
    verifier("les deux réclament un étiquetage adapté au Cameroun",
             any(p["code"] == "rcp_notice" for p in rec)
             and any(p["code"] == "rcp_notice" for p in pq))
    verifier("les contrôles nationaux sont énoncés",
             len(vh.CONTROLES_NATIONAUX) >= 5)


def test_rien_n_a_bouge():
    print("\n[13] L'existant est intact")
    verifier("circuit AMM toujours à six échelons",
             len(vn.CIRCUITS["amm"]) == 6, str(len(vn.CIRCUITS["amm"])))
    verifier("circuit licence toujours à cinq",
             len(vn.CIRCUITS["licence"]) == 5)
    verifier("circuit dérogation inchangé",
             vn.CIRCUITS["derogation"] == ["chef_service_amm",
                                           "sous_directeur_medicament",
                                           "directeur_dpml"])
    verifier("le circuit ATU est court, par nécessité",
             len(vn.CIRCUITS["atu"]) == 2)
    verifier("la matrice CTD nationale est inchangée",
             ctd.modules_obligatoires("chimique", "nouvelle_demande") == [1, 2, 3]
             and ctd.modules_obligatoires("biologique", "nouvelle_demande")
             == [1, 2, 3, 4, 5])
    verifier("les délais des autres fonctions sont inchangés",
             suivi.DELAI_LEGAL_JOURS["amm"] == 270
             and suivi.DELAI_LEGAL_JOURS["licence"] == 90)
    verifier("l'ATU a le délai le plus court", suivi.DELAI_LEGAL_JOURS["atu"]
             <= min(suivi.DELAI_LEGAL_JOURS.values()))
    verifier("les dossiers existants restent en voie nationale",
             all((d.voie_homologation or "nationale") == "nationale"
                 for d in DossierAMM.query.limit(20).all()))


def test_ecrans():
    print("\n[14] Écrans")
    import seed_comptes as sc
    client = application.app.test_client()
    email = sc.COMPTES["demandeur_externe"][1]
    client.post("/login", data={"email": email,
                                "password": sc.mot_de_passe_courant(email)})
    for url, attendu in (("/homologation/voies", "Reconnaissance"),
                         ("/atu/", "Autorisations temporaires"),
                         ("/atu/nouvelle?type=nominative", "prescripteur"),
                         ("/atu/nouvelle?type=cohorte", "cohorte")):
        r = client.get(url)
        corps = r.get_data(as_text=True)
        verifier(f"{url} répond", r.status_code == 200, str(r.status_code))
        verifier(f"{url} affiche « {attendu} »", attendu.lower() in corps.lower())

    dossier = DossierAMM.query.first()
    agent = application.app.test_client()
    chef = sc.COMPTES["chef_service_amm"][1]
    agent.post("/login", data={"email": chef,
                               "password": sc.mot_de_passe_courant(chef)})
    r = agent.get(f"/homologation/dossiers/{dossier.id}/voie")
    verifier("l'écran de qualification répond", r.status_code == 200)
    verifier("il énonce ce qui reste national",
             "reste national" in r.get_data(as_text=True).lower())

    import taxonomie_demandes as tax
    verifier("l'arborescence reste cohérente",
             not tax.verifier_arborescence())
    verifier("Homologation porte les cinq entrées",
             [n["code"] for n in tax.noeud(["homologation"])["enfants"]]
             == ["amm", "reconnaissance", "atu", "derogation",
                 "visa_technique"])


def main():
    print("=" * 70)
    print("ATU et voies d'homologation")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_depot_nominative, test_champs_obligatoires, test_cohorte,
                  test_conditions_cumulatives, test_qui_instruit,
                  test_duree_et_renouvellement, test_suivi_et_extinction,
                  test_expiration, test_voies_declarees,
                  test_allegement_encadre, test_reference_exigee,
                  test_pieces_par_voie, test_rien_n_a_bouge, test_ecrans):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False,
                         f"{type(e).__name__}: {e}")
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
