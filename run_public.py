"""
Exposition sur Internet, via un tunnel Cloudflare.

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

    print("Ouverture du tunnel...", flush=True)
    tunnel = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://localhost:{PORT}",
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
