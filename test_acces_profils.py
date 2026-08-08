"""
Tests des profils et des niveaux d'accès.

Deux exigences dominent :
  * COUVERTURE — chaque rôle du référentiel dispose d'un compte utilisable.
    Sans cela, un niveau de la chaîne n'est pas éprouvable, et une lacune de
    ce genre avait déjà bloqué le circuit de signature.
  * MONOTONIE — ce qu'un échelon peut consulter, l'échelon supérieur le peut
    aussi. L'inverse trahit une liste de permissions oubliée.

Exécution :  venv\\Scripts\\python test_acces_profils.py
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import seed_comptes as sc
from models import Personne, db
from permissions import (NIVEAU_MINIMAL_CONSULTATION, PERMISSIONS_TRANSVERSES,
                         ROLES, ROLES_EXTERNES, a_permission, niveau)

_res = []

# Routes témoins, choisies pour couvrir chaque famille de contrôle d'accès.
CONSULTATION = ("/reliance/", "/validation/parapheur")
RESERVE_ADMIN = "/admin/referentiels"
RESERVE_INDUSTRIEL = "/industriel/suivi"


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def _client(email):
    c = application.app.test_client()
    c.post("/login", data={"email": email,
                           "password": sc.mot_de_passe_courant(email)})
    return c


def test_couverture_des_roles():
    print("\n[1] Un compte utilisable par rôle du référentiel")
    verifier("chaque rôle est déclaré dans le jeu de comptes",
             set(sc.COMPTES) == set(ROLES),
             str(set(ROLES) ^ set(sc.COMPTES)) if set(sc.COMPTES) != set(ROLES) else "")
    manquants = sc.roles_sans_compte()
    verifier("aucun rôle sans compte en base", not manquants, ", ".join(manquants))

    inactifs, mauvais_role, mot_de_passe_ko = [], [], []
    for role, (_nom, email, _e) in sc.COMPTES.items():
        p = Personne.query.filter_by(email=email).first()
        if p is None:
            continue
        if p.statut_compte != "actif":
            inactifs.append(role)
        if p.role_systeme != role:
            mauvais_role.append(role)
        if not p.check_password(sc.mot_de_passe_courant(p.email)):
            mot_de_passe_ko.append(role)
    verifier("tous les comptes sont actifs", not inactifs, ", ".join(inactifs))
    verifier("chaque compte porte bien son rôle", not mauvais_role,
             ", ".join(mauvais_role))
    verifier("le mot de passe annoncé est le bon", not mot_de_passe_ko,
             ", ".join(mot_de_passe_ko))


def test_connexion_de_chaque_profil():
    print("\n[2] Chaque profil se connecte et atteint un espace exploitable")
    echecs, erreurs = [], []
    for role, (_nom, email, _e) in sc.COMPTES.items():
        c = _client(email)
        accueil = c.get("/", follow_redirects=True)
        if accueil.status_code != 200:
            echecs.append(f"{role}={accueil.status_code}")
        elif b"Traceback" in accueil.data:
            erreurs.append(role)
    verifier("les 31 profils atteignent leur accueil", not echecs, ", ".join(echecs))
    verifier("aucun accueil ne casse sur le rôle", not erreurs, ", ".join(erreurs))


def test_niveaux_declares():
    print("\n[3] Niveaux de responsabilité")
    verifier("les externes sont tous au niveau 0",
             all(niveau(r) == 0 for r in ROLES_EXTERNES))
    verifier("le ministre est seul au niveau 8",
             [r for r in ROLES if niveau(r) == 8] == ["ministre_sante"])
    verifier("l'inspecteur général est au-dessus de la direction",
             niveau("inspecteur_general") > niveau("directeur_dpml"))
    verifier("le secrétaire général est au-dessus de l'inspection générale",
             niveau("secretaire_general_ms") > niveau("inspecteur_general"))
    verifier("un chef de service dépasse un chef de bureau",
             niveau("chef_service_amm") > niveau("chef_bureau"))
    verifier("un chef de bureau dépasse un cadre",
             niveau("chef_bureau") > niveau("cadre_dpml"))
    verifier("tous les niveaux de 0 à 8 sont représentés",
             {niveau(r) for r in ROLES} == set(range(9)))


def test_reserve_aux_administrateurs():
    print("\n[4] L'administration système reste fermée")
    ouverts = []
    for role, (_nom, email, _e) in sc.COMPTES.items():
        if role == "administrateur_dpml":
            continue
        if _client(email).get(RESERVE_ADMIN).status_code == 200:
            ouverts.append(role)
    verifier("seul l'administrateur atteint les référentiels", not ouverts,
             ", ".join(ouverts))
    verifier("l'administrateur y accède",
             _client(sc.COMPTES["administrateur_dpml"][1])
             .get(RESERVE_ADMIN).status_code == 200)


def test_reserve_a_l_industriel():
    print("\n[5] L'espace industriel reste fermé aux autres profils")
    ouverts = []
    for role, (_nom, email, _e) in sc.COMPTES.items():
        if role == "demandeur_externe":
            continue
        if _client(email).get(RESERVE_INDUSTRIEL).status_code == 200:
            ouverts.append(role)
    verifier("seul l'industriel atteint son suivi", not ouverts, ", ".join(ouverts))
    verifier("le ministre lui-même n'entre pas dans l'espace industriel",
             _client(sc.COMPTES["ministre_sante"][1])
             .get(RESERVE_INDUSTRIEL).status_code == 403)


def test_circuit_ferme_aux_externes():
    print("\n[6] Le circuit d'un dossier n'est pas une pièce publique")
    from models import DossierAMM
    d = (DossierAMM.query.join(Personne, DossierAMM.demandeur_id == Personne.id)
         .filter(Personne.email == sc.COMPTES["demandeur_externe"][1]).first())
    if d is None:
        verifier("un dossier du déposant de démonstration existe", False)
        return
    url = f"/validation/DossierAMM/{d.id}"

    verifier("le déposant consulte le circuit de SON dossier",
             _client(sc.COMPTES["demandeur_externe"][1]).get(url).status_code == 200)
    for role in ("usager", "pharmacien", "grossiste", "laboratoire_prive",
                 "promoteur_essai"):
        verifier(f"« {role} » ne lit pas le circuit d'autrui",
                 _client(sc.COMPTES[role][1]).get(url).status_code == 404)
    verifier("un agent instructeur y accède au titre de l'instruction",
             _client(sc.COMPTES["cadre_dpml"][1]).get(url).status_code == 200)
    verifier("le parapheur est refusé à un externe",
             _client(sc.COMPTES["usager"][1])
             .get("/validation/parapheur").status_code == 403)


def test_monotonie_de_la_consultation():
    print("\n[7] Monotonie — un supérieur voit au moins ce que voit son subordonné")
    for url in CONSULTATION:
        acces = {}
        for role, (_nom, email, _e) in sc.COMPTES.items():
            acces[role] = _client(email).get(url).status_code == 200
        # Pour chaque rôle autorisé, aucun rôle de niveau strictement supérieur
        # ne doit être refusé.
        anomalies = []
        for role, ouvert in acces.items():
            if not ouvert:
                continue
            for autre, ouvert_autre in acces.items():
                if niveau(autre) > niveau(role) and not ouvert_autre:
                    anomalies.append(f"{autre}(n{niveau(autre)})<{role}(n{niveau(role)})")
        verifier(f"{url} — aucun supérieur exclu là où un subordonné entre",
                 not anomalies, "; ".join(sorted(set(anomalies))[:4]))


def test_consultation_par_le_rang():
    print("\n[8] Le rang ouvre la consultation, jamais la décision")
    ministre = Personne.query.filter_by(
        email=sc.COMPTES["ministre_sante"][1]).first()
    ig = Personne.query.filter_by(email=sc.COMPTES["inspecteur_general"][1]).first()
    cadre = Personne.query.filter_by(email=sc.COMPTES["cadre_dpml"][1]).first()
    usager = Personne.query.filter_by(email=sc.COMPTES["usager"][1]).first()

    for cle in NIVEAU_MINIMAL_CONSULTATION:
        verifier(f"le ministre consulte « {cle} »", a_permission(ministre, cle))
    verifier("l'inspecteur général consulte la reliance",
             a_permission(ig, "consulter_reliance"))
    verifier("un cadre ne consulte pas tout par son seul rang",
             not a_permission(cadre, "voir_toutes_inspections"))
    verifier("un externe ne consulte rien par son rang",
             not any(a_permission(usager, c) for c in NIVEAU_MINIMAL_CONSULTATION))

    # Les actes engageants restent nominatifs : le rang ne les confère pas.
    engageants = [c for c in PERMISSIONS_TRANSVERSES
                  if c not in NIVEAU_MINIMAL_CONSULTATION]
    usurpes = [c for c in engageants
               if a_permission(ministre, c)
               and "ministre_sante" not in PERMISSIONS_TRANSVERSES[c]]
    verifier("aucun acte engageant n'est acquis par le seul rang", not usurpes,
             ", ".join(usurpes))
    verifier("suspendre un établissement reste au directeur",
             PERMISSIONS_TRANSVERSES["suspendre_etablissement"] == ["directeur_dpml"])


def test_annuaire_de_demonstration():
    print("\n[9] Annuaire des comptes de démonstration")
    groupes = sc.annuaire()
    verifier("l'annuaire couvre les neuf niveaux", len(groupes) == 9,
             f"{len(groupes)} groupe(s)")
    total = sum(len(g["comptes"]) for g in groupes)
    verifier("tous les comptes y figurent", total == len(sc.COMPTES),
             f"{total}/{len(sc.COMPTES)}")
    verifier("chaque compte annonce ce qu'il permet d'éprouver",
             all(c["a_eprouver"] for g in groupes for c in g["comptes"]))
    verifier("les niveaux sont croissants",
             [g["niveau"] for g in groupes] == sorted(g["niveau"] for g in groupes))

    anonyme = application.app.test_client()
    r = anonyme.get("/comptes-demonstration")
    verifier("la page est consultable avant connexion", r.status_code == 200)
    verifier("le mot de passe commun y est annoncé",
             sc.MOT_DE_PASSE in r.get_data(as_text=True))
    verifier("l'avertissement de démonstration est présent",
             "réservés à la démonstration" in r.get_data(as_text=True))

    # En production, la page n'existe pas : elle publierait des identifiants.
    application.app.config["MODE_DEMONSTRATION"] = False
    try:
        code = application.app.test_client().get("/comptes-demonstration").status_code
        verifier("la page disparaît hors démonstration", code == 404, str(code))
        page = application.app.test_client().get("/login").get_data(as_text=True)
        verifier("le lien disparaît aussi de la page de connexion",
                 "comptes-demonstration" not in page)
    finally:
        application.app.config["MODE_DEMONSTRATION"] = True

    verifier("les comptes de démonstration sont repérables pour purge",
             len(sc.verifier_avant_production()) >= len(sc.COMPTES))


def main():
    print("=" * 70)
    print("Profils, identifiants et niveaux d'accès")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        for t in (test_couverture_des_roles, test_connexion_de_chaque_profil,
                  test_niveaux_declares, test_reserve_aux_administrateurs,
                  test_reserve_a_l_industriel, test_circuit_ferme_aux_externes,
                  test_monotonie_de_la_consultation, test_consultation_par_le_rang,
                  test_annuaire_de_demonstration):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False,
                         f"{type(e).__name__}: {e}")
        db.session.rollback()

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
