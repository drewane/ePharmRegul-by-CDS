"""
Lancement pour accès réseau local (autres ordinateurs, tablettes, téléphones sur
le même Wi-Fi). Utilise Waitress plutôt que le serveur de développement Flask :
même code applicatif, mais un serveur multi-thread plus stable pour plusieurs
appareils connectés en même temps, et sans le rechargeur automatique de Flask
(qui peut couper les connexions en cours quand un fichier est modifié).

Usage :
    venv\\Scripts\\python.exe run_lan.py

Affiche l'adresse à utiliser depuis les autres appareils du réseau. Voir
SETUP.md pour la configuration du pare-feu Windows nécessaire à l'accès
réseau/mobile.
"""
import socket

from waitress import serve

from app import app


def _adresse_locale():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    ip = _adresse_locale()
    port = 5000
    print("SIREPH — accès réseau local")
    print(f"  Sur cet ordinateur      : http://localhost:{port}")
    print(f"  Depuis un autre appareil : http://{ip}:{port}")
    print("  (l'appareil doit être sur le même réseau Wi-Fi ; voir SETUP.md")
    print("   si la connexion échoue — pare-feu Windows généralement en cause)")
    print()
    serve(app, host="0.0.0.0", port=port, threads=8)
