# Comptes de test — ePharmRegul (SIREPH)

> Généré depuis `seed_comptes.py` + `catalogue_fonctionnalites.py`. **Ne pas éditer à la main** : relancer le générateur si les comptes changent.

## Convention

- **Mot de passe commun** : `demo1234` (démonstration uniquement).
- **Domaine** : `@dpml.demo` et apparentés (`.demo`, `-demo.cm`). Décision Étape 0 : convention conservée.
- **Environnement** : le seed des comptes et du catalogue de gouvernance est **conditionné hors-production** ; `run_public.py` refuse l'exposition publique tant que le mot de passe commun est en place.
- **Super administrateur** : `admin@dpml.demo` (rôle `administrateur_dpml`). Le bootstrap garantit **au moins un super admin actif** ; `seed_gouvernance.py` le contrôle après coup.

## Un compte actif par rôle (33 rôles)

Colonne « Défauts » = nombre de fonctionnalités par défaut du rôle (catalogue Lot A, déduites des actions réelles).


### Niveau 0 — Externe

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `fabricant` | `fabricant@wouri.demo` | 10 | Agrément de fabrication, demandes d'inspection de site. L'homologation et l'essai clini… |
| `grossiste` | `ateba@grossiste-demo.cm` | 11 | Licence d'établissement, rappels de lots, signalement. |
| `demandeur_externe` | `demandeur@pharmacam.demo` | 13 | Dépôt d'AMM, modules CTD, paiement, suivi du dossier, demande d'inspection. Cloisonné à… |
| `laboratoire_prive` | `labo.prive@sireph.demo` | 11 | Demande d'analyse au laboratoire national, suivi des certificats. |
| `pharmacien` | `pharmacien@officine.demo` | 11 | Licence d'officine, alertes de retrait, signalement. |
| `promoteur_essai` | `promoteur@essai.demo` | 9 | Dépôt de protocole d'essai clinique et suivi de l'autorisation. |
| `usager` | `usager@sireph.demo` | 3 | Registre public, déclaration d'effet indésirable, signalement de produit suspect. Aucun… |

### Niveau 1 — Cadre — évaluateur / instructeur scientifique

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `agent_dros` | `dros@dpml.demo` | 3 | Instruction des protocoles d'essai clinique. |
| `agent_laboratoire` | `labo@lanacome.demo` | 3 | Réception d'échantillons, résultats d'analyse. |
| `agent_licences` | `licences@dpml.demo` | 3 | Instruction d'une demande de licence d'établissement. |
| `agent_surveillance_marche` | `surveillance@dpml.demo` | 5 | Signalements du marché, produits suspects. |
| `agent_vigilance` | `vigilance@dpml.demo` | 5 | Traitement des cas de pharmacovigilance. |
| `cadre_dpml` | `cadre@dpml.demo` | 3 | Instruction scientifique, saisie d'avis. Ne valide rien. |
| `inspecteur_igspl` | `inspecteur@igspl.demo` | 3 | Conduite d'inspection, rapport d'inspection. |
| `membre_commission_specialisee` | `commission1@dpml.demo` | 3 | Séance de commission, avis individuel, synthèse automatique. Bloqué en cas de conflit d… |
| `membre_commission_nationale` | `cnm1@dpml.demo` | 2 | Commission nationale du médicament. |
| `evaluateur_amm` | `evaluateur@dpml.demo` | 5 | Évaluation d'un dossier d'AMM qui lui est assigné. |
| `evaluateur_interne` | `evaluateur1@dpml.demo` | 3 | Réception d'une assignation, remise d'un rapport d'évaluation motivé. |

### Niveau 2 — Chef de bureau

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `chef_bureau` | `chefbureau@dpml.demo` | 7 | Recevabilité administrative et attribution des dossiers aux évaluateurs. Premier niveau… |

### Niveau 3 — Chef de service

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `chef_service_amm` | `chefservice@dpml.demo` | 15 | Recevabilité, attribution, convocation de commission, rapport d'instruction, PREMIÈRE S… |
| `chef_service_inspection` | `cs.inspection@dpml.demo` | 1 | Première signature du circuit Inspection. |
| `chef_service_labo` | `cs.labo@dpml.demo` | 1 | Première signature du circuit Contrôle qualité. |
| `chef_service_licences` | `cs.licences@dpml.demo` | 1 | Première signature du circuit Licence. |
| `responsable_qualite_labo` | `rq@lanacome.demo` | 3 | Validation qualité des analyses de laboratoire. |
| `responsable_financier` | `finances@dpml.demo` | 3 | APPROBATION DES RECETTES à /paiements/approbation. Son approbation démarre le délai lég… |

### Niveau 4 — Sous-direction

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `sous_directeur_etablissements` | `sd.etablissements@dpml.demo` | 1 | Deuxième signature (licences, inspections). |
| `sous_directeur_medicament` | `sousdirecteur@dpml.demo` | 2 | Deuxième signature (AMM, essais cliniques, contrôle qualité). Vue de synthèse, pas le d… |

### Niveau 5 — Direction

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `administrateur_dpml` | `admin@dpml.demo` | 30 | Comptes, référentiels, barèmes, paramètres, rapprochement des paiements. |
| `directeur_dpml` | `directeur@dpml.demo` | 16 | Signature de direction, suspension d'établissement, levée de déport. Vue de synthèse. |

### Niveau 6 — Inspection générale

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `inspecteur_general` | `ig@minsante.demo` | 1 | Audit d'intégrité transversal ; s'intercale dans le circuit AMM après le directeur et c… |

### Niveau 7 — Secrétariat général

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `directeur_general_agence` | `dg@agence.demo` | 1 | Signature en lieu et place du ministre lorsque l'Agence succédera à la direction. |
| `secretaire_general_ms` | `sg@minsante.demo` | 1 | Avant-dernière signature de l'AMM, des licences et des essais cliniques. Vue parcours s… |

### Niveau 8 — Ministre

| Rôle | E-mail | Défauts | À éprouver |
|---|---|---:|---|
| `ministre_sante` | `ministre@minsante.demo` | 1 | SIGNATURE FINALE de l'AMM, des licences et des autorisations d'essai clinique. Vue parc… |

## Lancer / relancer

```bash
.venv/bin/python migration_gouvernance.py   # schéma (idempotent)
.venv/bin/python seed_comptes.py            # 1 compte actif par rôle
.venv/bin/python seed_gouvernance.py        # catalogue + défauts
```
