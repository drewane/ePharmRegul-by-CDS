"""
Tests de l'arborescence des demandes.

Deux exigences :
  * AUCUNE IMPASSE — chaque branche mène à une démarche réellement servie. Un
    menu qui promet une page inexistante est pire qu'un menu absent.
  * UNE SEULE SOURCE — la barre latérale, les pages et le fil d'Ariane lisent
    la même déclaration, faute de quoi ils divergent (c'est exactement ce
    qu'avait fait le doublon « Nouvelle demande »).

Exécution :  venv\\Scripts\\python test_taxonomie_demandes.py
"""
import io
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import dossier_essai_clinique as dec
import taxonomie_demandes as tax
import workflow_agrement as wfa
from erreurs import ErreurWorkflow
from models import DemandeLicence, Etablissement, Notification, Personne, db

_res = []
_MODELES = (Notification, DemandeLicence, Personne, Etablissement)


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


def _client(email):
    """Session authentifiée, avec le mot de passe réellement en vigueur."""
    for source, motif in (("instance/IDENTIFIANTS-PRIVES.txt",
                           r"^\s+(" + re.escape(email) + r")\s+(\S+)\s"),):
        try:
            txt = io.open(source, encoding="utf-8").read()
            m = re.search(motif, txt, re.M)
            if m:
                mdp = m.group(2)
                break
        except OSError:
            pass
    else:
        mdp = "demo1234"
    c = application.app.test_client()
    c.post("/login", data={"email": email, "password": mdp})
    return c


def test_structure_demandee():
    print("\n[1] L'arborescence est celle qui a été demandée")
    racine = [n["code"] for n in tax.ARBORESCENCE]
    verifier("quatre familles à la racine",
             racine == ["homologation", "inspection", "essai_clinique",
                        "agrements"], str(racine))

    homologation = [n["code"] for n in tax.noeud(["homologation"])["enfants"]]
    verifier("Homologation → AMM, reconnaissance, ATU, dérogation, visa",
             homologation == ["amm", "reconnaissance", "atu", "derogation",
                              "visa_technique"],
             str(homologation))

    verifier("Inspection reste une entrée directe",
             tax.noeud(["inspection"]).get("lien") is not None
             and not tax.noeud(["inspection"]).get("enfants"))

    phases = [n["code"] for n in tax.noeud(["essai_clinique"])["enfants"]]
    verifier("Essai clinique → trois phases",
             phases == ["phase-1", "phase-2", "phase-3"], str(phases))

    domaines = [n["code"] for n in tax.noeud(["agrements"])["enfants"]]
    verifier("Agréments → Distribution, Fabrication",
             domaines == ["distribution", "fabrication"], str(domaines))

    for domaine in domaines:
        categories = [n["code"] for n in tax.noeud(["agrements", domaine])["enfants"]]
        verifier(f"{domaine} → Médicaments, Dispositifs médicaux",
                 categories == ["medicaments", "dispositifs_medicaux"],
                 str(categories))
        for categorie in categories:
            actes = [n["code"] for n in
                     tax.noeud(["agrements", domaine, categorie])["enfants"]]
            verifier(f"{domaine}/{categorie} → nouvelle, renouvellement, suspension",
                     actes == ["nouvelle", "renouvellement", "suspension"],
                     str(actes))

    verifier("douze démarches d'agrément au total",
             len([f for f in tax.feuilles()
                  if f["lien"].startswith("/demandes/agrements/")]) == 12)


def test_integrite():
    print("\n[2] Intégrité structurelle")
    anomalies = tax.verifier_arborescence()
    verifier("aucune impasse, aucun doublon", not anomalies, "; ".join(anomalies))
    verifier("chaque feuille porte un lien",
             all(f.get("lien") for f in tax.feuilles()))
    verifier("chaque nœud porte une icône",
             all(n.get("icone") for n in tax.feuilles()))


