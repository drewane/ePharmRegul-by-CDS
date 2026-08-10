"""
Exposition sur Internet : tunnel Cloudflare, ou repli SSH par le port 443.

Publie SIREPH sur une adresse https accessible de n'importe où, sans toucher
au routeur ni au pare-feu. Le tunnel sort de la machine ; rien n'entre.

    venv\\Scripts\\python run_public.py

POURQUOI UN SCRIPT PLUTÔT QUE DES VARIABLES D'ENVIRONNEMENT
-----------------------------------------------------------
La configuration de sécurité tient à deux variables. Posées en préfixe d'une
ligne de commande, elles n'atteignent pas toujours le processus — et l'échec
est silencieux : l'application démarre, sert les pages, et le cookie de
session part sans son attribut `Secure`. On les pose donc ici, en Python,
avant même d'importer l'application.

CE QUE LE SCRIPT REFUSE DE FAIRE
--------------------------------
Il s'arrête si les comptes portent encore le mot de passe commun de
démonstration : exposer sur Internet une application dont tous les comptes
partagent `demo1234`, du simple usager au ministre, reviendrait à n'avoir
aucune authentification. Lancez d'abord `securiser_exposition.py`.
"""
import os
import re
import subprocess
import sys
import threading
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# AVANT tout import de l'application : c'est ce qui rend la configuration sûre.
os.environ["SIREPH_PRODUCTION"] = "1"
os.environ["SIREPH_HTTPS"] = "1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED = os.path.join(BASE_DIR, "outils", "cloudflared.exe")
PORT = 5000
MOTIF_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# L'adresse change à chaque ouverture. On l'écrit aussi sur disque : la console
# peut être bufferisée, minimisée ou fermée par erreur, et l'adresse serait
# alors introuvable alors que le tunnel tourne toujours.
FICHIER_ADRESSE = os.path.join(BASE_DIR, "outils", "adresse_publique.txt")


def _controler_securite():
    """Refuse l'exposition tant que l'application n'a pas été durcie."""
    import app as application
    import seed_comptes
    from models import Personne

    problemes = []
    with application.app.app_context():
        faibles = [p.email for p in Personne.query.all()
                   if p.check_password(seed_comptes.MOT_DE_PASSE)]
        if faibles:
            problemes.append(
                f"{len(faibles)} compte(s) portent encore le mot de passe commun "
                f"« {seed_comptes.MOT_DE_PASSE} » (dont {faibles[0]}).")
    if application.app.config.get("MODE_DEMONSTRATION"):
        problemes.append("L'annuaire des comptes est encore publié.")

    # Le drapeau Secure se décide par requête, selon le schéma réellement
    # employé : on vérifie donc le comportement, pas une valeur de config.
    with application.app.test_request_context(
            "/", headers={"X-Forwarded-Proto": "https"}):
        if not application.app.session_interface.get_cookie_secure(application.app):
            problemes.append(
                "Le cookie de session ne serait pas marqué Secure derrière le "
                "tunnel.")
    if application.app.config["SECRET_KEY"].startswith("sireph-demo"):
        problemes.append(
            "La clé de signature des sessions est encore la valeur de "
            "démonstration : elle permettrait de forger n'importe quelle session.")
    return problemes


def _servir():
    from waitress import serve

    import app as application
    # Waitress efface par défaut les en-têtes X-Forwarded-*, qu'il considère
    # comme non fiables — à raison : n'importe quel client peut les inventer.
    # Conséquence ici : l'application ne voyait pas que la requête venait
    # d'HTTPS et n'appliquait pas le drapeau Secure au cookie de session.
    #
    # cloudflared s'exécute sur cette machine et se connecte par la boucle
    # locale : on peut donc déclarer 127.0.0.1 comme relais de confiance sans
    # ouvrir la porte à un tiers, puisque le serveur n'écoute que là.
    serve(application.app, host="127.0.0.1", port=PORT, threads=8,
          trusted_proxy="127.0.0.1",
          trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto",
                                 "x-forwarded-host"})


