# SIREPH — Système Intégré de Régulation Pharmaceutique (DPML, Cameroun)

Système Intégré de Régulation Pharmaceutique — République du Cameroun (DPML).
Les 9 fonctions du Global Benchmarking Tool de l'OMS (RS, MA, VL, RI, LI, LT,
MC, CT, LR) sont livrées et fonctionnelles.

Cette livraison couvre le **socle de données pivot commun** (Produit, DossierAMM,
Établissement, Personne, Lot, ÉvènementAudit, Notification, ParametreModule) et
les huit fonctions réglementaires **intégralement implémentées**, dans l'ordre
de priorité du cahier des charges :

- **MA (Enregistrement/AMM)** — module prioritaire.
- **VL (Pharmacovigilance)**.
- **RI (Inspection réglementaire)** — y compris la contrainte de fonctionnement
  hors connexion sur le terrain (voir section dédiée ci-dessous).
- **LI (Licences établissements)** — y compris le contrôle croisé avec MA
  (licence suspendue/révoquée bloque toute nouvelle création de dossier AMM) et
  la reprise en propre de la suspension de licence, jusque-là un pis-aller dans
  RI (voir « Historique de la suspension » ci-dessous).
- **LT (Analyses de laboratoire / LIMS)** — y compris la double validation
  obligatoire et la consultation croisée du certificat depuis le module d'origine.
- **MC (Surveillance et contrôle du marché)** — y compris la validation
  obligatoire du directeur pour un rappel de niveau I, la dérivation
  automatique de la liste des établissements à notifier, et l'intégration
  réelle avec LT (une non-conformité de laboratoire crée désormais un
  signalement MC, plus un simple stand-in).
- **CT (Supervision des essais cliniques)** — y compris le blocage strict de
  l'autorisation sans avis favorable du comité d'éthique renseigné, et le
  suivi des amendements/rapports d'étape sans altérer l'historique antérieur.
- **LR (Libération des lots)** — y compris le double contrôle croisé (AMM
  active + résultat de laboratoire conforme et validé, l'un sans l'autre ne
  suffisant jamais) et l'intégration automatique avec MC en cas de rejet
  après distribution partielle.

## Installation et lancement

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt

