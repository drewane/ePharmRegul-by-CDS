"""
Tests de la connexion : mots de passe saisissables et tentatives limitées.

Les deux vont ensemble. Une phrase de passe mémorisable serait imprudente sans
limitation du nombre d'essais ; une limitation stricte serait pénible avec un
mot de passe illisible, que l'on se trompe forcément à saisir.

Exécution :  venv\\Scripts\\python test_connexion.py
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import anti_force_brute as afb
import app as application
import securiser_exposition as se
import seed_comptes as sc
from models import Personne, db

_res = []


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def test_mots_de_passe_saisissables():
    print("\n[1] Des mots de passe qu'on peut réellement taper")
    verifier("liste de mots suffisante", len(se.MOTS) >= 200, str(len(se.MOTS)))
    verifier("aucun doublon", len(se.MOTS) == len(set(se.MOTS)))
    verifier("aucun accent ni caractère exotique",
             all(m.isascii() and m.isalpha() and m.islower() for m in se.MOTS),
             str([m for m in se.MOTS if not (m.isascii() and m.isalpha())][:3]))
    # L'ambiguïté l/1/I ou O/0 ne concerne que les suites aléatoires : dans
    # « lotus » ou « iris », le mot lui-même lève le doute. Ce qui compte ici,
    # c'est qu'aucun mot ne soit trop court pour être reconnu de loin.
    verifier("aucun mot trop court pour être relu",
             all(len(m) >= 3 for m in se.MOTS),
             str([m for m in se.MOTS if len(m) < 3]))

    echantillon = [se.mot_de_passe() for _ in range(200)]
    verifier("quatre mots et un nombre",
             all(len(p.split("-")) == 5 for p in echantillon))
    verifier("uniquement lettres, chiffres et tirets",
             all(c.isalnum() or c == "-" for p in echantillon for c in p))
    verifier("deux tirages ne se répètent pas",
             len(set(echantillon)) == len(echantillon))
    verifier("longueur raisonnable à saisir",
             all(20 <= len(p) <= 45 for p in echantillon),
             f"{min(len(p) for p in echantillon)}–{max(len(p) for p in echantillon)}")


def test_comptes_reellement_a_jour():
    print("\n[2] Le fichier d'identifiants correspond à la base")
    with application.app.app_context():
        divergents, absents = [], []
        for role, (_nom, email, _e) in sc.COMPTES.items():
            p = Personne.query.filter_by(email=email).first()
            if p is None:
                absents.append(email)
                continue
            if not p.check_password(sc.mot_de_passe_courant(email)):
                divergents.append(email)
        verifier("aucun compte manquant", not absents, ", ".join(absents))
        verifier("le mot de passe annoncé ouvre bien le compte",
                 not divergents, ", ".join(divergents[:3]))
        verifier("l'ancien mot de passe commun ne fonctionne plus",
                 not any(p.check_password("demo1234")
                         for p in Personne.query.all())
                 if sc._exposition_durcie() else True)


def test_blocage_apres_echecs():
    print("\n[3] Les tentatives sont limitées")
    afb.reinitialiser()
    email, ip = "cible@test.demo", "203.0.113.7"

    verifier("aucun blocage au départ", afb.secondes_restantes(email, ip) == 0)
    verifier("tous les essais sont disponibles",
             afb.essais_restants(email, ip) == afb.MAX_ESSAIS)

    for i in range(afb.MAX_ESSAIS - 1):
        afb.enregistrer_echec(email, ip)
    verifier("pas encore bloqué avant le seuil",
             afb.secondes_restantes(email, ip) == 0,
             f"{afb.essais_restants(email, ip)} essai(s) restant(s)")
    verifier("l'utilisateur est averti avant la sanction",
             afb.essais_restants(email, ip) == 1)

    declenche = afb.enregistrer_echec(email, ip)
    verifier("le seuil déclenche le blocage", declenche == afb.BLOCAGE)
    verifier("les tentatives suivantes sont refusées",
             afb.secondes_restantes(email, ip) > 0,
             afb.duree_lisible(afb.secondes_restantes(email, ip)))

    # Une autre IP ne doit pas être punie pour ce compte... mais le compte, si.
    afb.reinitialiser()
    for _ in range(afb.MAX_ESSAIS):
        afb.enregistrer_echec(email, "198.51.100.4")
    verifier("le compte reste protégé depuis une autre adresse",
             afb.secondes_restantes(email, "203.0.113.99") > 0)

    # Et une IP qui balaie plusieurs comptes est bloquée elle aussi.
    afb.reinitialiser()
    for i in range(afb.MAX_ESSAIS):
        afb.enregistrer_echec(f"compte{i}@test.demo", "192.0.2.50")
    verifier("une adresse qui balaie les comptes est bloquée",
             afb.secondes_restantes("encore-un@test.demo", "192.0.2.50") > 0)


def test_succes_efface_le_compteur():
    print("\n[4] Une réussite efface l'ardoise")
    afb.reinitialiser()
    email, ip = "maladroit@test.demo", "203.0.113.8"
    for _ in range(afb.MAX_ESSAIS - 1):
        afb.enregistrer_echec(email, ip)
    verifier("compteur entamé", afb.essais_restants(email, ip) < afb.MAX_ESSAIS)
    afb.enregistrer_succes(email, ip)
    verifier("compteur remis à zéro après connexion réussie",
             afb.essais_restants(email, ip) == afb.MAX_ESSAIS)
    verifier("aucun blocage résiduel", afb.secondes_restantes(email, ip) == 0)


def test_bout_en_bout():
    print("\n[5] Comportement réel de l'écran de connexion")
    afb.reinitialiser()
    with application.app.app_context():
        email = sc.COMPTES["demandeur_externe"][1]
        bon = sc.mot_de_passe_courant(email)

    client = application.app.test_client()
    r = client.post("/login", data={"email": email, "password": bon},
                    follow_redirects=True)
    verifier("le bon mot de passe ouvre la session",
             "Déconnexion" in r.get_data(as_text=True))

    afb.reinitialiser()
    mauvais = application.app.test_client()
    for i in range(afb.MAX_ESSAIS):
        r = mauvais.post("/login", data={"email": email, "password": "faux"})
    corps = r.get_data(as_text=True)
    verifier("le blocage est annoncé à l'écran",
             "Trop de tentatives" in corps, corps[-200:] if "Trop" not in corps else "")

    # Même avec le bon mot de passe, le blocage tient.
    r = mauvais.post("/login", data={"email": email, "password": bon},
                     follow_redirects=True)
    verifier("le blocage résiste au bon mot de passe",
             "Déconnexion" not in r.get_data(as_text=True))

    # Un autre poste n'est pas affecté par le blocage du premier... sauf que
    # le compte lui-même est protégé : c'est voulu.
    afb.reinitialiser()
    verifier("après remise à zéro, la connexion repasse",
             "Déconnexion" in application.app.test_client().post(
                 "/login", data={"email": email, "password": bon},
                 follow_redirects=True).get_data(as_text=True))


def main():
    print("=" * 70)
    print("Connexion — mots de passe saisissables et tentatives limitées")
    print("=" * 70)
    for t in (test_mots_de_passe_saisissables, test_comptes_reellement_a_jour,
              test_blocage_apres_echecs, test_succes_efface_le_compteur,
              test_bout_en_bout):
        try:
            t()
        except Exception as e:                       # noqa: BLE001
            with application.app.app_context():
                db.session.rollback()
            verifier(f"{t.__name__} sans exception", False,
                     f"{type(e).__name__}: {e}")
    afb.reinitialiser()

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