def _edge_cloudflare_joignable(delai=6):
    """Le réseau laisse-t-il sortir vers l'arête Cloudflare (TCP 7844) ?

    Certains réseaux d'entreprise et partages de connexion mobiles ferment ce
    port. Le tunnel s'ouvre alors en apparence — il annonce même une adresse —
    puis Cloudflare répond 530 « origine injoignable ». On sonde donc avant,
    plutôt que de laisser l'utilisateur découvrir la panne sur une adresse qui
    ne servira jamais.
    """
    # La sonde de tunnel_fixe est bornée par un fil : un connect vers un port
    # filtré peut sinon traîner bien au-delà de son délai, et le lanceur se
    # figerait avant même d'avoir essayé quoi que ce soit.
    import tunnel_fixe

    return any(tunnel_fixe._port_ouvert(hote, tunnel_fixe.PORT_ARETE, delai)
               for hote in tunnel_fixe.HOTES_ARETE)


def _annoncer(url, voie):
    with open(FICHIER_ADRESSE, "w", encoding="utf-8") as f:
        f.write(url + "\n")
    print()
    print("=" * 74)
    print("  SIREPH est en ligne")
    print("=" * 74)
    print(f"  Adresse publique : {url}")
    print(f"  Voie             : {voie}")
    print("  Ouvrable depuis n'importe quel appareil, sans Wi-Fi commun.")
    print()
    print("  Identifiants : instance\\IDENTIFIANTS-PRIVES.txt")
    print("                 (fichier local — ne le publiez pas)")
    print()
    print("  Cette fenêtre EST le tunnel. La fermer coupe l'accès,")
    print("  et la prochaine ouverture donnera une adresse différente.")
    print("=" * 74)
    print()
    sys.stdout.flush()


MOTIF_URL_SSH = re.compile(
    r"https://[a-z0-9.-]+\.(?:pinggy\.link|pinggy\.net|lhr\.life)")


def _tunnel_ssh_persistant():
    """Maintient un tunnel SSH ouvert, en le rouvrant chaque fois qu'il tombe.

    Le service gratuit ferme la session au bout d'une heure. Sans cette
    boucle, l'adresse cesse simplement de répondre et il faut relancer le
    script à la main — c'est précisément ce qui a fait croire deux fois à une
    panne de connexion.

    La réouverture donne une NOUVELLE adresse : le service gratuit ne réserve
    pas de nom. `outils/adresse_publique.txt` porte toujours l'adresse en
    cours, et la console annonce chaque renouvellement.
    """
    tentative = 0
    try:
        while True:
            url = _tunnel_ssh()
            if url is None:
                tentative += 1
                if tentative >= 3:
                    print("Trois tentatives sans adresse : on s'arrête.")
                    return 1
                attente = 10 * tentative
                print(f"Nouvelle tentative dans {attente} s...", flush=True)
                time.sleep(attente)
                continue
            tentative = 0
            print("Le tunnel s'est fermé (limite du service gratuit). "
                  "Réouverture...", flush=True)
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    finally:
        if os.path.exists(FICHIER_ADRESSE):
            os.remove(FICHIER_ADRESSE)
        print("Tunnel fermé. L'adresse publique ne répond plus.")
    return 0


