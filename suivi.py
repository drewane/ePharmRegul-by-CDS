"""
Suivi unifié d'un dossier, du dépôt à la décision.

Les huit fonctions réglementaires suivent le même parcours vu du demandeur.
Ce module en donne la représentation commune : un numéro national, une suite
d'états lisibles, et le décompte du délai légal.

    [Soumis] → [Paiement validé] → [Recevabilité] → [En cours d'évaluation]
    → [Clock Stop / Questions] → [Validation hiérarchique] → [Décision disponible]

LE DÉLAI LÉGAL
--------------
Le décompte ne démarre pas au dépôt mais à la **validation du paiement**
(Clock Start) : tant que la redevance n'est pas acquittée, l'administration
n'est pas saisie. Il se **suspend** dès l'envoi d'une liste de questions
(Clock Stop) et **reprend** à la réception de la réponse — le temps de
réflexion du demandeur ne s'impute pas sur le délai de l'administration.
"""
from datetime import datetime

from models import db

# ---------------------------------------------------------------------------
# Numérotation nationale
# ---------------------------------------------------------------------------
# Code porté par le numéro de suivi, par fonction réglementaire.
CODES_FONCTION = {
    "amm": "AMM",                    # Homologation
    "licence": "LIC",                # Licences et agréments d'établissements
    "controle_qualite": "LNC",       # Laboratoire national de contrôle
    "liberation_lot": "OCB",         # Libération de lots (OCABR)
    "surveillance": "SUR",           # Surveillance du marché
    "vigilance": "VIG",              # Pharmacovigilance et matériovigilance
    "inspection": "INS",             # Inspection réglementaire
    "essai_clinique": "ECL",         # Essais cliniques
    "derogation": "DER",
    "visa_technique": "VIS",
}

LIBELLE_FONCTION = {
    "amm": "Homologation / AMM",
    "licence": "Licences et agréments d'établissements",
    "controle_qualite": "Contrôle qualité (LNCQ)",
    "liberation_lot": "Libération réglementaire des lots",
    "surveillance": "Surveillance du marché",
    "vigilance": "Pharmacovigilance et matériovigilance",
    "inspection": "Inspection réglementaire",
    "essai_clinique": "Essais cliniques",
    "derogation": "Dérogation spéciale",
    "visa_technique": "Visa technique",
}

PREFIXE_NATIONAL = "CMR"


def numero_suivi(fonction):
    """Numéro national de suivi : CMR-AMM-2026-00123.

    Séquence continue par fonction et par année, jamais réutilisée — le
    compteur persistant existant est réutilisé pour ne pas créer deux sources
    de vérité.
    """
    from models import SequenceNumerotation

    if fonction not in CODES_FONCTION:
        raise ValueError(f"Fonction réglementaire inconnue : {fonction}")
    code = CODES_FONCTION[fonction]
    annee = datetime.utcnow().year
    cle = f"CMR{code}"
    seq = SequenceNumerotation.query.filter_by(module=cle, annee=annee).first()
    if not seq:
        seq = SequenceNumerotation(module=cle, annee=annee, dernier_numero=0)
        db.session.add(seq)
        db.session.flush()
    seq.dernier_numero += 1
    db.session.flush()
    return f"{PREFIXE_NATIONAL}-{code}-{annee}-{seq.dernier_numero:05d}"


# ---------------------------------------------------------------------------
# États visibles du demandeur
# ---------------------------------------------------------------------------
ETATS = [
    ("soumis", "Soumis", "Votre dossier est enregistré."),
    ("paiement_valide", "Paiement validé",
     "La redevance est encaissée ; le délai d'instruction a démarré."),
    ("recevabilite", "Recevabilité",
     "Le dossier est examiné quant à sa complétude administrative."),
    ("evaluation", "En cours d'évaluation",
     "Le dossier est en cours d'examen technique."),
    ("clock_stop", "Questions en attente",
     "Des renseignements complémentaires vous ont été demandés ; le délai est "
     "suspendu jusqu'à votre réponse."),
    ("validation_hierarchique", "Validation hiérarchique",
     "Le dossier remonte la chaîne de signature."),
    ("decision", "Décision disponible",
     "La décision est signée et le document est téléchargeable."),
]

ORDRE_ETATS = [code for code, _l, _d in ETATS]
LIBELLE_ETAT = {code: libelle for code, libelle, _d in ETATS}
EXPLICATION_ETAT = {code: desc for code, _l, desc in ETATS}


