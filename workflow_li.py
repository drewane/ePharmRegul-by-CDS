"""
Moteur de workflow — Module LI (Licences établissements), 14-LI-licences-etablissements.md.

Deux machines à états imbriquées, comme le spec les distingue :
- `DemandeLicence.statut` (deposee → en_instruction → approuvee|refusee) : le cycle
  d'instruction d'UNE demande.
- `Etablissement.statut_licence` (en_instruction → active → suspendue|expiree →
  revoquee|active) : l'état de licence COURANT de l'établissement, qui survit aux
  demandes individuelles (§4 du spec — c'est explicitement la machine à états de ce
  champ, pas de la demande).

Même règle de codage que les autres modules : seule cette couche change ces deux
champs, chaque fonction vérifie statut + rôle côté serveur et appelle
enregistrer_audit() avant tout commit(). Toute suspension conserve une référence
croisée vers son évènement déclencheur (inspection ou signalement), consultable
depuis la fiche établissement (critère d'acceptation LI).
"""
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from models import db, DemandeLicence, Etablissement, Personne
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier
from erreurs import ErreurWorkflow
from delais import get_parametre
from paiements import creer_paiement

STATUTS_DEMANDE = {
    "deposee": "Déposée",
    "en_instruction": "En instruction",
    "approuvee": "Approuvée",
    "refusee": "Refusée",
}

STATUTS_DEMANDE_FINAUX = {"approuvee", "refusee"}

STATUTS_LICENCE = {
    "en_instruction": "En instruction",
    "active": "Active",
    "suspendue": "Suspendue",
    "expiree": "Expirée",
    "refusee": "Refusée",
    "revoquee": "Révoquée",
}

TYPES_DEMANDE = {"nouvelle": "Nouvelle demande", "renouvellement": "Renouvellement"}


def _destinataires_etablissement(etablissement):
    return Personne.query.filter_by(etablissement_rattachement_id=etablissement.id,
                                     role_systeme="demandeur_externe").all()


def deposer_demande(etablissement, acteur, type_demande="nouvelle", pieces_justificatives=""):
    actif = (
        DemandeLicence.query.filter_by(etablissement_id=etablissement.id)
        .filter(DemandeLicence.statut.notin_(STATUTS_DEMANDE_FINAUX)).first()
    )
    if actif:
        raise ErreurWorkflow(
            f"Une demande de licence ({actif.numero}) est déjà en cours pour cet établissement."
        )
    if etablissement.statut_licence in ("suspendue", "revoquee"):
        raise ErreurWorkflow(
            "Un établissement suspendu ou révoqué ne peut pas déposer de demande de licence "
            "tant que sa situation n'a pas été régularisée."
        )

    from numerotation import generer_numero
    demande = DemandeLicence(numero=generer_numero("LIC"), etablissement_id=etablissement.id,
                              type_demande=type_demande, pieces_justificatives=pieces_justificatives,
                              statut="deposee")
    db.session.add(demande)
    db.session.flush()
    enregistrer_creation(demande, acteur, f"Dépôt d'une demande de licence ({TYPES_DEMANDE.get(type_demande, type_demande)})")

    ancien = etablissement.statut_licence
    etablissement.statut_licence = "en_instruction"
    enregistrer_audit(etablissement, "Établissement placé en instruction (nouvelle demande de licence)",
                       acteur, ancien, etablissement.statut_licence)

    destinataires = _destinataires_etablissement(etablissement)
    for dest in destinataires:
        notifier(dest, "li_demande_deposee",
                 f"Votre demande de licence {demande.numero} a été déposée avec succès.",
                 lien=f"/licences/{demande.id}")
    # Redevance de licence — montant tiré du barème, notification aux redevables.
    from paiements import exiger_paiement
    exiger_paiement(demande, destinataires, f"/licences/{demande.id}",
                    f"la demande de licence {demande.numero}")
    return demande


def instruire(demande, acteur):
    if demande.statut != "deposee":
        raise ErreurWorkflow("Seule une demande déposée peut être mise en instruction.")
    if acteur.role_systeme != "agent_licences":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = demande.statut
    demande.statut = "en_instruction"
    enregistrer_audit(demande, "Demande mise en instruction", acteur, ancien, demande.statut)


