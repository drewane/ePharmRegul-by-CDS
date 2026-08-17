"""
Rôles système, profils d'accès et permissions transversales.

ORGANISATION EN DEUX FAMILLES
-----------------------------
1. Acteurs EXTERNES (hors administration) — un profil par métier, car les droits
   et les parcours diffèrent réellement : un grossiste ne dépose pas d'essai
   clinique, un laboratoire privé ne demande pas d'AMM. Le rôle historique
   `demandeur_externe` est conservé (comptes existants) et reste le profil
   « industriel/titulaire » générique.

2. Acteurs RÉGULATEUR (DPML/IGSPL) — chaque rôle porte un NIVEAU DE
   RESPONSABILITÉ (1 à 4). Le niveau conditionne les actions engageantes
   (validation finale, signature, suspension, dérogation) indépendamment du
   métier : voir NIVEAU_PAR_ROLE et exige_niveau().

     niveau 1 — agent instructeur (instruit, propose)
     niveau 2 — responsable/chef de service (valide techniquement)
     niveau 3 — direction (décide, signe, suspend)
     niveau 4 — administrateur système (paramètre, gère les comptes)

DÉCISION ASSUMÉE : la matrice reste centralisée ici, en code Python, plutôt
qu'en table configurable. Point d'extension identifié : table RolePermission
éditable par administrateur_dpml sans redéploiement.

La correspondance statut → action → rôle spécifique au circuit MA reste dans
workflow_ma.py (colocalisée avec la machine à états).
"""

# ---------------------------------------------------------------------------
# 1. Profils EXTERNES (usagers du service public de la régulation)
# ---------------------------------------------------------------------------
ROLES_EXTERNES = {
    "usager": "Usager (citoyen / professionnel de santé)",
    "demandeur_externe": "Industriel / Titulaire d'AMM",
    "laboratoire_prive": "Laboratoire (demandeur d'analyses)",
    "fabricant": "Fabricant (site de production)",
    "grossiste": "Grossiste-répartiteur",
    "pharmacien": "Pharmacien d'officine",
    "promoteur_essai": "Promoteur d'essai clinique",
}

# ---------------------------------------------------------------------------
# 2. Profils RÉGULATEUR (DPML / IGSPL), avec niveau de responsabilité
# ---------------------------------------------------------------------------
ROLES_REGULATEUR = {
    "evaluateur_amm": "Évaluateur AMM",
    "agent_vigilance": "Agent de pharmacovigilance",
    "inspecteur_igspl": "Inspecteur IGSPL",
    "agent_licences": "Agent Licences",
    "agent_laboratoire": "Agent Laboratoire national de contrôle",
    "agent_surveillance_marche": "Agent Surveillance du marché",
    "agent_dros": "Agent DROS (essais cliniques)",
    "responsable_qualite_labo": "Responsable Qualité Laboratoire",
    # Approbation des recettes. Séparé de l'instruction par principe : celui qui
    # constate l'encaissement ne doit pas être celui qui instruit le dossier.
    "responsable_financier": "Responsable financier (approbation des recettes)",
    "cadre_dpml": "Cadre DPML",
    "evaluateur_interne": "Évaluateur interne",
    "membre_commission_specialisee": "Membre de commission spécialisée",
    "membre_commission_nationale": "Membre de la commission nationale",
    "chef_bureau": "Chef de bureau (recevabilité et attribution)",
    "chef_service_amm": "Chef de service Homologation",
    "chef_service_licences": "Chef de service Licences et Établissements",
    "chef_service_inspection": "Chef de service Inspection",
    "chef_service_labo": "Chef de service Laboratoire et Contrôle qualité",
    "sous_directeur_medicament": "Sous-directeur du Médicament",
    "sous_directeur_etablissements": "Sous-directeur des Établissements",
    "directeur_dpml": "Directeur DPML",
    # L'agence du médicament, appelée à succéder à la direction, est dirigée par
    # un directeur général qui pourra signer l'AMM en lieu et place du ministre.
    "directeur_general_agence": "Directeur général de l'Agence du Médicament",
    # Contrôle d'intégrité transversal : lecture sur tout, audit trail complet.
    "inspecteur_general": "Inspecteur général (Pharmacie / Services médicaux)",
    # Signataires du ministère : l'AMM est signée par le ministre de la Santé.
    "secretaire_general_ms": "Secrétaire général du Ministère de la Santé",
    "ministre_sante": "Ministre de la Santé publique",
    "administrateur_dpml": "Administrateur DPML",
}

