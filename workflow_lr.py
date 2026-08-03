"""
Moteur de workflow — Module LR (Libération des lots, vaccins/produits biologiques),
18-LR-liberation-lots.md.

Même règle de codage que les autres modules : seule cette couche change
`LiberationLot.statut` (et `Lot.statut` à la libération effective), chaque
fonction vérifie statut + rôle côté serveur et appelle enregistrer_audit()
avant tout commit(). Deux contrôles croisés non négociables (§7, critères
d'acceptation) :
  1. Le produit doit avoir une AMM active — vérifié à l'entrée dans le
     contrôle documentaire ET RE-vérifié au moment de la décision finale
     (le statut de l'AMM peut changer entre-temps).
  2. La libération exige À LA FOIS un contrôle documentaire validé ET un
     résultat de laboratoire conforme et validé — l'un sans l'autre ne
     suffit jamais, aucune dérogation possible.
"""
from datetime import datetime

from models import db, LiberationLot, Lot
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow

STATUTS = {
    "recu": "Reçu",
    "controle_documentaire": "Contrôle documentaire",
    "controle_laboratoire": "Contrôle laboratoire",
    "libere": "Libéré",
    "rejete": "Rejeté",
}

STATUTS_FINAUX = {"libere", "rejete"}

CATEGORIES_APPLICABLES = ("vaccin", "produit_sanguin")

ROLE_PAR_STATUT = {
    "recu": ["agent_laboratoire", "administrateur_dpml"],
    "controle_documentaire": ["agent_laboratoire", "administrateur_dpml"],
    "controle_laboratoire": ["directeur_dpml"],
}