python seed.py                  # crée la base SQLite + comptes et données de démonstration
python seed_comptes.py          # complète : un compte par rôle du référentiel
python seed_scenario_financier.py   # scénario de séparation des tâches (facultatif)
python app.py                   # lance le serveur sur http://localhost:5000
```

Cette commande n'est accessible que depuis cet ordinateur. Pour un accès
depuis un autre appareil du réseau (ordinateur, téléphone, tablette) — y
compris le mode hors connexion du module RI, qui suppose un vrai téléphone —
voir **[SETUP.md](SETUP.md)**.

## Comptes de démonstration
Mot de passe pour tous : `demo1234`

**L'annuaire complet — un compte pour chacun des 31 rôles, groupés par niveau
de responsabilité — est consultable dans l'application à
`/comptes-demonstration`**, avec pour chaque profil ce qu'il permet d'éprouver.
Il est produit par `seed_comptes.py`, qui garantit qu'aucun rôle ne reste sans
compte : un échelon sans titulaire rend la chaîne de signature intestable.

La page n'existe qu'en mode démonstration. Positionner `SIREPH_PRODUCTION=1`
la fait disparaître, ainsi que le lien sur l'écran de connexion — publier des
identifiants n'a de sens que sur un poste d'essai. Avant tout déploiement
réel, `seed_comptes.verifier_avant_production()` liste les comptes à purger.

Les principaux, pour mémoire :

| Rôle | E-mail |
|---|---|
| Administrateur DPML (recevabilité MA + admin référentiels/utilisateurs) | admin@dpml.demo |
| Évaluateur AMM | evaluateur@dpml.demo |
| Directeur DPML (décisions MA + arbitrage des signaux VL) | directeur@dpml.demo |
| Agent de pharmacovigilance | vigilance@dpml.demo |
| Inspecteur IGSPL | inspecteur@igspl.demo |
| Agent Licences | licences@dpml.demo |
| Agent Laboratoire | labo@lanacome.demo |
| Responsable Qualité Laboratoire | rq@lanacome.demo |
| Agent Surveillance du Marché | surveillance@dpml.demo |
| Agent DROS | dros@dpml.demo |
| Demandeur (PharmaCam Import SARL) | demandeur@pharmacam.demo |
| Demandeur (BioSanté Distribution) — pour vérifier l'isolement des portées | demandeur2@biosante.demo |
| Demandeur (Pharmacie Bafoussam Centre) — demande de licence tout juste déposée | demandeur3@bafoussam.demo |
| Demandeur (Nouveau Grossiste Attente SARL) — auto-inscription **en attente de validation**, ne peut pas se reconnecter tant qu'un `administrateur_dpml` ne l'a pas validée dans `/admin/utilisateurs` | attente@nouveaugrossiste.demo |

Les échelons de la chaîne de signature et les profils externes ajoutés par
`seed_comptes.py` :

| Niveau | Rôle | E-mail |
|---|---|---|
| 0 | Usager | usager@sireph.demo |
| 0 | Laboratoire privé | labo.prive@sireph.demo |
| 0 | Pharmacien d'officine | pharmacien@officine.demo |
| 0 | Promoteur d'essai clinique | promoteur@essai.demo |
| 1 | Évaluateur interne | evaluateur1@dpml.demo |
| 1 | Membre de commission spécialisée | commission1@dpml.demo |
| 2 | Chef de bureau — recevabilité | chefbureau@dpml.demo |
| 3 | Chef de service Homologation | chefservice@dpml.demo |
| 3 | Responsable financier — approbation des recettes | finances@dpml.demo |
| 4 | Sous-directeur du Médicament | sousdirecteur@dpml.demo |
| 5 | Directeur DPML | directeur@dpml.demo |
| 6 | Inspecteur général | ig@minsante.demo |
| 7 | Secrétaire général du Ministère | sg@minsante.demo |
| 8 | Ministre de la Santé publique | ministre@minsante.demo |

Pour éprouver le circuit AMM de bout en bout, signer successivement avec les
niveaux 3 → 4 → 5 → 6 → 7 → 8 depuis `/validation/parapheur`.

### Séparation des tâches : finances et instruction

L'approbation d'une recette relève du **responsable financier**, et de lui
seul — ni l'administrateur système, ni le directeur qui décidera du dossier.
Le contrôle est dans le moteur (`paiements.controler_separation`), pas
seulement dans les décorateurs de vue : trois interdits, approuver sans le
rôle, approuver sa propre créance ou celle de son établissement, approuver la
recette d'un dossier dont on est évaluateur assigné.

Son approbation produit trois effets d'un seul tenant :

1. le délai légal démarre (Clock Start) ;
2. le point « preuve de paiement » de la recevabilité est **attesté** — le chef
   de service ne peut ni le cocher, ni le décocher ;
3. le service instructeur est averti qu'il peut aller de l'avant.

Pour l'éprouver, `python seed_scenario_financier.py` prépare un dossier
bloqué sur ce seul point, puis :

| Étape | Compte | Écran | Ce qu'on observe |
|---|---|---|---|
| 1 | `chefservice@dpml.demo` | `/instruction/dossiers/<id>` | la case « preuve de paiement » est grisée, la recevabilité est refusée |
| 2 | `finances@dpml.demo` | `/paiements/approbation` | approbation de la créance |
| 3 | `chefservice@dpml.demo` | même écran | la case est attestée, la recevabilité passe, le délai court |

`seed.py` crée des données couvrant les statuts significatifs de chacun des
8 circuits (MA, VL, RI, LI, LT, MC, CT, LR), pour rejouer immédiatement les
critères d'acceptation ci-dessous — y compris les chaînes inter-modules
(un échantillon LT non conforme crée un signalement MC ; un lot LR rejeté
après distribution partielle crée un signalement MC ; un signal VL suivi
d'une mesure de retrait crée un dossier de retrait MA ; une non-conformité
RI grave permet une suspension LI). Le formulaire de notification VL
(`/vigilance/notifier`), le registre des établissements agréés
(`/etablissements`), le formulaire de signalement MC (`/signalements/public`)
et le registre public des rappels (`/rappels-public`) sont accessibles sans
compte, comme dans la vraie vie — des liens s'y trouvent depuis l'écran de
connexion.

## Accès libre et accès avec connexion

SIREPH distingue explicitement deux niveaux d'accès :

- **Accès libre (sans compte)** : registre public des AMM actives
  (`/registre-public`), établissements agréés (`/etablissements`), rappels de
  lots (`/rappels-public`), signalement d'un effet indésirable
  (`/vigilance/notifier`), signalement d'un défaut qualité
  (`/signalements/public`) — et **le dépôt d'une demande d'AMM**
  (`/dossiers/nouveau`), voir ci-dessous.
- **Accès avec connexion** : tout le reste (instruction, décisions, back-office
  de chaque module), réservé aux comptes internes DPML et aux comptes
  laboratoire (`demandeur_externe`).

### Dépôt d'une demande d'AMM sans compte préalable, avec auto-inscription en cours de parcours

Un laboratoire peut ouvrir `/dossiers/nouveau` sans être connecté et décrire
son produit (nom, DCI, forme, fabricant...). À la soumission de cette
première étape :
- Les informations produit sont conservées en session (`session["brouillon_amm"]`),
  **rien n'est encore écrit en base**.
- L'utilisateur est redirigé vers `/inscription-labo`, qui affiche un rappel du
  produit en cours de dépôt et demande les informations de compte (nom du
  laboratoire, nom du contact, e-mail, mot de passe).
- À la création du compte (rôle `demandeur_externe`, établissement rattaché
  créé ou réutilisé par raison sociale), l'utilisateur est connecté
  automatiquement et **son dossier AMM est créé dans la foulée**, dans le
  même commit applicatif que si le brouillon avait échoué à se créer, le
  compte reste tout de même acquis (l'échec ne doit jamais faire perdre un
  compte déjà créé).
- Un compte déjà connecté (`demandeur_externe` existant ou
  `administrateur_dpml`) ne voit jamais cette étape : le dossier est créé
  directement, comme avant.

Contrairement aux autres comptes de démonstration (tous en `demo1234`), un
compte auto-inscrit choisit son propre mot de passe (8 caractères minimum) —
c'est le seul point d'entrée où un compte est créé sans passer par
`administrateur_dpml` (`/admin/utilisateurs/nouveau`).

### Dépôt d'une demande de licence (grossiste-répartiteur) sans compte préalable

Même parcours que ci-dessus, pour les sociétés grossistes-répartiteurs :
`/licences/nouvelle` (lien « Vous êtes une société grossiste-répartiteur ? »
sur l'écran de connexion) demande le nom de la société, la catégorie
d'activité (médicaments / dispositifs médicaux / les deux) et une adresse,
puis redirige vers `/inscription-labo` — le même formulaire de création de
compte que pour l'AMM, généralisé pour reconnaître les deux types de
brouillon (`session["brouillon_amm"]` ou `session["brouillon_licence"]`, un
seul présent à la fois). Un demandeur déjà connecté et déjà rattaché à un
établissement réutilise cet établissement plutôt que d'en créer un doublon.

### Validation des inscriptions par la DPML

Un compte créé par auto-inscription (AMM ou licence) est créé avec
`statut_compte = "en_attente_validation"` — la session de la démarche en
cours reste active pour laisser le demandeur finaliser son dépôt, mais toute
**reconnexion future** est bloquée (message explicite à `/login`) tant qu'un
`administrateur_dpml` n'a pas validé le compte depuis `/admin/utilisateurs`
(bandeau d'alerte + bouton **Valider**, ou filtre par statut). La validation
génère un évènement d'audit et une notification in-app au demandeur. Un
compte peut aussi être suspendu depuis le même écran (jamais supprimé
physiquement, cf. limitation RS §6).

### Documents et paiement des frais

- **Téléversement de documents** : depuis la fiche d'un dossier d'AMM ou
  d'une demande de licence, le demandeur (propriétaire) ou
  `administrateur_dpml` peut téléverser des pièces (CPP, certificat GMP,
  statuts, CV du pharmacien responsable...). Stockage sur disque sous
  `static/documents/<TypeEntité>/<id>/`, entrée `PieceJointe` en base,
  téléchargement contrôlé par rôle/propriété via `/documents/<id>/telecharger`
  (`routes_pieces.py`). Chaque dépôt génère une entrée d'audit sur le dossier
  parent.
- **Paiement des frais** : à la soumission d'un dossier d'AMM ou au dépôt
  d'une demande de licence, un `Paiement` est créé automatiquement (montant
  configurable via `/admin/referentiels`, paramètres `MA.frais_dossier_xaf` et
  `LI.frais_dossier_xaf`). Le demandeur dépose une preuve de paiement (reçu de
  virement, dépôt mobile money...) depuis la fiche du dossier ; un
  `administrateur_dpml` la confirme ou la rejette (motif obligatoire) ; le
  demandeur reçoit une notification in-app dans les deux cas, et peut
  redéposer une nouvelle preuve après un rejet.
  **Limitation assumée et volontaire** : SIREPH ne traite, ne stocke ni ne
  transmet aucune donnée de carte bancaire ou de mobile money — il n'y a pas
  de passerelle de paiement en ligne réelle dans ce prototype (aucun compte ni
  identifiant de prestataire agréé n'a été fourni). L'intégration d'un
  agrégateur réel (Orange Money, MTN MoMo, carte bancaire) est une phase
  ultérieure distincte, documentée ici pour éviter toute ambiguïté.

### Explorateur de base de données (« où vont les données ? »)

`/admin/base-donnees` (réservé à `administrateur_dpml`) répond directement à
la question « où sont stockées les données » : affiche le chemin absolu du
fichier SQLite unique utilisé par l'application, puis, pour chaque table
(réfléchie dynamiquement depuis les modèles SQLAlchemy — aucune liste figée à
maintenir), le nombre de colonnes et de lignes, avec un lien vers un aperçu
en lecture seule des 50 lignes les plus récentes. Le champ `password_hash`
est masqué même sur cette vue d'administration : il n'apporte aucune
information utile et ne doit pas être exposé au-delà du strict nécessaire.

## Améliorations du parcours AMM (alignées sur le formulaire officiel DPML)

Cette section documente une série d'ajustements du circuit MA, à partir d'un
formulaire officiel DPML partagé (« Champs de formulaire — Template DPLM
Application Form ») et de demandes explicites de suivi/paiement/exceptions.

- **Frais différenciés par type de procédure** — `MA.frais_nouvelle_demande_xaf`
  (500 000 XAF), `MA.frais_renouvellement_xaf` (300 000 XAF),
  `MA.frais_variation_xaf` (150 000 XAF), configurables depuis
  `/admin/referentiels`. Un retrait ne donne lieu à aucun frais
  (`workflow_ma.montant_frais`).
- **Fenêtre de paiement à la soumission** — en cliquant sur « Soumettre le
  dossier », une fenêtre modale affiche le montant exact dû avant confirmation
  de l'envoi ; le circuit preuve de paiement + validation DPML existant
  (`paiements.py`) prend ensuite le relais depuis la fiche du dossier.
- **Suivi d'étapes avec voyants** — 4 étapes fixes (Soumission, Recevabilité,
  Évaluation technique, Décision) affichées sur la fiche du dossier, chacune
  avec un voyant vert (franchie), jaune (en cours) ou rouge (blocage —
  irrecevable, complément requis, clôture automatique, rejet), gris (à venir).
  Calculé par `workflow_ma.etapes_suivi()`.
- **Accusé de Réception généré par le système/DPML** — dès qu'un dossier est
  déclaré recevable, un PDF « Accusé de Réception » est généré automatiquement
  (numéro, produit, date de dépôt) et attaché comme document du dossier, avec
  notification au demandeur — distinct de la preuve de paiement fournie par le
  demandeur (`pdf_gen.generer_accuse_reception`, appelé depuis
  `workflow_ma.marquer_recevabilite`).
- **Décision favorable : délai de retrait du document physique** — le
  paramètre configurable `MA.delai_retrait_document_jours` (10 jours par
  défaut) est ajouté à la notification et affiché sur la fiche du dossier,
  précisant jusqu'à quelle date le certificat AMM peut être retiré à la DPML.
  La décision de rejet mentionne déjà systématiquement son motif.
- **Champs produit étendus (Section 2 du formulaire officiel)** —
  `Produit.composition_integrale`, `classe_therapeutique`,
  `indications_therapeutiques`, `voie_administration`, `duree_stabilite`,
  `prix_grossiste_ht` (PGHT, XAF), et `DossierAMM.representant_local_nom` /
  `representant_local_contact` (pharmacien interlocuteur local et son
  contact, essentiel pour l'envoi des accusés de réception). Tous facultatifs
  à la création, modifiables tant que le dossier reste en brouillon.
- **Dérogations spéciales** (`/derogations`) — un demandeur peut solliciter
  une exception motivée à une exigence réglementaire standard (délai, pièce
  justificative), éventuellement rattachée à un dossier d'AMM. Circuit à deux
  étapes : `administrateur_dpml` met en instruction, `directeur_dpml`
  approuve ou refuse (motif obligatoire en cas de refus).
- **Visas techniques** (`/visas`) — autorisation d'une opération
  d'importation précise d'un produit déjà titulaire d'une AMM active
  (distincte de l'AMM elle-même). Décision à une étape par
  `administrateur_dpml` (délivré/refusé). Un demandeur ne peut solliciter un
  visa que pour un produit dont il est identifié comme demandeur d'un dossier
  et dont l'AMM est active (`workflow_visas._demandeur_est_titulaire`).

## Vérification des critères d'acceptation

### Module MA (11-MA §9)

1. **DCI manquante bloque la soumission** — connectez-vous en `demandeur@pharmacam.demo`,
   ouvrez le dossier « Produit test (sans DCI) », cliquez sur Soumettre : message
   d'erreur explicite, le dossier reste en brouillon.
2. **`evaluateur_amm` ne peut jamais approuver** — sur un dossier en évaluation, le
   compte `evaluateur@dpml.demo` ne voit pas de bouton Approuver/Rejeter ; un
   appel direct de la route `POST /dossiers/<id>/decision` avec ce compte est
   refusé côté serveur (`ErreurWorkflow`), quel que soit le point d'entrée.
3. **Clôture automatique par délai dépassé** — le dossier « Fervex Adulte » a une
   date limite de réponse déjà passée dans les données de démonstration ;
   connectez-vous avec n'importe quel compte et ouvrez `/` (tableau de bord) :
   le dossier passe à « Clôturé (délai dépassé) », une notification est créée
   pour le demandeur, l'évènement d'audit correspondant a `acteur = Système`.
4. **AMM approuvée visible au registre public** — ouvrez `/registre-public` sans
   vous connecter : « Amodex 250 » y apparaît avec DCI, forme, titulaire et
   dates, sans aucune donnée commercialement sensible.
5. **Piste d'audit complète** — ouvrez la fiche d'un dossier ayant traversé
   plusieurs statuts : chaque transition est listée avec l'acteur exact (ou
   « Système ») et un horodatage complet ; le motif est affiché pour les
   dossiers irrecevables, en complément requis ou rejetés.

Vérifications complémentaires : créer un second dossier « nouvelle demande » sur
un produit ayant déjà un dossier actif du même type de procédure est bloqué avec
un message explicite ; `demandeur2@biosante.demo` ne voit pas les dossiers de
`demandeur@pharmacam.demo` dans `/dossiers` ; modifier un paramètre dans
`/admin/referentiels` crée une entrée d'audit avec l'ancienne et la nouvelle valeur.

### Module VL (12-VL §10)

1. **Notification sans compte** — ouvrez `/vigilance/notifier` déconnecté,
   soumettez un cas : un numéro de suivi (format `PV-{année}-{séquence}`) est
   affiché immédiatement, sans avoir créé de compte.
2. **Aucune donnée patient identifiante** — le formulaire ne demande que l'âge
   et le sexe du patient ; le champ « notificateur » (nom/contact) est
   explicitement distinct et facultatif. `models.NotificationVigilance` ne
   comporte aucun champ nom/identifiant de patient.
3. **Cas grave non traité au-delà du délai → alerte** — le cas créé par `seed.py`
   avec `date_notification` antérieure de 20 jours (délai par défaut : 15 jours)
   apparaît surligné dans `/vigilance/cas` dès la connexion d'un `agent_vigilance`,
   et une notification a été créée pour les rôles `agent_vigilance` et
   `administrateur_dpml`.
4. **Transmission VigiBase consultable ou explicitement en attente** — un cas
   `cloturee` non encore transmis affiche « Transmission en attente » sur sa
   fiche (jamais un état masqué) ; après action « Transmettre à VigiFlow », une
   référence E2B simulée est affichée avec sa date.

Vérification complémentaire de l'intégration inter-modules : sur le cas
« signal détecté » créé par `seed.py`, connectez-vous en `directeur@dpml.demo`,
choisissez la mesure « Retrait du produit » — un `DossierAMM` de type `retrait`
est créé automatiquement pour le produit concerné, consultable depuis `/dossiers`.

### Module RI (13-RI §9)

1. **Saisie hors connexion conservée sans perte** — connectez-vous en
   `inspecteur@igspl.demo`, ouvrez `/inspections/mobile`, démarrez une inspection
   planifiée puis ouvrez sa grille. Dans les DevTools du navigateur, coupez le
   réseau (onglet Réseau → Offline, ou mode avion) : cochez plusieurs items —
   chaque clic est conservé immédiatement dans le `localStorage` du navigateur
   (clé `sireph_grille_<id>`), sans dépendre d'un appel réseau. Rechargez la page
   hors connexion (si le navigateur a mis la page en cache) ou réactivez le
   réseau : les réponses saisies sont toujours là, et un évènement `online`
   déclenche automatiquement leur synchronisation vers le serveur (bandeau
   « À jour » une fois la synchro réussie).
2. **Pas de clôture silencieuse** — sur une grille partiellement remplie, cliquez
   sur « Clôturer la visite » : un bandeau explicite indique le nombre d'items
   non répondus et exige une confirmation active (case à cocher) avant de
   pouvoir clôturer quand même.
3. **Non-conformité grave → module MC + proposition au directeur, jamais une
   suspension directe par l'inspecteur** — sur l'inspection « non conforme grave »
   créée par `seed.py` (établissement Laboratoires CamPharma SA), le compte
   `inspecteur@igspl.demo` n'a accès à aucune action de suspension ; connectez-vous
   en `directeur@dpml.demo` sur cette même fiche pour voir le panneau « Proposition
   de suspension » et l'exécuter — la seule route capable de changer
   `Etablissement.statut_licence` est réservée au rôle `directeur_dpml`
   (`workflow_li.suspendre`, vérifié côté serveur ; la fiche RI transmet la
   référence de l'inspection à l'origine de la recommandation).

Vérification complémentaire : le plan d'action de l'inspection « BioSanté
Distribution » a une échéance déjà dépassée dans les données de démonstration —
il apparaît surligné dans `/inspections/plans-action` et sur le tableau de bord
dès la connexion de n'importe quel compte interne.

### Module LI (14-LI §9)

1. **Expiration automatique sans intervention** — l'établissement « Grossiste
   Sahel Nord » a une licence active dont l'échéance est déjà passée dans les
   données de démonstration, sans renouvellement engagé ; ouvrez `/` (tableau de
   bord) avec n'importe quel compte : sa licence passe automatiquement à
   « Expirée » (`workflow_li.expirer_si_echue`, action système).
2. **Établissement suspendu/révoqué bloqué comme fabricant ou titulaire** —
   l'établissement « Suspendu Test SARL » est suspendu dans les données de
   démonstration ; connectez-vous en `demandeur@pharmacam.demo`, ouvrez
   « Nouvelle demande » et saisissez « Suspendu Test SARL » comme fabricant :
   la création du dossier est bloquée avec un message explicite
   (`workflow_ma._verifier_etablissements_non_suspendus`), quel que soit le
   point d'entrée (nouvelle demande, renouvellement, variation, retrait).
3. **Référence croisée de suspension consultable** — sur la fiche de
   l'établissement « Laboratoires CamPharma SA » après l'avoir suspendu depuis
   l'inspection non conforme grave (voir critère RI #3 ci-dessus), l'historique
   des demandes de licence et la piste d'audit conservent la référence à
   l'inspection à l'origine de la suspension.

Vérifications complémentaires : la demande « Dépôt Sanaga (test refus) » est
refusée avec motif, consultable depuis sa fiche ; la demande de la « Pharmacie
Bafoussam Centre » (compte `demandeur3@bafoussam.demo`) est visible uniquement
par ce compte et les rôles internes, pas par `demandeur@pharmacam.demo`.

### Module LT (15-LT §9)

1. **Double validation obligatoire** — l'échantillon créé par `seed.py` avec
   `analyste_id` délibérément égal au compte `rq@lanacome.demo` (scénario
   construit pour ce test) refuse la validation dès qu'on se connecte avec ce
   même compte : message explicite côté écran, et un appel direct de
   `POST /echantillons/<id>/valider` est également refusé côté serveur
   (`workflow_lt.valider_resultats`), qu'il s'agisse d'un conflit de rôle ou
   d'une simple coïncidence d'identité.
2. **Certificat consultable depuis le module d'origine, sans ressaisie** —
   l'échantillon rattaché au dossier AMM d'Amodex 250 (origine `dossier_amm`)
   apparaît directement dans un encart « Analyses de laboratoire » sur la
   fiche de ce dossier (`/dossiers/<id>`), avec sa conclusion de conformité.
3. **Non-conformité → module MC automatique** — l'échantillon non conforme
   créé par `seed.py` (origine `demande_directe`) a généré, dès l'émission de
   son certificat, un `SignalementQualite` réel dans le registre MC (origine
   « Module LT ») — vérifiable dans `/signalements`.

### Module MC (16-MC §9)

1. **Rappel de niveau I impossible pour `agent_surveillance_marche` seul** —
   le signalement niveau I créé par `seed.py` (statut `evalue`) affiche un
   bouton désactivé pour ce rôle, avec le message « Validation du directeur
   requise pour un rappel de niveau I » ; un appel direct de
   `POST /signalements/<id>/rappel` avec ce compte est refusé côté serveur
   (`workflow_mc.engager_rappel`).
2. **Liste des établissements notifiés dérivée automatiquement** — au moment
   d'engager un rappel, la liste (`SignalementQualite.etablissements_notifies`)
   est calculée depuis les lots concernés (fabricant) et le titulaire d'AMM du
   produit — aucun champ de saisie manuelle n'existe sur cet écran.
3. **Rappel visible au registre public dès `notifie`** — ouvrez
   `/rappels-public` sans authentification : tout signalement ayant atteint ce
   statut y apparaît avec produit, lots, niveau de risque et date.

### Module CT (17-CT §9)

1. **Autorisation bloquée sans avis éthique favorable** — le protocole
   `CT-2026-0002` créé par `seed.py` (statut `evaluation_en_cours`, avis
   éthique `en_attente`) refuse la décision « Autoriser » avec un message
   explicite précisant le statut actuel de l'avis, y compris via un appel
   direct de `POST /protocoles/<id>/decision` (`workflow_ct.decider`).
2. **Amendement traçable sans altérer l'historique antérieur** — sur le
   protocole autorisé `CT-2026-0004`, soumettre un amendement (compte
   promoteur) ajoute une entrée à `amendements` sans toucher aux entrées
   précédentes ni à la piste d'audit déjà enregistrée ; le protocole revient à
   `autorise` une fois la décision d'amendement rendue.
3. **Échéance de rapport d'étape non respectée → alerte** — un rapport
   d'étape dont l'échéance est dépassée dans les données de démonstration
   déclenche une notification au promoteur et à `dros@dpml.demo`, visible dès
   le premier accès au tableau de bord.

### Module LR (18-LR §9)

1. **Lot non libérable sans AMM active** — `workflow_lr.controler_documentaire`
   et `workflow_lr.decider_liberation` revérifient tous deux le statut de
   l'AMM (et pas seulement à la réception du dossier), pour couvrir le cas où
   le statut change entre-temps.
2. **Libération bloquée sans résultat de laboratoire conforme et validé** —
   `LR-2026-0002` (statut `recu`, aucun échantillon encore rattaché) refuse
   toute décision de libération avec un message explicite tant que le
   contrôle documentaire puis le contrôle de laboratoire n'ont pas eu lieu.
3. **Rejet après distribution partielle → signalement MC automatique,
   jamais un archivage silencieux** — `LR-2026-0003`, rejeté avec un résultat
   de laboratoire non conforme dans les données de démonstration, a généré un
   `SignalementQualite` réel (origine « Module LR »), vérifiable dans
   `/signalements`.

## Mode hors connexion du module RI — approche technique

SIREPH est une application web multi-pages classique (pas une app mobile
native, pas un PWA avec service worker dans ce périmètre — voir limitation
ci-dessous). L'approche retenue pour respecter l'exigence « fonctionne hors
connexion » du cahier des charges (02-regles-transversales §9, 13-RI §6) :

- La page de grille (`templates/inspection/grille.html`) charge son état
  initial une fois, puis toute la logique de saisie est en JavaScript côté
  client : chaque réponse est écrite immédiatement dans `localStorage`, jamais
  bloquée par un appel réseau.
- Une tentative de synchronisation (`fetch` vers `/inspections/<id>/sync`) est
  déclenchée après chaque saisie, à l'évènement navigateur `online`, et au
  chargement de la page — mais un échec réseau est traité comme un mode
  dégradé normal (pas d'erreur affichée, la donnée reste protégée localement).
- La clôture de la visite peut elle-même être demandée hors connexion : elle
  est marquée `cloture_demandee` en local et se synchronise dès que possible,
  conformément au spec (« à la clôture de la visite, en ligne ou hors ligne
  puis synchronisée »).

## Limitations assumées (décisions de conception documentées)

- **Auto-inscription sans vérification d'e-mail.** `/inscription-labo` crée le
  compte immédiatement, sans envoi d'un lien de confirmation — aucune brique
  d'envoi d'e-mail dans ce périmètre (voir aussi la limite « pas de
  notifications e-mail » plus bas). En production, une vérification d'e-mail
  avant activation du compte serait recommandée.
- **Type d'établissement par défaut pour l'auto-inscription** :
  `importateur_exportateur`, faute de demander le type précis au moment de
  l'inscription (pour garder ce formulaire court) — modifiable ensuite par
  `administrateur_dpml`.
- **Pas de vrai scheduler.** Aucune tâche planifiée (Celery/cron) : la clôture
  automatique des compléments MA en retard, les rappels de renouvellement, et
  les alertes de cas VL en retard sont vérifiés à chaque accès au tableau de
  bord ou aux registres concernés (`delais.executer_verifications_delais` /
  `executer_verifications_delais_vl`, idempotentes). Suffisant pour un usage
  interne à faible fréquence de connexion ; à remplacer par un vrai job planifié
  en production.
- **Permissions centralisées en code** (`permissions.py`), pas dans une table
  configurable en base — jugé disproportionné pour ce périmètre. Point
  d'extension identifié : une table `RolePermission` éditable par
  `administrateur_dpml` sans redéploiement.
- **Numéro de dossier = numéro d'AMM.** Pas de numéro distinct attribué à
  l'approbation ; `DossierAMM.numero` (format `AMM-{année}-{séquence}`) sert de
  numéro d'AMM définitif, utilisé tel quel dans le registre public et
  `/verifier/<numero>`.
- **Impact des modifications de paramètres réglementaires** : s'applique aux
  nouveaux calculs uniquement. Un dossier déjà en `complement_requis` garde sa
  date limite déjà calculée même si le délai par défaut est modifié ensuite.
- **SQLite, pas de verrou distribué réel** sur le compteur de numérotation
  (`SequenceNumerotation`) — acceptable en usage interne à faible concurrence.
  Migration PostgreSQL recommandée avant une mise en production à plusieurs
  utilisateurs simultanés (transposable depuis `ARCHITECTURE.md` du prototype
  `ehomologation-dplm`, dans `Digitalisation AMM/`).
- **Établissements créés à la volée** depuis le formulaire MA (fabricant,
  titulaire) sont marqués `statut_licence = "active"` par défaut plutôt que
  `en_instruction`, pour ne pas obliger chaque scénario de démonstration MA à
  déposer une demande de licence LI au préalable. C'est un raccourci assumé :
  en production, un établissement inconnu du registre LI ne devrait pas
  pouvoir être désigné fabricant/titulaire d'un dossier AMM tant que sa licence
  n'est pas active.
- **Aucune passerelle de paiement en ligne réelle.** Le circuit de paiement
  (`paiements.py`) repose sur un dépôt de preuve + validation manuelle par un
  agent DPML — volontairement, aucune donnée de carte bancaire ou de mobile
  money n'est traitée, stockée ou transmise par SIREPH. L'intégration d'un
  agrégateur agréé (Orange Money, MTN MoMo, carte bancaire) nécessiterait des
  identifiants réels fournis par ce prestataire — hors périmètre de ce
  prototype.
- **Pas de scan antivirus ni d'analyse de contenu** sur les documents
  téléversés (`pieces.py`) — seules l'extension et la taille (10 Mo max) sont
  vérifiées. À ajouter avant un déploiement en production exposé à internet.
- **Validation des inscriptions binaire, sans motif de refus formalisé.**
  `/admin/utilisateurs` permet de valider ou de suspendre un compte en attente,
  mais ne capture pas de motif structuré en cas de rejet (l'administrateur
  peut suspendre puis contacter le demandeur hors SIREPH). Un futur écran
  pourrait ajouter un champ motif, sur le modèle du rejet de paiement.
- **"Signature électronique"** du certificat AMM : sceau graphique + hash
  SHA-256 + QR code de vérification publique, à des fins de démonstration
  uniquement. Ne constitue pas une signature électronique qualifiée.
- **VigiFlow/VigiBase simulé.** `workflow_vl.transmettre_vigiflow` ne réalise
  aucun appel réseau réel (hors de portée d'un environnement de démonstration) :
  elle génère une référence E2B simulée et horodate la transmission
  immédiatement. Le comportement observable exigé par le spec (référence
  consultable, ou statut explicite d'attente, jamais un échec silencieux) est
  respecté ; l'intégration réelle avec l'API VigiFlow reste à implémenter.
- **Tableau de signaux simplifié.** Le regroupement se fait par produit
  uniquement ; un regroupement plus fin par similarité de description d'effet
  (texte libre) n'est pas fiabilisé dans ce périmètre.
- **Pas de vrai PWA/service worker pour le module RI.** L'inspecteur doit
  charger la liste et la grille d'une inspection au moins une fois en ligne
  (l'application elle-même n'est pas mise en cache pour un premier accès hors
  connexion). Une fois la page chargée, la saisie et la conservation locale des
  réponses ne dépendent plus du réseau — voir section dédiée ci-dessus.
- **Pas de capture photo réelle** sur la grille de contrôle (champ `photo` du
  spec) : optionnel et hors périmètre pour cette livraison (aurait nécessité un
  pipeline de stockage d'images en base64 ou objet, disproportionné pour une
  démonstration).
- **Score de conformité RI** : proportion d'items conformes parmi les items
  conforme/non_conforme applicables (les items non_applicable ou laissés non
  répondus après confirmation explicite sont exclus du calcul).
- **Pas de pipeline de téléversement de fichiers pour LI.** Le champ
  `pieces_justificatives` de `DemandeLicence` est une description texte libre,
  pas une liste de documents réellement téléversés — même limite assumée que
  pour les pièces jointes MA dans le prototype voisin.
- **Une demande de licence refusée bloque le dépôt d'une nouvelle demande**
  tant que l'établissement reste au statut `refusee` : `workflow_li.deposer_demande`
  ne l'interdit pas explicitement (seuls `suspendue`/`revoquee` sont bloqués),
  mais aucun écran n'expose encore de bouton "nouvelle demande" pour un
  établissement refusé — à corriger si ce cas d'usage devient prioritaire (un
  établissement refusé doit normalement pouvoir redéposer un dossier corrigé).
- **Durée de validité de la licence** : 3 ans par défaut
  (`ParametreModule("LI", "duree_validite_licence_annees")`), valeur non
  spécifiée par le cahier des charges — choix assumé et configurable.
- **Comparaison de conformité LT simplifiée.** La spécification d'un
  paramètre est un texte libre ; `workflow_lt._conformite_parametre`
  interprète les formats numériques usuels (plage `18-22`, opérateurs
  `<=`/`>=`/`<`/`>`/`=`) et retombe sur une égalité texte sinon — une
  comparaison structurée complète (unités, incertitudes de mesure) est hors
  de portée d'une démonstration.
- **Pas de pipeline de fichiers pour LT/LR** non plus (résultats et dossier
  fabricant en texte libre), même limite assumée que pour LI/MA.
  **Photos MC/RI et pièces jointes CT** (protocole, brochure investigateur)
  également hors périmètre pour la même raison.
  **Illustration : le champ `photo` de l'inspection RI n'est jamais rempli.**
- **Établissements détenteurs de lot (MC) approximés.** Le socle ne modélise
  pas de chaîne de distribution ; `SignalementQualite.etablissements_notifies`
  dérive la liste des « détenteurs » à partir du fabricant du lot et du
  titulaire d'AMM du produit — une vraie chaîne de traçabilité (grossiste,
  officine) est hors de portée du modèle de données actuel.
- **Tous les rôles du cahier des charges sont désormais actifs**
  (`permissions.ROLES_ACTIFS`) : `agent_surveillance_marche` et `agent_dros`
  ont été activés par anticipation des modules MC et CT, livrés dans la
  continuité de cette même session. `permissions.ROLES_INERTES` est
  volontairement vide — conservé comme point d'extension pour un rôle futur.
- **Écrans RS avancés restants** : au-delà du tableau de bord, de la gestion
  des référentiels/paramètres et de la gestion des utilisateurs (déjà
  couverts), certains raffinements de gouvernance (ex. gestion fine des
  structures organisationnelles DPML/LANACOME/IGSPL/DROS comme entités
  éditables) ne sont pas exposés dans un écran dédié.

## Structure du projet

```
app.py            routes Flask du module MA + RS (auth, dashboard, dossiers, admin, public)
routes_vl.py       routes du module VL, en Blueprint Flask
routes_ri.py       routes du module RI (back-office + mobile) + registre/fiche Établissement, en Blueprint Flask
routes_li.py       routes du module LI (demandes, suspension/révocation d'établissement), en Blueprint Flask
routes_lt.py       routes du module LT (échantillons, résultats, certificats), en Blueprint Flask
routes_mc.py       routes du module MC (signalements, rappels, MITM, formulaire public), en Blueprint Flask
routes_ct.py       routes du module CT (protocoles, amendements, rapports d'étape), en Blueprint Flask
routes_lr.py       routes du module LR (dossiers de lot, interface PEV), en Blueprint Flask
routes_pieces.py   téléchargement générique des pièces jointes (MA/LI/paiements), contrôle d'accès par rôle/propriété
routes_derogation.py routes du module Dérogations spéciales, en Blueprint Flask
routes_visas.py    routes du module Visas techniques, en Blueprint Flask
auth.py           current_user/login_required/roles_required, partagés par app.py et les blueprints
erreurs.py        ErreurWorkflow, partagée par tous les moteurs de workflow
pieces.py          téléversement générique de documents (MA/LI), stockage disque + PieceJointe + audit
paiements.py       frais de dossier : création automatique, dépôt de preuve, confirmation/rejet par la DPML
workflow_derogation.py machine à états de DemandeDerogation (deposee → en_instruction → approuvee|refusee)
workflow_visas.py  machine à états de VisaTechnique (demande → delivre|refuse)
models.py         modèles SQLAlchemy — socle commun + DossierAMM/AvisEvaluationMA + NotificationVigilance +
                  Inspection + DemandeLicence + Echantillon + SignalementQualite + ProtocoleEssaiClinique +
                  LiberationLot
grille_ri.py       catalogue fixe de la grille de contrôle RI (sections/items) + calcul du score
workflow_ma.py     machine à états du DossierAMM — seule couche autorisée à changer son statut ; vérifie aussi
                  qu'aucun établissement suspendu/révoqué ne soit fabricant/titulaire à la création
workflow_vl.py     machine à états de la NotificationVigilance — idem, + intégration retrait → module MA
workflow_ri.py     machine à états de l'Inspection — idem
workflow_li.py     machine à états de DemandeLicence + du champ Etablissement.statut_licence (suspension,
                  révocation, expiration automatique), avec référence croisée vers l'évènement déclencheur
workflow_lt.py     machine à états de l'Échantillon — double validation obligatoire, comparaison de conformité
                  automatique, intégration réelle avec MC en cas de non-conformité
workflow_mc.py     machine à états du SignalementQualite — validation directeur pour un rappel niveau I,
                  dérivation automatique des établissements à notifier
workflow_ct.py     machine à états du ProtocoleEssaiClinique — blocage d'autorisation sans avis éthique
                  favorable, amendements et rapports d'étape en jalons
workflow_lr.py     machine à états de la LiberationLot — double contrôle croisé MA (AMM active) + LT (résultat
                  conforme et validé), intégration réelle avec MC en cas de rejet après distribution partielle
audit.py          piste d'audit universelle (EvenementAudit)
notifications.py  notifications in-app
permissions.py    rôles système et permissions transversales (tous les rôles du cahier des charges sont actifs)
numerotation.py    génération des numéros de dossier/cas/inspection/demande/échantillon/signalement/protocole/lot
delais.py          paramètres configurables + vérification des délais (clôture auto, rappels, alertes, expiration)
pdf_gen.py         génération des certificats AMM et laboratoire (PDF + QR + sceau SHA-256)
seed.py            comptes et données de démonstration pour les 8 circuits métier
seed_comptes.py    un compte actif par rôle du référentiel + annuaire des niveaux d'accès
seed_scenario_financier.py   dossier de démonstration bloqué en attente d'approbation financière
suivi.py           suivi unifié : numéro national, états visibles, Clock Start/Stop
run_lan.py          lancement réseau local (Waitress) pour l'accès depuis un autre appareil — voir SETUP.md
SETUP.md            accès local / réseau Wi-Fi / mobile, configuration du pare-feu Windows
templates/          gabarits HTML (Jinja + Bootstrap 5) ; un sous-dossier par module :
                  vigilance/ (VL), inspection/ (RI + établissements), licence/ (LI), laboratoire/ (LT),
                  marche/ (MC), essais_cliniques/ (CT), liberation/ (LR)
```
