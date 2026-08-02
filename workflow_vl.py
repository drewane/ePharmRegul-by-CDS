"""
Moteur de workflow — Module VL (Pharmacovigilance), 12-VL-pharmacovigilance.md.

Même règle de codage que workflow_ma.py : seule cette couche change
`NotificationVigilance.statut`, chaque fonction vérifie statut + rôle côté
serveur et appelle systématiquement enregistrer_audit() avant tout commit().

Interopérabilité VigiFlow/VigiBase (§7 du spec) : ce périmètre n'implémente PAS
d'appel réseau réel vers VigiFlow (hors de portée d'un environnement de
démonstration). `transmettre_vigiflow` simule une transmission réussie
immédiate et fixe `reference_e2b` ; tant que cette action n'a pas été
déclenchée, le cas affiche explicitement « transmission en attente », jamais
un échec silencieux — conforme au comportement observable exigé par le spec.
"""
import hashlib
from datetime import datetime

from models import db, NotificationVigilance, Produit, Lot
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow

STATUTS = {
    "recue": "Reçue",
    "en_evaluation": "En évaluation",
    "signal_detecte": "Signal détecté",
    "mesures_en_cours": "Mesures en cours",
    "cloturee": "Clôturée",
}

STATUTS_FINAUX = {"cloturee"}

TYPES_MESURE = {
    "information": "Information des prescripteurs",
    "restriction": "Restriction d'usage",
    "retrait": "Retrait du produit (génère un dossier de retrait AMM)",
}

ROLE_PAR_STATUT = {
    "recue": ["agent_vigilance"],
    "en_evaluation": ["agent_vigilance"],
    "signal_detecte": ["directeur_dpml"],
    "mesures_en_cours": ["agent_vigilance"],
}


