"""
Moteur de workflow — Demandes de dérogation spéciale : permet à un demandeur
de solliciter une exception motivée à une exigence réglementaire standard
(délai, pièce justificative...) rattachée à un dossier d'AMM en cours.

Même règle de codage que les autres modules : seule cette couche change
DemandeDerogation.statut ; chaque fonction vérifie statut/rôle côté serveur et
journalise l'audit avant tout commit().
"""
from datetime import datetime

from models import db, DemandeDerogation
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from numerotation import generer_numero

STATUTS = {
    "deposee": "Déposée",
    "en_instruction": "En instruction",
    "approuvee": "Approuvée",
    "refusee": "Refusée",
}
STATUTS_FINAUX = {"approuvee", "refusee"}


def deposer(demandeur, objet, motif, dossier_amm=None):
    if not objet or not objet.strip():
        raise ErreurWorkflow("L'objet de la dérogation doit être précisé.")
    if not motif or not motif.strip():
        raise ErreurWorkflow("Un motif détaillé est obligatoire pour une demande de dérogation.")
    d = DemandeDerogation(numero=generer_numero("DER"), demandeur_id=demandeur.id,
                           dossier_amm_id=dossier_amm.id if dossier_amm else None,
                           objet=objet.strip(), motif=motif.strip(), statut="deposee")
    db.session.add(d)
    db.session.flush()
    enregistrer_creation(d, demandeur, "Dépôt d'une demande de dérogation spéciale")
    notifier_tous("administrateur_dpml", "derogation_a_traiter",
                  f"Nouvelle demande de dérogation {d.numero} à instruire.", lien=f"/derogations/{d.id}")
    return d


def instruire(demande, acteur):
    if demande.statut != "deposee":
        raise ErreurWorkflow("Seule une demande déposée peut être mise en instruction.")
    if acteur.role_systeme != "administrateur_dpml":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = demande.statut
    demande.statut = "en_instruction"
    enregistrer_audit(demande, "Demande mise en instruction", acteur, ancien, demande.statut)
    notifier_tous("directeur_dpml", "derogation_a_decider",
                  f"Demande de dérogation {demande.numero} en instruction, décision attendue.",
                  lien=f"/derogations/{demande.id}")


def decider(demande, acteur, decision, motif=None):
    if demande.statut != "en_instruction":
        raise ErreurWorkflow("Une décision ne peut être prise que sur une demande en instruction.")
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut approuver ou refuser une dérogation.")
    ancien = demande.statut
    if decision == "approuve":
        demande.statut = "approuvee"
        demande.date_decision = datetime.utcnow()
        enregistrer_audit(demande, "Dérogation approuvée", acteur, ancien, demande.statut, commentaire=motif)
        notifier(demande.demandeur, "derogation_decision",
                 f"Dérogation {demande.numero} approuvée." + (f" {motif}" if motif else ""),
                 lien=f"/derogations/{demande.id}")
    elif decision == "refuse":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour refuser une dérogation.")
        demande.statut = "refusee"
        demande.motif_decision = motif.strip()
        demande.date_decision = datetime.utcnow()
        enregistrer_audit(demande, "Dérogation refusée", acteur, ancien, demande.statut, commentaire=motif)
        notifier(demande.demandeur, "derogation_decision",
                 f"Dérogation {demande.numero} refusée : {motif}", lien=f"/derogations/{demande.id}")
    else:
        raise ErreurWorkflow("Décision inconnue.")
