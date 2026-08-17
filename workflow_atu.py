"""
Autorisation temporaire d'utilisation : accès à un produit avant son AMM.

DEUX VOIES, DEUX DEMANDEURS
---------------------------
NOMINATIVE  un prescripteur nommément identifié demande le produit pour UN
            patient, sous sa responsabilité. La demande vient du soignant.
COHORTE     le titulaire demande l'accès pour un groupe de patients et
            s'engage à déposer une demande d'AMM. Un protocole d'utilisation
            encadre le recueil des données, qui nourriront ce dossier.

QUATRE CONDITIONS CUMULATIVES
-----------------------------
  1. maladie grave, rare ou invalidante ;
  2. absence de traitement approprié disponible ;
  3. traitement ne pouvant être différé ;
  4. présomption favorable d'efficacité et de sécurité.

Elles sont cumulatives : c'est ce qui distingue l'ATU d'une facilité
d'importation. `CONDITIONS` les porte, et `prononcer_decision` refuse d'accorder
tant que l'instructeur ne les a pas toutes constatées — le contrôle est dans
le moteur, pas seulement à l'écran.

CE QUE L'ACCÈS ANTICIPÉ COÛTE AU DEMANDEUR
-------------------------------------------
Une ATU n'est pas une AMM au rabais : elle est bornée dans le temps, se
renouvelle sur justification, impose des rapports périodiques et une
déclaration sans délai des effets indésirables. Elle s'éteint dès que l'AMM
est tranchée — accordée ou refusée.
"""
from datetime import date, datetime

from audit import enregistrer_audit, enregistrer_creation
from erreurs import ErreurWorkflow
from models import AutorisationTemporaire, db
from notifications import notifier, notifier_tous
from numerotation import generer_numero

TYPES = {
    "nominative": "ATU nominative — un patient désigné",
    "cohorte": "ATU de cohorte — groupe de patients",
}

STATUTS = {
    "brouillon": "Brouillon",
    "soumise": "Soumise",
    "en_instruction": "En instruction",
    "complement_requis": "Complément requis",
    "accordee": "Accordée",
    "refusee": "Refusée",
    "suspendue": "Suspendue",
    "expiree": "Expirée",
    "close": "Close",
}

STATUTS_ACTIFS = ("soumise", "en_instruction", "complement_requis", "accordee")

# Conditions à constater avant d'accorder. L'ordre est celui du raisonnement.
CONDITIONS = [
    ("gravite", "La maladie est grave, rare ou invalidante"),
    ("absence_alternative", "Aucun traitement approprié n'est disponible au "
                            "Cameroun"),
    ("urgence", "Le traitement ne peut pas être différé"),
    ("presomption_favorable", "L'efficacité et la sécurité sont présumées "
                              "favorables au vu des données disponibles"),
]

ROLES_INSTRUCTION = ("chef_service_amm", "chef_bureau", "administrateur_dpml")

DUREE_DEFAUT_MOIS = 12
DUREE_MAX_MOIS = 12          # au-delà, c'est une AMM qu'il faut demander


