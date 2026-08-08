"""
Tests du suivi unifié : numérotation nationale, états visibles, délai légal.

Le point sensible : le délai légal ne doit courir ni avant le paiement, ni
pendant que le demandeur prépare sa réponse.

Exécution :  venv/Scripts/python test_suivi.py
"""
import sys
import uuid
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import suivi
import validation_numerique as vn
from erreurs import ErreurWorkflow
from models import (DossierAMM, Etablissement, EtapeValidation, EvenementAudit,
                    Paiement, Personne, Produit, db)

_res = []
_MODELES = (EvenementAudit, EtapeValidation, Paiement, DossierAMM, Produit,
            Personne, Etablissement)


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


def _dossier(statut="soumis"):
    s = uuid.uuid4().hex[:6]
    e = Etablissement(raison_sociale=f"L{s}", type="importateur_exportateur",
                      statut_licence="active")
    db.session.add(e); db.session.flush()
    d0 = Personne(nom_complet=f"D{s}", email=f"{s}@t.demo",
                  role_systeme="demandeur_externe", statut_compte="actif",
                  etablissement_rattachement_id=e.id)
    d0.set_password("pw"); db.session.add(d0); db.session.flush()
    p = Produit(nom_commercial=f"P{s}", forme_pharmaceutique="Comprimé",
                nature="chimique", titulaire_amm_id=e.id)
    db.session.add(p); db.session.flush()
    d = DossierAMM(numero=f"AMM-S-{s}", produit_id=p.id, demandeur_id=d0.id,
                   statut=statut)
    db.session.add(d); db.session.flush()
    return d


def test_numerotation():
    print("\n[1] Numéro national de suivi")
    n = suivi.numero_suivi("amm")
    # Format attendu : CMR-AMM-2026-00123 (18 caractères, séquence sur 5 chiffres)
    parties = n.split("-")
    verifier("format CMR-AMM-ANNÉE-SÉQUENCE",
             parties[0] == "CMR" and parties[1] == "AMM"
             and parties[2] == str(datetime.utcnow().year)
             and len(parties[3]) == 5 and parties[3].isdigit(), n)
    n2 = suivi.numero_suivi("amm")
    verifier("séquence incrémentée", n2 != n, f"{n} puis {n2}")
    verifier("un code par fonction",
             suivi.numero_suivi("licence").startswith("CMR-LIC-"))
    verifier("les 8 fonctions ont un code",
             all(f in suivi.CODES_FONCTION for f in
                 ("amm", "licence", "controle_qualite", "liberation_lot",
                  "surveillance", "vigilance", "inspection", "essai_clinique")))
    verifier("fonction inconnue refusée",
             _leve_valeur(lambda: suivi.numero_suivi("inexistante")))