def peut_agir(cas, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(cas.statut, [])


def _get_or_create_lot(produit, numero_lot):
    numero_lot = (numero_lot or "").strip()
    if not produit or not numero_lot:
        return None
    lot = Lot.query.filter_by(produit_id=produit.id, numero_lot=numero_lot).first()
    if lot:
        return lot
    lot = Lot(produit_id=produit.id, numero_lot=numero_lot, statut="non_applicable")
    db.session.add(lot)
    db.session.flush()
    return lot


def creer_notification(donnees, acteur=None):
    """
    Réception d'un cas (§3.1). Accessible sans authentification (acteur=None) —
    un notificateur externe (professionnel de santé, patient, industriel) peut
    créer un cas sans compte utilisateur et reçoit un numéro de suivi (critère
    d'acceptation VL #1).

    donnees : description_effet, gravite, source, produit_id (optionnel),
    numero_lot (optionnel), patient_age, patient_sexe, notificateur_nom,
    notificateur_contact.
    """
    if not (donnees.get("description_effet") or "").strip():
        raise ErreurWorkflow("La description de l'effet observé est obligatoire.")
    if donnees.get("gravite") not in ("non_grave", "grave", "fatal"):
        raise ErreurWorkflow("La gravité doit être précisée (non grave, grave ou fatal).")
    if donnees.get("source") not in ("professionnel_sante", "patient", "industriel", "litterature"):
        raise ErreurWorkflow("La source de la notification doit être précisée.")

    produit = None
    produit_id = donnees.get("produit_id")
    if produit_id:
        produit = Produit.query.get(produit_id)
    lot = _get_or_create_lot(produit, donnees.get("numero_lot"))

    from numerotation import generer_numero
    cas = NotificationVigilance(
        numero=generer_numero("PV"),
        produit_id=produit.id if produit else None,
        lot_id=lot.id if lot else None,
        patient_age=donnees.get("patient_age") or None,
        patient_sexe=donnees.get("patient_sexe") or None,
        description_effet=donnees["description_effet"].strip(),
        gravite=donnees["gravite"],
        source=donnees["source"],
        notificateur_nom=(donnees.get("notificateur_nom") or "").strip() or None,
        notificateur_contact=(donnees.get("notificateur_contact") or "").strip() or None,
        statut="recue",
    )
    db.session.add(cas)
    db.session.flush()
    enregistrer_creation(cas, acteur, "Réception d'une notification de pharmacovigilance")
    notifier_tous("agent_vigilance", "vl_nouveau_cas",
                  f"Nouveau cas {cas.numero} ({cas.gravite_label}) à instruire.", lien=f"/vigilance/cas/{cas.id}")
    return cas


def modifier_cas(cas, acteur, donnees):
    """Complétude / correction par l'agent (§3.2) — produit, lot, description, gravité
    déclarée peuvent être ajustés tant que le cas n'a pas atteint une décision de suivi."""
    if cas.statut not in ("recue", "en_evaluation"):
        raise ErreurWorkflow("Ce cas n'est plus modifiable dans son statut actuel.")
    if acteur.role_systeme != "agent_vigilance":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if "produit_id" in donnees:
        produit_id = donnees.get("produit_id")
        cas.produit_id = int(produit_id) if produit_id else None
    if "numero_lot" in donnees and cas.produit_id:
        lot = _get_or_create_lot(Produit.query.get(cas.produit_id), donnees.get("numero_lot"))
        cas.lot_id = lot.id if lot else None
    if "description_effet" in donnees and donnees["description_effet"].strip():
        cas.description_effet = donnees["description_effet"].strip()
    if "gravite" in donnees and donnees["gravite"] in ("non_grave", "grave", "fatal"):
        cas.gravite = donnees["gravite"]
    if "evaluation_causalite" in donnees:
        cas.evaluation_causalite = donnees["evaluation_causalite"]


def prendre_en_charge(cas, acteur):
    """Contrôle de complétude effectué, passage à l'évaluation (§3.2-3.3)."""
    if cas.statut != "recue":
        raise ErreurWorkflow("Seul un cas reçu peut être pris en charge.")
    if acteur.role_systeme != "agent_vigilance":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = cas.statut
    cas.statut = "en_evaluation"
    enregistrer_audit(cas, "Cas pris en charge, évaluation de causalité en cours", acteur, ancien, cas.statut)


def decider_suivi(cas, acteur, decision, commentaire=None):
    """Décision de suivi de l'agent de vigilance (§3.4) : cas isolé sans signal → clôture,
    ou cas grave/signal potentiel → transmission au directeur pour arbitrage."""
    if cas.statut != "en_evaluation":
        raise ErreurWorkflow("Une décision de suivi ne peut être prise que sur un cas en évaluation.")
    if acteur.role_systeme != "agent_vigilance":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = cas.statut
    if decision == "cloturer":
        cas.statut = "cloturee"
        enregistrer_audit(cas, "Cas clôturé (isolé, sans signal détecté)", acteur, ancien, cas.statut,
                           commentaire=commentaire)
    elif decision == "signal_detecte":
        cas.statut = "signal_detecte"
        enregistrer_audit(cas, "Signal potentiel détecté, transmis pour arbitrage", acteur, ancien, cas.statut,
                           commentaire=commentaire)
        notifier_tous("directeur_dpml", "vl_arbitrage_requis",
                      f"Cas {cas.numero} : arbitrage requis sur une éventuelle mesure de minimisation du risque.",
                      lien=f"/vigilance/cas/{cas.id}")
    else:
        raise ErreurWorkflow("Décision de suivi inconnue.")


def arbitrer_signal(cas, acteur, decision, motif=None, type_mesure=None):
    """Arbitrage du directeur DPML sur un signal détecté (§3.4, règle transversale n°6 :
    l'agent qui instruit ne décide jamais seul d'une mesure)."""
    if cas.statut != "signal_detecte":
        raise ErreurWorkflow("L'arbitrage n'est possible que sur un cas au statut « signal détecté ».")
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut arbitrer un signal détecté.")

    ancien = cas.statut
    if decision == "mesure_decidee":
        if type_mesure not in TYPES_MESURE:
            raise ErreurWorkflow("Le type de mesure de minimisation du risque doit être précisé.")
        if type_mesure == "retrait" and not cas.produit_id:
            raise ErreurWorkflow("Un retrait ne peut être engagé que si le produit concerné est identifié.")
        cas.statut = "mesures_en_cours"
        cas.type_mesure = type_mesure
        enregistrer_audit(cas, f"Mesure de minimisation du risque décidée : {TYPES_MESURE[type_mesure]}",
                           acteur, ancien, cas.statut, commentaire=motif)
        if type_mesure == "retrait":
            _initier_retrait_ma(cas, acteur)
    elif decision == "aucune_mesure":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour clôturer un signal sans mesure décidée.")
        cas.statut = "cloturee"
        cas.motif_decision = motif.strip()
        enregistrer_audit(cas, "Signal examiné : aucune mesure jugée nécessaire", acteur, ancien, cas.statut,
                           commentaire=motif)
    else:
        raise ErreurWorkflow("Décision d'arbitrage inconnue.")


def _initier_retrait_ma(cas, acteur):
    """Point d'intégration avec le module MA (§4 : mesure décidée impliquant un retrait
    → création automatique d'un DossierAMM de type retrait). Le demandeur du dossier est
    le pharmacien responsable de l'établissement titulaire, à défaut l'acteur lui-même."""
    import workflow_ma as wf_ma
    produit = Produit.query.get(cas.produit_id)
    demandeur = acteur
    if produit.titulaire_amm and produit.titulaire_amm.pharmacien_responsable:
        demandeur = produit.titulaire_amm.pharmacien_responsable
    try:
        dossier = wf_ma.creer_dossier_procedure(produit, demandeur, "retrait")
    except wf_ma.ErreurWorkflow:
        # Un dossier de retrait est déjà actif pour ce produit : pas de doublon, la mesure
        # VL reste rattachée au dossier existant plutôt que d'échouer silencieusement.
        dossier = wf_ma.DossierAMM.query.filter_by(produit_id=produit.id, type_procedure="retrait") \
            .filter(wf_ma.DossierAMM.statut.notin_(wf_ma.STATUTS_FINAUX)).first()
    notifier_tous("administrateur_dpml", "vl_retrait_initie",
                  f"Retrait initié pour le produit {produit.libelle} suite au cas de pharmacovigilance {cas.numero}"
                  f" (dossier {dossier.numero or ('brouillon #' + str(dossier.id))}).",
                  lien=f"/dossiers/{dossier.id}")


def cloturer_mesure(cas, acteur):
    if cas.statut != "mesures_en_cours":
        raise ErreurWorkflow("Seul un cas avec une mesure en cours peut être clôturé à ce titre.")
    if acteur.role_systeme != "agent_vigilance":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = cas.statut
    cas.statut = "cloturee"
    enregistrer_audit(cas, "Mesure de minimisation du risque exécutée, cas clôturé", acteur, ancien, cas.statut)


def transmettre_vigiflow(cas, acteur):
    """Export ICH E2B(R3) simulé — voir note en tête de module."""
    if acteur.role_systeme not in ("agent_vigilance", "administrateur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if cas.reference_e2b:
        raise ErreurWorkflow("Ce cas a déjà été transmis à VigiFlow.")
    base = f"{cas.numero}|{cas.date_notification.isoformat()}"
    cas.reference_e2b = "E2B-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:12].upper()
    cas.date_transmission_e2b = datetime.utcnow()
    enregistrer_audit(cas, f"Cas transmis à VigiFlow (référence {cas.reference_e2b})",
                       acteur, cas.statut, cas.statut)