# ---------------------------------------------------------------------------
# Dépôt
# ---------------------------------------------------------------------------
def deposer(acteur, donnees):
    """Enregistre une demande d'ATU et saisit le service instructeur."""
    type_atu = (donnees.get("type_atu") or "nominative").strip()
    if type_atu not in TYPES:
        raise ErreurWorkflow(f"Type d'ATU inconnu : {type_atu}")

    for champ, libelle in (("denomination", "la dénomination du produit"),
                           ("indication", "l'indication thérapeutique"),
                           ("justification", "la justification de la demande")):
        if not (donnees.get(champ) or "").strip():
            raise ErreurWorkflow(f"Renseignez {libelle}.")

    if type_atu == "nominative":
        for champ, libelle in (("prescripteur_nom", "le nom du prescripteur"),
                               ("patient_reference",
                                "la référence du patient")):
            if not (donnees.get(champ) or "").strip():
                raise ErreurWorkflow(f"Une ATU nominative exige {libelle}.")
    else:
        if not donnees.get("effectif_estime"):
            raise ErreurWorkflow(
                "Une ATU de cohorte exige l'effectif de patients estimé.")
        if not (donnees.get("protocole_utilisation") or "").strip():
            raise ErreurWorkflow(
                "Une ATU de cohorte exige un protocole d'utilisation "
                "thérapeutique et de recueil d'informations.")
        if not donnees.get("engagement_amm"):
            raise ErreurWorkflow(
                "Une ATU de cohorte suppose l'engagement du titulaire à "
                "déposer une demande d'AMM. Sans cet engagement, la voie "
                "nominative est la seule ouverte.")

    atu = AutorisationTemporaire(
        numero=generer_numero("ATU"),
        type_atu=type_atu,
        denomination=donnees["denomination"].strip(),
        dci=(donnees.get("dci") or "").strip() or None,
        forme_dosage=(donnees.get("forme_dosage") or "").strip() or None,
        fabricant=(donnees.get("fabricant") or "").strip() or None,
        demandeur_id=acteur.id,
        etablissement_id=acteur.etablissement_rattachement_id,
        prescripteur_nom=(donnees.get("prescripteur_nom") or "").strip() or None,
        prescripteur_qualite=(donnees.get("prescripteur_qualite") or "").strip() or None,
        prescripteur_etablissement=(donnees.get("prescripteur_etablissement")
                                    or "").strip() or None,
        patient_reference=(donnees.get("patient_reference") or "").strip() or None,
        patient_age=_entier(donnees.get("patient_age")),
        patient_sexe=(donnees.get("patient_sexe") or "").strip() or None,
        effectif_estime=_entier(donnees.get("effectif_estime")),
        protocole_utilisation=(donnees.get("protocole_utilisation") or "").strip() or None,
        engagement_amm=bool(donnees.get("engagement_amm")),
        indication=donnees["indication"].strip(),
        justification=donnees["justification"].strip(),
        alternatives_examinees=(donnees.get("alternatives_examinees") or "").strip() or None,
        statut="soumise",
        date_depot=datetime.utcnow())
    db.session.add(atu)
    db.session.flush()

    import suivi
    atu.numero_suivi = suivi.numero_suivi("atu")

    enregistrer_creation(atu, acteur,
                         f"Dépôt d'une demande d'ATU ({TYPES[type_atu]})")
    notifier(acteur, "atu_receptionnee",
             f"Votre demande d'ATU {atu.numero} est réceptionnée pour "
             f"{atu.libelle}. Elle sera instruite en priorité.",
             lien=f"/atu/{atu.id}")
    for role in ROLES_INSTRUCTION:
        notifier_tous(role, "atu_a_instruire",
                      f"Demande d'ATU {atu.numero} à instruire — {atu.libelle}. "
                      "Une ATU concerne un patient en attente : le délai "
                      "d'instruction est court.",
                      lien=f"/atu/{atu.id}")
    return atu


def _entier(valeur):
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Instruction et décision
# ---------------------------------------------------------------------------
def prendre_en_instruction(atu, acteur):
    _verifier_instructeur(acteur)
    if atu.statut not in ("soumise", "complement_requis"):
        raise ErreurWorkflow(
            f"Une demande au statut « {STATUTS.get(atu.statut, atu.statut)} » "
            "ne se met pas en instruction.")
    ancien, atu.statut = atu.statut, "en_instruction"
    enregistrer_audit(atu, "Demande d'ATU prise en instruction", acteur,
                      ancien, atu.statut)
    return atu


def demander_complement(atu, acteur, question):
    _verifier_instructeur(acteur)
    if not (question or "").strip():
        raise ErreurWorkflow("Précisez ce qui manque au dossier.")
    ancien, atu.statut = atu.statut, "complement_requis"
    enregistrer_audit(atu, "Complément demandé au demandeur", acteur, ancien,
                      atu.statut, commentaire=question.strip())
    notifier(atu.demandeur, "atu_complement",
             f"Un complément est demandé sur votre ATU {atu.numero} : "
             f"{question.strip()}", lien=f"/atu/{atu.id}")
    return atu


