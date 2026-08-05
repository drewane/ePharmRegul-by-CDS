"""
Lancement pour accès réseau local (autres ordinateurs, tablettes, téléphones sur
le même Wi-Fi). Utilise Waitress plutôt que le serveur de développement Flask :
même code applicatif, mais un serveur multi-thread plus stable pour plusieurs
appareils connectés en même temps, et sans le rechargeur automatique de Flask
(qui peut couper les connexions en cours quand un fichier est modifié).

Usage :
    venv\\Scripts\\python.exe run_lan.py

Ou, plus simplement, double-cliquer sur DEMARRER.bat, qui prépare
l'environnement, la base et les comptes avant d'appeler ce script.

Le serveur reste joignable tant que ce processus vit : fermer la fenêtre coupe
l'accès. Il n'y a aucune expiration de lien.
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from waitress import serve

import acces
from app import app

PORT = 5000

if __name__ == "__main__":
    print()
    print(acces.resume(PORT))
    print()
    print("  Comptes de démonstration : /comptes-demonstration "
          "(mot de passe demo1234)")
    print()
    print("  Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
    print()
    try:
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except KeyboardInterrupt:
        print("\nServeur arrêté.")
    except OSError as e:
        print(f"\nImpossible de démarrer sur le port {PORT} : {e}")
        print("Un autre serveur SIREPH tourne peut-être déjà — vérifiez les")
        print("fenêtres ouvertes avant d'en relancer un.")
        sys.exit(1)
