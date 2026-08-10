"""
Adresse publique FIXE : tunnel Cloudflare nommé.

Un tunnel « rapide » (trycloudflare.com) tire une adresse au hasard à chaque
ouverture. Un tunnel NOMMÉ garde la sienne : il est enregistré sur un compte
Cloudflare et rattaché à un sous-domaine que vous possédez, par exemple
`sireph.mondomaine.cm`. L'adresse ne change plus, jamais.

CE QUE CE MODULE FAIT, ET CE QU'IL NE PEUT PAS FAIRE
-----------------------------------------------------
Il enchaîne les quatre étapes de création et il lance le tunnel. Il ne peut
pas créer votre compte Cloudflare ni acheter votre domaine : l'authentification
passe par votre navigateur, sur le site de Cloudflare, et c'est très bien
ainsi — aucun mot de passe ne transite par ici.

PRÉ-REQUIS RÉSEAU — À VÉRIFIER AVANT TOUT
-----------------------------------------
cloudflared joint l'arête de Cloudflare par le **port 7844**, en TCP et en
UDP. Ce port n'est PAS le 443 : beaucoup de réseaux d'entreprise, et certains
partages de connexion mobiles, le ferment. Dans ce cas le tunnel s'ouvre en
apparence, annonce son adresse, et Cloudflare répond 530 « origine
injoignable » — panne d'autant plus déroutante que le serveur local répond
parfaitement.

`diagnostic()` tranche la question en quelques secondes. Si le port est fermé,
aucun réglage Cloudflare n'y changera rien : il faut ouvrir le port, changer
de réseau, ou passer par un service qui emprunte le 443.

USAGE
-----
    venv\\Scripts\\python tunnel_fixe.py --diagnostic
    venv\\Scripts\\python tunnel_fixe.py --configurer sireph.mondomaine.cm
    venv\\Scripts\\python run_public.py        (utilise le tunnel fixe s'il existe)
"""
import json
import os
import socket
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED = os.path.join(BASE_DIR, "outils", "cloudflared.exe")
CONFIG = os.path.join(BASE_DIR, "instance", "tunnel-fixe.json")
NOM_TUNNEL = "sireph"
PORT_LOCAL = 5000

# Ports de l'arête Cloudflare. Le 7844 est le seul chemin possible : cloudflared
# ne sait pas se replier sur le 443.
HOTES_ARETE = ("region1.v2.argotunnel.com", "region2.v2.argotunnel.com")
PORT_ARETE = 7844


def _port_ouvert(hote, port, delai=8):
    """Le port répond-il ? Jamais plus de `delai` secondes, quoi qu'il arrive.

    Le délai passé à create_connection ne borne que la poignée de main : la
    résolution DNS, elle, peut traîner sans limite, et sur un port filtré
    Windows retransmet ses SYN bien au-delà. Un diagnostic qui se fige est
    pire qu'un diagnostic faux — il bloque le lancement avant toute autre
    tentative. On l'exécute donc dans un fil dont on n'attend que le temps
    imparti ; s'il n'a pas répondu, le port est tenu pour fermé.
    """
    import threading

    resultat = []

    def sonder():
        try:
            with socket.create_connection((hote, port), timeout=delai):
                resultat.append(True)
        except OSError:
            resultat.append(False)

    fil = threading.Thread(target=sonder, daemon=True)
    fil.start()
    fil.join(delai + 2)
    return bool(resultat) and resultat[0]


def diagnostic():
    """Le réseau permet-il un tunnel Cloudflare ? Retourne (possible, détail)."""
    for hote in HOTES_ARETE:
        if _port_ouvert(hote, PORT_ARETE):
            return True, f"{hote}:{PORT_ARETE} joignable"
    reference = _port_ouvert("api.cloudflare.com", 443)
    if reference:
        return False, (
            f"Le port {PORT_ARETE} est fermé en sortie sur ce réseau, alors "
            "que le 443 passe. Un tunnel Cloudflare — rapide ou nommé — ne "
            "peut pas s'établir ici.")
    return False, ("Aucune sortie vers Cloudflare, ni sur 7844 ni sur 443. "
                   "La connexion Internet semble filtrée ou absente.")