def prononcer_decision(atu, acteur, accordee, conditions=None, duree_mois=None,
                       motif=None):
    """Accorde ou refuse. Les quatre conditions doivent être constatées.

    Le contrôle vit ici et non dans le formulaire : une ATU accordée sans que
    l'absence d'alternative ait été constatée serait une mise sur le marché
    déguisée, échappant à l'évaluation d'une AMM.
    """
    _verifier_instructeur(acteur)
    if atu.statut not in ("soumise", "en_instruction", "complement_requis"):
        raise ErreurWorkflow(
            "Cette demande n'est plus en cours d'instruction.")

    if accordee:
        coches = conditions or {}
        manquantes = [libelle for code, libelle in CONDITIONS
                      if not coches.get(code)]
        if manquantes:
            raise ErreurWorkflow(
                "Les conditions de l'ATU ne sont pas toutes réunies : "
                + " ; ".join(manquantes) + ".")
        duree = _entier(duree_mois) or DUREE_DEFAUT_MOIS
        if not 1 <= duree <= DUREE_MAX_MOIS:
            raise ErreurWorkflow(
                f"La durée doit être comprise entre 1 et {DUREE_MAX_MOIS} mois. "
                "Au-delà, c'est une demande d'AMM qui s'impose.")
        atu.duree_mois = duree
        atu.date_debut = date.today()
        atu.date_echeance = _echeance(atu.date_debut, duree)
    elif not (motif or "").strip():
        raise ErreurWorkflow("Un refus d'ATU doit être motivé.")

    ancien = atu.statut
    atu.statut = "accordee" if accordee else "refusee"
    atu.date_decision = datetime.utcnow()
    if motif:
        atu.motif_decision = motif.strip()

    if accordee:
        enregistrer_audit(
            atu, f"ATU accordée pour {atu.duree_mois} mois, jusqu'au "
                 f"{atu.date_echeance.strftime('%d/%m/%Y')}",
            acteur, ancien, atu.statut)
        notifier(atu.demandeur, "atu_accordee",
                 f"Votre ATU {atu.numero} est accordée jusqu'au "
                 f"{atu.date_echeance.strftime('%d/%m/%Y')}. Vous êtes tenu de "
                 "déclarer sans délai tout effet indésirable et de remettre "
                 "les rapports de suivi prévus.",
                 lien=f"/atu/{atu.id}")
    else:
        enregistrer_audit(atu, f"ATU refusée : {atu.motif_decision}", acteur,
                          ancien, atu.statut)
        notifier(atu.demandeur, "atu_refusee",
                 f"Votre ATU {atu.numero} est refusée : {atu.motif_decision}",
                 lien=f"/atu/{atu.id}")
    return atu


def renouveler(atu, acteur, duree_mois=None, justification=""):
    """Prolonge une ATU en cours. Le renouvellement se justifie, il n'est pas
    automatique : c'est l'occasion de vérifier que les conditions tiennent
    encore, notamment l'absence d'alternative."""
    _verifier_instructeur(acteur)
    if atu.statut != "accordee":
        raise ErreurWorkflow("Seule une ATU en cours se renouvelle.")
    if not (justification or "").strip():
        raise ErreurWorkflow(
            "Motivez le renouvellement : les conditions initiales "
            "tiennent-elles toujours ?")
    duree = _entier(duree_mois) or DUREE_DEFAUT_MOIS
    if not 1 <= duree <= DUREE_MAX_MOIS:
        raise ErreurWorkflow(
            f"La durée doit être comprise entre 1 et {DUREE_MAX_MOIS} mois.")

    depart = max(atu.date_echeance or date.today(), date.today())
    atu.date_echeance = _echeance(depart, duree)
    atu.renouvellements = (atu.renouvellements or 0) + 1
    enregistrer_audit(
        atu, f"ATU renouvelée pour {duree} mois, jusqu'au "
             f"{atu.date_echeance.strftime('%d/%m/%Y')} "
             f"(renouvellement n° {atu.renouvellements})",
        acteur, commentaire=justification.strip())
    notifier(atu.demandeur, "atu_renouvelee",
             f"Votre ATU {atu.numero} est renouvelée jusqu'au "
             f"{atu.date_echeance.strftime('%d/%m/%Y')}.",
             lien=f"/atu/{atu.id}")
    return atu