NIVEAU_PAR_ROLE = {
    # Externes : aucun pouvoir d'instruction
    "usager": 0,
    "demandeur_externe": 0,
    "laboratoire_prive": 0,
    "fabricant": 0,
    "grossiste": 0,
    "pharmacien": 0,
    "promoteur_essai": 0,
    # Niveau 1 — instruction
    "cadre_dpml": 1,
    "evaluateur_amm": 1,
    "evaluateur_interne": 1,
    "membre_commission_specialisee": 1,
    "membre_commission_nationale": 1,
    "agent_vigilance": 1,
    "inspecteur_igspl": 1,
    "agent_licences": 1,
    "agent_laboratoire": 1,
    "agent_surveillance_marche": 1,
    "agent_dros": 1,
    # Niveau 2 — chef de bureau : recevabilité administrative et attribution
    "chef_bureau": 2,
    # Niveau 3 — chefs de service : arbitrage technique, validation de la LoQ
    "responsable_qualite_labo": 3,
    "responsable_financier": 3,
    "chef_service_amm": 3,
    "chef_service_licences": 3,
    "chef_service_inspection": 3,
    "chef_service_labo": 3,
    # Niveau 4 — sous-direction : cohérence et supervision
    "sous_directeur_medicament": 4,
    "sous_directeur_etablissements": 4,
    # Niveau 5 — direction
    "directeur_dpml": 5,
    # Niveau 6 — inspection générale : audit et contrôle d'intégrité
    "inspecteur_general": 6,
    # Niveau 7 — secrétariat général et direction générale de l'agence
    "directeur_general_agence": 7,
    "secretaire_general_ms": 7,
    # Niveau 8 — ministre : signature des actes
    "ministre_sante": 8,
    # Administration du système : droits techniques, pas un échelon hiérarchique
    "administrateur_dpml": 5,
}

LIBELLE_NIVEAU = {
    0: "Externe",
    1: "Cadre — évaluateur / instructeur scientifique",
    2: "Chef de bureau",
    3: "Chef de service",
    4: "Sous-direction",
    5: "Direction",
    6: "Inspection générale",
    7: "Secrétariat général",
    8: "Ministre",
}

ROLES_ACTIFS = {**ROLES_EXTERNES, **ROLES_REGULATEUR}
ROLES_INERTES = {}
ROLES = {**ROLES_ACTIFS, **ROLES_INERTES}


def est_externe(role):
    return role in ROLES_EXTERNES


def est_regulateur(role):
    return role in ROLES_REGULATEUR


def niveau(user_ou_role):
    """Niveau de responsabilité (0 = externe). Accepte un utilisateur ou un code rôle."""
    if user_ou_role is None:
        return 0
    role = getattr(user_ou_role, "role_systeme", user_ou_role)
    return NIVEAU_PAR_ROLE.get(role, 0)


def a_niveau(user, minimum):
    """L'utilisateur dispose-t-il au moins du niveau de responsabilité requis ?"""
    return niveau(user) >= minimum


# ---------------------------------------------------------------------------
# 3. Permissions transverses (hors machine à états)
# ---------------------------------------------------------------------------
# Profils externes autorisés à déposer une demande d'AMM : les industriels et
# titulaires. Un grossiste, un pharmacien ou un usager n'en déposent pas.
_DEPOSANTS_AMM = ["demandeur_externe", "administrateur_dpml"]

