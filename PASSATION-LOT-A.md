# Passation — Lot A : Gouvernance des accès (RBAC piloté par la donnée)

> Note de passation à destination des prochains développeurs.
> Travaux de la session du **18 août 2026**. Toutes les décisions ont été
> validées par la cheffe de projet avant implémentation.

---

## 1. En une phrase

On a ajouté à ePharmRegul (SIREPH) un **contrôle d'accès piloté par la donnée** :
un catalogue de fonctionnalités, des défauts par rôle, des surcharges par
utilisateur, un résolveur unique `utilisateur_peut()`, et un **espace super
administrateur** à quatre onglets — **sans casser l'existant** (les 23 suites de
tests sont vertes).

---

## 2. État d'avancement

| Étape | Objet | État |
|---|---|---|
| 0 | Réconciliation de la taxonomie (analyse) | ✅ Fait |
| 1 | Architecture RBAC (conception) | ✅ Fait |
| 2 | Modèles + migration + seed du catalogue + comptes de test | ✅ Fait |
| 3 | `utilisateur_peut()` + branchement `permission_requise` + tests | ✅ Fait |
| 4 | Espace super admin (4 onglets) | ✅ Fait |
| 5 | Câblage des contrôles sur les actions existantes des autres lots | ⏳ **À faire** |
| 6 | **Lot B1** — parapheur du sous-directeur + check-list héritée | ⏳ À faire |
| 7 | **Lot B2/B3** — commissions spécialisées et routage | ⏳ À faire |
| 8 | **Lot B4** — entrée « Demandes d'inspection » dans le menu | ⏳ À faire |

**Tests : 23 suites / 23 vertes.** `verifier_machine()` sans anomalie.

---

## 3. Décisions structurantes (à respecter)

Prises à l'Étape 0/1, validées, elles cadrent tout le reste :

1. **Ne pas renommer les rôles.** Les 33 rôles réels (`permissions.ROLES`) restent.
   Le vocabulaire du cahier des charges est traduit dans
   `matrice_acces.CORRESPONDANCE_ROLES`. (Le brief parlait de « 31 rôles » et d'un
   « axe niveau 1–4 » : le code réel a **33 rôles** et un **axe niveau 0–8**.)
2. **super_admin = `administrateur_dpml`** (rôle existant réutilisé). Garantie :
   **au moins un super admin actif** ; le dernier ne peut être ni suspendu ni
   rétrogradé (`gouvernance.est_dernier_super_admin`).
3. **Axe `niveau` (0–8) conservé, cantonné à la CONSULTATION.** Tout acte
   **engageant** passe par `utilisateur_peut(fonctionnalité)` ; la consultation
   reste ouverte par seuil de niveau. Frontière nette : niveau = droit de VOIR,
   `utilisateur_peut` = droit d'AGIR. Pas de recouvrement.
4. **Réutiliser `EvenementAudit`** comme journal d'accès (piste d'audit
   universelle) — pas de table dédiée.
5. **Comptes de test : `@dpml.demo` + `demo1234`**, seed conditionné hors-prod.
6. **`utilisateur_peut` a un repli legacy** : tant qu'une clé
   (`confirmer_paiement`, `gerer_referentiels`, `voir_tous_*`…) n'est pas portée
   au catalogue, elle se résout comme avant (`a_permission`). C'est ce qui permet
   de migrer route par route sans rien casser.

---

## 4. Ce qui a été livré (fichiers)

**Nouveaux**
- `catalogue_fonctionnalites.py` — 63 fonctionnalités (23 🔒), défauts par rôle
  **déduits** des actions réelles (`PERMISSIONS_TRANSVERSES` + `roles` des
  transitions). `defauts_role()`, `categorie_de()`, `verifier_catalogue()`.
- `migration_gouvernance.py` — idempotent : `ALTER personne` (+`date_inscription`,
  `date_decision`, `decide_par_id`) + `create_all()` des 4 tables.
- `seed_gouvernance.py` — idempotent, **hors-prod**, seede le catalogue et
  contrôle « ≥ 1 super admin actif ».
