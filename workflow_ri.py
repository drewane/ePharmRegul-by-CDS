"""
Moteur de workflow — Module RI (Inspection réglementaire), 13-RI-inspection.md.

Même règle de codage que les autres modules : seule cette couche change
`Inspection.statut` ou `Etablissement.statut_licence`, chaque fonction vérifie
statut + rôle côté serveur et appelle enregistrer_audit() avant tout commit().

Note sur la synchronisation (§3, étape 3) : la mise à jour de la grille reçue
depuis le client hors-ligne N'EST PAS un changement de statut — c'est un
mécanisme technique, conformément au spec ("le statut ne change pas du fait de
la synchronisation elle-même"). Elle est néanmoins auditée (traçabilité), avec
ancien_statut = nouveau_statut pour le signaler comme non-transitionnel.
"""
from datetime import date, datetime

from models import db, Inspection, Etablissement
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from grille_ri import grille_initiale, items_non_repondus, calculer_score

STATUTS = {
    "planifiee": "Planifiée",
    "en_cours": "En cours",
    "rapport_redige": "Rapport rédigé",
    "conforme": "Conforme",
    "non_conforme": "Non conforme",
    "plan_action_en_cours": "Plan d'action en cours",
    "suivi_programme": "Suivi programmé",
    "cloturee": "Clôturée",
}

STATUTS_FINAUX = {"conforme", "cloturee", "suivi_programme"}

TYPES = {
    "routine": "Routine (programme annuel)",
    "suivi_plainte": "Suivi de plainte",
    "suivi_non_conformite": "Suivi de non-conformité",
    "declenchee_signalement": "Déclenchée par un signalement",
}

ROLE_PAR_STATUT = {
    "planifiee": ["inspecteur_igspl"],
    "en_cours": ["inspecteur_igspl"],
    "rapport_redige": ["inspecteur_igspl", "administrateur_dpml"],
    "non_conforme": ["inspecteur_igspl", "administrateur_dpml"],
    "plan_action_en_cours": ["administrateur_dpml"],
}