def suspendre(atu, acteur, motif):
    """Interrompt une ATU en cours — signal de sécurité, le plus souvent."""
    _verifier_instructeur(acteur)
    if atu.statut != "accordee":
        raise ErreurWorkflow("Seule une ATU en cours se suspend.")
    if not (motif or "").strip():
        raise ErreurWorkflow("Une suspension d'ATU doit être motivée.")
    ancien, atu.statut = atu.statut, "suspendue"
    atu.motif_decision = motif.strip()
    enregistrer_audit(atu, f"ATU suspendue : {atu.motif_decision}", acteur,
                      ancien, atu.statut)
    notifier(atu.demandeur, "atu_suspendue",
             f"Votre ATU {atu.numero} est suspendue : {atu.motif_decision} "
             "Cessez la dispensation et contactez la DPML.",
             lien=f"/atu/{atu.id}")
    return atu


def clore_sur_amm(atu, acteur, dossier):
    """Éteint l'ATU parce que l'AMM a été tranchée.

    C'est la fin normale du dispositif : l'accès anticipé n'a plus d'objet dès
    lors que le produit est autorisé — ou définitivement refusé.
    """
    if atu.statut not in ("accordee", "suspendue"):
        raise ErreurWorkflow("Cette ATU n'est pas en cours.")
    ancien, atu.statut = atu.statut, "close"
    atu.dossier_amm_id = dossier.id if dossier else None
    issue = "octroi de l'AMM" if dossier and dossier.statut == "approuve" \
        else "décision sur la demande d'AMM"
    enregistrer_audit(atu, f"ATU close — {issue}", acteur, ancien, atu.statut)
    notifier(atu.demandeur, "atu_close",
             f"Votre ATU {atu.numero} prend fin : {issue}.",
             lien=f"/atu/{atu.id}")
    return atu


GRAVITES = {
    "non_grave": "Non grave",
    "grave": "Grave",
    "fatal": "Issue fatale",
}


def remettre_rapport(atu, acteur, periode, contenu, effets_indesirables=0,
                     gravite=None, description_effets=None):
    """Rapport périodique de suivi — la contrepartie de l'accès anticipé.

    Dès qu'un effet indésirable est rapporté, un cas de pharmacovigilance est
    ouvert AUTOMATIQUEMENT. C'est la raison d'être du suivi renforcé : un
    produit sans AMM est administré sur la foi de données incomplètes, et
    laisser au déclarant le soin de saisir une seconde fois l'information dans
    un autre écran serait le meilleur moyen qu'elle ne parte jamais.

    La gravité devient alors obligatoire : un cas ouvert sans elle ne peut être
    ni trié ni priorisé par le service de vigilance, et encombrerait le
    registre au lieu de l'alimenter.
    """
    if atu.statut not in ("accordee", "suspendue"):
        raise ErreurWorkflow(
            "Un rapport ne se remet que sur une ATU en cours.")
    if not (contenu or "").strip():
        raise ErreurWorkflow("Le rapport ne peut pas être vide.")

    nombre = _entier(effets_indesirables) or 0
    if nombre < 0:
        raise ErreurWorkflow("Le nombre d'effets indésirables ne peut pas être "
                             "négatif.")
    if nombre and gravite not in GRAVITES:
        raise ErreurWorkflow(
            "Précisez la gravité des effets rapportés : elle conditionne le "
            "délai de traitement du cas de pharmacovigilance.")

    cas = _ouvrir_cas_vigilance(atu, acteur, nombre, gravite,
                                description_effets or contenu) if nombre else None

    atu.ajouter_rapport({
        "periode": (periode or "").strip() or date.today().strftime("%m/%Y"),
        "contenu": contenu.strip(),
        "effets_indesirables": nombre,
        "gravite": gravite if nombre else None,
        "cas_vigilance": cas.numero if cas else None,
        "date": datetime.utcnow().isoformat(timespec="seconds"),
        "auteur": acteur.nom_complet if acteur else "—",
    })
    enregistrer_audit(
        atu,
        "Rapport de suivi remis"
        + (f" — {nombre} effet(s) indésirable(s), cas {cas.numero} ouvert"
           if cas else " — aucun effet indésirable"),
        acteur)
    for role in ROLES_INSTRUCTION:
        notifier_tous(role, "atu_rapport",
                      f"Rapport de suivi remis sur l'ATU {atu.numero}."
                      + (f" {nombre} effet(s) indésirable(s) — cas "
                         f"{cas.numero}." if cas else ""),
                      lien=f"/atu/{atu.id}")
    return atu