- `gouvernance.py` — services `accorder/retirer/annuler_surcharge`
  (anti-auto-élévation + journalisation), `fonctionnalites_effectives()`,
  `est_dernier_super_admin()`. `ErreurGouvernance`.
- `routes_gouvernance.py` — blueprint `gouvernance` (préfixe `/gouvernance`),
  4 onglets. Toutes les routes gardées par `permission_requise(<fonctionnalité>)`.
- `templates/gouvernance/` — 7 gabarits.
- `test_gouvernance_acces.py` (23 vérifs, résolveur/service) et
  `test_gouvernance_espace.py` (16 vérifs, routes/protection serveur).
- `COMPTES_DE_TEST.md` — généré depuis les données.

**Modifiés**
- `models.py` — `Personne` étendue (3 colonnes + relation `decide_par`),
  `statut_compte` gagne la valeur `rejete` ; 4 modèles `Categorie`,
  `Fonctionnalite`, `Role` (JSON en `db.Text`), `SurchargeFonctionnalite`.
- `permissions.py` — `utilisateur_peut(user, code)` (garde statut → surcharge →
  défaut rôle → repli legacy). `a_permission` inchangé.
- `auth.py` — `permission_requise` résout via `utilisateur_peut` (décorateur
  inchangé).
- `app.py` — import + `register_blueprint(gouvernance_bp)`.
- `templates/base.html` — entrée menu « Gouvernance des accès ».
- `instance/sireph.db` — schéma migré + catalogue seedé (base de démonstration).

---

## 5. Reprendre le développement

### 5.1 ⚠️ Piège d'environnement macOS (scrypt / LibreSSL)

Le Python système de macOS est lié à **LibreSSL**, qui n'expose pas
`hashlib.scrypt`. Or Werkzeug 3.0 hache les mots de passe en scrypt → **l'auth et
14 suites de tests échouent** avec `AttributeError: module 'hashlib' has no
attribute 'scrypt'`. **Sur Windows (la cible réelle, `DEMARRER.bat`), le problème
n'existe pas.**

Correctif retenu : un **shim dans le venv** (hors dépôt), adossé à `cryptography`.
Pour le (re)poser sur une machine macOS :

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install cryptography            # DEV UNIQUEMENT, hors requirements.txt
SITE=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_path('purelib'))")
cat > "$SITE/sitecustomize.py" <<'PY'
import hashlib
if not hasattr(hashlib, "scrypt"):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    def _scrypt(password, *, salt, n, r, p, maxmem=0, dklen=64):
        if isinstance(password, str): password = password.encode()
        if isinstance(salt, str): salt = salt.encode()
        return Scrypt(salt=salt, length=dklen, n=n, r=r, p=p).derive(password)
    hashlib.scrypt = _scrypt