def test_toutes_les_pages_repondent():
    print("\n[3] Toute branche mène à une page servie")
    c = _client("demandeur@pharmacam.demo")
    intermediaires = ["/demandes/",
                      "/demandes/rubrique/homologation",
                      "/demandes/rubrique/essai_clinique",
                      "/demandes/rubrique/agrements",
                      "/demandes/rubrique/agrements/distribution",
                      "/demandes/rubrique/agrements/fabrication",
                      "/demandes/rubrique/agrements/fabrication/medicaments"]
    echecs = [(u, c.get(u, follow_redirects=True).status_code)
              for u in intermediaires]
    echecs = [e for e in echecs if e[1] != 200]
    verifier("les pages de rubrique répondent", not echecs, str(echecs))

    echecs = [(f["lien"], c.get(f["lien"], follow_redirects=True).status_code)
              for f in tax.feuilles()]
    echecs = [e for e in echecs if e[1] != 200]
    verifier(f"les {len(tax.feuilles())} démarches terminales répondent",
             not echecs, str(echecs[:3]))

    verifier("une rubrique inconnue renvoie 404",
             c.get("/demandes/rubrique/inexistante").status_code == 404)
    verifier("un agrément mal qualifié renvoie 404",
             c.get("/demandes/agrements/distribution/vehicules/nouvelle")
             .status_code == 404)


def test_sous_onglets():
    print("\n[4] La barre latérale lit la même déclaration")
    c = _client("demandeur@pharmacam.demo")
    page = c.get("/demandes/").get_data(as_text=True)
    for libelle in ("Homologation", "Inspection", "Essai clinique", "Agréments"):
        verifier(f"« {libelle} » figure dans la navigation", libelle in page)
    for libelle in ("AMM", "Dérogation", "Visa technique", "Phase I",
                    "Distribution", "Fabrication"):
        verifier(f"sous-onglet « {libelle} » présent", libelle in page)


def test_essai_clinique_documentaire():
    print("\n[5] Besoin documentaire par phase d'essai clinique")
    verifier("trois phases décrites", set(dec.PHASES) ==
             {"phase-1", "phase-2", "phase-3"})
    for phase in dec.PHASES:
        liste = dec.exigences(phase)
        obligatoires, total = dec.compte(phase)
        verifier(f"{phase} — pièces listées", total >= 15, f"{total} pièces")
        verifier(f"{phase} — majorité obligatoire", obligatoires >= 12,
                 f"{obligatoires} obligatoires")
        verifier(f"{phase} — chaque pièce est précisée",
                 all(e["intitule"] and e["precision"] for e in liste))
        codes = [e["code"] for e in liste]
        verifier(f"{phase} — aucun doublon", len(codes) == len(set(codes)))

    # Le tronc commun est le même partout ; le spécifique diffère.
    commun = {e["code"] for e in dec.exigences("phase-1") if e["origine"] == "commun"}
    for phase in ("phase-2", "phase-3"):
        autres = {e["code"] for e in dec.exigences(phase) if e["origine"] == "commun"}
        verifier(f"{phase} partage le tronc commun", autres == commun)
    spec1 = {e["code"] for e in dec.exigences("phase-1") if e["origine"] == "phase"}
    spec3 = {e["code"] for e in dec.exigences("phase-3") if e["origine"] == "phase"}
    verifier("les pièces spécifiques diffèrent d'une phase à l'autre",
             not (spec1 & spec3))
    verifier("la phase I exige le dossier préclinique", "precliniques" in spec1)
    verifier("la phase I exige la justification de la première dose",
             "premiere_dose" in spec1)
    verifier("la phase III exige le comité de surveillance", "dsmb_phase3" in spec3)
    verifier("la phase III exige le calcul d'effectif", "effectif" in spec3)
    verifier("l'avis éthique est commun et obligatoire",
             any(e["code"] == "avis_ethique" and e["obligatoire"]
                 for e in dec.exigences("phase-2")))
    verifier("phase inconnue refusée", _leve_valeur(lambda: dec.exigences("phase-9")))


