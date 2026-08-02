# Plateforme de paiement SIREPH

Quatre moyens de règlement, un contrat technique unique. Ajouter un opérateur
(Wave, Moov, un autre PSP carte) revient à écrire une classe dans
`paiement/fournisseurs.py` : ni les routes ni les workflows ne changent.

## Moyens raccordés

| Moyen | Famille | Flux | Confirmation | Frais opérateur |
|---|---|---|---|---|
| MTN Mobile Money | mobile | `push` | notification signée + interrogation de statut | ~1,5 % |
| Orange Money | mobile | `push` → redirection | notification signée | ~1,5 % |
| Carte bancaire (Visa/Mastercard) | carte | `redirection` (3-D Secure) | webhook signé | ~1,8 % |
| Virement bancaire | virement | `hors_ligne` | rapprochement sur relevé | — |

**Les trois flux**

- `redirection` — l'usager part sur la page du prestataire, revient ; le retour
  navigateur **ne confirme rien** (il est falsifiable), seul le webhook fait foi.
- `push` — une demande est poussée sur le téléphone ; la page d'attente
  interroge le statut toutes les 5 s, et le webhook peut confirmer sans que
  l'usager revienne.
- `hors_ligne` — avis de paiement portant une référence unique, encaissement
  constaté ensuite par rapprochement bancaire.

## Faits générateurs facturés

Barème centralisé dans `bareme.py`, montants modifiables sans redéploiement
(Administration → paramètres). Un montant à **0 vaut exonération** : aucun
paiement n'est créé.

| Acte | Redevable | Défaut |
|---|---|---|
| Homologation (AMM) | Industriel / titulaire | 500 000 XAF |
| Autorisation d'essai clinique | Promoteur | 300 000 XAF |
| Licence d'établissement | Grossiste, officine, laboratoire | 150 000 XAF |
| Libération de lot | Établissement | 100 000 XAF |
| Analyse de laboratoire | Opérateur demandeur | 75 000 XAF |
| Inspection (descente) | Établissement inspecté | 0 (non facturée) |

## Sécurité

1. **Aucune donnée sensible stockée** — ni numéro de carte, ni code mobile
   money. La saisie a lieu chez l'opérateur ; SIREPH ne manipule que des
   références opaques. L'application reste hors périmètre PCI-DSS.
2. **Signature HMAC-SHA256** de chaque notification, vérifiée en comparaison à
   temps constant (pas de fuite par le temps de calcul).
3. **Un secret par fournisseur** — une notification signée par le PSP carte est
   refusée si elle est présentée au connecteur MTN.
4. **Contrôle strict du montant et de la devise** avant toute confirmation :
   une notification divergente, même correctement signée, est rejetée et tracée.
5. **Idempotence** par référence marchande unique : rejouer une notification
   n'encaisse jamais deux fois.
6. **Anti-rejeu** : horodatage signé, fenêtre de validité de 15 minutes.
7. **Expiration** des sessions non abouties.
8. **Traçabilité** : chaque transition, y compris chaque refus, est écrite au
   journal d'audit — une tentative de fraude laisse une trace exploitable.

Contrôle d'accès : seul le redevable rattaché à la créance (ou un agent
habilité `confirmer_paiement`) peut engager un règlement.

## Raccorder un prestataire réel

Tant que les identifiants sont absents, le fournisseur fonctionne en
**simulation** — signalée dans l'interface, jamais silencieuse. Aucun
encaissement n'est prétendu : le connecteur réel refuse de démarrer sans
identifiants plutôt que de produire un faux positif.

```bash
# Carte bancaire (PSP agréé)
SIREPH_PSP_CARTE_URL=https://api.mon-psp.com/v1
SIREPH_PSP_CARTE_CLE=pk_live_...
SIREPH_PSP_CARTE_SECRET=whsec_...          # vérification du webhook

# MTN Mobile Money — API Collections
SIREPH_PSP_MTN_URL=https://proxy.momoapi.mtn.com
SIREPH_PSP_MTN_CLE=...                      # jeton OAuth
SIREPH_PSP_MTN_ABONNEMENT=...               # Ocp-Apim-Subscription-Key
SIREPH_PSP_MTN_SECRET=...                   # vérification du callback
SIREPH_PSP_MTN_ENV=mtncameroon

# Orange Money — Web Payment
SIREPH_PSP_ORANGE_URL=https://api.orange.com/orange-money-webpay/cm/v1
SIREPH_PSP_ORANGE_CLE=...                   # merchant_key
SIREPH_PSP_ORANGE_SECRET=...

# Virement — coordonnées du compte de recette publique
SIREPH_BANQUE_NOM="BICEC"
SIREPH_BANQUE_TITULAIRE="DPML — Recettes réglementaires"
SIREPH_BANQUE_IBAN="CM21 ..."
SIREPH_BANQUE_BIC="..."
```

Le **virement bancaire est le seul mode pleinement opérationnel sans contrat
prestataire** : il suffit de renseigner les coordonnées du compte de recette.
Les trois autres exigent un contrat marchand avec l'opérateur concerné.

`requests` doit être installé pour les connecteurs réels
(`pip install requests`) ; il n'est chargé que si un prestataire est raccordé.

## Exploitation

- **Rapprochement bancaire** — `/paiements/rapprochement` (agents habilités) :
  saisie d'une ligne de relevé, contrôle strict du montant. Un virement partiel
  est refusé et tracé.
- **Espace du redevable** — `/mon-espace` : créances dues, total, règlement en
  un clic, historique.
- **Webhook** — `POST /paiements/notification`, authentifié par la seule
  signature (pas de session). À déclarer auprès de chaque prestataire.

## Tests

```bash
venv\Scripts\python test_plateforme_paiement.py
```

62 vérifications : catalogue, les trois flux, sécurité commune (montant
falsifié puis resigné, rejeu, référence croisée), cloisonnement des secrets
entre fournisseurs, idempotence, absence de donnée sensible.
