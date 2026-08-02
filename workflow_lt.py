"""
Moteur de workflow — Module LT (Analyses de laboratoire / LIMS), 15-LT-laboratoire.md.

Même règle de codage que les autres modules : seule cette couche change
`Echantillon.statut`, chaque fonction vérifie statut + rôle côté serveur et
appelle enregistrer_audit() avant tout commit().

Comparaison automatique de conformité (§7) : la spécification est un texte libre
(ex. "18-22", "<=5", ">=95", "=Blanc"). `_conformite_parametre` interprète les
formats numériques usuels et retombe sur une égalité texte sinon — une
comparaison structurée complète (unités, incertitudes de mesure) est hors de
portée d'une démonstration et documentée comme telle dans README.md.
"""
import re
from datetime import datetime

from models import db, Echantillon, Lot
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow

STATUTS = {
    "recu": "Reçu",
    "en_analyse": "En analyse",
    "resultat_saisi": "Résultat saisi",
    "valide": "Validé",
    "certificat_emis": "Certificat émis",
}

STATUTS_FINAUX = {"certificat_emis"}

ORIGINES = {
    "dossier_amm": "Dossier AMM",
    "inspection": "Inspection",
    "signalement_marche": "Signalement de marché",
    "demande_directe": "Demande directe",
    "liberation_lot": "Libération de lot",
}

ROLE_PAR_STATUT = {
    "recu": ["agent_laboratoire"],
    "en_analyse": ["agent_laboratoire"],
    "resultat_saisi": ["responsable_qualite_labo"],
    "valide": ["responsable_qualite_labo"],
}