def _tunnel_ssh():
    """Une session de tunnel inverse SSH par le port 443. Retourne l'URL servie.

    Rend la main quand la session se termine — c'est
    `_tunnel_ssh_persistant` qui décide de rouvrir.

    Choisi parce que 443 sort presque partout, y compris là où le port 7844 de
    Cloudflare est fermé. Aucune inscription ni clé n'est requise.

    DEUX LIMITES À CONNAÎTRE :
      * la version gratuite ferme le tunnel au bout d'une heure — la
        réouverture est automatique, mais l'adresse change ;
      * comme pour Cloudflare, le service voit passer le trafic après
        terminaison TLS de son côté. Acceptable pour une démonstration,
        jamais pour des données réelles.

    localhost.run, sur le port 22, a été écarté : il délivre bien une adresse
    mais son point d'entrée HTTPS refuse la connexion, et servir l'application
    en clair ferait voyager les mots de passe à découvert.
    """
    tunnel = subprocess.Popen(
        ["ssh", "-p", "443", "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "ServerAliveInterval=30",
         "-o", "ExitOnForwardFailure=yes",
         "-R0:127.0.0.1:" + str(PORT), "qr@a.pinggy.io"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1)
    url = None
    debut = time.monotonic()
    try:
        for ligne in tunnel.stdout:
            trouve = MOTIF_URL_SSH.search(ligne)
            if trouve and not url:
                url = trouve.group(0)
                _annoncer(url, "tunnel SSH par le port 443")
            if url is None and time.monotonic() - debut > 90:
                print("Le tunnel SSH n'a pas fourni d'adresse en 90 secondes.")
                break
        tunnel.wait()
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tunnel.kill()
    return url


def main():
    if not os.path.exists(CLOUDFLARED):
        print("cloudflared est absent. Téléchargez-le depuis")
        print("  https://github.com/cloudflare/cloudflared/releases/latest")
        print(f"et placez cloudflared.exe dans {os.path.dirname(CLOUDFLARED)}")
        return 1

    problemes = _controler_securite()
    if problemes:
        print("=" * 74)
        print("EXPOSITION REFUSÉE — l'application n'est pas prête à être publiée")
        print("=" * 74)
        for p in problemes:
            print(f"  - {p}")
        print()
        print("  Lancez d'abord :  venv\\Scripts\\python securiser_exposition.py")
        return 1

    # Le serveur n'écoute que sur la boucle locale : seul le tunnel y accède,
    # ce qui évite d'exposer en clair le même service sur le réseau local.
    threading.Thread(target=_servir, daemon=True).start()
    time.sleep(2)

    # Un tunnel fixe, s'il a été configuré, prime sur tout le reste : c'est la
    # seule voie dont l'adresse ne change pas d'une ouverture à l'autre.
    import tunnel_fixe
    commande = tunnel_fixe.commande_lancement()
    if commande and _edge_cloudflare_joignable():
        conf = tunnel_fixe.configuration()
        threading.Thread(target=_servir, daemon=True).start()
        time.sleep(2)
        _annoncer(conf["url"], "tunnel Cloudflare nommé — adresse permanente")
        tunnel = subprocess.Popen([CLOUDFLARED] + commande)
        try:
            tunnel.wait()
        except KeyboardInterrupt:
            pass
        finally:
            tunnel.terminate()
            if os.path.exists(FICHIER_ADRESSE):
                os.remove(FICHIER_ADRESSE)
        return 0
    if commande:
        print("Un tunnel fixe est configuré, mais le port 7844 est fermé sur "
              "ce réseau : impossible de l'utiliser ici.", flush=True)

    if not _edge_cloudflare_joignable():
        print("Le port 7844, nécessaire au tunnel Cloudflare, est bloqué en "
              "sortie sur ce réseau.", flush=True)
        print("Repli sur un tunnel SSH (localhost.run), qui passe par le "
              "port 22.\n", flush=True)
        return _tunnel_ssh_persistant()

    print("Ouverture du tunnel...", flush=True)
    # 127.0.0.1 et non « localhost » : Windows résout localhost en ::1 avant
    # 127.0.0.1, or le serveur n'écoute qu'en IPv4. Le tunnel s'ouvre alors
    # normalement, annonce son adresse, et Cloudflare répond 530 « origine
    # injoignable » — panne d'autant plus déroutante que le serveur local
    # répond parfaitement quand on le teste à la main.
    tunnel = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{PORT}",
         "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1)

    url = None
    debut = time.monotonic()
    try:
        for ligne in tunnel.stdout:
            trouve = MOTIF_URL.search(ligne)
            if trouve and not url:
                url = trouve.group(0)
                with open(FICHIER_ADRESSE, "w", encoding="utf-8") as f:
                    f.write(url + "\n")
                print()
                print("=" * 74)
                print("  SIREPH est en ligne")
                print("=" * 74)
                print(f"  Adresse publique : {url}")
                print("  Ouvrable depuis n'importe quel appareil, sans Wi-Fi commun.")
                print()
                print("  Identifiants : instance\\IDENTIFIANTS-PRIVES.txt")
                print("                 (fichier local — ne le publiez pas)")
                print()
                print("  Cette fenêtre EST le tunnel. La fermer coupe l'accès,")
                print("  et la prochaine ouverture donnera une adresse différente.")
                print("=" * 74)
                print()
                sys.stdout.flush()
            if url is None and time.monotonic() - debut > 60:
                print("Le tunnel n'a pas fourni d'adresse en 60 secondes.")
                break
        tunnel.wait()
    except KeyboardInterrupt:
        print("\nFermeture du tunnel...")
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tunnel.kill()
        if os.path.exists(FICHIER_ADRESSE):
            os.remove(FICHIER_ADRESSE)
        print("Tunnel fermé. L'adresse publique ne répond plus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
