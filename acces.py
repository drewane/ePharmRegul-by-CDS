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


# Interroger Windows coûte cher : chaque appel lance un processus PowerShell,
# soit deux à trois secondes. La page d'accès en enchaînait quatre et mettait
# onze secondes à s'afficher. On mémorise brièvement les réponses — assez pour
# qu'une page ne paie qu'une fois, assez peu pour qu'un changement de réseau
# soit visible en rechargeant.
_CACHE = {}
_CACHE_SECONDES = 20


def _memo(cle, calcul):
    import time

    maintenant = time.monotonic()
    valeur, expire = _CACHE.get(cle, (None, 0))
    if maintenant < expire:
        return valeur
    valeur = calcul()
    _CACHE[cle] = (valeur, maintenant + _CACHE_SECONDES)
    return valeur


def _powershell(commande, timeout=10):
    """Exécute une commande PowerShell et rend sa sortie, ou None en cas d'échec.

    L'encodage est forcé en UTF-8 des deux côtés : par défaut la console
    Windows répond en page de code OEM, et un nom de réseau accentué revenait
    en « R‚seau ». La commande de correction affichée à l'utilisateur devenait
    alors incopiable — un défaut d'autant plus fâcheux qu'elle est justement
    ce qui débloque l'accès.
    """
    import subprocess
    import sys

    if not sys.platform.startswith("win"):
        return None
    prelude = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    try:
        sortie = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             prelude + commande],
            capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if sortie.returncode != 0:
        return None
    return sortie.stdout.decode("utf-8", errors="replace").strip()


def profil_reseau():
    """Catégorie Windows du réseau actif : Private, Public ou DomainAuthenticated.

    Ce détail décide de tout : une règle de pare-feu créée pour le profil
    « Privé » ne s'applique pas si Windows a classé le réseau en « Public ».
    La règle existe alors, la commande a réussi, et rien ne fonctionne.
    """
    return _memo("profil", lambda: _powershell(
        "(Get-NetConnectionProfile | Select-Object -First 1).NetworkCategory"))


def nom_reseau():
    return _memo("nom_reseau", lambda: _powershell(
        "(Get-NetConnectionProfile | Select-Object -First 1).Name"))


def regle_pare_feu_presente(port=PORT_DEFAUT):
    """La règle entrante existe-t-elle ET couvre-t-elle le réseau actif ?

    Sans elle, Windows refuse silencieusement les connexions des autres
    appareils : le serveur tourne, le téléphone ne charge rien, et rien
    n'explique pourquoi. Retourne None si la question n'a pas de sens sur
    cette plateforme ou n'a pas pu être tranchée.
    """
    profils = _memo(f"regle_{port}", lambda: _powershell(
        f'(Get-NetFirewallRule -DisplayName "SIREPH (port {port})" '
        '-ErrorAction SilentlyContinue | Where-Object '
        '{ $_.Enabled -eq "True" -and $_.Direction -eq "Inbound" -and '
        '$_.Action -eq "Allow" }).Profile'))
    if profils is None:
        return None
    if not profils:
        return False
    couverts = {p.strip().lower() for p in profils.replace("\n", ",").split(",")}
    if "any" in couverts:
        return True
    actif = (profil_reseau() or "").strip().lower()
    if not actif:
        return bool(couverts)
    # DomainAuthenticated côté profil réseau ↔ Domain côté règle de pare-feu.
    return actif.replace("domainauthenticated", "domain") in couverts


COMMANDE_PARE_FEU = (
    'New-NetFirewallRule -DisplayName "SIREPH (port {port})" -Direction Inbound '
    '-Protocol TCP -LocalPort {port} -Action Allow -Profile Private')

COMMANDE_RESEAU_PRIVE = (
    'Set-NetConnectionProfile -Name "{reseau}" -NetworkCategory Private')


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
                   "  ADMINISTRATEUR, une seule fois :"]
        if (profil_reseau() or "").strip().lower() != "private":
            lignes += [f'    {COMMANDE_RESEAU_PRIVE.format(reseau=nom_reseau() or "")}']
        lignes += ["    " + COMMANDE_PARE_FEU.format(port=port)]
    return "\n".join(lignes)
