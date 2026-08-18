"""
Catalogue des fonctionnalités et défauts par rôle (Lot A — gouvernance des accès).

CE QUE CE FICHIER EST
---------------------
La source Python du catalogue RBAC. `seed_gouvernance.py` le LIT pour peupler les
tables `Fonctionnalite`, `Categorie` et `Role`. À l'exécution, l'autorisation se
résout dans `permissions.utilisateur_peut` en interrogeant la base, pas ce fichier.

ALIGNÉ SUR LES ACTIONS RÉELLES, PAS SUR UNE LISTE THÉORIQUE
-----------------------------------------------------------
Les défauts d'un rôle ne sont pas saisis à la main : `defauts_role()` les DÉDUIT
des listes nominatives de `permissions.PERMISSIONS_TRANSVERSES` et des `roles`
déclarés dans les transitions de `machine_etats.TRANSITIONS`. C'est la garantie
de sûreté de la migration (Étape 1) : les détenteurs par défaut d'une
fonctionnalité de workflow sont exactement le `roles` actuel de la transition,
donc `utilisateur_peut` renverra le même booléen qu'aujourd'hui → 21 suites
vertes. Les extras (`EXPLICIT`) et le socle par catégorie (`CATEGORY_BASE`)
complètent, au moindre privilège.

Aucune de ces déclarations n'est encore branchée sur l'autorisation : à l'Étape 2,
on ne fait qu'AMORCER le catalogue. Le câblage vient aux étapes suivantes.
"""

# ---------------------------------------------------------------------------
# Catégories (Categorie.code)
# ---------------------------------------------------------------------------
CATEGORIES = {
    "regulateur": "Régulateur (DPML / IGSPL / agences)",
    "demandeur": "Demandeur / opérateur réglementé",
    "usager": "Usager (citoyen / professionnel de santé)",
}