def decider(demande, acteur, decision, motif=None):
    if demande.statut != "en_instruction":
        raise ErreurWorkflow("Une décision ne peut être prise que sur une demande en instruction.")
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut octroyer ou refuser une licence.")

    etab = demande.etablissement
    ancien_demande = demande.statut
    ancien_etab = etab.statut_licence
    if decision == "approuve":
        demande.statut = "approuvee"
        demande.date_decision = datetime.utcnow()
        annees = int(get_parametre("LI", "duree_validite_licence_annees", default=3))
        etab.statut_licence = "active"
        etab.date_expiration_licence = date.today() + relativedelta(years=annees)
        enregistrer_audit(demande, "Demande approuvée", acteur, ancien_demande, demande.statut)
        enregistrer_audit(etab, "Licence octroyée", acteur, ancien_etab, etab.statut_licence,
                           commentaire=f"Valide jusqu'au {etab.date_expiration_licence.strftime('%d/%m/%Y')}")
        for dest in _destinataires_etablissement(etab):
            notifier(dest, "li_decision",
                     f"Licence octroyée pour {etab.raison_sociale}, valide jusqu'au "
                     f"{etab.date_expiration_licence.strftime('%d/%m/%Y')}.", lien=f"/etablissements/{etab.id}")
    elif decision == "refuse":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour refuser une demande de licence.")
        demande.statut = "refusee"
        demande.motif_decision = motif.strip()
        demande.date_decision = datetime.utcnow()
        etab.statut_licence = "refusee"
        enregistrer_audit(demande, "Demande refusée", acteur, ancien_demande, demande.statut, commentaire=motif)
        enregistrer_audit(etab, "Licence refusée", acteur, ancien_etab, etab.statut_licence, commentaire=motif)
        for dest in _destinataires_etablissement(etab):
            notifier(dest, "li_decision", f"Demande de licence refusée pour {etab.raison_sociale} : {motif}",
                     lien=f"/etablissements/{etab.id}")
    else:
        raise ErreurWorkflow("Décision inconnue.")


def suspendre(etablissement, acteur, motif, origine_type=None, origine_id=None, origine_numero=None):
    """origine_* : référence croisée vers l'évènement déclencheur (ex. Inspection du
    module RI, ou futur SignalementQualite du module MC), conservée dans le commentaire
    d'audit pour rester consultable lors d'un contrôle ultérieur (critère d'acceptation)."""
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut suspendre une licence d'établissement.")
    if etablissement.statut_licence != "active":
        raise ErreurWorkflow("Seul un établissement dont la licence est active peut être suspendu.")
    if not motif or not motif.strip():
        raise ErreurWorkflow("Un motif est obligatoire pour suspendre un établissement.")

    ancien = etablissement.statut_licence
    etablissement.statut_licence = "suspendue"
    commentaire = motif.strip()
    if origine_type and origine_numero:
        commentaire += f" (référence : {origine_type} {origine_numero})"
    enregistrer_audit(etablissement, "Licence suspendue", acteur, ancien, etablissement.statut_licence,
                       commentaire=commentaire)
    for dest in _destinataires_etablissement(etablissement):
        notifier(dest, "li_suspension", f"La licence de {etablissement.raison_sociale} a été suspendue : {motif}",
                 lien=f"/etablissements/{etablissement.id}")
    if etablissement.pharmacien_responsable:
        notifier(etablissement.pharmacien_responsable, "li_suspension",
                 f"La licence de {etablissement.raison_sociale} a été suspendue : {motif}")


def lever_suspension(etablissement, acteur):
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut lever une suspension de licence.")
    if etablissement.statut_licence != "suspendue":
        raise ErreurWorkflow("Cet établissement n'est pas suspendu.")
    ancien = etablissement.statut_licence
    etablissement.statut_licence = "active"
    enregistrer_audit(etablissement, "Suspension de licence levée", acteur, ancien, etablissement.statut_licence)


def revoquer(etablissement, acteur, motif):
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut révoquer une licence.")
    if etablissement.statut_licence != "suspendue":
        raise ErreurWorkflow("Seul un établissement suspendu peut être révoqué.")
    if not motif or not motif.strip():
        raise ErreurWorkflow("Un motif est obligatoire pour révoquer une licence.")
    ancien = etablissement.statut_licence
    etablissement.statut_licence = "revoquee"
    enregistrer_audit(etablissement, "Licence révoquée (retrait définitif)", acteur, ancien,
                       etablissement.statut_licence, commentaire=motif)


def expirer_si_echue(etablissement):
    """Action système (acteur=None) — appelée par delais.executer_verifications_delais_li().
    Sans renouvellement engagé (i.e. sans nouvelle DemandeLicence active), une licence
    active passe automatiquement à expirée à la date d'échéance (critère d'acceptation LI #1)."""
    if etablissement.statut_licence != "active" or not etablissement.date_expiration_licence:
        return False
    if date.today() <= etablissement.date_expiration_licence:
        return False
    demande_en_cours = DemandeLicence.query.filter_by(
        etablissement_id=etablissement.id, type_demande="renouvellement"
    ).filter(DemandeLicence.statut.notin_(STATUTS_DEMANDE_FINAUX)).first()
    if demande_en_cours:
        return False
    ancien = etablissement.statut_licence
    etablissement.statut_licence = "expiree"
    enregistrer_audit(etablissement, "Licence expirée automatiquement (échéance dépassée sans renouvellement)",
                       None, ancien, etablissement.statut_licence)
    for dest in _destinataires_etablissement(etablissement):
        notifier(dest, "li_expiree", f"La licence de {etablissement.raison_sociale} a expiré.",
                 lien=f"/etablissements/{etablissement.id}")
    return True