def peut_agir(liberation, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(liberation.statut, [])


def recevoir_dossier_lot(produit, lot, acteur, dossier_fabricant=""):
    if produit.categorie not in CATEGORIES_APPLICABLES:
        raise ErreurWorkflow(
            "Le processus de libération de lot ne s'applique qu'aux vaccins et produits sanguins."
        )
    from numerotation import generer_numero
    liberation = LiberationLot(numero=generer_numero("LR"), produit_id=produit.id, lot_id=lot.id,
                                dossier_fabricant=dossier_fabricant, statut="recu")
    db.session.add(liberation)
    db.session.flush()
    enregistrer_creation(liberation, acteur, "Réception du dossier de lot")
    # Redevance de libération, à la charge du titulaire de l'AMM du produit :
    # on notifie son représentant déclaré (résolu par la couche paiement).
    from paiements import _demandeur, exiger_paiement
    paiement = exiger_paiement(liberation, [], f"/liberations/{liberation.id}",
                               f"la libération du lot {liberation.numero}")
    if paiement is not None:
        redevable = _demandeur(paiement)
        if redevable is not None:
            notifier(redevable, "paiement_attendu",
                     f"Frais de {paiement.montant} {paiement.devise} à régler pour la "
                     f"libération du lot {liberation.numero} ({paiement.numero}).",
                     lien=f"/liberations/{liberation.id}")
    if produit.statut_amm_courant != "active":
        notifier_tous("agent_laboratoire", "lr_amm_non_active",
                      f"Dossier de lot {liberation.numero} reçu pour un produit sans AMM active "
                      f"({produit.libelle}) — blocage à corriger.", lien=f"/liberations/{liberation.id}")
        notifier_tous("administrateur_dpml", "lr_amm_non_active",
                      f"Dossier de lot {liberation.numero} reçu pour un produit sans AMM active "
                      f"({produit.libelle}) — blocage à corriger.", lien=f"/liberations/{liberation.id}")
    return liberation


def controler_documentaire(liberation, acteur, decision, motif=None):
    """recu → controle_documentaire | rejete. Un lot ne peut entrer dans le processus de
    contrôle que si son produit a une AMM active — vérifié ici, pas seulement à la
    réception (contrôle croisé avec le module MA, critère d'acceptation LR)."""
    if liberation.statut != "recu":
        raise ErreurWorkflow("Le contrôle documentaire n'est possible que sur un dossier reçu.")
    if acteur.role_systeme not in ("agent_laboratoire", "administrateur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")

    ancien = liberation.statut
    if decision == "valide":
        if liberation.produit.statut_amm_courant != "active":
            raise ErreurWorkflow(
                f"Le produit {liberation.produit.libelle} n'a pas d'AMM active : "
                "ce lot ne peut pas entrer dans le processus de libération."
            )
        liberation.statut = "controle_documentaire"
        enregistrer_audit(liberation, "Contrôle documentaire validé", acteur, ancien, liberation.statut)
    elif decision == "rejete":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire en cas d'incohérence documentaire.")
        liberation.statut = "rejete"
        liberation.motif_rejet = motif.strip()
        enregistrer_audit(liberation, "Rejeté pour incohérence documentaire", acteur, ancien, liberation.statut,
                           commentaire=motif)
    else:
        raise ErreurWorkflow("Décision de contrôle documentaire inconnue.")


def lancer_controle_laboratoire(liberation, acteur):
    if liberation.statut != "controle_documentaire":
        raise ErreurWorkflow("Le contrôle de laboratoire ne peut être lancé qu'après validation documentaire.")
    if acteur.role_systeme not in ("agent_laboratoire", "administrateur_dpml"):
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    import workflow_lt as wflt
    echantillon = wflt.creer_echantillon(liberation.produit, acteur, origine="liberation_lot", lot=liberation.lot,
                                          origine_reference_id=liberation.id)
    liberation.echantillon_lt_id = echantillon.id
    ancien = liberation.statut
    liberation.statut = "controle_laboratoire"
    enregistrer_audit(liberation, f"Contrôle de laboratoire lancé (échantillon {echantillon.numero})", acteur,
                       ancien, liberation.statut)


def decider_liberation(liberation, acteur, decision, motif=None, deja_distribue=False):
    if liberation.statut != "controle_laboratoire":
        raise ErreurWorkflow("Une décision de libération ne peut être prise qu'après contrôle de laboratoire.")
    if acteur.role_systeme != "directeur_dpml":
        raise ErreurWorkflow("Seul le directeur DPML peut décider de la libération d'un lot.")

    ancien = liberation.statut
    if decision == "libere":
        ech = liberation.echantillon_lt
        if not (ech and ech.statut == "certificat_emis" and ech.conclusion == "conforme"):
            raise ErreurWorkflow(
                "La libération exige un contrôle documentaire validé ET un résultat de laboratoire "
                "conforme et validé — l'un sans l'autre ne suffit pas."
            )
        if liberation.produit.statut_amm_courant != "active":
            raise ErreurWorkflow(
                f"Le produit {liberation.produit.libelle} n'a plus d'AMM active : "
                "le lot ne peut pas être libéré."
            )
        liberation.statut = "libere"
        liberation.date_liberation = datetime.utcnow()
        liberation.lot.statut = "libere"
        enregistrer_audit(liberation, "Lot libéré", acteur, ancien, liberation.statut)
        notifier_tous("administrateur_dpml", "lr_libere",
                      f"Lot {liberation.lot.numero_lot} ({liberation.produit.libelle}) libéré — "
                      "disponible pour le Programme Élargi de Vaccination.", lien=f"/liberations/{liberation.id}")
    elif decision == "rejete":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour rejeter un lot.")
        liberation.statut = "rejete"
        liberation.motif_rejet = motif.strip()
        enregistrer_audit(liberation, "Lot rejeté", acteur, ancien, liberation.statut, commentaire=motif)
        if deja_distribue:
            # Jamais un simple archivage silencieux (critère d'acceptation LR) : signalement
            # automatique au module MC pour évaluation d'un éventuel rappel.
            import workflow_mc as wfmc
            wfmc.signaler(
                liberation.produit, None,
                f"Lot {liberation.lot.numero_lot} rejeté en libération après distribution partielle "
                f"(dossier {liberation.numero}) : {motif}",
                origine="module_lr", numeros_lots=[liberation.lot.numero_lot],
            )
    else:
        raise ErreurWorkflow("Décision de libération inconnue.")