# ---------------------------------------------------------------------------
# Catalogue — 🔒 sensible = jamais accordé implicitement
# ---------------------------------------------------------------------------
# Chaque entrée : code · libellé · module · sensible · description.
FONCTIONNALITES = [
    # -- Gouvernance ------------------------------------------------------
    {"code": "inscription.valider", "module": "gouvernance", "sensible": True,
     "libelle": "Valider une inscription",
     "description": "Activer un compte en attente, avec choix du rôle."},
    {"code": "inscription.rejeter", "module": "gouvernance", "sensible": True,
     "libelle": "Rejeter une inscription",
     "description": "Refuser un compte en attente ; motif obligatoire."},
    {"code": "utilisateur.lister", "module": "gouvernance", "sensible": False,
     "libelle": "Lister les utilisateurs",
     "description": "Consulter l'annuaire des comptes et leur statut."},
    {"code": "utilisateur.suspendre", "module": "gouvernance", "sensible": True,
     "libelle": "Suspendre un utilisateur",
     "description": "Suspendre un compte actif ; jamais le dernier super admin."},
    {"code": "role.gerer", "module": "gouvernance", "sensible": True,
     "libelle": "Gérer les défauts d'un rôle",
     "description": "Modifier les fonctionnalités par défaut d'un rôle (impact global)."},
    {"code": "fonctionnalite.attribuer", "module": "gouvernance", "sensible": True,
     "libelle": "Attribuer une fonctionnalité",
     "description": "Accorder une surcharge à un utilisateur ; jamais à soi-même."},
    {"code": "fonctionnalite.retirer", "module": "gouvernance", "sensible": True,
     "libelle": "Retirer une fonctionnalité",
     "description": "Retirer une fonctionnalité à un utilisateur ; jamais à soi-même."},
    {"code": "audit.consulter", "module": "gouvernance", "sensible": True,
     "libelle": "Consulter le journal d'audit",
     "description": "Lire la piste d'audit universelle (EvenementAudit)."},
    {"code": "referentiel.gerer", "module": "gouvernance", "sensible": True,
     "libelle": "Gérer les référentiels",
     "description": "Éditer barèmes, paramètres et référentiels."},

    # -- Inscription déléguée --------------------------------------------
    {"code": "evaluateur.inscrire", "module": "inscription_deleguee", "sensible": True,
     "libelle": "Enrôler un évaluateur interne",
     "description": "Créer un compte évaluateur interne, actif immédiatement."},
    {"code": "membre_commission.inscrire", "module": "inscription_deleguee", "sensible": True,
     "libelle": "Enrôler un membre de commission",
     "description": "Créer un membre de commission ; note ministérielle obligatoire."},

    # -- Demandes ---------------------------------------------------------
    {"code": "demande.creer", "module": "demandes", "sensible": False,
     "libelle": "Créer une demande",
     "description": "Ouvrir un nouveau dossier de démarche."},
    {"code": "demande.modifier", "module": "demandes", "sensible": False,
     "libelle": "Modifier une demande",
     "description": "Éditer une demande non encore soumise."},
    {"code": "demande.soumettre", "module": "demandes", "sensible": False,
     "libelle": "Soumettre une demande",
     "description": "Transmettre la demande et déclencher le circuit."},
    {"code": "demande.consulter_siennes", "module": "demandes", "sensible": False,
     "libelle": "Consulter ses demandes",
     "description": "Voir ses propres dossiers, cloisonnés à son établissement."},
    {"code": "demande.consulter_toutes", "module": "demandes", "sensible": False,
     "libelle": "Consulter toutes les demandes",
     "description": "Vue transversale des dossiers d'AMM."},

    # -- Dossier technique ------------------------------------------------
    {"code": "dossier.constituer", "module": "dossier_technique", "sensible": False,
     "libelle": "Constituer le dossier technique",
     "description": "Composer les modules CTD du dossier."},
    {"code": "dossier.televerser_documents", "module": "dossier_technique", "sensible": False,
     "libelle": "Téléverser des documents",
     "description": "Joindre les pièces au dossier."},
    {"code": "dossier.suivre", "module": "dossier_technique", "sensible": False,
     "libelle": "Suivre son dossier",
     "description": "Consulter l'avancement en temps réel."},

    # -- Paiement ---------------------------------------------------------
    {"code": "paiement.effectuer", "module": "paiement", "sensible": False,
     "libelle": "Effectuer un paiement",
     "description": "Régler une créance via la plateforme."},
    {"code": "paiement.valider", "module": "paiement", "sensible": True,
     "libelle": "Approuver une recette",
     "description": "Constater l'encaissement (verrou financier)."},
    {"code": "paiement.consulter", "module": "paiement", "sensible": False,
     "libelle": "Consulter les paiements",
     "description": "Exploiter la console des paiements."},

    # -- Recevabilité -----------------------------------------------------
    {"code": "recevabilite.examiner", "module": "recevabilite", "sensible": False,
     "libelle": "Examiner la recevabilité",
     "description": "Instruire la liste de contrôle de recevabilité."},
    {"code": "recevabilite.decider", "module": "recevabilite", "sensible": True,
     "libelle": "Décider de la recevabilité",
     "description": "Déclarer recevable/irrecevable, demander un complément, inscrire en commission."},
    {"code": "checklist.gerer", "module": "recevabilite", "sensible": False,
     "libelle": "Gérer la check-list",
     "description": "Composer et renseigner la liste de contrôle."},

    # -- Évaluation -------------------------------------------------------
    {"code": "dossier.evaluer", "module": "evaluation", "sensible": False,
     "libelle": "Évaluer un dossier",
     "description": "Conduire l'évaluation scientifique d'un dossier assigné."},
    {"code": "rapport_evaluation.rediger", "module": "evaluation", "sensible": False,
     "libelle": "Rédiger un rapport d'évaluation",
     "description": "Remettre un rapport d'évaluation motivé."},

    # -- Commissions ------------------------------------------------------
    {"code": "commission.consulter", "module": "commissions", "sensible": False,
     "libelle": "Consulter les commissions",
     "description": "Voir l'ordre du jour de sa commission."},
    {"code": "commission.emettre_avis", "module": "commissions", "sensible": False,
     "libelle": "Émettre un avis de commission",
     "description": "Rendre un avis individuel puis consolider."},

    # -- Validation & actes ----------------------------------------------
    {"code": "parapheur.consulter", "module": "validation_actes", "sensible": False,
     "libelle": "Consulter le parapheur",
     "description": "Voir les dossiers en attente de visa/validation."},
    {"code": "dossier.annoter", "module": "validation_actes", "sensible": False,
     "libelle": "Annoter un dossier",
     "description": "Ajouter des notes au dossier en parapheur."},
    {"code": "dossier.ajouter_piece", "module": "validation_actes", "sensible": False,
     "libelle": "Ajouter une pièce",
     "description": "Joindre une pièce au dossier en parapheur."},
    {"code": "dossier.viser", "module": "validation_actes", "sensible": True,
     "libelle": "Viser un dossier",
     "description": "Visa du chef de service ouvrant le parapheur sous-directeur (Lot B1)."},
    {"code": "dossier.valider_conformite", "module": "validation_actes", "sensible": True,
     "libelle": "Valider la conformité",
     "description": "Contrôle de conformité du sous-directeur (Lot B1)."},
    {"code": "dossier.valider_final", "module": "validation_actes", "sensible": True,
     "libelle": "Valider en dernier ressort",
     "description": "Validation finale du directeur ; produit les actes."},
    {"code": "certificat.generer", "module": "validation_actes", "sensible": True,
     "libelle": "Générer le certificat",
     "description": "Éditer le certificat d'homologation."},
    {"code": "amm.generer", "module": "validation_actes", "sensible": True,
     "libelle": "Générer l'AMM",
     "description": "Éditer l'AMM à signer."},
    {"code": "acte.marquer_signe", "module": "validation_actes", "sensible": True,
     "libelle": "Enregistrer la signature",
     "description": "Transmettre au cabinet et acter la signature."},

    # -- Agréments / Licences --------------------------------------------
    {"code": "agrement.instruire", "module": "agrements", "sensible": False,
     "libelle": "Instruire un agrément", "description": "Instruire un agrément d'établissement."},
    {"code": "agrement.valider", "module": "agrements", "sensible": True,
     "libelle": "Valider un agrément", "description": "Valider un agrément d'établissement."},
    {"code": "licence.demander", "module": "agrements", "sensible": False,
     "libelle": "Demander une licence", "description": "Déposer une demande de licence d'établissement."},
    {"code": "licence.instruire", "module": "agrements", "sensible": False,
     "libelle": "Instruire une licence", "description": "Instruire une demande de licence."},
    {"code": "licence.consulter", "module": "agrements", "sensible": False,
     "libelle": "Consulter les licences", "description": "Vue transversale des licences."},

    # -- Inspection -------------------------------------------------------
    {"code": "inspection.planifier", "module": "inspection", "sensible": True,
     "libelle": "Planifier une inspection", "description": "Programmer une inspection de terrain."},
    {"code": "inspection.conduire", "module": "inspection", "sensible": False,
     "libelle": "Conduire une inspection", "description": "Mener l'inspection et rédiger le rapport."},
    {"code": "inspection.consulter", "module": "inspection", "sensible": False,
     "libelle": "Consulter les inspections", "description": "Vue transversale des inspections."},

    # -- Vigilances -------------------------------------------------------
    {"code": "vigilance.declarer", "module": "vigilances", "sensible": False,
     "libelle": "Déclarer un effet indésirable", "description": "Notifier un effet indésirable (santé publique)."},
    {"code": "vigilance.traiter", "module": "vigilances", "sensible": False,
     "libelle": "Traiter un cas de vigilance", "description": "Instruire un cas de pharmacovigilance."},
    {"code": "vigilance.consulter", "module": "vigilances", "sensible": False,
     "libelle": "Consulter la vigilance", "description": "Vue transversale des cas de vigilance."},

    # -- Contrôle qualité -------------------------------------------------
    {"code": "controle_qualite.demander", "module": "controle_qualite", "sensible": False,
     "libelle": "Demander une analyse", "description": "Solliciter une analyse au laboratoire national."},
    {"code": "controle_qualite.analyser", "module": "controle_qualite", "sensible": False,
     "libelle": "Analyser un échantillon", "description": "Réceptionner et analyser un échantillon."},
    {"code": "controle_qualite.liberer", "module": "controle_qualite", "sensible": True,
     "libelle": "Libérer un lot", "description": "Validation qualité et libération d'un lot."},
    {"code": "controle_qualite.consulter", "module": "controle_qualite", "sensible": False,
     "libelle": "Consulter le contrôle qualité", "description": "Vue transversale échantillons et libérations."},

    # -- Surveillance du marché ------------------------------------------
    {"code": "surveillance.signaler", "module": "surveillance", "sensible": False,
     "libelle": "Signaler un produit suspect", "description": "Signalement ouvert au marché, à l'officine, au public."},
    {"code": "surveillance.traiter", "module": "surveillance", "sensible": False,
     "libelle": "Traiter un signalement", "description": "Instruire un signalement du marché."},
    {"code": "surveillance.consulter", "module": "surveillance", "sensible": False,
     "libelle": "Consulter la surveillance", "description": "Vue transversale des signalements."},

    # -- Essais cliniques -------------------------------------------------
    {"code": "essai_clinique.deposer", "module": "essais_cliniques", "sensible": False,
     "libelle": "Déposer un protocole", "description": "Soumettre un protocole d'essai clinique."},
    {"code": "essai_clinique.instruire", "module": "essais_cliniques", "sensible": False,
     "libelle": "Instruire un protocole", "description": "Instruire un protocole d'essai clinique."},
    {"code": "essai_clinique.consulter", "module": "essais_cliniques", "sensible": False,
     "libelle": "Consulter les essais", "description": "Vue transversale des protocoles."},

    # -- Établissements ---------------------------------------------------
    {"code": "etablissement.suspendre", "module": "etablissements", "sensible": True,
     "libelle": "Suspendre un établissement", "description": "Décision de suspension d'un établissement."},

    # -- Reliance régionale ----------------------------------------------
    {"code": "reliance.consulter", "module": "reliance", "sensible": False,
     "libelle": "Consulter la reliance", "description": "Consulter la reliance régionale CEEAC."},
    {"code": "reliance.gerer", "module": "reliance", "sensible": True,
     "libelle": "Gérer la reliance", "description": "Émettre requêtes et partages de reliance."},

    # -- Tableaux de bord -------------------------------------------------
    {"code": "tableau_bord.consulter", "module": "tableaux_bord", "sensible": False,
     "libelle": "Consulter le tableau de bord", "description": "Accès au tableau de bord adapté au profil."},
]

