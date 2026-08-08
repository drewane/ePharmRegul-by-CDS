"""
Limitation des tentatives de connexion.

Sans elle, un mot de passe se devine par essais répétés : c'est la faille la
plus banale d'une application exposée, et elle rendait inacceptable tout mot
de passe mémorisable. Les deux vont ensemble — on ne peut pas donner aux
utilisateurs des phrases tapables sans fermer la porte au bélier.

MÉCANIQUE
---------
Compteur glissant par couple (adresse e-mail, IP). Au-delà de MAX_ESSAIS
échecs dans FENÊTRE, le couple est bloqué pendant BLOCAGE. Un succès efface le
compteur.

Le comptage porte sur l'e-mail ET sur l'IP séparément : bloquer seulement par
e-mail laisse balayer les comptes depuis une même machine ; bloquer seulement
par IP laisse marteler un compte depuis un réseau distribué.

LIMITE ASSUMÉE : le compteur vit en mémoire du processus. Il suffit pour un
serveur unique, ce qui est le périmètre ici ; une mise à l'échelle sur
plusieurs instances demanderait un stockage partagé (Redis, ou une table).
Un redémarrage remet les compteurs à zéro — un attaquant ne provoque pas ce
redémarrage, la limite est donc acceptable.
"""
import threading
import time

MAX_ESSAIS = 5
FENETRE = 15 * 60          # 15 minutes d'observation
BLOCAGE = 15 * 60          # 15 minutes de blocage une fois le seuil atteint

_verrou = threading.Lock()
_echecs = {}               # clé → [horodatages des échecs récents]
_bloques = {}              # clé → horodatage de fin de blocage


def _nettoyer(maintenant):
    """Purge les entrées périmées : le dictionnaire ne doit pas croître sans fin."""
    for cle in [c for c, fin in _bloques.items() if fin <= maintenant]:
        del _bloques[cle]
    for cle in list(_echecs):
        recents = [t for t in _echecs[cle] if maintenant - t < FENETRE]
        if recents:
            _echecs[cle] = recents
        else:
            del _echecs[cle]


def _cles(email, ip):
    return [f"email:{(email or '').strip().lower()}", f"ip:{ip or '?'}"]


def secondes_restantes(email, ip):
    """Durée de blocage restante, ou 0 si la tentative est permise."""
    maintenant = time.time()
    with _verrou:
        _nettoyer(maintenant)
        fins = [_bloques[c] for c in _cles(email, ip) if c in _bloques]
    return int(max(fins) - maintenant) if fins else 0


def enregistrer_echec(email, ip):
    """Comptabilise un échec ; retourne les secondes de blocage déclenchées."""
    maintenant = time.time()
    with _verrou:
        _nettoyer(maintenant)
        declenche = 0
        for cle in _cles(email, ip):
            _echecs.setdefault(cle, []).append(maintenant)
            if len(_echecs[cle]) >= MAX_ESSAIS:
                _bloques[cle] = maintenant + BLOCAGE
                _echecs.pop(cle, None)
                declenche = BLOCAGE
        return declenche


def enregistrer_succes(email, ip):
    """Une connexion réussie efface l'ardoise : on ne punit pas la maladresse."""
    with _verrou:
        for cle in _cles(email, ip):
            _echecs.pop(cle, None)
            _bloques.pop(cle, None)


def essais_restants(email, ip):
    """Nombre d'essais avant blocage — pour avertir avant de sanctionner."""
    maintenant = time.time()
    with _verrou:
        _nettoyer(maintenant)
        pires = max((len(_echecs.get(c, [])) for c in _cles(email, ip)),
                    default=0)
    return max(0, MAX_ESSAIS - pires)


def reinitialiser():
    """Remise à zéro complète — réservée aux tests."""
    with _verrou:
        _echecs.clear()
        _bloques.clear()


def duree_lisible(secondes):
    minutes = max(1, round(secondes / 60))
    return f"{minutes} minute" + ("s" if minutes > 1 else "")
