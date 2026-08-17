"""
Tests du tableau de bord par profil et de « Mon portefeuille ».

Trois exigences du cahier des charges :
  * les dossiers récents se limitent à moins de trois mois ;
  * aucune section « demandes d'inspection » sur le tableau de bord d'un
    titulaire — l'inspection a rejoint « Demande » ;
  * le contenu s'adapte au type de demandeur.

Et une quatrième, que le cahier suppose sans la nommer : le portefeuille doit
montrer quelque chose de réel à CHAQUE profil. Servir une liste d'AMM
invariablement vide à un fabricant serait pire que ne rien lui montrer.

Exécution :  venv\\Scripts\\python test_tableau_bord.py
"""
import sys
import uuid
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import seed_comptes as sc
import tableau_de_bord as tdb
from models import (DossierAMM, Etablissement, Personne, Produit, db)
from permissions import ROLES_EXTERNES

_res = []
_MODELES = (DossierAMM, Produit, Personne, Etablissement)


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def _max_ids():
    return {M: (db.session.query(db.func.max(M.id)).scalar() or 0) for M in _MODELES}


def _nettoyer(reperes):
    for M in _MODELES:
        for obj in M.query.filter(M.id > reperes[M]).all():
            db.session.delete(obj)
    db.session.commit()


def _u(email):
    return Personne.query.filter_by(email=email).first()


def _client(email):
    c = application.app.test_client()
    c.post("/login", data={"email": email,
                           "password": sc.mot_de_passe_courant(email)})
    return c


def _dossier(proprietaire, statut="soumis", jours=0):
    """Dossier rattaché à la société du propriétaire, daté de N jours."""
    s = uuid.uuid4().hex[:6]
    p = Produit(nom_commercial=f"Produit {s}", forme_pharmaceutique="Comprimé",
                denomination_commune_internationale=f"Testine {s}",
                nature="chimique",
                titulaire_amm_id=proprietaire.etablissement_rattachement_id)
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=f"AMM-TB-{s}", produit_id=p.id,
                   demandeur_id=proprietaire.id, statut=statut,
                   date_maj=datetime.utcnow() - timedelta(days=jours))
    db.session.add(d)
    db.session.flush()
    return d


# ---------------------------------------------------------------------------
def test_composition_par_profil():
    print("\n[1] Chaque profil a sa composition")
    verifier("tous les profils externes sont couverts",
             all(r in tdb.COMPOSITION for r in ROLES_EXTERNES),
             str(set(ROLES_EXTERNES) - set(tdb.COMPOSITION)))
    for code, fiche in tdb.COMPOSITION.items():
        verifier(f"« {code} » a un titre et des raccourcis",
                 bool(fiche["titre"]) and isinstance(fiche["raccourcis"], list))

    labo = tdb.composition(_u("demandeur@pharmacam.demo"))
    fab = tdb.composition(_u("fabricant@wouri.demo"))
    verifier("le laboratoire et le fabricant n'ont pas le même titre",
             labo["titre"] != fab["titre"])
    verifier("leurs indicateurs diffèrent",
             {i[0] for i in labo["indicateurs"]}
             != {i[0] for i in fab["indicateurs"]})
    verifier("un agent n'a pas de composition d'opérateur",
             tdb.composition(_u("chefservice@dpml.demo")) is None)


def test_aucune_section_inspection():
    print("\n[2] L'inspection quitte le tableau de bord du titulaire")
    labo = tdb.composition(_u("demandeur@pharmacam.demo"))
    verifier("aucune section inspection pour le titulaire",
             "inspections" not in labo["sections"], str(labo["sections"]))
    verifier("aucun indicateur d'inspection",
             not any("inspection" in i[0] for i in labo["indicateurs"]))

    page = _client("demandeur@pharmacam.demo").get(
        "/industriel/", follow_redirects=True).get_data(as_text=True)
    verifier("la page ne parle pas de demandes d'inspection",
             "Demandes d'inspection" not in page)

    # Elle demeure pertinente pour le fabricant, dont c'est le quotidien.
    fab = tdb.composition(_u("fabricant@wouri.demo"))
    verifier("le fabricant, lui, garde ses inspections",
             "inspections" in fab["sections"])