PERMISSIONS_TRANSVERSES = {
    "gerer_utilisateurs": ["administrateur_dpml"],
    "gerer_referentiels": ["administrateur_dpml"],
    "creer_dossier_ma": _DEPOSANTS_AMM,
    "voir_tous_dossiers_ma": ["administrateur_dpml", "evaluateur_amm", "chef_service_amm",
                              "directeur_dpml"],
    "voir_tous_cas_vigilance": ["administrateur_dpml", "agent_vigilance", "directeur_dpml"],
    "traiter_cas_vigilance": ["agent_vigilance"],
    # Tout professionnel de santé et tout usager peut notifier un effet indésirable :
    # c'est un objectif de santé publique, pas un privilège administratif.
    "declarer_effet_indesirable": ["usager", "pharmacien", "grossiste", "laboratoire_prive",
                                   "fabricant", "demandeur_externe", "promoteur_essai",
                                   "agent_vigilance", "administrateur_dpml"],
    "planifier_inspection": ["administrateur_dpml"],
    "voir_toutes_inspections": ["administrateur_dpml", "inspecteur_igspl", "directeur_dpml"],
    "suspendre_etablissement": ["directeur_dpml"],
    "voir_toutes_licences": ["administrateur_dpml", "agent_licences", "directeur_dpml"],
    "instruire_licence": ["agent_licences"],
    # Une demande de licence est déposée par l'établissement concerné.
    "demander_licence": ["demandeur_externe", "fabricant", "grossiste",
                         "pharmacien", "laboratoire_prive",
                         "administrateur_dpml"],
    "voir_tous_echantillons": ["administrateur_dpml", "agent_laboratoire",
                               "responsable_qualite_labo"],
    # Une analyse de laboratoire peut être sollicitée par un opérateur privé.
    "demander_analyse": ["laboratoire_prive", "demandeur_externe", "grossiste", "pharmacien",
                         "administrateur_dpml"],
    "voir_tous_signalements": ["administrateur_dpml", "agent_surveillance_marche",
                               "directeur_dpml"],
    # Signaler un produit suspect est ouvert largement (marché, officine, public).
    "signaler_produit": ["usager", "pharmacien", "grossiste", "laboratoire_prive",
                         "fabricant", "demandeur_externe",
                         "agent_surveillance_marche", "administrateur_dpml"],
    "voir_tous_protocoles": ["administrateur_dpml", "agent_dros", "directeur_dpml"],
    "deposer_essai_clinique": ["promoteur_essai", "administrateur_dpml"],
    "voir_toutes_liberations": ["administrateur_dpml", "agent_laboratoire",
                                "responsable_qualite_labo", "directeur_dpml"],
    # Paiements — SÉPARATION DES TÂCHES. Deux permissions distinctes :
    #   * `gerer_paiements` : exploitation de la plateforme (émettre une créance,
    #     assister un redevable, consulter la console). Ouverte à l'administration.
    #   * `confirmer_paiement` : APPROBATION de la recette, c'est-à-dire
    #     l'attestation que l'argent est entré. Réservée au responsable
    #     financier. Ni l'administrateur système, ni le directeur qui décidera
    #     du dossier ne l'exercent : constater la recette et instruire la
    #     demande sont deux mains différentes.
    "gerer_paiements": ["responsable_financier", "administrateur_dpml"],
    "confirmer_paiement": ["responsable_financier"],
    # Reliance régionale CEEAC
    "consulter_reliance": ["administrateur_dpml", "evaluateur_amm", "chef_service_amm",
                           "directeur_dpml", "agent_vigilance", "agent_surveillance_marche"],
    "gerer_reliance": ["administrateur_dpml", "directeur_dpml", "chef_service_amm"],
}


# ---------------------------------------------------------------------------
# 4. Permissions de CONSULTATION ouvertes par le niveau hiérarchique
# ---------------------------------------------------------------------------
# Les listes ci-dessus énumèrent des métiers ; elles ont été écrites avant que
# la hiérarchie à huit niveaux n'existe. Résultat observé en éprouvant les
# comptes : un évaluateur consultait la reliance régionale quand le directeur
# général, l'inspecteur général et le ministre en étaient exclus — l'inverse de
# la règle voulue.
#
# On corrige par le niveau plutôt qu'en rallongeant les listes. Le seuil est
# le chef de bureau (2) et non le chef de service : chacune de ces consultations
# est déjà ouverte nominativement à un cadre de niveau 1, et il serait absurde
# que le chef de bureau qui l'encadre en soit privé. La monotonie — un supérieur
# voit au moins ce que voit son subordonné — est vérifiée par test_acces_profils.
#
# Les actes ENGAGEANTS (instruire, suspendre, confirmer un paiement, gérer la
# reliance) gardent leur liste nominative : ils relèvent d'une attribution, pas
# d'un rang. Aucun niveau, si élevé soit-il, ne les confère.
NIVEAU_MINIMAL_CONSULTATION = {
    "voir_tous_dossiers_ma": 2,
    "voir_tous_cas_vigilance": 2,
    "voir_toutes_inspections": 2,
    "voir_toutes_licences": 2,
    "voir_tous_echantillons": 2,
    "voir_tous_signalements": 2,
    "voir_tous_protocoles": 2,
    "voir_toutes_liberations": 2,
    "consulter_reliance": 2,
}


def a_permission(user, cle_permission):
    """La permission est acquise par attribution métier OU par rang hiérarchique.

    Le rang n'ouvre que la consultation : aucun niveau, si élevé soit-il, ne
    confère à lui seul le droit d'instruire ou de décider à la place du service
    compétent.
    """
    if user is None:
        return False
    if user.role_systeme in PERMISSIONS_TRANSVERSES.get(cle_permission, []):
        return True
    minimum = NIVEAU_MINIMAL_CONSULTATION.get(cle_permission)
    return minimum is not None and a_niveau(user, minimum)