PY
```

> `cryptography` ne doit **jamais** entrer dans `requirements.txt` : c'est un
> outil de poste de développement, pas une dépendance du projet (règle du cahier
> des charges : 8 paquets, pas un de plus).

### 5.2 Initialiser / réinitialiser la base

```bash
.venv/bin/python migration_gouvernance.py   # schéma (idempotent)
.venv/bin/python seed_comptes.py            # 1 compte actif par rôle
.venv/bin/python seed_gouvernance.py        # catalogue + défauts (hors-prod)
```

### 5.3 Lancer les tests

Pas de `pytest` : chaque suite est un script autonome (sort en code 1 au premier
échec). **La suite complète dépasse 2 minutes** (≈200 ms/hash × 33 comptes × 23
suites) — la lancer en tâche de fond, **jamais avec un timeout court** :

```bash
for f in test_*.py; do .venv/bin/python "$f" || echo "ECHEC $f"; done
```

> **Piège observé** : un run de tests interrompu (timeout) laisse des **dossiers
> orphelins** en base, ce qui fait ensuite échouer `test_tableau_bord`
> (`dossiers_recents` a `limite=10`). La base committée = **3 `DossierAMM`**. En
> cas de doute : `git checkout -- instance/sireph.db` puis re-migrer/re-seeder.

### 5.4 Lancer le serveur

```bash
.venv/bin/python app.py        # http://localhost:5000
```

Super admin de démonstration : **admin@dpml.demo / demo1234** → menu
« Administration » → « Gouvernance des accès ».

---

## 6. Ce qu'il reste à faire

### Étape 5 — Câblage sur l'existant (prochaine étape logique)
- Migrer les routes qui utilisent `roles_required(...)` ou des clés legacy
  (`confirmer_paiement`, `gerer_referentiels`, `voir_tous_*`…) vers les
  fonctionnalités du catalogue, **une par une**, en s'appuyant sur le repli de
  `utilisateur_peut` (aucune régression tant que la migration n'est pas faite).
- **Point le plus délicat** : faire résoudre le **champ `roles` des transitions**
  (`machine_etats.py`) via `utilisateur_peut`. Plan validé à l'Étape 1 :
  1. ajouter une clé `fonction` à chaque transition engageante (mapping déjà
     défini dans `catalogue_fonctionnalites.ACTION_FONCTION`) ;
  2. dans `appliquer_transition`, remplacer `if role not in t["roles"]` par
     `utilisateur_peut(acteur, t["fonction"])` (repli sur `roles` si pas de
     `fonction`) ;
  3. faire prendre l'**utilisateur** (et non le seul rôle) à
     `transitions_autorisees`, pour que le bouton n'apparaisse que si le serveur
     l'accepterait (surcharges comprises). Touche `files_attente.contenu` et les
     gabarits.
  - **Garantie de sûreté** : les défauts d'une fonctionnalité de workflow sont
    seedés depuis le `roles` actuel → même booléen → 23 suites vertes. **`roles`
    n'est PAS supprimé** (il reste la source de présentation des files).
  - Ajouter un `verifier_gouvernance()` (sur le modèle de `verifier_machine`).

### Étape 6 — Lot B1 : parapheur du sous-directeur
Circuit cible à trois échelons dans `machine_etats.py` :
`retour_homologation → (viser) → parapheur_sous_directeur → (valider_conformite)
→ parapheur_directeur → (valider) → valide`. Nécessite 2 statuts, 3 transitions,
2 files, et surtout une **check-list héritée** circulant entre échelons
(extension du moteur : proposer le mécanisme — colonne JSON sur le dossier ou
table `ChecklistParapheur` — **avant** de coder). Les fonctionnalités
`dossier.viser` et `dossier.valider_conformite` **existent déjà au catalogue**
(non encore attribuées). Réutiliser le rôle `sous_directeur_medicament`.

### Étapes 7-8 — Lots B2/B3/B4
Commissions spécialisées (9, extensibles) + routage par type de produit ; écran
de gestion des commissions ; entrée « Demandes d'inspection » au menu (vérifier
d'abord si c'est bien la même chose que « Mes inspections (terrain) »).

### Sous-item différé (à trancher avec la cheffe de projet)
**Écran « compte en attente » CONNECTÉ.** Le brief dit « connexion possible,
aucune action métier ». Aujourd'hui le login (`app.py:~328`) laisse le message
d'attente mais **n'ouvre pas de session** pour les comptes `en_attente_validation`
/ `rejete` / `suspendu`. Le faire réellement entrer modifie le flux d'auth (et
peut toucher `test_connexion`) — décision volontairement laissée en suspens.

### Points encore ouverts (non bloquants)
- Périmètre de `dossier.valider_final` pour **DROS / LANACOME / IGSPL** (l'AMM est
  un acte **DPML** exclusif ; ces directions n'ont pas de circuit dans le code).
- Nombre d'instances par commission spécialisée (défaut retenu : 1 par commission).

---

## 7. Principes à ne pas violer (rappel du cahier des charges)

- **Aucune dépendance nouvelle** dans `requirements.txt` (8 paquets).
- **Une seule couche d'auth** : tout passe par `auth.py` + `permissions.py`.
- **Contrôle côté serveur systématique** : le masquage d'un bouton n'est jamais
  l'unique protection.
- **Aucune auto-élévation** : refusée **et journalisée**.
- Libellés, commentaires et messages **en français**.
- Après chaque étape : `verifier_machine()` + suite complète **verte** avant de
  continuer.