def test_recents_trois_mois():
    print("\n[3] Dossiers récents : moins de trois mois")
    verifier("la fenêtre vaut trois mois", tdb.FENETRE_RECENTS_JOURS == 90)
    dep = _u("demandeur@pharmacam.demo")
    recent = _dossier(dep, "soumis", jours=10)
    limite = _dossier(dep, "soumis", jours=89)
    vieux = _dossier(dep, "soumis", jours=120)
    db.session.commit()

    ids = {d.id for d in tdb.dossiers_recents(dep)}
    verifier("un dossier de 10 jours est présent", recent.id in ids)
    verifier("un dossier de 89 jours est présent", limite.id in ids)
    verifier("un dossier de 120 jours est absent", vieux.id not in ids)
    # Ordre RELATIF : la base peut contenir d'autres dossiers de la société,
    # et figer des positions absolues rendrait le test dépendant du jeu de
    # données plutôt que du tri lui-même.
    ordre = [d.id for d in tdb.dossiers_recents(dep)]
    verifier("le plus récent précède le plus ancien",
             ordre.index(recent.id) < ordre.index(limite.id))
    verifier("les dates décroissent",
             all(a.date_maj >= b.date_maj
                 for a, b in zip(tdb.dossiers_recents(dep),
                                 tdb.dossiers_recents(dep)[1:])))


def test_prochaine_action():
    print("\n[4] Prochaine action attendue")
    dep = _u("demandeur@pharmacam.demo")
    attendus = {
        "brouillon": "vous",
        "complement_requis": "vous",
        "soumis": "l'administration",
        "evaluation_en_cours": "l'administration",
        "rejete": None,
        "irrecevable": None,
    }
    for statut, acteur in attendus.items():
        d = _dossier(dep, statut)
        obtenu, libelle = tdb.prochaine_action(d)
        verifier(f"« {statut} » attend {acteur or 'personne'}",
                 obtenu == acteur, f"{obtenu} — {libelle}")
        verifier(f"« {statut} » porte un libellé", bool(libelle))
    db.session.commit()

    verifier("chaque statut connu a une entrée",
             all(s in tdb.PROCHAINE_ACTION
                 for s in ("brouillon", "soumis", "recevable",
                           "evaluation_en_cours", "complement_requis",
                           "approuve", "rejete")))
    verifier("un statut inconnu ne casse pas",
             tdb.prochaine_action(_dossier(dep, "statut_imprevu"))[1]
             == tdb.ACTION_PAR_DEFAUT[1])


def test_a_faire():
    print("\n[5] « Ce qui attend une action de votre part »")
    dep = _u("demandeur@pharmacam.demo")
    mien = _dossier(dep, "complement_requis")
    pas_mien = _dossier(dep, "evaluation_en_cours")
    db.session.commit()

    ids = {d.id for d in tdb.a_faire(dep)}
    verifier("un complément requis y figure", mien.id in ids)
    verifier("un dossier en évaluation n'y figure pas", pas_mien.id not in ids)
    verifier("a_vous_de_jouer distingue les deux",
             tdb.a_vous_de_jouer(mien) and not tdb.a_vous_de_jouer(pas_mien))


def test_indicateurs_cibles():
    print("\n[6] Les indicateurs calculés sont ceux du profil, et pas d'autres")
    for email in ("demandeur@pharmacam.demo", "fabricant@wouri.demo",
                  "ateba@grossiste-demo.cm", "promoteur@essai.demo",
                  "pharmacien@officine.demo"):
        u = _u(email)
        fiche = tdb.composition(u)
        valeurs = tdb.indicateurs(u)
        manquants = [c for c, *_ in fiche["indicateurs"] if c not in valeurs]
        verifier(f"{u.role_systeme} : tous ses indicateurs sont calculés",
                 not manquants, str(manquants))
        verifier(f"{u.role_systeme} : valeurs numériques",
                 all(isinstance(valeurs.get(c), int)
                     for c, *_ in fiche["indicateurs"]))

    labo = tdb.indicateurs(_u("demandeur@pharmacam.demo"))
    verifier("le laboratoire ne fait pas calculer les protocoles",
             "protocoles_en_cours" not in labo)
    promo = tdb.indicateurs(_u("promoteur@essai.demo"))
    verifier("le promoteur ne fait pas calculer les AMM",
             "approuves" not in promo)


