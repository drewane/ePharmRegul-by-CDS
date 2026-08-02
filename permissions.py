"""
Rôles système et permissions transversales (02-regles-transversales.md, section 1).

DÉCISION ASSUMÉE (documentée dans README.md) : la matrice est centralisée ici, en
code Python, plutôt que dans une table configurable en base — jugé disproportionné
pour ce périmètre. Point d'extension identifié pour une future livraison : une table
RolePermission éditable par administrateur_dpml sans redéploiement.

La correspondance statut → action → rôle spécifique au circuit MA reste dans
workflow_ma.py (colocalisée avec la machine à états, seule source de vérité pour ce
sujet). Ce module ne contient que les rôles et les permissions "transverses"
(hors machine à états).
"""

# Rôles actifs dans cette livraison (modules MA + VL + RI + LI + LT + administration ;
# agent_surveillance_marche et agent_dros sont activés par anticipation des modules
# MC et CT, livrés dans la foulée dans cette même session).
ROLES_ACTIFS = {
    "administrateur_dpml": "Administrateur DPML",
    "evaluateur_amm": "Évaluateur AMM",
    "directeur_dpml": "Directeur DPML",
    "demandeur_externe": "Demandeur externe",
    "agent_vigilance": "Agent de pharmacovigilance",
    "inspecteur_igspl": "Inspecteur IGSPL",
    "agent_licences": "Agent Licences",
    "agent_laboratoire": "Agent Laboratoire de contrôle",
    "responsable_qualite_labo": "Responsable Qualité Laboratoire",
    "agent_surveillance_marche": "Agent Surveillance du marché",
    "agent_dros": "Agent DROS",
}

# Plus aucun rôle du cahier des charges n'est inerte à ce stade de la livraison —
# dictionnaire conservé pour la structure (et pour un futur rôle éventuel).
ROLES_INERTES = {}

ROLES = {**ROLES_ACTIFS, **ROLES_INERTES}

PERMISSIONS_TRANSVERSES = {
    "gerer_utilisateurs": ["administrateur_dpml"],
    "gerer_referentiels": ["administrateur_dpml"],
    "creer_dossier_ma": ["demandeur_externe", "administrateur_dpml"],
    "voir_tous_dossiers_ma": ["administrateur_dpml", "evaluateur_amm", "directeur_dpml"],
    "voir_tous_cas_vigilance": ["administrateur_dpml", "agent_vigilance", "directeur_dpml"],
    "traiter_cas_vigilance": ["agent_vigilance"],
    "planifier_inspection": ["administrateur_dpml"],
    "voir_toutes_inspections": ["administrateur_dpml", "inspecteur_igspl", "directeur_dpml"],
    "suspendre_etablissement": ["directeur_dpml"],
    "voir_toutes_licences": ["administrateur_dpml", "agent_licences", "directeur_dpml"],
    "instruire_licence": ["agent_licences"],
    "voir_tous_echantillons": ["administrateur_dpml", "agent_laboratoire", "responsable_qualite_labo"],
    "voir_tous_signalements": ["administrateur_dpml", "agent_surveillance_marche", "directeur_dpml"],
    "voir_tous_protocoles": ["administrateur_dpml", "agent_dros", "directeur_dpml"],
    "voir_toutes_liberations": ["administrateur_dpml", "agent_laboratoire", "responsable_qualite_labo",
                                 "directeur_dpml"],
}


def a_permission(user, cle_permission):
    if user is None:
        return False
    return user.role_systeme in PERMISSIONS_TRANSVERSES.get(cle_permission, [])
