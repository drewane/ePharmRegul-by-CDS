"""
Moteur de workflow — Visas techniques : autorisation technique d'importation
délivrée pour un produit déjà titulaire d'une AMM active, distincte de l'AMM
elle-même (une AMM autorise le produit sur le marché ; un visa technique
autorise une opération d'importation précise de ce produit).

Même règle de codage que les autres modules : seule cette couche change
VisaTechnique.statut ; chaque fonction vérifie statut/rôle côté serveur et
journalise l'audit avant tout commit().
"""
from datetime import datetime

from models import db, VisaTechnique, DossierAMM
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from numerotation import generer_numero

STATUTS = {
    "demande": "Demandé",
    "delivre": "Délivré",
    "refuse": "Refusé",
}
STATUTS_FINAUX = {"delivre", "refuse"}


def _demandeur_est_titulaire(demandeur, produit):
    return DossierAMM.query.filter_by(produit_id=produit.id, demandeur_id=demandeur.id).first() is not None


def demander(demandeur, produit, description):
    if produit.statut_amm_courant != "active":
        raise ErreurWorkflow(
            "Un visa technique ne peut être demandé que pour un produit dont l'AMM est active."
        )
    if not _demandeur_est_titulaire(demandeur, produit):
        raise ErreurWorkflow("Vous n'êtes pas identifié comme demandeur d'un dossier pour ce produit.")
    visa = VisaTechnique(numero=generer_numero("VIS"), produit_id=produit.id, demandeur_id=demandeur.id,
                          description=(description or "").strip() or None, statut="demande")
    db.session.add(visa)
    db.session.flush()
    enregistrer_creation(visa, demandeur, "Demande de visa technique")
    notifier_tous("administrateur_dpml", "visa_a_traiter",
                  f"Nouvelle demande de visa technique {visa.numero} à traiter.", lien=f"/visas/{visa.id}")
    return visa


def decider(visa, acteur, decision, motif=None):
    if visa.statut != "demande":
        raise ErreurWorkflow("Une décision ne peut être prise que sur une demande de visa non encore traitée.")
    if acteur.role_systeme != "administrateur_dpml":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = visa.statut
    if decision == "delivre":
        visa.statut = "delivre"
        visa.date_decision = datetime.utcnow()
        enregistrer_audit(visa, "Visa technique délivré", acteur, ancien, visa.statut, commentaire=motif)
        notifier(visa.demandeur, "visa_decision",
                 f"Visa technique {visa.numero} délivré pour {visa.produit.libelle}.", lien=f"/visas/{visa.id}")
    elif decision == "refuse":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour refuser un visa technique.")
        visa.statut = "refuse"
        visa.motif_decision = motif.strip()
        visa.date_decision = datetime.utcnow()
        enregistrer_audit(visa, "Visa technique refusé", acteur, ancien, visa.statut, commentaire=motif)
        notifier(visa.demandeur, "visa_decision",
                 f"Visa technique {visa.numero} refusé : {motif}", lien=f"/visas/{visa.id}")
    else:
        raise ErreurWorkflow("Décision inconnue.")