def etat_visible(dossier):
    """État du dossier tel que le demandeur doit le comprendre.

    Traduit les statuts internes, propres à chaque fonction, en une étape du
    parcours commun. Le demandeur n'a pas à connaître notre vocabulaire.
    """
    import validation_numerique as vn

    statut = getattr(dossier, "statut", "") or ""

    if statut in ("approuve", "octroye", "autorise", "rejete", "irrecevable",
                  "refuse", "cloture_delai_depasse"):
        return "decision"
    if statut in ("complement_requis", "clock_stop"):
        return "clock_stop"
    if vn.circuit_ouvert(dossier):
        return "validation_hierarchique"
    if statut in ("evaluation_en_cours", "en_evaluation", "en_analyse", "en_cours"):
        return "evaluation"
    if statut in ("soumis", "recu", "depose", "recevable"):
        return "paiement_valide" if _paiement_valide(dossier) else "soumis"
    return "soumis"


def _paiement_valide(dossier):
    from models import Paiement
    return (Paiement.query
            .filter_by(entite_type=dossier.__class__.__name__, entite_id=dossier.id,
                       statut="confirme").first() is not None)


def etapes_parcours(dossier):
    """Les sept étapes, avec celle atteinte — support du tableau de bord."""
    courant = etat_visible(dossier)
    rang = ORDRE_ETATS.index(courant)
    resultat = []
    for i, (code, libelle, description) in enumerate(ETATS):
        # Le Clock Stop n'est présenté que s'il est effectivement survenu.
        if code == "clock_stop" and courant != "clock_stop" and not _a_eu_clock_stop(dossier):
            continue
        resultat.append({
            "code": code, "libelle": libelle, "description": description,
            "atteint": i < rang, "courant": i == rang,
        })
    return resultat


def _a_eu_clock_stop(dossier):
    return bool(getattr(dossier, "clock_total_suspendu_jours", 0))


# ---------------------------------------------------------------------------
# Historique opposable au demandeur
# ---------------------------------------------------------------------------
# Le demandeur a droit à la traçabilité de SA procédure, non à la délibération
# interne. On publie donc une liste blanche de jalons : ce qui lui a été
# notifié ou ce qui engage l'administration à son égard. Tout le reste — avis
# d'évaluateurs, ordres du jour de commission, listes de contrôle internes —
# reste dans l'espace régulateur.
JALONS_PUBLICS = (
    "Dossier soumis",
    "Dossier déclaré recevable",
    "Dossier déclaré irrecevable",
    "Complément de dossier demandé",
    "Passage en complément requis",
    "Réponse au complément déposée",
    "Passage automatique en évaluation",
    "Délai légal d'instruction démarré",
    "Délai suspendu",
    "Délai repris",
    "Dossier approuvé",
    "Dossier rejeté",
    "Dossier de retrait approuvé",
    "Clôture automatique",
)


def jalons_publics(dossier):
    """Historique horodaté que le demandeur peut légitimement consulter."""
    from models import EvenementAudit

    evenements = (EvenementAudit.query
                  .filter_by(entite_type=dossier.__class__.__name__,
                             entite_id=dossier.id)
                  .order_by(EvenementAudit.horodatage.asc()).all())
    return [e for e in evenements
            if any(e.action.startswith(p) for p in JALONS_PUBLICS)]


# ---------------------------------------------------------------------------
# Délai légal : Clock Start / Clock Stop
# ---------------------------------------------------------------------------
def demarrer_delai(dossier, acteur=None, motif="Paiement validé"):
    """Clock Start — déclenché par la validation du paiement.

    Idempotent : un dossier dont le délai court déjà n'est pas redémarré.
    """
    from audit import enregistrer_audit

    if getattr(dossier, "clock_debut", None) is not None:
        return dossier
    dossier.clock_debut = datetime.utcnow()
    dossier.clock_suspendu_depuis = None
    dossier.clock_total_suspendu_jours = 0
    enregistrer_audit(dossier, f"Délai légal d'instruction démarré ({motif})", acteur)
    return dossier


