# SIREPH — Guide d'installation et d'accès (local, réseau, mobile)

Ce guide couvre trois façons d'utiliser SIREPH, du plus simple au plus large :

1. **Local** — uniquement sur cet ordinateur.
2. **Réseau local (Wi-Fi)** — depuis un autre ordinateur du même réseau.
3. **Mobile** — depuis un téléphone ou une tablette (même réseau, ou au-delà).

Aucune de ces trois options ne modifie l'application elle-même : c'est le même
serveur, seule la façon de le lancer et d'y accéder change.

---

## 1. Usage local (cet ordinateur uniquement)

C'est la configuration par défaut, déjà en place.

```bash
cd C:\Users\user\Claude\Projects\SIREPH
venv\Scripts\python.exe seed.py       # une seule fois (ou après suppression de instance\sireph.db)
venv\Scripts\python.exe app.py
```

Ouvrez ensuite `http://localhost:5000` dans le navigateur **de ce même
ordinateur**. Aucun autre appareil ne peut s'y connecter avec cette commande —
c'est le serveur de développement Flask, qui n'accepte que les connexions
locales par défaut pour la sécurité et le confort de développement (rechargement
automatique à chaque modification de code).

---

## 2. Accès réseau local — depuis un autre ordinateur du même Wi-Fi

Pour qu'un collègue sur le même réseau (ou vous, depuis un autre poste) puisse
ouvrir SIREPH dans son navigateur, deux changements sont nécessaires : lancer
le serveur en écoute réseau, et autoriser le port dans le pare-feu Windows.

### 2.1 Lancer le serveur en mode réseau

Utilisez `run_lan.py` plutôt que `app.py` : il utilise **Waitress**, un serveur
plus stable que le serveur de développement Flask pour plusieurs connexions
simultanées, et sans rechargement automatique qui pourrait couper les
connexions en cours.

```bash
cd C:\Users\user\Claude\Projects\SIREPH
venv\Scripts\python.exe run_lan.py
```

Le script affiche l'adresse à utiliser, par exemple :

```
SIREPH — accès réseau local
  Sur cet ordinateur       : http://localhost:5000
  Depuis un autre appareil : http://172.20.10.5:5000
```

**Votre adresse actuelle est `http://172.20.10.5:5000`** (elle peut changer si
vous changez de réseau Wi-Fi — relancez `run_lan.py` pour la revérifier).

### 2.2 Autoriser le port dans le pare-feu Windows (nécessaire une seule fois)

Windows bloque par défaut les connexions entrantes vers une application non
reconnue. Sans cette étape, les autres appareils ne pourront pas se connecter
même si le serveur tourne. Cette action nécessite les droits administrateur —
je n'ai pas pu l'exécuter automatiquement, à vous de jouer :