def _ouvrir_cas_vigilance(atu, acteur, nombre, gravite, description):
    """Crée le cas de pharmacovigilance rattaché à un rapport d'ATU.

    Un seul cas par rapport, et non un par effet : le rapport ne porte pas le
    détail patient par patient, et fabriquer des cas vides pour atteindre le
    compte donnerait une fausse impression de précision. Le nombre est consigné
    dans la description, à charge pour le service de vigilance de ventiler s'il
    obtient le détail.
    """
    import workflow_vl as wfvl

    # Un prescripteur qui relaie un effet observé n'est pas un industriel :
    # la source conditionne la lecture du signal.
    source = "industriel" if atu.type_atu == "cohorte" else "professionnel_sante"

    entete = (f"[ATU {atu.numero} — {atu.libelle}] "
              f"{nombre} effet(s) indésirable(s) rapporté(s) dans le cadre "
              f"d'une autorisation temporaire d'utilisation "
              f"({TYPES.get(atu.type_atu, atu.type_atu)}). "
              f"Indication : {atu.indication}. ")
    cas = wfvl.creer_notification({
        "description_effet": entete + (description or "").strip(),
        "gravite": gravite,
        "source": source,
        "produit_id": atu.produit_id,
        "patient_age": atu.patient_age,
        "patient_sexe": atu.patient_sexe,
        "notificateur_nom": (atu.prescripteur_nom
                             or (acteur.nom_complet if acteur else None)),
    }, acteur)

    # Un effet grave ou fatal sous ATU appelle un réexamen de l'autorisation
    # elle-même, pas seulement le traitement du cas.
    if gravite in ("grave", "fatal"):
        for role in ROLES_INSTRUCTION:
            notifier_tous(
                role, "atu_signal_grave",
                f"Effet indésirable {GRAVITES[gravite].lower()} sous l'ATU "
                f"{atu.numero} (cas {cas.numero}). La poursuite de "
                "l'autorisation doit être réexaminée.",
                lien=f"/atu/{atu.id}")
    return cas


def expirer_echues():
    """Passe à « expirée » les ATU dont l'échéance est dépassée.

    Sans cela, une ATU accordée resterait indéfiniment « en cours » à l'écran,
    et le caractère temporaire du dispositif deviendrait une fiction.
    Idempotente : appelée à chaque accès au registre.
    """
    echues = (AutorisationTemporaire.query
              .filter(AutorisationTemporaire.statut == "accordee",
                      AutorisationTemporaire.date_echeance.isnot(None),
                      AutorisationTemporaire.date_echeance < date.today())
              .all())
    for atu in echues:
        atu.statut = "expiree"
        enregistrer_audit(atu, "ATU expirée — échéance atteinte", None,
                          "accordee", "expiree")
        if atu.demandeur:
            notifier(atu.demandeur, "atu_expiree",
                     f"Votre ATU {atu.numero} est arrivée à échéance. Toute "
                     "poursuite de la dispensation suppose un renouvellement.",
                     lien=f"/atu/{atu.id}")
    if echues:
        db.session.commit()
    return len(echues)


def _echeance(depart, duree_mois):
    mois = depart.month - 1 + duree_mois
    annee = depart.year + mois // 12
    mois = mois % 12 + 1
    jour = min(depart.day, [31, 29 if annee % 4 == 0 and (annee % 100 != 0
               or annee % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31,
               30, 31][mois - 1])
    return date(annee, mois, jour)


def _verifier_instructeur(acteur):
    if acteur is None or acteur.role_systeme not in ROLES_INSTRUCTION:
        raise ErreurWorkflow(
            "L'instruction d'une ATU relève du service Homologation.")


def etat(atu):
    """Résumé affichable : échéance, jours restants, obligations en cours."""
    restants = None
    if atu.date_echeance:
        restants = (atu.date_echeance - date.today()).days
    return {
        "statut": STATUTS.get(atu.statut, atu.statut),
        "type": TYPES.get(atu.type_atu, atu.type_atu),
        "en_cours": atu.statut == "accordee",
        "echeance": atu.date_echeance,
        "jours_restants": restants,
        "bientot_echue": restants is not None and 0 <= restants <= 30,
        "renouvellements": atu.renouvellements or 0,
        "rapports": len(atu.rapports()),
    }