def _leve_valeur(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def _etablissement():
    e = Etablissement(raison_sociale=f"Agr-{len(_res)}-test",
                      type="grossiste_repartiteur", statut_licence="active")
    db.session.add(e)
    db.session.flush()
    p = Personne(nom_complet="Exploitant test", email=f"agr{e.id}@test.demo",
                 role_systeme="demandeur_externe", statut_compte="actif",
                 etablissement_rattachement_id=e.id)
    p.set_password("pw")
    db.session.add(p)
    db.session.flush()
    return e, p


def test_depot_agrement():
    print("\n[6] Dépôt d'une demande d'agrément")
    e, p = _etablissement()
    d = wfa.deposer(e, p, "distribution", "medicaments", "nouvelle")
    db.session.flush()
    verifier("demande numérotée", d.numero.startswith("LIC-"), d.numero)
    verifier("domaine enregistré", d.domaine == "distribution")
    verifier("catégorie enregistrée", d.categorie == "medicaments")
    verifier("acte enregistré", d.type_demande == "nouvelle")
    verifier("intitulé lisible",
             "distribution" in wfa.intitule(d) and "médicaments" in wfa.intitule(d),
             wfa.intitule(d))
    verifier("accusé de réception au déposant",
             Notification.query.filter_by(destinataire_id=p.id,
                                          type="demande_receptionnee").count() == 1)
    verifier("le service instructeur est saisi",
             Notification.query.filter_by(type="agrement_a_instruire").count() >= 1)
    verifier("une seule demande ouverte à la fois",
             leve(lambda: wfa.deposer(e, p, "fabrication", "medicaments",
                                      "nouvelle"), "déjà en cours"))


def test_controles_agrement():
    print("\n[7] Contrôles de saisie et suspension motivée")
    e, p = _etablissement()
    verifier("domaine inconnu refusé",
             leve(lambda: wfa.deposer(e, p, "transport", "medicaments", "nouvelle"),
                  "domaine"))
    verifier("catégorie inconnue refusée",
             leve(lambda: wfa.deposer(e, p, "distribution", "cosmetiques",
                                      "nouvelle"), "catégorie"))
    verifier("acte inconnu refusé",
             leve(lambda: wfa.deposer(e, p, "distribution", "medicaments",
                                      "annulation"), "acte"))
    verifier("suspension sans motif refusée",
             leve(lambda: wfa.deposer(e, p, "distribution", "medicaments",
                                      "suspension"), "motivée"))
    d = wfa.deposer(e, p, "distribution", "medicaments", "suspension",
                    motif="Transfert du site de stockage vers Douala.")
    db.session.flush()
    verifier("suspension motivée acceptée", d.type_demande == "suspension")
    verifier("le motif est conservé", "Douala" in (d.motif_demande or ""))

    orphelin = Personne(nom_complet="Sans société", email="orphelin@test.demo",
                        role_systeme="demandeur_externe", statut_compte="actif")
    orphelin.set_password("pw")
    db.session.add(orphelin)
    db.session.flush()
    verifier("un compte sans établissement ne dépose pas",
             leve(lambda: wfa.deposer(None, orphelin, "distribution",
                                      "medicaments", "nouvelle"),
                  "aucun établissement"))


def test_pieces_attendues():
    print("\n[8] Pièces attendues, adaptées au domaine et à la catégorie")
    fab = wfa.pieces_attendues("fabrication", "medicaments", "nouvelle")
    dist = wfa.pieces_attendues("distribution", "medicaments", "nouvelle")
    verifier("la fabrication réclame le dossier permanent du site",
             any("Site Master File" in p for p in fab))
    verifier("la distribution réclame la cartographie thermique",
             any("thermique" in p for p in dist))
    verifier("les deux listes diffèrent", set(fab) != set(dist))

    dm = wfa.pieces_attendues("distribution", "dispositifs_medicaux", "nouvelle")
    verifier("les dispositifs médicaux réclament leur classe",
             any("classes" in p.lower() for p in dm))

    renouv = wfa.pieces_attendues("distribution", "medicaments", "renouvellement")
    verifier("le renouvellement réclame le rapport d'activité",
             any("rapport d'activité" in p.lower() for p in renouv))

    susp = wfa.pieces_attendues("distribution", "medicaments", "suspension")
    verifier("la suspension ne réclame pas de refaire le dossier complet",
             len(susp) < len(dist), f"{len(susp)} contre {len(dist)}")
    verifier("la suspension réclame la continuité d'approvisionnement",
             any("continuité" in p.lower() for p in susp))


def main():
    print("=" * 70)
    print("Arborescence des demandes, essais cliniques et agréments")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_structure_demandee, test_integrite,
                  test_toutes_les_pages_repondent, test_sous_onglets,
                  test_essai_clinique_documentaire, test_depot_agrement,
                  test_controles_agrement, test_pieces_attendues):
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
