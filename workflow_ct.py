"""
Moteur de workflow — Module CT (Supervision des essais cliniques), 17-CT.

Même règle de codage que les autres modules : seule cette couche change
`ProtocoleEssaiClinique.statut`, chaque fonction vérifie statut + rôle côté
serveur et appelle enregistrer_audit() avant tout commit(). Règle bloquante
non négociable : un protocole ne peut être autorisé sans avis favorable du
comité d'éthique renseigné dans le système (§7, critère d'acceptation).
"""
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from models import db, ProtocoleEssaiClinique, Etablissement
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from delais import get_parametre

STATUTS = {
    "depose": "Déposé",
    "recevable": "Recevable",
    "irrecevable": "Irrecevable",
    "evaluation_en_cours": "Évaluation en cours",
    "complement_requis": "Complément requis",
    "cloture_delai_depasse": "Clôturé (délai dépassé)",
    "autorise": "Autorisé",
    "amendement_en_cours": "Amendement en cours",
    "rejete": "Rejeté",
    "cloture": "Clôturé",
}

STATUTS_FINAUX = {"irrecevable", "cloture_delai_depasse", "rejete", "cloture"}

ROLE_PAR_STATUT = {
    "depose": ["agent_dros"],
    "evaluation_en_cours": ["agent_dros", "directeur_dpml"],
    "complement_requis": ["demandeur_externe"],
    "autorise": ["demandeur_externe", "agent_dros"],
    "amendement_en_cours": ["agent_dros", "directeur_dpml"],
}


