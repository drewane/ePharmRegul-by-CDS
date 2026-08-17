"""
Tests de la matrice d'accès et de la navigation qui s'en déduit.

Trois exigences du cahier des charges :
  * « Demandes d'inspection » quitte le menu principal et devient un
    sous-onglet de « Demande » ;
  * un clic déroule un groupe, un second le replie ;
  * les rubriques hors profil sont GRISÉES — visibles, non cliquables, avec le
    motif — et non masquées : masquer appauvrit la lisibilité de l'offre.

Une quatrième, plus discrète mais décisive : le menu ne doit jamais promettre
ce que le serveur refusera. Le dernier test compare donc les deux.

Exécution :  venv\\Scripts\\python test_matrice_navigation.py
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import matrice_acces as ma
import seed_comptes as sc
import taxonomie_demandes as tax
from models import Personne, db
from permissions import ROLES, ROLES_EXTERNES

_res = []


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def _u(email):
    return Personne.query.filter_by(email=email).first()


def _menu(email, drapeaux=None):
    with application.app.test_request_context("/"):
        return ma.entrees(_u(email), drapeaux or {})


def _plat(menu):
    """Libellés de premier niveau."""
    return [e["libelle"] for e in menu]


def _sous(menu, code):
    for e in menu:
        if e["code"] == code:
            return e["enfants"]
    return []


def test_matrice_saine():
    print("\n[1] Déclaration de la matrice")
    anomalies = ma.verifier_matrice()
    verifier("aucune anomalie de déclaration", not anomalies, "; ".join(anomalies))
    verifier("chaque profil externe a une fiche",
             all(r in ma.PROFILS_DEMANDEUR for r in ROLES_EXTERNES),
             str(set(ROLES_EXTERNES) - set(ma.PROFILS_DEMANDEUR)))
    verifier("les cinq rôles du cahier ont une correspondance réelle",
             all(v in ROLES for v in ma.CORRESPONDANCE_ROLES.values()),
             str([v for v in ma.CORRESPONDANCE_ROLES.values() if v not in ROLES]))
    verifier("les profils du cahier ont une correspondance réelle",
             all(v in ROLES for v in ma.CORRESPONDANCE_PROFILS.values()))
    verifier("le profil fabricant existe désormais", "fabricant" in ROLES)
    verifier("role_reel traduit le vocabulaire du cahier",
             ma.role_reel("financier") == "responsable_financier"
             and ma.role_reel("directeur") == "directeur_dpml")


def test_inspection_quitte_le_menu_principal():
    print("\n[2] « Demandes d'inspection » n'est plus au premier niveau")
    menu = _menu("demandeur@pharmacam.demo", {"demandeur_a_amm": True})
    principaux = _plat(menu)
    verifier("aucune entrée « inspection » au premier niveau",
             not any("nspection" in libelle for libelle in principaux),
             str(principaux))
    sous = [f["libelle"] for f in _sous(menu, "demande")]
    verifier("l'inspection figure sous « Demande »",
             any("nspection" in libelle for libelle in sous), str(sous))
    verifier("elle reste accessible au laboratoire",
             any("nspection" in f["libelle"] and f["accessible"]
                 for f in _sous(menu, "demande")))


def test_structure_attendue():
    print("\n[3] Structure cible du menu")
    menu = _menu("demandeur@pharmacam.demo", {"demandeur_a_amm": True})
    attendus = ["Tableau de bord", "Mon portefeuille", "Suivi de mes dossiers",
                "Demande", "Mes paiements", "Dossiers AMM", "Essais cliniques",
                "Dérogations spéciales", "Visas techniques"]
    verifier("les neuf entrées du cahier, dans l'ordre",
             _plat(menu) == attendus, str(_plat(menu)))
    verifier("« Demande » porte les quatre familles",
             len(_sous(menu, "demande")) == 4)
    verifier("les sous-onglets viennent de la taxonomie",
             [f["code"] for f in _sous(menu, "demande")]
             == [n["code"] for n in tax.ARBORESCENCE])


def test_grisage_par_profil():
    print("\n[4] Grisage, et non masquage")
    labo = _menu("demandeur@pharmacam.demo", {"demandeur_a_amm": True})
    essais = next(e for e in labo if e["code"] == "essais")
    verifier("l'essai clinique est PRÉSENT pour un labo AMM",
             essais is not None)
    verifier("mais grisé, comme le demande le cahier",
             not essais["accessible"])
    verifier("le motif est explicite",
             "profil" in (essais["motif"] or "").lower(), essais["motif"])
    verifier("son sous-onglet est grisé aussi",
             all(not f["accessible"] for f in essais["enfants"]))
    verifier("le sous-onglet Essai clinique de « Demande » est grisé",
             any(f["code"] == "essai_clinique" and not f["accessible"]
                 for f in _sous(labo, "demande")))
    verifier("l'homologation, elle, reste ouverte",
             any(f["code"] == "homologation" and f["accessible"]
                 for f in _sous(labo, "demande")))

    fab = _menu("fabricant@wouri.demo")
    verifier("pour un fabricant, l'homologation est grisée",
             any(f["code"] == "homologation" and not f["accessible"]
                 for f in _sous(fab, "demande")))
    verifier("pour un fabricant, les agréments sont ouverts",
             any(f["code"] == "agrements" and f["accessible"]
                 for f in _sous(fab, "demande")))
    verifier("l'inspection lui reste ouverte",
             any(f["code"] == "inspection" and f["accessible"]
                 for f in _sous(fab, "demande")))

    promo = _menu("promoteur@essai.demo")
    verifier("pour un promoteur, l'essai clinique est ouvert",
             any(f["code"] == "essai_clinique" and f["accessible"]
                 for f in _sous(promo, "demande")))


def test_agents_non_grises():
    print("\n[5] Un agent n'a pas de profil demandeur — rien ne lui est grisé")
    for role in ("chef_service_amm", "directeur_dpml", "responsable_financier"):
        menu = _menu(sc.COMPTES[role][1])
        grisees = [e["libelle"] for e in menu if not e["accessible"]]
        verifier(f"« {role} » n'a aucune entrée grisée", not grisees,
                 str(grisees))
    verifier("l'agent ne voit pas « Mon portefeuille »",
             "Mon portefeuille" not in _plat(_menu(sc.COMPTES["directeur_dpml"][1])))
    verifier("l'usager ne voit ni portefeuille ni suivi",
             not {"Mon portefeuille", "Suivi de mes dossiers"}
             & set(_plat(_menu(sc.COMPTES["usager"][1]))))


def test_accordeon_rendu():
    print("\n[6] Accordéon : un clic déroule, un second replie")
    client = application.app.test_client()
    email = sc.COMPTES["demandeur_externe"][1]
    client.post("/login", data={"email": email,
                                "password": sc.mot_de_passe_courant(email)})
    page = client.get("/", follow_redirects=True).get_data(as_text=True)

    verifier("les groupes utilisent le repli Bootstrap",
             'data-bs-toggle="collapse"' in page)
    verifier("chaque groupe a une cible identifiée", 'id="groupe-demande"' in page)
    verifier("l'état déplié est annoncé aux lecteurs d'écran",
             'aria-expanded=' in page and 'aria-controls="groupe-demande"' in page)
    verifier("le chevron reflète l'état", "sireph-chevron" in page)
    verifier("les entrées grisées portent une infobulle",
             'data-bs-toggle="tooltip"' in page)
    verifier("les entrées grisées sortent de la navigation clavier",
             'tabindex="-1"' in page and 'aria-disabled="true"' in page)
    verifier("le groupe de la page courante est ouvert d'emblée",
             "collapse show" in page or 'class="collapse ' in page)


def test_menu_ouvert_sur_la_page_courante():
    print("\n[7] Le groupe s'ouvre sur la rubrique consultée")
    with application.app.test_request_context("/demandes/rubrique/homologation"):
        menu = ma.entrees(_u("demandeur@pharmacam.demo"), {},
                          "/demandes/rubrique/homologation")
    demande = next(e for e in menu if e["code"] == "demande")
    verifier("le groupe « Demande » est ouvert",
             demande["ouvert"], str(demande["ouvert"]))
    verifier("le sous-onglet consulté est marqué actif",
             any(f["actif"] for f in demande["enfants"]))

    with application.app.test_request_context("/"):
        menu = ma.entrees(_u("demandeur@pharmacam.demo"), {}, "/")
    demande = next(e for e in menu if e["code"] == "demande")
    verifier("ailleurs, le groupe reste replié", not demande["ouvert"])


def test_menu_et_serveur_concordent():
    print("\n[8] Le menu ne promet rien que le serveur refuse")
    # Une entrée présentée comme accessible doit répondre ; une entrée grisée
    # ne doit pas être annoncée comme cliquable. C'est la garantie qui manque
    # quand le menu est écrit à la main dans le gabarit.
    for role in ("demandeur_externe", "fabricant", "grossiste",
                 "promoteur_essai"):
        email = sc.COMPTES[role][1]
        client = application.app.test_client()
        client.post("/login", data={"email": email,
                                    "password": sc.mot_de_passe_courant(email)})
        menu = _menu(email, {"demandeur_a_amm": True})
        incoherences = []
        for e in menu:
            cibles = ([(e["libelle"], e["href"])] if e["accessible"] and e["href"]
                      else [])
            cibles += [(f["libelle"], f["href"]) for f in e["enfants"]
                       if f["accessible"]]
            for libelle, href in cibles:
                code = client.get(href, follow_redirects=True).status_code
                if code != 200:
                    incoherences.append(f"{libelle} → {code}")
        verifier(f"« {role} » : tout ce qui est offert répond",
                 not incoherences, "; ".join(incoherences[:3]))


def test_facade_renommee():
    print("\n[9] Renommage de façade")
    page = application.app.test_client().get("/login").get_data(as_text=True)
    verifier("le nom commercial est ePharmRegul", "ePharmRegul" in page)
    verifier("l'éditeur est mentionné", "by CDS" in page)
    verifier("l'ancien nom ne s'affiche plus dans l'ossature",
             "Système Intégré de Régulation Pharmaceutique" not in page)
    verifier("le pied de page cite l'autorité",
             "Ministère de la Santé Publique" in page
             or "MINSANTE" in page)


def main():
    print("=" * 70)
    print("Matrice d'accès et navigation")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        for t in (test_matrice_saine, test_inspection_quitte_le_menu_principal,
                  test_structure_attendue, test_grisage_par_profil,
                  test_agents_non_grises, test_accordeon_rendu,
                  test_menu_ouvert_sur_la_page_courante,
                  test_menu_et_serveur_concordent, test_facade_renommee):
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