CODES_CONNUS = {f["code"] for f in FONCTIONNALITES}

# ---------------------------------------------------------------------------
# Traductions vers les actions réelles (pour DÉDUIRE les défauts)
# ---------------------------------------------------------------------------
# Clé de permissions.PERMISSIONS_TRANSVERSES → fonctionnalité.
LEGACY_FONCTION = {
    "gerer_referentiels": "referentiel.gerer",
    "gerer_utilisateurs": "utilisateur.lister",
    "creer_dossier_ma": "demande.creer",
    "voir_tous_dossiers_ma": "demande.consulter_toutes",
    "voir_tous_cas_vigilance": "vigilance.consulter",
    "traiter_cas_vigilance": "vigilance.traiter",
    "declarer_effet_indesirable": "vigilance.declarer",
    "planifier_inspection": "inspection.planifier",
    "voir_toutes_inspections": "inspection.consulter",
    "suspendre_etablissement": "etablissement.suspendre",
    "voir_toutes_licences": "licence.consulter",
    "instruire_licence": "licence.instruire",
    "demander_licence": "licence.demander",
    "voir_tous_echantillons": "controle_qualite.consulter",
    "demander_analyse": "controle_qualite.demander",
    "voir_tous_signalements": "surveillance.consulter",
    "signaler_produit": "surveillance.signaler",
    "voir_tous_protocoles": "essai_clinique.consulter",
    "deposer_essai_clinique": "essai_clinique.deposer",
    "voir_toutes_liberations": "controle_qualite.consulter",
    "gerer_paiements": "paiement.consulter",
    "confirmer_paiement": "paiement.valider",
    "consulter_reliance": "reliance.consulter",
    "gerer_reliance": "reliance.gerer",
}