def peut_agir(inspection, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(inspection.statut, [])


def planifier(etablissement, inspecteur, acteur, type_insp="routine", date_planifiee=None):
    if acteur.role_systeme != "administrateur_dpml":
        raise ErreurWorkflow("Rôle non autorisé pour planifier une inspection.")
    if inspecteur.role_systeme != "inspecteur_igspl":
        raise ErreurWorkflow("L'inspection doit être affectée à un compte inspecteur IGSPL.")
    from numerotation import generer_numero
    insp = Inspection(
        numero=generer_numero("INS"), etablissement_id=etablissement.id, inspecteur_id=inspecteur.id,
        type=type_insp, date_planifiee=date_planifiee, statut="planifiee",
    )
    insp.grille = grille_initiale()
    db.session.add(insp)
    db.session.flush()
    enregistrer_creation(insp, acteur, f"Inspection planifiée ({TYPES.get(type_insp, type_insp)})")
    notifier(inspecteur, "inspection_planifiee",
             f"Inspection {insp.numero} planifiée chez {etablissement.raison_sociale}.",
             lien=f"/inspections/{insp.id}")
    # Redevance d'inspection : nulle par défaut (paramètre RI/frais_inspection_xaf).
    # Tant qu'elle vaut 0, aucune créance n'est créée et l'établissement n'est
    # pas sollicité — la facturation s'active par simple paramétrage.
    from paiements import _demandeur, exiger_paiement
    paiement = exiger_paiement(insp, [], f"/inspections/{insp.id}",
                               f"l'inspection {insp.numero}")
    if paiement is not None:
        redevable = _demandeur(paiement)
        if redevable is not None:
            notifier(redevable, "paiement_attendu",
                     f"Frais de {paiement.montant} {paiement.devise} à régler pour "
                     f"l'inspection {insp.numero} ({paiement.numero}).",
                     lien=f"/inspections/{insp.id}")
    return insp


def demarrer(inspection, acteur):
    if inspection.statut != "planifiee":
        raise ErreurWorkflow("Seule une inspection planifiée peut être démarrée.")
    if acteur.id != inspection.inspecteur_id:
        raise ErreurWorkflow("Seul l'inspecteur affecté peut démarrer cette inspection.")
    ancien = inspection.statut
    inspection.statut = "en_cours"
    inspection.date_realisee = datetime.utcnow()
    enregistrer_audit(inspection, "Inspection démarrée sur site", acteur, ancien, inspection.statut)


def synchroniser_grille(inspection, acteur, grille):
    """Mécanisme technique (pas une transition métier) — voir note en tête de module."""
    if inspection.statut != "en_cours":
        raise ErreurWorkflow("La grille ne peut être synchronisée que sur une inspection en cours.")
    if acteur.id != inspection.inspecteur_id:
        raise ErreurWorkflow("Seul l'inspecteur affecté peut synchroniser cette inspection.")
    inspection.grille = grille
    enregistrer_audit(inspection, "Synchronisation de la grille de contrôle (saisie de terrain)",
                       acteur, inspection.statut, inspection.statut)


def cloturer_visite(inspection, acteur, grille, confirmation_items_manquants=False):
    """en_cours → rapport_redige. Un item non renseigné doit être explicitement signalé
    avant que l'inspecteur puisse clôturer (critère d'acceptation RI) — jamais une
    clôture silencieuse avec des champs vides."""
    if inspection.statut != "en_cours":
        raise ErreurWorkflow("Seule une inspection en cours peut être clôturée.")
    if acteur.id != inspection.inspecteur_id:
        raise ErreurWorkflow("Seul l'inspecteur affecté peut clôturer cette visite.")
    manquants = items_non_repondus(grille)
    if manquants and not confirmation_items_manquants:
        raise ErreurWorkflow(
            f"{len(manquants)} élément(s) de la grille ne sont pas renseignés. "
            "Complétez-les ou confirmez explicitement la clôture malgré ces éléments manquants."
        )
    inspection.grille = grille
    inspection.score_conformite = calculer_score(grille)
    if not inspection.date_realisee:
        inspection.date_realisee = datetime.utcnow()
    ancien = inspection.statut
    inspection.statut = "rapport_redige"
    commentaire = (f"{len(manquants)} élément(s) non répondu(s), clôture confirmée malgré tout."
                   if manquants else None)
    enregistrer_audit(inspection, f"Visite clôturée, rapport rédigé (score : {inspection.score_conformite}"
                       f"{'%' if inspection.score_conformite is not None else ''})",
                       acteur, ancien, inspection.statut, commentaire=commentaire)
    notifier_tous("administrateur_dpml", "ri_rapport_redige",
                  f"Rapport rédigé pour l'inspection {inspection.numero} — décision de conformité à prendre.",
                  lien=f"/inspections/{inspection.id}")


def decider_conformite(inspection, acteur, decision, non_conforme_grave=False):
    """rapport_redige → conforme | non_conforme. Le score calculé est une aide à la
    décision (règle de gestion RI) : la décision reste un acte explicite, jamais une
    bascule automatique à partir du seul score."""
    if inspection.statut != "rapport_redige":
        raise ErreurWorkflow("Une décision de conformité ne peut être prise qu'après rédaction du rapport.")
    if acteur.role_systeme not in ("inspecteur_igspl", "administrateur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette décision.")

    ancien = inspection.statut
    if decision == "conforme":
        inspection.statut = "conforme"
        enregistrer_audit(inspection, "Inspection déclarée conforme", acteur, ancien, inspection.statut)
    elif decision == "non_conforme":
        inspection.statut = "non_conforme"
        inspection.non_conformite_grave = bool(non_conforme_grave)
        enregistrer_audit(inspection, "Inspection déclarée non conforme", acteur, ancien, inspection.statut)
        # Point d'extension documenté : notification destinée au futur module MC
        # (surveillance du marché), non livré ici — adressée à administrateur_dpml.
        notifier_tous("administrateur_dpml", "ri_non_conforme",
                      f"Inspection {inspection.numero} non conforme chez "
                      f"{inspection.etablissement.raison_sociale} (module MC non livré : suivi à assurer manuellement).",
                      lien=f"/inspections/{inspection.id}")
        if non_conforme_grave:
            # L'inspecteur ne décide jamais seul d'une suspension — recommandation
            # transmise au directeur, exécutée (si validée) dans un futur module LI.
            notifier_tous("directeur_dpml", "ri_proposition_suspension",
                          f"Non-conformité grave lors de l'inspection {inspection.numero} chez "
                          f"{inspection.etablissement.raison_sociale} : suspension de licence proposée.",
                          lien=f"/inspections/{inspection.id}")
    else:
        raise ErreurWorkflow("Décision de conformité inconnue.")


def soumettre_plan_action(inspection, acteur, plan_action, date_echeance):
    if inspection.statut != "non_conforme":
        raise ErreurWorkflow("Un plan d'action ne peut être soumis que sur une inspection non conforme.")
    if acteur.role_systeme not in ("inspecteur_igspl", "administrateur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if not plan_action or not plan_action.strip():
        raise ErreurWorkflow("Le plan d'action correctif est obligatoire pour une inspection non conforme.")
    if not date_echeance:
        raise ErreurWorkflow("La date d'échéance du plan d'action est obligatoire.")
    ancien = inspection.statut
    inspection.plan_action = plan_action.strip()
    inspection.date_echeance_plan_action = date_echeance
    inspection.statut = "plan_action_en_cours"
    enregistrer_audit(inspection, "Plan d'action correctif enregistré", acteur, ancien, inspection.statut,
                       commentaire=plan_action)


def cloturer_plan_action(inspection, acteur):
    if inspection.statut != "plan_action_en_cours":
        raise ErreurWorkflow("Seule une inspection avec un plan d'action en cours peut être clôturée à ce titre.")
    if acteur.role_systeme != "administrateur_dpml":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = inspection.statut
    inspection.statut = "cloturee"
    enregistrer_audit(inspection, "Plan d'action jugé suffisant, inspection clôturée", acteur, ancien, inspection.statut)


def initier_suivi(inspection, acteur, inspecteur):
    """Empêche une clôture précipitée : au lieu de clore directement, planifie une
    inspection de suivi lorsque les preuves de correction ne sont pas jugées suffisantes."""
    if inspection.statut != "plan_action_en_cours":
        raise ErreurWorkflow("Un suivi ne peut être programmé que depuis un plan d'action en cours.")
    if acteur.role_systeme != "administrateur_dpml":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = inspection.statut
    inspection.statut = "suivi_programme"
    enregistrer_audit(inspection, "Inspection de suivi programmée", acteur, ancien, inspection.statut)

    nouvelle = planifier(inspection.etablissement, inspecteur, acteur, type_insp="suivi_non_conformite")
    nouvelle.inspection_precedente_id = inspection.id
    return nouvelle


# NOTE : la suspension/réactivation d'un établissement a été implémentée ici comme
# solution provisoire tant que le module LI n'était pas livré. Elle vit désormais
# dans workflow_li.py (suspendre/lever_suspension/revoquer), qui reçoit une référence
# croisée vers l'inspection à l'origine de la recommandation — voir routes_li.py.
# La règle « l'inspecteur ne décide jamais seul » reste garantie de la même façon :
# ces fonctions exigent toutes acteur.role_systeme == "directeur_dpml".
