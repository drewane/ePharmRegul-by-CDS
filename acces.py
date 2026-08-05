"""
Adresses d'accès à SIREPH — poste, réseau local, téléphone.

Le serveur ne « périme » pas : il vit le temps du processus qui l'exécute.
Ce module donne les adresses par lesquelles on l'atteint, et un QR code à
scanner pour ouvrir l'application sur un téléphone sans recopier l'adresse à
la main — l'adresse IP change à chaque changement de réseau Wi-Fi, et la
recopier de tête est la première source d'échec.
"""
import base64
import io
import socket

PORT_DEFAUT = 5000


def adresse_locale():
    """Adresse IPv4 de cette machine sur son réseau, ou None si hors réseau.

    On ouvre un socket UDP vers une adresse extérieure sans rien émettre :
    c'est le moyen le plus fiable de laisser le système choisir l'interface
    réellement utilisée, plutôt que d'énumérer des cartes réseau dont
    plusieurs sont virtuelles (VPN, WSL, machines virtuelles).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def urls(port=PORT_DEFAUT):
    """Les adresses utiles, avec leur destinataire."""
    ip = adresse_locale()
    return {
        "poste": f"http://localhost:{port}",
        "reseau": f"http://{ip}:{port}" if ip else None,
        "ip": ip,
        "port": port,
    }


def qr_data_uri(url, taille=8):
    """QR code du lien, en data URI — aucune ressource externe à charger."""
    import qrcode

    img = qrcode.make(url, box_size=taille, border=2)
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode()


def regle_pare_feu_presente(port=PORT_DEFAUT):
    """La règle de pare-feu entrante existe-t-elle ?

    Sans elle, Windows refuse silencieusement les connexions des autres
    appareils : le serveur tourne, le téléphone ne charge rien, et rien
    n'explique pourquoi. Autant le dire à l'écran. Retourne None si la
    question n'a pas de sens sur cette plateforme ou n'a pas pu être tranchée.
    """
    import subprocess
    import sys

    if not sys.platform.startswith("win"):
        return None
    try:
        sortie = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name=SIREPH (port {port})"],
            capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return None
    return sortie.returncode == 0 and "SIREPH" in (sortie.stdout or "")


COMMANDE_PARE_FEU = (
    'New-NetFirewallRule -DisplayName "SIREPH (port {port})" -Direction Inbound '
    '-Protocol TCP -LocalPort {port} -Action Allow -Profile Private')


def resume(port=PORT_DEFAUT):
    """Bloc texte affiché au lancement, en console."""
    u = urls(port)
    lignes = ["SIREPH — adresses d'accès",
              f"  Sur cet ordinateur       : {u['poste']}"]
    if u["reseau"]:
        lignes.append(f"  Téléphone / autre poste  : {u['reseau']}")
        lignes.append(f"  QR code à scanner        : {u['poste']}/acces")
    else:
        lignes.append("  Téléphone / autre poste  : indisponible "
                      "(cet ordinateur n'est sur aucun réseau)")
    if regle_pare_feu_presente(port) is False:
        lignes += ["",
                   "  Le pare-feu Windows bloque encore le port : les autres",
                   "  appareils ne se connecteront pas. Dans un PowerShell",
                   "  ADMINISTRATEUR, une seule fois :",
                   "    " + COMMANDE_PARE_FEU.format(port=port)]
    return "\n".join(lignes)