# Action de machine_etats.TRANSITIONS → fonctionnalité (mapping de l'Étape 1).
ACTION_FONCTION = {
    "soumettre": "demande.soumettre",
    "repondre_complement": "demande.soumettre",
    "valider_paiement": "paiement.valider",
    "rejeter_paiement": "paiement.valider",
    "declarer_recevable": "recevabilite.decider",
    "demander_complement": "recevabilite.decider",
    "declarer_irrecevable": "recevabilite.decider",
    "envoyer_commission": "recevabilite.decider",
    "retour_service": "commission.emettre_avis",
    "demander_complement_commission": "commission.emettre_avis",
    "valider": "dossier.valider_final",
    "renvoyer_complement": "dossier.valider_final",
    "rejeter": "dossier.valider_final",
    "transmettre_signature": "acte.marquer_signe",
    "enregistrer_signature": "acte.marquer_signe",
}

# Socle attribué à tout rôle d'une catégorie (moindre privilège).
CATEGORY_BASE = {
    "demandeur": ["demande.consulter_siennes", "dossier.constituer",
                  "dossier.televerser_documents", "dossier.suivre",
                  "paiement.effectuer", "paiement.consulter",
                  "tableau_bord.consulter"],
    "usager": ["tableau_bord.consulter"],
    "regulateur": ["tableau_bord.consulter"],
}