def peut_agir(protocole, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(protocole.statut, [])


def deposer(promoteur, titre, produit_etudie=None, sites=None, reference_comite_ethique=""):
    if not titre or not titre.strip():
        raise ErreurWorkflow("Le titre du protocole est obligatoire.")
    from numerotation import generer_numero
    protocole = ProtocoleEssaiClinique(
        numero=generer_numero("CT"), titre=titre.strip(), promoteur_id=promoteur.id,
        produit_etudie_id=produit_etudie.id if produit_etudie else None,
        reference_comite_ethique=(reference_comite_ethique or "").strip(), statut_avis_ethique="en_attente",
        statut="depose", date_depot=datetime.utcnow(),
    )
    if sites:
        protocole.sites_investigation = sites
    db.session.add(protocole)
    db.session.flush()
    enregistrer_creation(protocole, promoteur, "Dépôt du protocole d'essai clinique")
    notifier_tous("agent_dros", "ct_nouveau_protocole", f"Nouveau protocole {protocole.numero} déposé.",
                  lien=f"/protocoles/{protocole.id}")
    return protocole


def marquer_recevabilite(protocole, acteur, decision, motif=None):
    if protocole.statut != "depose":
        raise ErreurWorkflow("Le contrôle de recevabilité n'est possible que sur un protocole déposé.")
    if acteur.role_systeme != "agent_dros":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = protocole.statut
    if decision == "recevable":
        protocole.statut = "recevable"
        enregistrer_audit(protocole, "Protocole déclaré recevable", acteur, ancien, protocole.statut)
        ancien2 = protocole.statut
        protocole.statut = "evaluation_en_cours"
        enregistrer_audit(protocole, "Passage automatique en évaluation scientifique", None, ancien2,
                           protocole.statut)
    elif decision == "irrecevable":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour déclarer un protocole irrecevable.")
        protocole.statut = "irrecevable"
        protocole.motif_decision = motif.strip()
        enregistrer_audit(protocole, "Protocole déclaré irrecevable", acteur, ancien, protocole.statut,
                           commentaire=motif)
        notifier(protocole.promoteur, "ct_irrecevable", f"Protocole {protocole.numero} irrecevable : {motif}",
                 lien=f"/protocoles/{protocole.id}")
    else:
        raise ErreurWorkflow("Décision de recevabilité inconnue.")


def mettre_a_jour_avis_ethique(protocole, acteur, statut_avis_ethique, reference=None):
    if acteur.role_systeme not in ("agent_dros", "administrateur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if statut_avis_ethique not in ("favorable", "en_attente", "defavorable"):
        raise ErreurWorkflow("Statut d'avis éthique inconnu.")
    protocole.statut_avis_ethique = statut_avis_ethique
    if reference is not None:
        protocole.reference_comite_ethique = reference.strip()
    enregistrer_audit(protocole, f"Avis du comité d'éthique renseigné : {statut_avis_ethique}", acteur,
                       protocole.statut, protocole.statut)


def formuler_avis(protocole, acteur, commentaire):
    if protocole.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Un avis ne peut être formulé que sur un protocole en évaluation.")
    if acteur.role_systeme != "agent_dros":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    enregistrer_audit(protocole, "Avis scientifique consigné", acteur, protocole.statut, protocole.statut,
                       commentaire=commentaire)


def decider(protocole, acteur, decision, motif=None, rapports_attendus=None):
    """rapports_attendus : liste de {titre, echeance (YYYY-MM-DD)} définie à l'autorisation
    (§7 : jalons suivis avec alerte en cas de non-réception)."""
    if protocole.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Une décision ne peut être prise que sur un protocole en évaluation.")
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut statuer sur un protocole d'essai clinique.")

    ancien = protocole.statut
    if decision == "autorise":
        # Contrôle bloquant, pas seulement un rappel visuel (critère d'acceptation CT).
        if protocole.statut_avis_ethique != "favorable":
            raise ErreurWorkflow(
                "L'autorisation ne peut être finalisée sans avis favorable du comité d'éthique "
                f"(statut actuel : {protocole.statut_avis_ethique})."
            )
        protocole.statut = "autorise"
        protocole.date_decision = datetime.utcnow()
        annees = int(get_parametre("CT", "duree_validite_annees", default=3))
        protocole.date_validite = date.today() + relativedelta(years=annees)
        rapports = []
        for r in (rapports_attendus or []):
            if r.get("titre") and r.get("echeance"):
                rapports.append({"titre": r["titre"], "echeance": r["echeance"], "statut": "attendu"})
        protocole.rapports_etape = rapports
        enregistrer_audit(protocole, "Protocole autorisé", acteur, ancien, protocole.statut)
        notifier(protocole.promoteur, "ct_decision",
                 f"Protocole {protocole.numero} autorisé, valide jusqu'au "
                 f"{protocole.date_validite.strftime('%d/%m/%Y')}.", lien=f"/protocoles/{protocole.id}")
    elif decision == "rejete":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour rejeter un protocole.")
        protocole.statut = "rejete"
        protocole.motif_decision = motif.strip()
        protocole.date_decision = datetime.utcnow()
        enregistrer_audit(protocole, "Protocole rejeté", acteur, ancien, protocole.statut, commentaire=motif)
        notifier(protocole.promoteur, "ct_decision", f"Protocole {protocole.numero} rejeté : {motif}",
                 lien=f"/protocoles/{protocole.id}")
    elif decision == "complement_requis":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif détaillé est obligatoire pour demander un complément.")
        protocole.statut = "complement_requis"
        jours = int(get_parametre("CT", "delai_reponse_complement_jours", default=60))
        protocole.date_limite_reponse_complement = datetime.utcnow() + timedelta(days=jours)
        enregistrer_audit(protocole, "Passage en complément requis", acteur, ancien, protocole.statut,
                           commentaire=motif)
        notifier(protocole.promoteur, "ct_complement_requis",
                 f"Complément requis sur le protocole {protocole.numero} : {motif}. Délai : {jours} jours.",
                 lien=f"/protocoles/{protocole.id}")
    else:
        raise ErreurWorkflow("Décision inconnue.")


def deposer_reponse_complement(protocole, acteur):
    if protocole.statut != "complement_requis":
        raise ErreurWorkflow("Une réponse ne peut être déposée que sur un protocole en complément requis.")
    if acteur.id != protocole.promoteur_id:
        raise ErreurWorkflow("Seul le promoteur peut répondre à ce complément.")
    ancien = protocole.statut
    protocole.statut = "evaluation_en_cours"
    enregistrer_audit(protocole, "Réponse au complément déposée, retour en évaluation", acteur, ancien,
                       protocole.statut)


def cloturer_si_delai_depasse(protocole):
    if protocole.statut != "complement_requis" or not protocole.date_limite_reponse_complement:
        return False
    if datetime.utcnow() <= protocole.date_limite_reponse_complement:
        return False
    ancien = protocole.statut
    protocole.statut = "cloture_delai_depasse"
    enregistrer_audit(protocole, "Clôture automatique : délai de réponse au complément dépassé", None, ancien,
                       protocole.statut)
    notifier(protocole.promoteur, "ct_cloture_delai_depasse",
             f"Protocole {protocole.numero} clôturé automatiquement (délai de réponse dépassé).",
             lien=f"/protocoles/{protocole.id}")
    return True


def soumettre_amendement(protocole, acteur, description):
    if protocole.statut != "autorise":
        raise ErreurWorkflow("Un amendement ne peut être soumis que sur un protocole autorisé.")
    if acteur.id != protocole.promoteur_id:
        raise ErreurWorkflow("Seul le promoteur peut soumettre un amendement.")
    if not description or not description.strip():
        raise ErreurWorkflow("La description de l'amendement est obligatoire.")
    amendements = protocole.amendements
    amendements.append({"date": datetime.utcnow().isoformat(), "description": description.strip(),
                         "statut": "en_cours"})
    protocole.amendements = amendements
    ancien = protocole.statut
    protocole.statut = "amendement_en_cours"
    enregistrer_audit(protocole, "Amendement soumis", acteur, ancien, protocole.statut, commentaire=description)
    notifier_tous("agent_dros", "ct_amendement", f"Amendement soumis sur le protocole {protocole.numero}.",
                  lien=f"/protocoles/{protocole.id}")


def decider_amendement(protocole, acteur, decision, motif=None):
    """Workflow simplifié (recevabilité puis décision confondues) — l'historique
    antérieur du protocole n'est jamais modifié, seul le dernier amendement est mis à
    jour et le protocole retourne à `autorise` (critère d'acceptation CT)."""
    if protocole.statut != "amendement_en_cours":
        raise ErreurWorkflow("Aucun amendement en cours à traiter.")
    if acteur.role_systeme not in ("agent_dros", "directeur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if decision not in ("approuve", "rejete"):
        raise ErreurWorkflow("Décision d'amendement inconnue.")
    amendements = protocole.amendements
    if amendements:
        amendements[-1]["statut"] = decision
        if motif:
            amendements[-1]["motif"] = motif.strip()
    protocole.amendements = amendements
    ancien = protocole.statut
    protocole.statut = "autorise"
    enregistrer_audit(protocole, f"Amendement {decision}", acteur, ancien, protocole.statut, commentaire=motif)
    notifier(protocole.promoteur, "ct_amendement_decision", f"Amendement du protocole {protocole.numero} : {decision}.",
             lien=f"/protocoles/{protocole.id}")


def deposer_rapport_etape(protocole, acteur, titre):
    if acteur.id != protocole.promoteur_id:
        raise ErreurWorkflow("Seul le promoteur peut déposer un rapport d'étape.")
    rapports = protocole.rapports_etape
    trouve = False
    for r in rapports:
        if r.get("titre") == titre and r.get("statut") == "attendu":
            r["statut"] = "recu"
            r["date_reception"] = datetime.utcnow().isoformat()
            trouve = True
            break
    if not trouve:
        raise ErreurWorkflow("Aucun rapport attendu ne correspond à ce titre.")
    protocole.rapports_etape = rapports
    enregistrer_audit(protocole, f"Rapport d'étape reçu : {titre}", acteur, protocole.statut, protocole.statut)


def cloturer(protocole, acteur):
    if protocole.statut != "autorise":
        raise ErreurWorkflow("Seul un protocole autorisé peut être clôturé.")
    if acteur.role_systeme not in ("agent_dros", "directeur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = protocole.statut
    protocole.statut = "cloture"
    enregistrer_audit(protocole, "Protocole clôturé (rapport final reçu et validé)", acteur, ancien,
                       protocole.statut)