**Option A — ligne de commande (PowerShell en tant qu'administrateur)**

Clic droit sur le menu Démarrer → *Terminal (Admin)* ou *Windows PowerShell
(Admin)*, puis :

```powershell
New-NetFirewallRule -DisplayName "SIREPH (port 5000)" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

Le paramètre `-Profile Private` limite volontairement la règle aux réseaux
déclarés « privés » dans Windows (votre domicile, votre hotspot) — pas aux
réseaux publics (café, aéroport), par prudence.

**Option B — interface graphique**

1. *Pare-feu Windows Defender avec fonctions avancées de sécurité* (recherche
   dans le menu Démarrer).
2. *Règles de trafic entrant* → *Nouvelle règle...*
3. Type : **Port** → Suivant.
4. **TCP**, port spécifique local : `5000` → Suivant.
5. **Autoriser la connexion** → Suivant.
6. Cochez uniquement **Privé** → Suivant.
7. Nom : `SIREPH (port 5000)` → Terminer.

### 2.3 Se connecter depuis l'autre appareil

Sur l'autre ordinateur, **connecté au même réseau Wi-Fi**, ouvrez un
navigateur et allez sur l'adresse affichée par `run_lan.py`
(ex. `http://172.20.10.5:5000`).

---

## 3. Accès mobile (téléphone, tablette)

SIREPH est déjà une application web responsive (Bootstrap 5) : elle s'affiche
correctement sur un écran de téléphone sans configuration supplémentaire.
L'accès mobile utilise **exactement le même mécanisme que la section 2**
(réseau local) :

1. Le téléphone doit être connecté au **même réseau Wi-Fi** que l'ordinateur
   qui fait tourner SIREPH (ou vous pouvez faire l'inverse : partager la
   connexion du téléphone en point d'accès et connecter l'ordinateur dessus —
   c'est d'ailleurs déjà le cas ici, l'adresse `172.20.10.x` est une plage
   caractéristique du partage de connexion iPhone).
2. Lancez `run_lan.py` sur l'ordinateur (section 2.1) et autorisez le port
   dans le pare-feu (section 2.2, une seule fois).
3. Sur le téléphone, ouvrez le navigateur et saisissez l'adresse affichée
   (ex. `http://172.20.10.5:5000`).

### Raccourci sur l'écran d'accueil (optionnel)

Pour un accès plus rapide, ressemblant à une application :
- **iPhone (Safari)** : ouvrir l'URL → bouton Partager → *Sur l'écran d'accueil*.
- **Android (Chrome)** : ouvrir l'URL → menu ⋮ → *Ajouter à l'écran d'accueil*.

Cela crée un raccourci, pas une vraie application installée — SIREPH reste un
site web ouvert dans le navigateur (pas de PWA avec fonctionnement hors ligne
généralisé, voir limitation ci-dessous).

### Point d'attention — module Inspection (RI) hors connexion

Le module Inspection est conçu pour fonctionner sur le terrain sans réseau
(saisie de la grille de contrôle conservée sur l'appareil, synchronisée au
retour de connexion — voir `README.md`). **Condition nécessaire : l'inspecteur
doit avoir chargé au moins une fois la page de la grille pendant qu'il était
connecté**, avant de partir en zone blanche. Il n'y a pas de mise en cache de
l'application elle-même (pas de PWA/service worker dans ce périmètre) : sans
ce premier chargement en ligne, la page n'est simplement pas accessible hors
connexion.

---

## 4. Aller plus loin : accès depuis l'extérieur du réseau local (optionnel)

Les sections précédentes couvrent l'accès depuis le même réseau Wi-Fi. Pour
qu'un appareil complètement extérieur (hors du domicile/bureau, via Internet)
accède à SIREPH, il faut un tunnel ou une exposition Internet — **non
configuré ici**, et à examiner avec prudence :

- **Ngrok** (https://ngrok.com) ou **Cloudflare Tunnel** créent une URL
  Internet temporaire pointant vers `localhost:5000`, sans configuration du
  routeur. Pratique pour une démonstration ponctuelle.
- ⚠️ **SIREPH reste un prototype de démonstration** (voir « Limitations
  assumées » dans `README.md`) : base SQLite locale, mots de passe de démo
  identiques pour tous les comptes (`demo1234`), pas de HTTPS, pas de
  signature électronique qualifiée. **Ne pas exposer sur Internet avec des
  données réelles** sans d'abord traiter ces points (voir aussi
  `Digitalisation AMM/ehomologation-dplm/ARCHITECTURE.md` pour la trajectoire
  de mise en production recommandée : hébergement national, PostgreSQL,
  authentification forte, etc.).

---

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| L'autre appareil ne charge pas la page (délai puis échec) | Port bloqué par le pare-feu | Refaire la section 2.2 |
| L'autre appareil ne charge pas la page (échec immédiat) | Pas sur le même réseau Wi-Fi | Vérifier le nom du réseau sur les deux appareils |
| L'adresse IP a changé depuis hier | Wi-Fi/hotspot réattribue une adresse | Relancer `run_lan.py`, relire l'adresse affichée |
| `ModuleNotFoundError: waitress` | Dépendance pas encore installée | `venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Page blanche ou erreur 500 | Base de données absente ou modèle désynchronisé | `venv\Scripts\python.exe seed.py` (recrée `instance\sireph.db` si absente) |
