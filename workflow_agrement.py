"""
Agréments d'établissement : distribution ou fabrication, médicaments ou
dispositifs médicaux, et trois actes possibles sur chacun.

Le module réutilise DemandeLicence — c'est le même objet réglementaire, qu'on
qualifie désormais par son domaine et sa catégorie de produits. Ajouter une
seconde entité aurait dédoublé l'instruction, les paiements et les circuits de
signature pour une distinction qui tient à deux colonnes.

LA SUSPENSION VOLONTAIRE
------------------------
`workflow_li.suspendre()` existe déjà, mais c'est une SANCTION prononcée par la
direction. L'acte ouvert ici est autre chose : la demande, par l'exploitant
lui-même, d'interrompre son agrément — arrêt temporaire d'activité, transfert
de site, cessation d'une ligne. Elle s'instruit comme les autres demandes et se
conclut par une décision ; elle ne suspend rien à elle seule. Les deux voies
coexistent sans se confondre, et la seconde exige un motif.
"""
from audit import enregistrer_creation
from erreurs import ErreurWorkflow
from models import DemandeLicence, Personne, db
from notifications import notifier, notifier_tous
from numerotation import generer_numero
from taxonomie_demandes import (ACTES_AGREMENT, CATEGORIES_AGREMENT,
                                DOMAINES_AGREMENT)

# Statuts non définitifs : une seule demande à la fois par établissement.
STATUTS_OUVERTS = ("deposee", "en_instruction")

# Actes exigeant que le demandeur motive sa démarche.
MOTIF_REQUIS = {"suspension": True}

ROLES_INSTRUCTION = ("agent_licences", "chef_service_licences")

# Pièces attendues, par acte puis par domaine. Le socle vaut pour tous ; les
# ajouts tiennent au risque propre à l'activité et à la catégorie de produits.
_SOCLE = [
    "Statuts de la société et registre de commerce",
    "Plan de localisation et titre d'occupation des locaux",
    "Diplôme et inscription à l'Ordre du pharmacien responsable",
    "Organigramme et effectifs qualifiés",
    "Quittance de la redevance",
]

_PAR_DOMAINE = {
    "distribution": [
        "Description des aires de stockage et de leur cartographie thermique",
        "Procédures de réception, de stockage et de transport",
        "Plan de rappel de lots",
    ],
    "fabrication": [
        "Dossier permanent du site de fabrication (Site Master File)",
        "Plan des locaux avec flux du personnel, des matières et des déchets",
        "Certificat de bonnes pratiques de fabrication, s'il existe",
        "Système de gestion de la qualité et liste des procédures maîtresses",
    ],
}

_PAR_CATEGORIE = {
    "medicaments": [
        "Liste des formes pharmaceutiques concernées",
    ],
    "dispositifs_medicaux": [
        "Classes de dispositifs concernées (I, IIa, IIb, III)",
        "Certificat de marquage ou équivalent du pays d'origine",
    ],
}

_PAR_ACTE = {
    "nouvelle": [],
    "renouvellement": [
        "Rapport d'activité de la période écoulée",
        "Suites données aux écarts relevés lors de la dernière inspection",
    ],
    "suspension": [
        "Note motivant la suspension et sa durée prévisible",
        "Inventaire des stocks et destination envisagée",
        "Modalités de continuité pour les clients ou patients concernés",
    ],
}


def pieces_attendues(domaine, categorie, acte):
    """Liste des pièces, du socle au plus spécifique."""
    if acte == "suspension":
        # Une suspension ne réexamine pas l'agrément : réclamer à nouveau les
        # statuts et les plans n'aurait pas de sens.
        return list(_PAR_ACTE["suspension"])
    return (_SOCLE + _PAR_DOMAINE.get(domaine, [])
            + _PAR_CATEGORIE.get(categorie, []) + _PAR_ACTE.get(acte, []))


def demandes_en_cours(etablissement):
    if etablissement is None:
        return []
    return (DemandeLicence.query
            .filter(DemandeLicence.etablissement_id == etablissement.id,
                    DemandeLicence.statut.in_(STATUTS_OUVERTS))
            .order_by(DemandeLicence.id.desc()).all())


def deposer(etablissement, acteur, domaine, categorie, acte, motif="",
            pieces=""):
    """Dépose une demande d'agrément qualifiée par son domaine et sa catégorie."""
    if etablissement is None:
        raise ErreurWorkflow(
            "Votre compte n'est rattaché à aucun établissement : une demande "
            "d'agrément est déposée au nom d'un établissement, jamais d'une "
            "personne.")
    if domaine not in DOMAINES_AGREMENT:
        raise ErreurWorkflow(f"Domaine d'agrément inconnu : {domaine}")
    if categorie not in CATEGORIES_AGREMENT:
        raise ErreurWorkflow(f"Catégorie de produits inconnue : {categorie}")
    if acte not in ACTES_AGREMENT:
        raise ErreurWorkflow(f"Acte inconnu : {acte}")
    if MOTIF_REQUIS.get(acte) and not (motif or "").strip():
        raise ErreurWorkflow(
            "Une demande de suspension doit être motivée : l'administration "
            "doit pouvoir apprécier la continuité de l'approvisionnement.")

    ouverte = demandes_en_cours(etablissement)
    if ouverte:
        raise ErreurWorkflow(
            f"Une demande est déjà en cours pour cet établissement "
            f"({ouverte[0].numero}). Attendez sa décision avant d'en déposer "
            "une autre.")

    demande = DemandeLicence(
        numero=generer_numero("LIC"), etablissement_id=etablissement.id,
        type_demande=acte, domaine=domaine, categorie=categorie,
        statut="deposee", motif_demande=(motif or "").strip() or None,
        pieces_justificatives=(pieces or "").strip() or None)
    db.session.add(demande)
    db.session.flush()

    libelle = intitule(demande)
    enregistrer_creation(demande, acteur, f"Dépôt d'une demande — {libelle}")
    notifier(acteur, "demande_receptionnee",
             f"Votre demande {demande.numero} ({libelle}) est réceptionnée. "
             "Vous serez informé de son instruction.",
             lien=f"/licences/{demande.id}")
    for role in ROLES_INSTRUCTION:
        notifier_tous(role, "agrement_a_instruire",
                      f"Demande {demande.numero} à instruire — {libelle} "
                      f"({etablissement.raison_sociale}).",
                      lien=f"/licences/{demande.id}")
    return demande


def intitule(demande):
    """Libellé lisible d'une demande, pour les écrans et les notifications."""
    acte = ACTES_AGREMENT.get(demande.type_demande, (demande.type_demande, ""))[0]
    domaine = DOMAINES_AGREMENT.get(demande.domaine)
    categorie = CATEGORIES_AGREMENT.get(demande.categorie)
    if domaine and categorie:
        return f"{acte} — agrément {domaine.lower()}, {categorie.lower()}"
    return acte