def suspendre_delai(dossier, acteur=None, motif="Liste de questions adressée"):
    """Clock Stop — le délai cesse de courir pendant que le demandeur répond."""
    from audit import enregistrer_audit
    from erreurs import ErreurWorkflow

    if getattr(dossier, "clock_debut", None) is None:
        raise ErreurWorkflow(
            "Le délai n'a pas démarré : le paiement n'a pas encore été validé.")
    if getattr(dossier, "clock_suspendu_depuis", None) is not None:
        return dossier                       # déjà suspendu
    dossier.clock_suspendu_depuis = datetime.utcnow()
    enregistrer_audit(dossier, f"Délai suspendu — Clock Stop ({motif})", acteur)
    return dossier


def reprendre_delai(dossier, acteur=None, motif="Réponse du demandeur reçue"):
    """Le délai repart ; le temps de suspension est capitalisé, pas perdu."""
    from audit import enregistrer_audit

    depuis = getattr(dossier, "clock_suspendu_depuis", None)
    if depuis is None:
        return dossier
    jours = max(0, (datetime.utcnow() - depuis).days)
    dossier.clock_total_suspendu_jours = (
        getattr(dossier, "clock_total_suspendu_jours", 0) or 0) + jours
    dossier.clock_suspendu_depuis = None
    enregistrer_audit(dossier,
                      f"Délai repris après {jours} jour(s) de suspension ({motif})",
                      acteur)
    return dossier


def jours_ecoules(dossier):
    """Jours effectivement imputables à l'administration.

    Exclut les périodes de suspension : le temps de réponse du demandeur ne
    s'impute pas sur le délai réglementaire.
    """
    debut = getattr(dossier, "clock_debut", None)
    if debut is None:
        return None
    fin = getattr(dossier, "date_decision", None) or datetime.utcnow()
    brut = max(0, (fin - debut).days)
    suspendu = getattr(dossier, "clock_total_suspendu_jours", 0) or 0
    depuis = getattr(dossier, "clock_suspendu_depuis", None)
    if depuis is not None:
        suspendu += max(0, (datetime.utcnow() - depuis).days)
    return max(0, brut - suspendu)


# Délai réglementaire d'instruction, en jours, par fonction. Valeurs de
# référence ; l'administrateur pourra les ajuster par paramètre de module.
DELAI_LEGAL_JOURS = {
    "amm": 270,
    "licence": 90,
    "controle_qualite": 30,
    "liberation_lot": 30,
    "surveillance": 60,
    "vigilance": 60,
    "inspection": 90,
    "essai_clinique": 60,
    "derogation": 15,
    "visa_technique": 30,
}


def fonction_du_dossier(dossier):
    """Fonction réglementaire dont relève un dossier.

    Un DossierAMM porte plusieurs procédures (octroi, renouvellement,
    variation) qui relèvent toutes de l'homologation ; les autres entités
    déclarent leur fonction explicitement.
    """
    fonction = getattr(dossier, "fonction_reglementaire", None)
    if fonction in CODES_FONCTION:
        return fonction
    if dossier.__class__.__name__ == "DossierAMM":
        return "amm"
    return "amm"


def delai_legal(dossier):
    return DELAI_LEGAL_JOURS.get(fonction_du_dossier(dossier))


def etat_delai(dossier, delai_legal_jours=None):
    """Situation du délai, pour affichage au demandeur comme à l'agent."""
    debut = getattr(dossier, "clock_debut", None)
    if debut is None:
        # Un dossier déjà instruit sans décompte est antérieur au Clock Start :
        # annoncer « en attente de paiement » serait faux. On le dit tel quel.
        anterieur = ORDRE_ETATS.index(etat_visible(dossier)) > \
            ORDRE_ETATS.index("paiement_valide")
        return {"demarre": False, "anterieur": anterieur,
                "libelle": ("Décompte non applicable — dossier antérieur au suivi "
                            "des délais" if anterieur
                            else "En attente de validation du paiement"),
                "jours": None, "restant": None, "suspendu": False, "depasse": False}
    suspendu = getattr(dossier, "clock_suspendu_depuis", None) is not None
    ecoules = jours_ecoules(dossier)
    restant = (delai_legal_jours - ecoules) if delai_legal_jours else None
    return {
        "demarre": True,
        "suspendu": suspendu,
        "jours": ecoules,
        "restant": restant,
        "depasse": bool(restant is not None and restant < 0),
        "jours_suspendus": getattr(dossier, "clock_total_suspendu_jours", 0) or 0,
        "libelle": ("Délai suspendu — en attente de votre réponse" if suspendu
                    else f"{ecoules} jour(s) d'instruction"),
    }
