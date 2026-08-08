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
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import Personne, db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHIER_IDENTIFIANTS = os.path.join(BASE_DIR, "instance", "IDENTIFIANTS-PRIVES.txt")
FICHIER_CLE = os.path.join(BASE_DIR, "instance", "cle_secrete.txt")

# Mots courts, sans accent ni homographe : ces phrases se recopient à la main,
# souvent depuis un écran vers un téléphone. Un mot de passe illisible n'est
# pas un mot de passe sûr — il est contourné, noté sur un papier, ou empêche
# simplement de se connecter. La première version de ce script produisait des
# suites comme « A43z75kB3MU2s#L# » : personne n'a pu les saisir.
MOTS = """
acacia acajou acier ancre arbre argile atlas aurore avoine azur balise bambou
baobab basalte bassin bergame beryl bison bosquet boussole brise bruyere cacao
calcaire canari capre cargo cedre cerfeuil chalut chanvre charme chene cistre
citron cobalt colline comete copal corail cormier coton coupole cristal cuivre
cumin cypres dahlia damier delta dolmen dune ebene ecume email emeraude epeautre
erable escale estuaire etoile fanal fenouil ferrite figuier filao flore fougere
frene galet garrigue genet gingembre girofle givre granit grenat gypse harmonie
hetre horizon houle ibis indigo iode iris ivoire jade jaspe jonquille jujube
karite lagune laurier lavande liane lichen limon lin lotus lucarne lupin
magnolia mandarine mangrove marbre menthe mesange meteore mica mimosa mistral
mousson muscade myrte nacre narcisse nebuleuse nenuphar nimbe nopal noyer
obsidienne ocre olivier onyx opale orage orchidee origan osier oursin palme
papyrus paprika passiflore pastel peuplier phare pierre pigment pin pivoine
platane pluie polaire pollen prairie prisme pyrite quartz quinoa raphia ravine
recif reglisse resine rivage romarin roseau rubis safran sagou saline santal
sapin sarment sauge savane sequoia sericine sesame sillage sisal sorbier soufre
spinelle stellaire sureau sycomore syenite talc tamarin tempete terrasse thym
tilleul topaze torrent toundra tourbe tulipe turquoise vanille varech vent
verglas vetiver vigne violette voile zenith zephyr zircon
""".split()

# 4 mots parmi ~210, plus deux chiffres : environ 37 bits d'entropie. C'est
# insuffisant SEUL face à un attaquant qui essaie sans limite — c'est pourquoi
# `anti_force_brute` bloque après cinq échecs. Les deux mesures ne valent
# qu'ensemble : allonger la phrase sans limiter les tentatives, ou l'inverse,
# laisserait le compte exposé.
def mot_de_passe(mots=4):
    phrase = "-".join(secrets.choice(MOTS) for _ in range(mots))
    return f"{phrase}-{secrets.randbelow(90) + 10}"


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
            lignes.append(f"  {c['email']:34}  {c['secret']:34}  {c['role']}")
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
        "Tentatives de connexion limitées à 5 par quart d'heure (anti_force_brute) "
        "— compteur en mémoire, remis à zéro au redémarrage du serveur.",
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
