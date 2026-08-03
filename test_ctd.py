"""
Tests du dossier technique : matrice des exigences et parcours séquentiel.

Exécution :  venv\\Scripts\\python test_ctd.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import modules_ctd as ctd
from models import DossierAMM, Etablissement, Personne, Produit, db

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


def _dossier(nature="chimique", type_procedure="nouvelle_demande"):
    s = uuid.uuid4().hex[:6]
    etab = Etablissement(raison_sociale=f"L-{s}", type="importateur_exportateur",
                         statut_licence="active")
    db.session.add(etab); db.session.flush()
    dep = Personne(nom_complet=f"D{s}", email=f"{s}@t.demo",
                   role_systeme="demandeur_externe", statut_compte="actif",
                   etablissement_rattachement_id=etab.id)
    dep.set_password("pw"); db.session.add(dep); db.session.flush()
    p = Produit(nom_commercial=f"P{s}", forme_pharmaceutique="Comprimé",
                nature=nature, titulaire_amm_id=etab.id)
    db.session.add(p); db.session.flush()
    d = DossierAMM(numero=f"AMM-C-{s}", produit_id=p.id, demandeur_id=dep.id,
                   statut="brouillon", type_procedure=type_procedure)
    db.session.add(d); db.session.flush()
    return d


def test_matrice():
    print("\n[1] Matrice des modules obligatoires")
    verifier("chimique / nouvelle demande → 3 modules",
             ctd.modules_obligatoires("chimique", "nouvelle_demande") == [1, 2, 3])
    verifier("biologique / nouvelle demande → 5 modules",
             ctd.modules_obligatoires("biologique", "nouvelle_demande") == [1, 2, 3, 4, 5])
    verifier("chimique / renouvellement → 1 module",
             ctd.modules_obligatoires("chimique", "renouvellement") == [1])
    verifier("biologique / renouvellement → 2 modules",
             ctd.modules_obligatoires("biologique", "renouvellement") == [1, 3])
    verifier("le renouvellement allège toujours la nouvelle demande",
             all(len(ctd.modules_obligatoires(n, "renouvellement"))
                 <= len(ctd.modules_obligatoires(n, "nouvelle_demande"))
                 for n in ctd.NATURES_PRODUIT))
    verifier("biologique toujours au moins aussi exigeant que chimique",
             all(len(ctd.modules_obligatoires("biologique", t))
                 >= len(ctd.modules_obligatoires("chimique", t))
                 for t in ("nouvelle_demande", "renouvellement", "variation")))
    verifier("combinaison inconnue → valeur de repli",
             ctd.modules_obligatoires("inconnu", "inconnu") == ctd.DEFAUT)


def test_nature_derivee():
    print("\n[2] Nature du produit")
    verifier("5 natures proposées", len(ctd.NATURES_PRODUIT) == 5)
    p = Produit(nom_commercial="X", categorie="vaccin")
    verifier("un vaccin est biologique", ctd.nature_du_produit(p) == "biologique")
    p2 = Produit(nom_commercial="Y", categorie="medicament")
    verifier("un médicament est chimique par défaut",
             ctd.nature_du_produit(p2) == "chimique")
    p3 = Produit(nom_commercial="Z", categorie="medicament", nature="biologique")
    verifier("la nature explicite prime sur la catégorie",
             ctd.nature_du_produit(p3) == "biologique")


def test_champs_modules():
    print("\n[3] Champs des modules")
    verifier("5 modules définis", len(ctd.MODULES) == 5)
    for n, meta in ctd.MODULES.items():
        verifier(f"module {n} ({meta['titre'][:28]}) a des champs",
                 len(meta["champs"]) >= 5, f"{len(meta['champs'])} champs")
    types = {t.split(":")[0] for _c, _l, t in
             (c for m in ctd.MODULES.values() for c in m["champs"])}
    verifier("types de champ reconnus",
             types <= {"texte", "zone", "nombre", "date", "liste"}, str(types))
    verifier("options de liste extraites",
             ctd.options_liste("liste:a|b|c") == ["a", "b", "c"])


def test_parcours_sequentiel():
    print("\n[4] Parcours séquentiel — biologique, nouvelle demande (5 modules)")
    d = _dossier("biologique", "nouvelle_demande")
    exiges = ctd.modules_du_dossier(d)
    verifier("5 modules exigés", exiges == [1, 2, 3, 4, 5])
    verifier("progression initiale nulle", ctd.progression(d) == (0, 5))
    verifier("premier module à traiter = 1", ctd.module_suivant(d) == 1)
    verifier("dossier technique incomplet", not ctd.dossier_technique_complet(d))

    for n in exiges:
        # Remplissage partiel : le module ne doit pas compter comme complet
        premier = ctd.champs(n)[0][0]
        ctd.ecrire_module(d, n, {premier: "valeur"})
        db.session.flush()
        if n == 1:
            verifier("un module partiellement rempli n'est pas complet",
                     not ctd.module_complet(d, n))
        # Remplissage complet
        ctd.ecrire_module(d, n, {c: "valeur" for c, _l, _t in ctd.champs(n)})
        db.session.flush()
        verifier(f"module {n} complété", ctd.module_complet(d, n))
        attendu = exiges[exiges.index(n) + 1] if n != exiges[-1] else None
        verifier(f"après le module {n}, suivant = {attendu}",
                 ctd.module_suivant(d, apres=n) == attendu)

    verifier("progression finale 5/5", ctd.progression(d) == (5, 5))
    verifier("dossier technique complet", ctd.dossier_technique_complet(d))


def test_parcours_allege():
    print("\n[5] Parcours allégé — chimique, renouvellement (1 module)")
    d = _dossier("chimique", "renouvellement")
    verifier("un seul module exigé", ctd.modules_du_dossier(d) == [1])
    ctd.ecrire_module(d, 1, {c: "v" for c, _l, _t in ctd.champs(1)})
    db.session.flush()
    verifier("dossier complet après un module", ctd.dossier_technique_complet(d))
    verifier("les modules non exigés n'entrent pas dans le calcul",
             ctd.progression(d) == (1, 1))


def test_apercu_matrice():
    print("\n[6] Tableau récapitulatif")
    apercu = ctd.apercu_matrice()
    verifier("une ligne par nature", len(apercu) == len(ctd.NATURES_PRODUIT))
    verifier("toutes les procédures couvertes",
             all(len(l["exigences"]) == 4 for l in apercu))


def main():
    print("=" * 70)
    print("Dossier technique (CTD) — tests")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_matrice, test_nature_derivee, test_champs_modules,
                  test_parcours_sequentiel, test_parcours_allege, test_apercu_matrice):
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
