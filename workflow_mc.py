"""
Moteur de workflow — Module MC (Surveillance et contrôle du marché), 16-MC.

Même règle de codage que les autres modules : seule cette couche change
`SignalementQualite.statut`, chaque fonction vérifie statut + rôle côté
serveur et appelle enregistrer_audit() avant tout commit(). La liste des
établissements à notifier lors d'un rappel n'est JAMAIS saisie manuellement :
elle est dérivée de `SignalementQualite.etablissements_notifies` (property du
modèle, calculée à partir des lots concernés et du registre pivot).
"""
from datetime import datetime

from models import db, SignalementQualite, RappelStatutEtablissement, Lot, Personne
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow

STATUTS = {
    "signale": "Signalé",
    "evalue": "Évalué",
    "rappel_engage": "Rappel engagé",
    "notifie": "Notifié",
    "suivi": "Suivi en cours",
    "quarantaine": "Quarantaine",
    "sans_suite": "Sans suite",
    "cloture": "Clôturé",
}

STATUTS_FINAUX = {"sans_suite", "cloture"}

ORIGINES = {
    "titulaire_amm": "Titulaire d'AMM", "module_lt": "Module LT (laboratoire)",
    "module_ri": "Module RI (inspection)", "signalement_public": "Signalement public",
    "module_lr": "Module LR (libération de lots)",
}

ROLE_PAR_STATUT = {
    "signale": ["agent_surveillance_marche"],
    "evalue": ["agent_surveillance_marche", "directeur_dpml"],
    "quarantaine": ["agent_surveillance_marche"],
    "rappel_engage": ["agent_surveillance_marche"],
    "notifie": ["agent_surveillance_marche"],
    "suivi": ["agent_surveillance_marche"],
}


