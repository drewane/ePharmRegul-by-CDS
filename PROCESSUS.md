# Parcours d'un dossier, du dépôt à la signature

Ce document décrit le chemin complet d'une demande dans SIREPH, et qui
intervient à chaque étape.

---

## 1. Le déposant constitue sa demande

**Navigation** : « Demande » → AMM / Dérogation / Visa technique.
Sous AMM : nouvelle demande, renouvellement, variation, retrait.

| Type | Ce que le déposant saisit |
|---|---|
| Nouvelle demande | Tout : produit, titulaire, fabricant… |
| Renouvellement, variation, retrait | Il choisit un n° d'AMM ; les informations produit sont **reprises automatiquement** |

### Dossier technique (CTD)

Les modules exigés dépendent de la **nature du produit** et du **type de demande** :

| | Nouvelle demande | Renouvellement | Variation | Retrait |
|---|---|---|---|---|
| Chimique | 1, 2, 3 | 1 | 1, 3 | 1 |
| **Biologique** | **1 à 5** | 1, 3 | 1, 3, 5 | 1 |
| Phytothérapie | 1, 2, 3 | 1 | 1, 3 | 1 |
| Dispositif médical | 1, 3 | 1 | 1, 3 | 1 |

> Ces combinaisons sont une **proposition de travail**, à valider par la DPML.
> Elles se modifient dans `modules_ctd.py`, sans reprise du logiciel.

Les cinq modules (47 champs au total) : administratif · résumés · qualité
pharmaceutique · non-clinique · clinique. Le déposant les remplit **dans
l'ordre**, avec une pièce jointe à la fin de chacun.

### Puis le paiement

Dossier complet → **Continuer** → règlement des frais (mobile money, carte,
virement) → **téléchargement du reçu** → dépôt du reçu comme preuve →
**transmission à la DPML**.

Un accusé de réception part aussitôt, dans l'application **et par courriel**.

---

## 2. La DPML instruit

### Recevabilité — chef de service

Liste de contrôle en sept points, dont **quatre bloquants** :

- identification du produit complète
- titulaire et fabricant identifiés
- modules obligatoires chargés
- **preuve de paiement reçue**

La recevabilité ne peut pas être prononcée tant qu'un point bloquant manque —
le contrôle est fait côté serveur, pas seulement dans l'interface. Une
irrecevabilité doit être motivée.

Dès l'acceptation, le déposant est informé que son dossier **est en cours
d'évaluation** (application + courriel).

### Évaluation interne — évaluateurs internes

Le chef de service confie le dossier à un ou plusieurs **évaluateurs
internes**, avec consigne et échéance. Chacun remet un rapport et une
conclusion. Leur travail prépare la commission ; il ne décide de rien.

### Commission — membres de commission

Le chef de service convoque une séance (**spécialisée** ou **nationale**) et y
inscrit les dossiers. Chaque membre saisit son avis **en séance, sur tablette**,
via une grille de six questions (Oui / Non / Sans objet) :

1. Qualité pharmaceutique démontrée ?
2. Profil de sécurité acceptable ?
3. Efficacité thérapeutique établie ?
4. Rapport bénéfice/risque favorable ?
5. Étiquetage et notice conformes ?
6. Intérêt de santé publique ?

Un avis défavorable ou un complément doit être motivé. Un membre peut corriger
son avis tant que la séance est ouverte.

À la clôture, les avis sont **synthétisés automatiquement**. Règle retenue :
l'avis global suit la majorité ; **à égalité, le complément de dossier
l'emporte** — on ne tranche pas au bénéfice du doute.

### Rapport — chef de service

Le chef de service consolide l'instruction :

- **avis favorable ou défavorable** → ouvre le circuit de signature ;
- **complément requis** → renvoie au déposant, sans mobiliser la direction.

---

## 3. Le circuit de signature