def configuration():
    """Configuration du tunnel fixe, ou None s'il n'a jamais été créé."""
    if not os.path.exists(CONFIG):
        return None
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _executer(arguments, titre):
    """Lance cloudflared en laissant sa sortie visible : l'étape d'ouverture de
    session affiche une URL que l'utilisateur doit ouvrir lui-même."""
    print(f"\n>> {titre}")
    resultat = subprocess.run([CLOUDFLARED] + arguments, text=True)
    return resultat.returncode == 0


def configurer(nom_hote):
    """Crée le tunnel nommé et le rattache au sous-domaine demandé.

    Quatre étapes, dans l'ordre :
      1. ouverture de session Cloudflare (dans VOTRE navigateur) ;
      2. création du tunnel, qui produit un certificat local ;
      3. enregistrement DNS pointant le sous-domaine vers ce tunnel ;
      4. mémorisation, pour que run_public.py le retrouve.
    """
    possible, detail = diagnostic()
    if not possible:
        print("CONFIGURATION IMPOSSIBLE SUR CE RÉSEAU")
        print(f"  {detail}")
        print("  Rien ne sert de créer le tunnel : il ne pourrait pas se")
        print("  connecter. Ouvrez le port 7844 en sortie, ou recommencez")
        print("  depuis un réseau qui le laisse passer.")
        return 1

    if not _executer(["tunnel", "login"],
                     "Ouverture de session Cloudflare — une page va s'ouvrir "
                     "dans votre navigateur"):
        print("Session non ouverte. Reprenez lorsque vous serez connecté.")
        return 1

    # `tunnel create` échoue si le nom existe déjà : ce n'est pas une erreur.
    _executer(["tunnel", "create", NOM_TUNNEL],
              f"Création du tunnel « {NOM_TUNNEL} »")

    if not _executer(["tunnel", "route", "dns", "--overwrite-dns",
                      NOM_TUNNEL, nom_hote],
                     f"Rattachement de {nom_hote} au tunnel"):
        print("Le rattachement DNS a échoué. Vérifiez que le domaine est bien")
        print("géré par Cloudflare (serveurs de noms délégués).")
        return 1

    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump({"nom": NOM_TUNNEL, "hote": nom_hote,
                   "url": f"https://{nom_hote}"}, f, ensure_ascii=False,
                  indent=2)

    print("\n" + "=" * 74)
    print("  ADRESSE FIXE CONFIGURÉE")
    print("=" * 74)
    print(f"  https://{nom_hote}")
    print("  Elle ne changera plus. Lancez le serveur avec :")
    print("      venv\\Scripts\\python run_public.py")
    print("=" * 74)
    return 0


def commande_lancement():
    """Arguments cloudflared pour servir le tunnel fixe, ou None."""
    conf = configuration()
    if conf is None:
        return None
    return ["tunnel", "--no-autoupdate", "run",
            "--url", f"http://127.0.0.1:{PORT_LOCAL}", conf["nom"]]


def main():
    if "--diagnostic" in sys.argv:
        possible, detail = diagnostic()
        print("Tunnel Cloudflare possible sur ce réseau : "
              + ("OUI" if possible else "NON"))
        print(f"  {detail}")
        return 0 if possible else 1

    if "--configurer" in sys.argv:
        i = sys.argv.index("--configurer")
        if i + 1 >= len(sys.argv):
            print("Indiquez le sous-domaine : --configurer sireph.mondomaine.cm")
            return 1
        return configurer(sys.argv[i + 1])

    conf = configuration()
    if conf:
        print(f"Tunnel fixe configuré : {conf['url']}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