def test_portefeuille_titulaire():
    print("\n[7] Portefeuille du titulaire d'AMM")
    dep = _u("demandeur@pharmacam.demo")
    soumis = _dossier(dep, "soumis")
    brouillon = _dossier(dep, "brouillon")
    db.session.commit()

    c = _client("demandeur@pharmacam.demo")
    page = c.get("/industriel/portefeuille").get_data(as_text=True)
    verifier("le dossier soumis est listé", soumis.numero in page)
    verifier("le brouillon est exclu par défaut", brouillon.numero not in page)
    avec = c.get("/industriel/portefeuille?brouillons=1").get_data(as_text=True)
    verifier("la case les réintègre", brouillon.numero in avec)

    verifier("la prochaine action est affichée",
             "Prochaine action attendue" in page)
    verifier("la recherche est proposée", 'name="q"' in page)
    verifier("le tri est proposé", 'name="tri"' in page)

    trouve = c.get(f"/industriel/portefeuille?q={soumis.numero}").get_data(
        as_text=True)
    verifier("la recherche par référence fonctionne", soumis.numero in trouve)
    absent = c.get("/industriel/portefeuille?q=INTROUVABLE-XYZ").get_data(
        as_text=True)
    verifier("une recherche infructueuse le dit",
             "Aucun dossier ne correspond" in absent)

    for tri in ("recent", "ancien", "reference", "statut"):
        verifier(f"tri « {tri} » accepté",
                 c.get(f"/industriel/portefeuille?tri={tri}").status_code == 200)
    verifier("un tri inconnu ne casse pas",
             c.get("/industriel/portefeuille?tri=nimporte").status_code == 200)


def test_portefeuille_agrements():
    print("\n[8] Portefeuille des profils dont l'objet est l'agrément")
    for email in ("fabricant@wouri.demo", "ateba@grossiste-demo.cm"):
        page = _client(email).get("/industriel/portefeuille").get_data(
            as_text=True)
        verifier(f"{email} obtient un portefeuille d'agréments",
                 "agrément" in page.lower())
        verifier(f"{email} ne se voit pas servir une liste d'AMM vide",
                 "Prochaine action attendue" not in page)
        verifier(f"{email} voit l'état de son établissement",
                 "Agrément de l'établissement" in page
                 or "aucun établissement" in page.lower())


def test_cloisonnement():
    print("\n[9] Le cloisonnement tient")
    dep = _u("demandeur@pharmacam.demo")
    mien = _dossier(dep, "soumis")

    # Dossier d'une autre société.
    s = uuid.uuid4().hex[:6]
    autre_etab = Etablissement(raison_sociale=f"Concurrent {s}",
                               type="importateur_exportateur",
                               statut_licence="active")
    db.session.add(autre_etab)
    db.session.flush()
    autre = Personne(nom_complet=f"Rival {s}", email=f"rival{s}@test.demo",
                     role_systeme="demandeur_externe", statut_compte="actif",
                     etablissement_rattachement_id=autre_etab.id)
    autre.set_password("pw")
    db.session.add(autre)
    db.session.flush()
    dossier_rival = _dossier(autre, "soumis")
    db.session.commit()

    page = _client("demandeur@pharmacam.demo").get(
        "/industriel/portefeuille").get_data(as_text=True)
    verifier("mon dossier apparaît", mien.numero in page)
    verifier("celui du concurrent n'apparaît pas",
             dossier_rival.numero not in page)
    verifier("les indicateurs ne comptent que ma société",
             all(d.demandeur_id != autre.id
                 for d in tdb.dossiers_recents(dep)))


def test_agents_ecartes():
    print("\n[10] Un agent n'a pas de tableau de bord d'opérateur")
    for role in ("chef_service_amm", "directeur_dpml", "responsable_financier"):
        c = _client(sc.COMPTES[role][1])
        verifier(f"« {role} » est écarté de /industriel/",
                 c.get("/industriel/").status_code == 403)
        verifier(f"« {role} » est écarté du portefeuille",
                 c.get("/industriel/portefeuille").status_code == 403)
        verifier(f"« {role} » garde son propre tableau de bord",
                 c.get("/", follow_redirects=True).status_code == 200)


def main():
    print("=" * 70)
    print("Tableau de bord par profil et portefeuille")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        reperes = _max_ids()
        for t in (test_composition_par_profil, test_aucune_section_inspection,
                  test_recents_trois_mois, test_prochaine_action, test_a_faire,
                  test_indicateurs_cibles, test_portefeuille_titulaire,
                  test_portefeuille_agrements, test_cloisonnement,
                  test_agents_ecartes):
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
