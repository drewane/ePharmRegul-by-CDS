"""
Préparation d'une exposition sur Internet.

Ce que le mode démonstration tolère devient dangereux dès que l'application
est joignable de n'importe où : un annuaire publiant les identifiants, un mot
de passe unique pour trente-deux comptes, une clé de session en dur. Ce script
traite ces trois points.

    venv\\Scripts\\python securiser_exposition.py

Il attribue à chaque compte un mot de passe distinct, tiré au hasard, et les
écrit dans `instance/IDENTIFIANTS-PRIVES.txt` — un fichier local, exclu du
dépôt, qui ne quitte jamais cette machine. Aucun mot de passe n'est affiché
sur une page web ni transmis nulle part.

RETOUR EN ARRIÈRE
-----------------
    venv\\Scripts\\python securiser_exposition.py --restaurer-demo

remet le mot de passe commun `demo1234` partout. À n'utiliser qu'une fois le
tunnel refermé.
"""
import os
import secrets
import string
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import Personne, db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHIER_IDENTIFIANTS = os.path.join(BASE_DIR, "instance", "IDENTIFIANTS-PRIVES.txt")
FICHIER_CLE = os.path.join(BASE_DIR, "instance", "cle_secrete.txt")

# Alphabet sans caractères ambigus : l/1/I et O/0 se confondent à la lecture,
# et ces mots de passe seront recopiés à la main depuis un fichier texte.
ALPHABET = ("".join(c for c in string.ascii_letters + string.digits
                    if c not in "lI1O0") + "!@#%*+-=?")


def mot_de_passe(longueur=16):
    return "".join(secrets.choice(ALPHABET) for _ in range(longueur))


def cle_secrete():
    """Clé de signature des sessions, créée une fois puis conservée."""
    if os.path.exists(FICHIER_CLE):
        with open(FICHIER_CLE, encoding="utf-8") as f:
            existante = f.read().strip()
        if existante:
            return existante, False
    valeur = secrets.token_urlsafe(48)
    os.makedirs(os.path.dirname(FICHIER_CLE), exist_ok=True)
    with open(FICHIER_CLE, "w", encoding="utf-8") as f:
        f.write(valeur)
    return valeur, True


def reinitialiser_mots_de_passe():
    """Un mot de passe distinct par compte. Retourne la liste (compte, secret)."""
    from permissions import LIBELLE_NIVEAU, ROLES, niveau

    attribues = []
    for p in Personne.query.order_by(Personne.id).all():
        secret = mot_de_passe()
        p.set_password(secret)
        attribues.append({
            "email": p.email, "nom": p.nom_complet,
            "role": ROLES.get(p.role_systeme, p.role_systeme),
            "niveau": niveau(p.role_systeme),
            "libelle_niveau": LIBELLE_NIVEAU.get(niveau(p.role_systeme), ""),
            "secret": secret,
        })
    db.session.commit()
    return attribues


def ecrire_identifiants(attribues):
    """Écrit les identifiants dans un fichier local, jamais servi par le web."""
    from datetime import datetime

    os.makedirs(os.path.dirname(FICHIER_IDENTIFIANTS), exist_ok=True)
    lignes = [
        "IDENTIFIANTS SIREPH — DOCUMENT CONFIDENTIEL",
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
        "",
        "Ce fichier ne quitte pas cette machine : il est exclu du dépôt git et",
        "n'est servi par aucune route de l'application. Ne le transmettez que",
        "par un canal sûr, et à la seule personne concernée par chaque compte.",
        "=" * 78, "",
    ]
    par_niveau = {}
    for c in attribues:
        par_niveau.setdefault(c["niveau"], []).append(c)
    for n in sorted(par_niveau):
        lignes.append(f"-- Niveau {n} — {par_niveau[n][0]['libelle_niveau']} "
                      + "-" * 30)
        for c in sorted(par_niveau[n], key=lambda x: x["role"]):
            lignes.append(f"  {c['email']:36} {c['secret']:18} {c['role']}")
        lignes.append("")
    with open(FICHIER_IDENTIFIANTS, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))
    return FICHIER_IDENTIFIANTS


def restaurer_demo():
    """Remet le mot de passe commun — uniquement après fermeture du tunnel."""
    import seed_comptes

    n = 0
    for p in Personne.query.all():
        p.set_password(seed_comptes.MOT_DE_PASSE)
        n += 1
    db.session.commit()
    if os.path.exists(FICHIER_IDENTIFIANTS):
        os.remove(FICHIER_IDENTIFIANTS)
    return n


def controles_restants():
    """Ce que ce script ne traite pas, et qu'il faut savoir avant d'exposer."""
    return [
        "Base SQLite locale, sans sauvegarde automatique ni chiffrement au repos.",
        "Aucune limitation du nombre de tentatives de connexion.",
        "Pas de double authentification.",
        "Pas de journalisation des accès au niveau du serveur web.",
        "Signature électronique interne (empreinte HMAC), non qualifiée au sens "
        "réglementaire.",
        "Aucune donnée réelle ne devrait transiter par cette exposition.",
    ]


def main():
    import app as application

    restaurer = "--restaurer-demo" in sys.argv
    with application.app.app_context():
        if restaurer:
            n = restaurer_demo()
            print(f"Mot de passe commun rétabli sur {n} compte(s).")
            print("L'application est de nouveau en configuration de démonstration.")
            return 0

        _cle, creee = cle_secrete()
        attribues = reinitialiser_mots_de_passe()
        chemin = ecrire_identifiants(attribues)

        print("=" * 78)
        print("PRÉPARATION D'UNE EXPOSITION SUR INTERNET")
        print("=" * 78)
        print(f"  Clé de session      : {'créée' if creee else 'déjà en place'} "
              f"({os.path.relpath(FICHIER_CLE, BASE_DIR)})")
        print(f"  Mots de passe       : {len(attribues)} comptes, un secret "
              "distinct par compte")
        print(f"  Identifiants écrits : {os.path.relpath(chemin, BASE_DIR)}")
        print()
        print("  Lancez ensuite le serveur avec SIREPH_PRODUCTION=1 : l'annuaire")
        print("  des comptes disparaît, et les cookies de session passent en")
        print("  Secure/HttpOnly.")
        print()
        print("  CE QUI RESTE NON TRAITÉ")
        for point in controles_restants():
            print(f"    - {point}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