| Document | Circuit | Signataire final |
|---|---|---|
| **AMM** | chef de service → sous-directeur → directeur → SG MINSANTE → **ministre** | Ministre de la Santé |
| Essai clinique | chef → sous-directeur → directeur | Directeur DPML |
| Licence | chef Licences → sous-directeur Étab. → directeur | Directeur DPML |
| Contrôle qualité | chef Labo → sous-directeur → directeur | Directeur DPML |
| Inspection | chef Inspection → sous-directeur Étab. → directeur | Directeur DPML |
| Dérogation, visa technique | chef → sous-directeur → directeur | Directeur DPML |

Seuls l'AMM et l'essai clinique passent devant une commission. Les licences en
sont dispensées : leur instruction est purement administrative — le moteur
reste prêt à en accueillir une le jour venu.

> Lorsque la direction deviendra une **agence du médicament**, le directeur
> général (rôle déjà créé, échelon 5) pourra signer l'AMM en lieu et place du
> ministre : il suffira de modifier une ligne de `validation_numerique.py`.

### Garanties

- **L'ordre est structurel** : un échelon ne peut pas signer avant le
  précédent. Vérifié par test — le ministre ne peut pas court-circuiter la
  chaîne.
- Chaque signature est **nominative, horodatée**, avec empreinte SHA-256.
- Un **refus motivé** interrompt le circuit ; il est relançable après
  correction.
- Le **document PDF n'est produit qu'à la dernière signature**, jamais avant.

### Chaque échelon voit ce qui lui est utile

| Échelon | Vue |
|---|---|
| Chefs de service | **Technique** — détail, avis individuels, liste de contrôle |
| Sous-directeurs, directeur | **Synthèse** — conclusions consolidées, rapport |
| SG, ministre, directeur général | **Parcours** — six contrôles de régularité, avis de la direction, fil horodaté |

Le ministre ne reçoit ni le détail des assignations ni la liste de contrôle
technique : lui présenter un mur de données qu'il ne peut pas exploiter
diluerait sa responsabilité.

---

## 4. Le document officiel

À la signature finale, l'AMM numérique est produite : en-tête MINSANTE,
identification du produit, validité, **visas de toute la chaîne**, empreinte et
QR de vérification.

> Le modèle actuel est un **standard de travail**, à remplacer par la version
> officielle de la DPML.

---

## Comptes de démonstration

Mot de passe : `demo1234`

| Rôle | Compte |
|---|---|
| Industriel / titulaire | `demandeur@pharmacam.demo` |
| Chef de service Homologation | `chefservice@dpml.demo` |
| Évaluateur interne | `evaluateur1@dpml.demo`, `evaluateur2@dpml.demo` |
| Membre commission spécialisée | `commission1@dpml.demo` à `commission3@dpml.demo` |
| Membre commission nationale | `cnm1@dpml.demo` |
| Sous-directeur du Médicament | `sousdirecteur@dpml.demo` |
| Directeur DPML | `directeur@dpml.demo` |
| Secrétaire général MINSANTE | `sg@minsante.demo` |
| **Ministre de la Santé** | `ministre@minsante.demo` |
| Directeur général de l'Agence | `dg@agence.demo` |
| Chefs Licences / Inspection / Labo | `cs.licences@`, `cs.inspection@`, `cs.labo@dpml.demo` |
| Administrateur | `admin@dpml.demo` |

## Courriels

Seize types de notification partent par messagerie. **Sans configuration SMTP,
les messages sont journalisés au lieu d'être envoyés** — consultables dans
Administration → Courriels sortants, et l'interface le signale clairement.

```bash
SIREPH_SMTP_HOTE=smtp.exemple.cm
SIREPH_SMTP_UTILISATEUR=notifications@dpml.cm
SIREPH_SMTP_MOTDEPASSE=...
SIREPH_SMTP_EXPEDITEUR="SIREPH — DPML <notifications@dpml.cm>"
SIREPH_URL_PUBLIQUE=https://sireph.dpml.cm
```

## Tests

```bash
venv\Scripts\python test_instruction.py
venv\Scripts\python test_ctd.py
venv\Scripts\python test_lot_d.py
venv\Scripts\python test_industriel_validation.py
venv\Scripts\python test_plateforme_paiement.py
venv\Scripts\python test_chaine_paiement.py
venv\Scripts\python test_reliance.py
```

**301 vérifications** au total.