def peut_agir(echantillon, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(echantillon.statut, [])


def _conformite_parametre(resultat_mesure, specification):
    spec = (specification or "").strip()
    val = (resultat_mesure or "").strip()
    try:
        m = re.match(r"^(-?\d+(?:[.,]\d+)?)\s*-\s*(-?\d+(?:[.,]\d+)?)$", spec)
        if m:
            lo, hi = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
            return "conforme" if lo <= float(val.replace(",", ".")) <= hi else "non_conforme"
        m = re.match(r"^(<=|>=|<|>|=)\s*(-?\d+(?:[.,]\d+)?)$", spec)
        if m:
            op, seuil = m.group(1), float(m.group(2).replace(",", "."))
            mesure = float(val.replace(",", "."))
            resultat = {"<=": mesure <= seuil, ">=": mesure >= seuil, "<": mesure < seuil,
                        ">": mesure > seuil, "=": mesure == seuil}[op]
            return "conforme" if resultat else "non_conforme"
    except (ValueError, TypeError):
        pass
    return "conforme" if val.lower() == spec.lower() else "non_conforme"


def creer_echantillon(produit, acteur, origine="demande_directe", lot=None, origine_reference_id=None):
    from numerotation import generer_numero
    ech = Echantillon(numero=generer_numero("LAB"), produit_id=produit.id, lot_id=lot.id if lot else None,
                       origine=origine, origine_reference_id=origine_reference_id, statut="recu")
    db.session.add(ech)
    db.session.flush()
    enregistrer_creation(ech, acteur, f"Réception d'un échantillon ({ORIGINES.get(origine, origine)})")
    notifier_tous("agent_laboratoire", "lt_nouvel_echantillon",
                  f"Nouvel échantillon {ech.numero} reçu ({produit.libelle}).", lien=f"/echantillons/{ech.id}")
    return ech


def prendre_en_charge(echantillon, acteur):
    if echantillon.statut != "recu":
        raise ErreurWorkflow("Seul un échantillon reçu peut être pris en charge.")
    if acteur.role_systeme != "agent_laboratoire":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = echantillon.statut
    echantillon.analyste_id = acteur.id
    echantillon.statut = "en_analyse"
    enregistrer_audit(echantillon, "Échantillon pris en charge pour analyse", acteur, ancien, echantillon.statut)


def saisir_resultats(echantillon, acteur, resultats):
    """resultats : liste de {parametre, methode, resultat_mesure, specification}."""
    if echantillon.statut != "en_analyse":
        raise ErreurWorkflow("Les résultats ne peuvent être saisis que sur un échantillon en analyse.")
    if acteur.id != echantillon.analyste_id:
        raise ErreurWorkflow("Seul l'analyste ayant pris en charge l'échantillon peut saisir ses résultats.")
    if not resultats:
        raise ErreurWorkflow("Au moins un paramètre de résultat doit être renseigné.")
    for r in resultats:
        r["conformite"] = _conformite_parametre(r.get("resultat_mesure", ""), r.get("specification", ""))
    echantillon.resultats = resultats
    ancien = echantillon.statut
    echantillon.statut = "resultat_saisi"
    enregistrer_audit(echantillon, "Résultats saisis", acteur, ancien, echantillon.statut)
    notifier_tous("responsable_qualite_labo", "lt_a_valider",
                  f"Échantillon {echantillon.numero} à valider.", lien=f"/echantillons/{echantillon.id}")


def valider_resultats(echantillon, acteur, decision, conclusion=None, observation=None):
    """decision : "valide" (exige conclusion conforme/non_conforme) ou "rejet" (exige observation).
    Double validation obligatoire (règle de gestion LT, critère d'acceptation) : l'analyste
    qui a saisi le résultat ne peut jamais le valider lui-même, même s'il détient aussi le
    rôle responsable_qualite_labo sur d'autres échantillons — vérifié ici, pas seulement
    masqué côté interface."""
    if echantillon.statut != "resultat_saisi":
        raise ErreurWorkflow("Seul un échantillon avec résultat saisi peut être validé.")
    if acteur.role_systeme != "responsable_qualite_labo":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if acteur.id == echantillon.analyste_id:
        raise ErreurWorkflow("L'analyste ayant saisi le résultat ne peut pas le valider lui-même.")

    ancien = echantillon.statut
    if decision == "valide":
        if conclusion not in ("conforme", "non_conforme"):
            raise ErreurWorkflow("La conclusion de conformité globale (conforme/non conforme) est obligatoire.")
        echantillon.validateur_id = acteur.id
        echantillon.conclusion = conclusion
        echantillon.statut = "valide"
        enregistrer_audit(echantillon, f"Résultats validés (conclusion : {conclusion})", acteur, ancien,
                           echantillon.statut)
    elif decision == "rejet":
        if not observation or not observation.strip():
            raise ErreurWorkflow("Une observation est obligatoire en cas de rejet de la saisie.")
        echantillon.statut = "en_analyse"
        echantillon.observation_rejet = observation.strip()
        enregistrer_audit(echantillon, "Saisie rejetée, retour à l'analyste", acteur, ancien, echantillon.statut,
                           commentaire=observation)
        if echantillon.analyste:
            notifier(echantillon.analyste, "lt_saisie_rejetee",
                     f"Résultats de l'échantillon {echantillon.numero} renvoyés : {observation}",
                     lien=f"/echantillons/{echantillon.id}")
    else:
        raise ErreurWorkflow("Décision de validation inconnue.")


def emettre_certificat(echantillon, acteur):
    if echantillon.statut != "valide":
        raise ErreurWorkflow("Le certificat ne peut être émis que sur un échantillon validé.")
    if acteur.role_systeme != "responsable_qualite_labo":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    ancien = echantillon.statut
    echantillon.statut = "certificat_emis"
    enregistrer_audit(echantillon, f"Certificat émis (conclusion : {echantillon.conclusion})", acteur, ancien,
                       echantillon.statut)
    _notifier_module_origine(echantillon)
    if echantillon.conclusion == "non_conforme" and echantillon.origine != "signalement_marche":
        _signaler_non_conformite_mc(echantillon)
    return echantillon


def _notifier_module_origine(echantillon):
    """Le résultat doit être automatiquement rattaché et visible depuis le module
    d'origine, sans ressaisie (critère d'acceptation LT) — les fiches MA/RI concernées
    interrogent directement Echantillon par (origine, origine_reference_id), voir
    dossier_detail.html / inspection/fiche.html. Cette notification complète l'accès
    direct par une alerte proactive."""
    if echantillon.origine == "dossier_amm" and echantillon.origine_reference_id:
        from models import DossierAMM
        dossier = DossierAMM.query.get(echantillon.origine_reference_id)
        if dossier:
            notifier(dossier.demandeur, "lt_certificat_emis",
                     f"Certificat de laboratoire émis pour l'échantillon {echantillon.numero} "
                     f"(dossier {dossier.numero}) : {echantillon.conclusion}.", lien=f"/dossiers/{dossier.id}")
    elif echantillon.origine == "inspection" and echantillon.origine_reference_id:
        notifier_tous("administrateur_dpml", "lt_certificat_emis",
                      f"Certificat de laboratoire émis pour l'échantillon {echantillon.numero} "
                      f"(inspection #{echantillon.origine_reference_id}) : {echantillon.conclusion}.",
                      lien=f"/inspections/{echantillon.origine_reference_id}")


def _signaler_non_conformite_mc(echantillon):
    """Point d'intégration avec le module MC (§8 : non-conformité détectée → module MC,
    alerte pour évaluation d'un éventuel rappel)."""
    import workflow_mc as wfmc
    numeros_lots = [echantillon.lot.numero_lot] if echantillon.lot else []
    wfmc.signaler(
        echantillon.produit, None,
        f"Résultat non conforme détecté sur l'échantillon {echantillon.numero} "
        f"(origine : {ORIGINES.get(echantillon.origine, echantillon.origine)}).",
        origine="module_lt", numeros_lots=numeros_lots,
    )