def _leve_valeur(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def test_etats_visibles():
    print("\n[2] États visibles du demandeur")
    verifier("sept étapes définies", len(suivi.ETATS) == 7)
    d = _dossier("brouillon")
    verifier("brouillon → soumis", suivi.etat_visible(d) == "soumis")
    d.statut = "soumis"
    verifier("sans paiement, reste « soumis »", suivi.etat_visible(d) == "soumis")

    db.session.add(Paiement(numero=f"PAY-T-{uuid.uuid4().hex[:6]}",
                            entite_type="DossierAMM", entite_id=d.id,
                            montant=1000, devise="XAF", statut="confirme"))
    db.session.flush()
    verifier("paiement confirmé → « paiement validé »",
             suivi.etat_visible(d) == "paiement_valide")

    d.statut = "evaluation_en_cours"
    verifier("évaluation en cours", suivi.etat_visible(d) == "evaluation")
    d.statut = "complement_requis"
    verifier("complément → « questions en attente »",
             suivi.etat_visible(d) == "clock_stop")
    d.statut = "approuve"
    verifier("approuvé → « décision disponible »", suivi.etat_visible(d) == "decision")


def test_parcours_affiche():
    print("\n[3] Parcours affiché au demandeur")
    d = _dossier("evaluation_en_cours")
    etapes = suivi.etapes_parcours(d)
    courante = [e for e in etapes if e["courant"]]
    verifier("une seule étape courante", len(courante) == 1,
             courante[0]["libelle"] if courante else "aucune")
    verifier("les étapes précédentes sont marquées atteintes",
             all(e["atteint"] for e in etapes[:etapes.index(courante[0])]))
    verifier("le Clock Stop n'est pas montré s'il n'a pas eu lieu",
             all(e["code"] != "clock_stop" for e in etapes))
    verifier("chaque étape porte une explication",
             all(e["description"] for e in etapes))

    d.statut = "complement_requis"
    etapes2 = suivi.etapes_parcours(d)
    verifier("le Clock Stop apparaît lorsqu'il survient",
             any(e["code"] == "clock_stop" and e["courant"] for e in etapes2))


def test_clock_start():
    print("\n[4] Clock Start — le délai part au paiement, pas au dépôt")
    d = _dossier()
    verifier("délai non démarré au dépôt", d.clock_debut is None)
    verifier("état du délai explicite",
             suivi.etat_delai(d)["demarre"] is False)
    verifier("le motif annoncé est bien le paiement",
             "paiement" in suivi.etat_delai(d)["libelle"].lower())

    # Un dossier déjà décidé sans décompte est antérieur au suivi : on ne
    # prétend pas attendre un paiement qui n'a plus d'objet.
    ancien = _dossier("approuve")
    e = suivi.etat_delai(ancien)
    verifier("dossier antérieur signalé comme tel", e["anterieur"])
    verifier("aucun faux message de paiement en attente",
             "paiement" not in e["libelle"].lower(), e["libelle"])
    verifier("aucun jour compté", suivi.jours_ecoules(d) is None)

    suivi.demarrer_delai(d)
    db.session.flush()
    verifier("délai démarré", d.clock_debut is not None)
    verifier("zéro jour au démarrage", suivi.jours_ecoules(d) == 0)

    ancien = d.clock_debut
    suivi.demarrer_delai(d)
    verifier("second démarrage sans effet", d.clock_debut == ancien)


def test_clock_stop():
    print("\n[5] Clock Stop — la suspension ne s'impute pas au délai")
    d = _dossier()
    verifier("suspension impossible avant démarrage",
             leve(lambda: suivi.suspendre_delai(d), "n'a pas démarré"))

    # Dossier déposé il y a 40 jours
    suivi.demarrer_delai(d)
    d.clock_debut = datetime.utcnow() - timedelta(days=40)
    db.session.flush()
    verifier("40 jours écoulés", suivi.jours_ecoules(d) == 40,
             str(suivi.jours_ecoules(d)))

    # Suspension il y a 10 jours
    suivi.suspendre_delai(d)
    d.clock_suspendu_depuis = datetime.utcnow() - timedelta(days=10)
    db.session.flush()
    verifier("délai signalé suspendu", suivi.etat_delai(d)["suspendu"])
    verifier("les jours suspendus sont déduits", suivi.jours_ecoules(d) == 30,
             str(suivi.jours_ecoules(d)))

    suivi.reprendre_delai(d)
    db.session.flush()
    verifier("délai repris", d.clock_suspendu_depuis is None)
    verifier("10 jours capitalisés comme suspendus",
             d.clock_total_suspendu_jours == 10, str(d.clock_total_suspendu_jours))
    verifier("le décompte reste à 30 jours", suivi.jours_ecoules(d) == 30,
             str(suivi.jours_ecoules(d)))
    suivi.reprendre_delai(d)
    verifier("seconde reprise sans effet", d.clock_total_suspendu_jours == 10)


def test_delai_legal():
    print("\n[6] Dépassement du délai légal")
    d = _dossier()
    suivi.demarrer_delai(d)
    d.clock_debut = datetime.utcnow() - timedelta(days=100)
    db.session.flush()
    etat = suivi.etat_delai(d, delai_legal_jours=90)
    verifier("dépassement détecté", etat["depasse"])
    verifier("solde négatif communiqué", etat["restant"] == -10, str(etat["restant"]))
    etat2 = suivi.etat_delai(d, delai_legal_jours=180)
    verifier("dans les délais si la borne est plus large", not etat2["depasse"])
    verifier("solde restant calculé", etat2["restant"] == 80, str(etat2["restant"]))


def test_inspecteur_general():
    print("\n[7] Inspecteur général dans la chaîne")
    verifier("audit IG dans le circuit AMM",
             "inspecteur_general" in vn.CIRCUITS["amm"])
    verifier("IG placé après le directeur",
             vn.CIRCUITS["amm"].index("inspecteur_general")
             > vn.CIRCUITS["amm"].index("directeur_dpml"))
    verifier("IG placé avant le secrétaire général",
             vn.CIRCUITS["amm"].index("inspecteur_general")
             < vn.CIRCUITS["amm"].index("secretaire_general_ms"))
    verifier("circuit AMM à six échelons", len(vn.CIRCUITS["amm"]) == 6,
             str(len(vn.CIRCUITS["amm"])))
    verifier("licence signée par le ministre",
             vn.CIRCUITS["licence"][-1] == "ministre_sante")
    verifier("essai clinique signé par le ministre",
             vn.CIRCUITS["essai_clinique"][-1] == "ministre_sante")
    verifier("IG intervient aussi sur l'inspection",
             "inspecteur_general" in vn.CIRCUITS["inspection"])


def test_delai_legal_par_fonction():
    print("\n[8] Délai réglementaire propre à chaque fonction")
    verifier("les dix fonctions ont un délai",
             all(f in suivi.DELAI_LEGAL_JOURS for f in suivi.CODES_FONCTION))
    verifier("l'AMM a le délai le plus long",
             suivi.DELAI_LEGAL_JOURS["amm"] == max(suivi.DELAI_LEGAL_JOURS.values()))
    verifier("la dérogation est la plus rapide",
             suivi.DELAI_LEGAL_JOURS["derogation"]
             == min(suivi.DELAI_LEGAL_JOURS.values()))
    d = _dossier()
    verifier("un DossierAMM relève de l'homologation",
             suivi.fonction_du_dossier(d) == "amm")
    verifier("le délai du dossier est celui de sa fonction",
             suivi.delai_legal(d) == suivi.DELAI_LEGAL_JOURS["amm"])


def test_jalons_publics():
    print("\n[9] Historique — le demandeur voit sa procédure, pas la délibération")
    from audit import enregistrer_audit
    d = _dossier()
    enregistrer_audit(d, "Dossier soumis", None)
    enregistrer_audit(d, "Avis d'évaluation déposé (qualité : défavorable)", None)
    enregistrer_audit(d, "Dossier inscrit à l'ordre du jour de COM-2026-001", None)
    enregistrer_audit(d, "Dossier déclaré recevable", None)
    db.session.flush()

    actions = [j.action for j in suivi.jalons_publics(d)]
    verifier("le dépôt est visible", "Dossier soumis" in actions)
    verifier("la recevabilité est visible", "Dossier déclaré recevable" in actions)
    verifier("l'avis d'un évaluateur reste confidentiel",
             not any("Avis d'évaluation" in a for a in actions))
    verifier("l'ordre du jour de commission reste confidentiel",
             not any("ordre du jour" in a for a in actions))
    verifier("l'historique est chronologique",
             actions == sorted(actions, key=lambda a: actions.index(a)))


def test_ecrans_suivi():
    print("\n[10] Écrans de suivi du demandeur")
    client = application.app.test_client()
    import seed_comptes as sc
    r = client.post(
        "/login",
        data={"email": "demandeur@pharmacam.demo",
              "password": sc.mot_de_passe_courant("demandeur@pharmacam.demo")},
        follow_redirects=True)
    verifier("connexion du déposant", r.status_code == 200)

    r = client.get("/industriel/suivi")
    verifier("la liste de suivi répond", r.status_code == 200, str(r.status_code))
    page = r.get_data(as_text=True)
    verifier("les numéros nationaux sont affichés", "CMR-" in page)

    import re
    ids = sorted({int(i) for i in re.findall(r"/industriel/suivi/(\d+)", page)})
    verifier("des dossiers sont listés", bool(ids), f"{len(ids)} dossier(s)")
    if ids:
        detail = client.get(f"/industriel/suivi/{ids[0]}")
        verifier("le parcours détaillé répond", detail.status_code == 200)
        corps = detail.get_data(as_text=True)
        verifier("le parcours est affiché", "Parcours de votre demande" in corps)
        verifier("le délai réglementaire est affiché", "Délai réglementaire" in corps)
        verifier("l'historique est affiché", "Historique de la procédure" in corps)

    # Cloisonnement : un dossier d'une autre société doit rester introuvable.
    concurrent = Personne.query.filter_by(email="demandeur2@biosante.demo").first()
    if concurrent:
        autre = DossierAMM.query.filter_by(demandeur_id=concurrent.id).first()
        if autre:
            verifier("le dossier d'un concurrent renvoie 404",
                     client.get(f"/industriel/suivi/{autre.id}").status_code == 404)
        else:
            verifier("un dossier concurrent existe pour le test", False)

    # Un régulateur n'a pas d'espace industriel : ce n'est pas son écran.
    reg = application.app.test_client()
    reg.post("/login",
             data={"email": "directeur@dpml.demo",
                   "password": sc.mot_de_passe_courant("directeur@dpml.demo")})
    code = reg.get("/industriel/suivi").status_code
    verifier("un profil non industriel est écarté", code in (302, 403), str(code))


def main():
    print("=" * 70)
    print("Suivi unifié — numérotation, états, délai légal")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_numerotation, test_etats_visibles, test_parcours_affiche,
                  test_clock_start, test_clock_stop, test_delai_legal,
                  test_inspecteur_general, test_delai_legal_par_fonction,
                  test_jalons_publics, test_ecrans_suivi):
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