def peut_agir(signalement, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(signalement.statut, [])


def _get_or_create_lot(produit, numero_lot):
    numero_lot = (numero_lot or "").strip()
    if not numero_lot:
        return None
    lot = Lot.query.filter_by(produit_id=produit.id, numero_lot=numero_lot).first()
    if lot:
        return lot
    lot = Lot(produit_id=produit.id, numero_lot=numero_lot, statut="en_circulation")
    db.session.add(lot)
    db.session.flush()
    return lot


def signaler(produit, acteur, description, origine, numeros_lots=None):
    if not description or not description.strip():
        raise ErreurWorkflow("La description du défaut qualité est obligatoire.")
    if origine not in ORIGINES:
        raise ErreurWorkflow("Origine du signalement inconnue.")
    from numerotation import generer_numero
    sig = SignalementQualite(numero=generer_numero("SIG"), produit_id=produit.id, description=description.strip(),
                              origine=origine, statut="signale")
    for numero_lot in (numeros_lots or []):
        lot = _get_or_create_lot(produit, numero_lot)
        if lot:
            sig.lots_concernes.append(lot)
    db.session.add(sig)
    db.session.flush()
    enregistrer_creation(sig, acteur, f"Signalement de défaut qualité ({ORIGINES.get(origine, origine)})")
    notifier_tous("agent_surveillance_marche", "mc_nouveau_signalement",
                  f"Nouveau signalement {sig.numero} ({produit.libelle}) à évaluer.", lien=f"/signalements/{sig.id}")
    return sig


def evaluer(signalement, acteur, niveau_risque):
    if signalement.statut != "signale":
        raise ErreurWorkflow("Seul un signalement reçu peut être évalué.")
    if acteur.role_systeme != "agent_surveillance_marche":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if niveau_risque not in ("I", "II", "III"):
        raise ErreurWorkflow("Le niveau de risque doit être I, II ou III.")
    ancien = signalement.statut
    signalement.niveau_risque = niveau_risque
    signalement.statut = "evalue"
    enregistrer_audit(signalement, f"Signalement évalué (niveau de risque {niveau_risque})", acteur, ancien,
                       signalement.statut)
    if niveau_risque == "I":
        notifier_tous("directeur_dpml", "mc_validation_requise",
                      f"Signalement {signalement.numero} classé niveau I : validation requise avant tout rappel.",
                      lien=f"/signalements/{signalement.id}")


def _notifier_etablissements_rappel(signalement):
    for etab in signalement.etablissements_notifies:
        if not RappelStatutEtablissement.query.filter_by(signalement_id=signalement.id,
                                                           etablissement_id=etab.id).first():
            db.session.add(RappelStatutEtablissement(signalement_id=signalement.id, etablissement_id=etab.id,
                                                       statut="notifie"))
        for dest in Personne.query.filter_by(etablissement_rattachement_id=etab.id,
                                              role_systeme="demandeur_externe").all():
            notifier(dest, "mc_rappel_engage",
                     f"Rappel engagé sur {signalement.produit.libelle} (signalement {signalement.numero}) : "
                     f"{signalement.description}", lien=f"/signalements/{signalement.id}")


def engager_rappel(signalement, acteur):
    """evalue|quarantaine → rappel_engage → notifie (automatique). Un rappel de niveau I
    exige explicitement le rôle directeur_dpml — critère d'acceptation MC : impossible
    à exécuter par un compte agent_surveillance_marche seul, quelle que soit la voie
    d'accès (vérifié ici, pas seulement un bouton désactivé côté template)."""
    if signalement.statut not in ("evalue", "quarantaine"):
        raise ErreurWorkflow("Un rappel ne peut être engagé que depuis un signalement évalué ou en quarantaine.")
    if signalement.niveau_risque == "I":
        if acteur.role_systeme != "directeur_dpml":
            raise ErreurWorkflow("Validation du directeur requise pour un rappel de niveau I.")
    elif acteur.role_systeme != "agent_surveillance_marche":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")

    if not signalement.etablissements_notifies:
        raise ErreurWorkflow("Aucun établissement détenteur connu pour les lots concernés : "
                              "impossible de dériver automatiquement la liste à notifier.")

    ancien = signalement.statut
    signalement.statut = "rappel_engage"
    enregistrer_audit(signalement, "Rappel engagé", acteur, ancien, signalement.statut)
    ancien2 = signalement.statut
    signalement.statut = "notifie"
    _notifier_etablissements_rappel(signalement)
    enregistrer_audit(signalement, "Établissements notifiés (liste dérivée des lots concernés)", None, ancien2,
                       signalement.statut)


def mettre_en_quarantaine(signalement, acteur):
    if signalement.statut != "evalue":
        raise ErreurWorkflow("La mise en quarantaine n'est possible que depuis un signalement évalué.")
    if acteur.role_systeme != "agent_surveillance_marche":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = signalement.statut
    signalement.statut = "quarantaine"
    enregistrer_audit(signalement, "Lots mis en quarantaine dans l'attente des résultats d'investigation",
                       acteur, ancien, signalement.statut)


def classer_sans_suite(signalement, acteur, motif):
    if signalement.statut not in ("evalue", "quarantaine"):
        raise ErreurWorkflow("Un classement sans suite n'est possible que depuis un signalement évalué ou en quarantaine.")
    if acteur.role_systeme != "agent_surveillance_marche":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if not motif or not motif.strip():
        raise ErreurWorkflow("Un motif est obligatoire pour classer un signalement sans suite.")
    ancien = signalement.statut
    signalement.statut = "sans_suite"
    signalement.motif_decision = motif.strip()
    enregistrer_audit(signalement, "Signalement classé sans suite", acteur, ancien, signalement.statut,
                       commentaire=motif)


def confirmer_retrait(rappel_statut, acteur):
    if acteur.role_systeme != "agent_surveillance_marche":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if rappel_statut.statut == "confirme_retrait":
        raise ErreurWorkflow("Ce retrait est déjà confirmé.")
    rappel_statut.statut = "confirme_retrait"
    rappel_statut.date_confirmation = datetime.utcnow()

    sig = rappel_statut.signalement
    ancien = sig.statut
    if sig.statut == "notifie":
        sig.statut = "suivi"
        enregistrer_audit(sig, f"Retrait confirmé par {rappel_statut.etablissement.raison_sociale}, "
                           "suivi en cours", acteur, ancien, sig.statut)
    else:
        enregistrer_audit(sig, f"Retrait confirmé par {rappel_statut.etablissement.raison_sociale}",
                           acteur, sig.statut, sig.statut)
    if all(r.statut == "confirme_retrait" for r in sig.statuts_etablissements.all()):
        ancien2 = sig.statut
        sig.statut = "cloture"
        enregistrer_audit(sig, "Tous les établissements ont confirmé le retrait, signalement clôturé",
                           None, ancien2, sig.statut)


def cloturer_manuellement(signalement, acteur):
    """Clôture déclarée par l'agent (ex. retrait vérifié lors d'une inspection ultérieure,
    sans passer par la confirmation déclarative établissement par établissement)."""
    if signalement.statut not in ("notifie", "suivi"):
        raise ErreurWorkflow("Seul un signalement notifié ou en suivi peut être clôturé.")
    if acteur.role_systeme != "agent_surveillance_marche":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = signalement.statut
    signalement.statut = "cloture"
    enregistrer_audit(signalement, "Signalement clôturé (retrait vérifié)", acteur, ancien, signalement.statut)


def declarer_disponibilite_mitm(produit, acteur, disponibilite):
    if disponibilite not in ("disponible", "rupture"):
        raise ErreurWorkflow("Statut de disponibilité inconnu.")
    ancien = produit.disponibilite_declaree
    produit.disponibilite_declaree = disponibilite
    enregistrer_audit(produit, "Disponibilité MITM déclarée", acteur, ancien, disponibilite)
    if disponibilite == "rupture":
        notifier_tous("administrateur_dpml", "mc_rupture_mitm",
                      f"Rupture de disponibilité déclarée pour {produit.libelle} (MITM).",
                      lien=f"/mitm")
