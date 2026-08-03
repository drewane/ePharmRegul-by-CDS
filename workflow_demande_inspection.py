"""
Demande d'inspection sollicitée par un industriel.

Un titulaire peut demander la venue de l'autorité sur son site de fabrication,
au Cameroun ou à l'étranger. La DPML statue sur la recevabilité, puis planifie
l'inspection au moyen du module RI existant.
"""
from datetime import datetime

from audit import enregistrer_audit, enregistrer_creation
from erreurs import ErreurWorkflow
from models import DemandeInspection, db
from notifications import notifier, notifier_tous
from numerotation import generer_numero

STATUTS = {
    "soumise": "Soumise",
    "recevable": "Recevable — à planifier",
    "irrecevable": "Irrecevable",
    "planifiee": "Inspection planifiée",
    "realisee": "Inspection réalisée",
    "close": "Close",
}

STATUTS_FINAUX = {"irrecevable", "close"}


def deposer(demandeur, site_nom, site_pays, motif, site_adresse="", site_contact="",
            produits_concernes="", periode_souhaitee=""):
    for champ, valeur in (("nom du site", site_nom), ("pays", site_pays),
                          ("motif", motif)):
        if not (valeur or "").strip():
            raise ErreurWorkflow(f"Le champ « {champ} » est obligatoire.")

    demande = DemandeInspection(
        numero=generer_numero("DIN"), demandeur_id=demandeur.id,
        etablissement_id=demandeur.etablissement_rattachement_id,
        site_nom=site_nom.strip(), site_pays=site_pays.strip(),
        site_adresse=(site_adresse or "").strip() or None,
        site_contact=(site_contact or "").strip() or None,
        motif=motif.strip(),
        produits_concernes=(produits_concernes or "").strip() or None,
        periode_souhaitee=(periode_souhaitee or "").strip() or None,
        statut="soumise")
    db.session.add(demande)
    db.session.flush()

    enregistrer_creation(
        demande, demandeur,
        f"Demande d'inspection déposée — {demande.site_nom} ({demande.site_pays})")

    # Accusé de réception au demandeur : il doit savoir que son dossier est pris en charge.
    notifier(demandeur, "demande_receptionnee",
             f"Votre demande d'inspection {demande.numero} a bien été réceptionnée. "
             f"Elle est en cours d'examen par la DPML.",
             lien=f"/industriel/inspections/{demande.id}")
    for role in ("administrateur_dpml", "inspecteur_igspl"):
        notifier_tous(role, "din_nouvelle_demande",
                      f"Demande d'inspection {demande.numero} — {demande.site_nom} "
                      f"({demande.site_pays})"
                      + (" — site à l'étranger" if demande.a_l_etranger else ""),
                      lien=f"/industriel/inspections/{demande.id}")
    return demande


def statuer_recevabilite(demande, acteur, recevable, motif=None):
    if demande.statut != "soumise":
        raise ErreurWorkflow(
            f"La recevabilité ne s'examine que sur une demande soumise "
            f"(statut actuel : {STATUTS.get(demande.statut, demande.statut)}).")
    if not recevable and not (motif or "").strip():
        raise ErreurWorkflow("Une décision d'irrecevabilité doit être motivée.")

    ancien = demande.statut
    demande.statut = "recevable" if recevable else "irrecevable"
    demande.motif_decision = (motif or "").strip() or None
    demande.date_decision = datetime.utcnow()
    enregistrer_audit(demande,
                      f"Demande d'inspection déclarée {demande.statut}"
                      + (f" : {demande.motif_decision}" if demande.motif_decision else ""),
                      acteur, ancien, demande.statut)
    notifier(demande.demandeur, "din_decision",
             f"Votre demande d'inspection {demande.numero} a été déclarée "
             f"{STATUTS[demande.statut].lower()}.",
             lien=f"/industriel/inspections/{demande.id}")
    return demande


def rattacher_inspection(demande, inspection, acteur):
    """Relie la demande à l'inspection planifiée dans le module RI."""
    if demande.statut != "recevable":
        raise ErreurWorkflow("Seule une demande recevable donne lieu à planification.")
    ancien = demande.statut
    demande.inspection_id = inspection.id
    demande.statut = "planifiee"
    enregistrer_audit(demande,
                      f"Inspection {inspection.numero} planifiée pour cette demande",
                      acteur, ancien, demande.statut)
    notifier(demande.demandeur, "din_planifiee",
             f"Une inspection a été planifiée à la suite de votre demande "
             f"{demande.numero}.", lien=f"/industriel/inspections/{demande.id}")
    return demande