# Extras métier non déductibles des deux tables ci-dessus (moindre privilège).
EXPLICIT = {
    # Super administrateur = administrateur_dpml (décision Étape 0).
    "administrateur_dpml": [
        "inscription.valider", "inscription.rejeter", "utilisateur.lister",
        "utilisateur.suspendre", "role.gerer", "fonctionnalite.attribuer",
        "fonctionnalite.retirer", "audit.consulter", "referentiel.gerer",
        "evaluateur.inscrire", "membre_commission.inscrire",
    ],
    "chef_service_amm": [
        "evaluateur.inscrire", "membre_commission.inscrire",
        "recevabilite.examiner", "checklist.gerer",
        "parapheur.consulter", "dossier.annoter", "dossier.ajouter_piece",
        "certificat.generer",
    ],
    "chef_bureau": ["recevabilite.examiner", "checklist.gerer",
                    "parapheur.consulter"],
    "cadre_dpml": ["dossier.evaluer", "rapport_evaluation.rediger"],
    "evaluateur_amm": ["dossier.evaluer", "rapport_evaluation.rediger"],
    "evaluateur_interne": ["dossier.evaluer", "rapport_evaluation.rediger"],
    "membre_commission_specialisee": ["commission.consulter"],
    "membre_commission_nationale": ["commission.consulter"],
    "directeur_dpml": ["parapheur.consulter", "dossier.annoter",
                       "certificat.generer", "amm.generer"],
    "sous_directeur_medicament": ["parapheur.consulter"],
    "inspecteur_igspl": ["inspection.conduire"],
    "agent_dros": ["essai_clinique.instruire"],
    "agent_laboratoire": ["controle_qualite.analyser"],
    "responsable_qualite_labo": ["controle_qualite.liberer",
                                 "controle_qualite.consulter"],
    "agent_surveillance_marche": ["surveillance.traiter"],
    "agent_licences": ["licence.instruire"],
}

_CATEGORIE_PAR_ROLE = None


def categorie_de(role):
    """Catégorie (regulateur | demandeur | usager) d'un rôle du référentiel."""
    global _CATEGORIE_PAR_ROLE
    if _CATEGORIE_PAR_ROLE is None:
        import permissions as perm
        _CATEGORIE_PAR_ROLE = {}
        for r in perm.ROLES_EXTERNES:
            _CATEGORIE_PAR_ROLE[r] = "usager" if r == "usager" else "demandeur"
        for r in perm.ROLES_REGULATEUR:
            _CATEGORIE_PAR_ROLE[r] = "regulateur"
    return _CATEGORIE_PAR_ROLE.get(role, "regulateur")


def defauts_role(role):
    """Fonctionnalités par défaut d'un rôle, DÉDUITES des actions réelles.

    Ne renvoie que des codes présents au catalogue : un mapping erroné laisse
    donc une trace (fonctionnalité manquante) plutôt qu'un code fantôme en base.
    """
    import permissions as perm
    import machine_etats as me

    codes = set(CATEGORY_BASE.get(categorie_de(role), []))
    for cle, titulaires in perm.PERMISSIONS_TRANSVERSES.items():
        if role in titulaires and cle in LEGACY_FONCTION:
            codes.add(LEGACY_FONCTION[cle])
    for t in me.TRANSITIONS:
        if role in t["roles"] and t["action"] in ACTION_FONCTION:
            codes.add(ACTION_FONCTION[t["action"]])
    codes.update(EXPLICIT.get(role, []))
    return sorted(c for c in codes if c in CODES_CONNUS)


def verifier_catalogue():
    """Anomalies du catalogue — support de test, pas d'exécution."""
    anomalies = []
    codes = [f["code"] for f in FONCTIONNALITES]
    for c in set(codes):
        if codes.count(c) > 1:
            anomalies.append(f"fonctionnalité en double : {c}")
    for f in FONCTIONNALITES:
        if f["module"] not in {x["module"] for x in FONCTIONNALITES}:
            anomalies.append(f"{f['code']} : module inconnu")
    for cle, code in LEGACY_FONCTION.items():
        if code not in CODES_CONNUS:
            anomalies.append(f"LEGACY_FONCTION[{cle}] → code inconnu {code}")
    for action, code in ACTION_FONCTION.items():
        if code not in CODES_CONNUS:
            anomalies.append(f"ACTION_FONCTION[{action}] → code inconnu {code}")
    for role, extras in EXPLICIT.items():
        for code in extras:
            if code not in CODES_CONNUS:
                anomalies.append(f"EXPLICIT[{role}] → code inconnu {code}")
    for cat, extras in CATEGORY_BASE.items():
        for code in extras:
            if code not in CODES_CONNUS:
                anomalies.append(f"CATEGORY_BASE[{cat}] → code inconnu {code}")
    return anomalies
