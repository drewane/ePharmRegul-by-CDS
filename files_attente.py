"""
Files d'attente : ce qui attend une décision, et depuis combien de temps.

CE QU'UNE FILE EST, ET CE QU'ELLE N'EST PAS
--------------------------------------------
Une file d'attente n'est PAS une liste de statuts recopiée à la main. Elle se
déduit de la machine à états : un dossier est dans ma file si, dans son état
actuel, une transition m'est ouverte. Ajouter une transition au modèle peuple
la file automatiquement ; en retirer une la vide. Il n'y a aucun endroit où la
liste puisse diverger du workflow, parce qu'il n'y a pas de liste.

Ce module ne déclare donc que la PRÉSENTATION : comment on regroupe, comment
on nomme, à partir de quand on s'inquiète. Le « qui peut agir sur quoi » reste
dans `machine_etats`.

L'ANCIENNETÉ
------------
Un dossier qui attend est un dossier qui vieillit. On compte les jours depuis
son dernier changement d'état — pas depuis son dépôt : un dossier déposé il y
a six mois mais traité hier n'est pas en retard. Trois paliers, parce que deux
ne disent pas assez et quatre ne se retiennent pas.
"""
from datetime import datetime, timedelta

import machine_etats as me
from models import DossierAMM, EvenementAudit, db

# ---------------------------------------------------------------------------
# Paliers d'ancienneté
# ---------------------------------------------------------------------------
# Seuils en jours ouvrés approchés par des jours calendaires : le délai légal
# se compte ainsi dans les textes, on ne fait pas plus fin ici.
SEUIL_ATTENTION = 7
SEUIL_ALERTE = 15

PALIERS = {
    "normal": ("À traiter", "secondary"),
    "attention": (f"Plus de {SEUIL_ATTENTION} jours", "warning"),
    "alerte": (f"Plus de {SEUIL_ALERTE} jours", "danger"),
}


def palier(jours):
    if jours is None:
        return "normal"
    if jours >= SEUIL_ALERTE:
        return "alerte"
    if jours >= SEUIL_ATTENTION:
        return "attention"
    return "normal"


# ---------------------------------------------------------------------------
# Files déclarées — présentation seulement
# ---------------------------------------------------------------------------
# `roles` sert à décider qui voit la file. Les dossiers qu'elle contient
# viennent de la machine à états, jamais d'une énumération de statuts.
FILES = [
    {"code": "financier",
     "libelle": "File du service financier",
     "resume": "Recettes à constater avant que l'administration soit saisie.",
     "icone": "bi-cash-coin",
     "roles": ("responsable_financier",)},

    {"code": "homologation",
     "libelle": "File du service d'homologation",
     "resume": "Recevabilité, inscription en commission, édition des actes.",
     "icone": "bi-clipboard-check",
     "roles": ("chef_service_amm", "chef_bureau")},

    {"code": "commission",
     "libelle": "File des commissions",
     "resume": "Dossiers inscrits, en attente d'avis.",
     "icone": "bi-people",
     "roles": ("membre_commission_specialisee",)},

    {"code": "direction",
     "libelle": "File de la direction",
     "resume": "Dossiers consolidés, en attente de la décision finale.",
     "icone": "bi-patch-check",
     "roles": ("directeur_dpml",)},
]

FILES_PAR_CODE = {f["code"]: f for f in FILES}


def files_visibles(utilisateur):
    """Files que cet utilisateur peut consulter.

    L'administrateur les voit toutes — c'est son rôle de surveiller
    l'engorgement — mais il n'hérite d'aucun droit d'agir pour autant : ce que
    la page lui proposera reste ce que la machine à états lui ouvre.
    """
    role = getattr(utilisateur, "role_systeme", None)
    if role == "administrateur_dpml":
        return list(FILES)
    return [f for f in FILES if role in f["roles"]]


def file_par_defaut(utilisateur):
    visibles = files_visibles(utilisateur)
    return visibles[0] if visibles else None


# ---------------------------------------------------------------------------
# Contenu d'une file — dérivé de la machine à états
# ---------------------------------------------------------------------------
def statuts_de(role):
    """Statuts depuis lesquels ce rôle a au moins une action ouverte."""
    return {t["depuis"] for t in me.TRANSITIONS if role in t["roles"]}


def statuts_de_la_file(code_file):
    """Statuts couverts par la file, tous ses rôles réunis."""
    entree = FILES_PAR_CODE.get(code_file)
    if entree is None:
        return set()
    couverts = set()
    for role in entree["roles"]:
        couverts |= statuts_de(role)
    return couverts


def _statuts_stockes(canoniques):
    """Statuts tels qu'ils peuvent être stockés en base.

    La machine raisonne en vocabulaire canonique, mais un dossier antérieur
    porte encore `soumis` ou `approuve`. Interroger la base sur les seuls
    codes canoniques laisserait ces dossiers hors des files — invisibles,
    donc jamais traités.
    """
    stockes = set(canoniques)
    for ancien, canonique in me.ALIAS.items():
        if canonique in canoniques:
            stockes.add(ancien)
    return stockes


def dossiers(code_file, limite=None):
    """Dossiers présents dans la file, du plus ancien au plus récent."""
    statuts = _statuts_stockes(statuts_de_la_file(code_file))
    if not statuts:
        return []
    q = (DossierAMM.query
         .filter(DossierAMM.statut.in_(sorted(statuts)))
         .order_by(DossierAMM.date_maj.asc().nullsfirst()))
    if limite:
        q = q.limit(limite)
    return q.all()


def _dernier_changement(dossiers_liste):
    """Date du dernier changement d'état, par dossier, en une seule requête.

    Une requête par dossier ferait N+1 appels sur une page qui en affiche
    cinquante : la file d'attente serait elle-même en attente.
    """
    if not dossiers_liste:
        return {}
    ids = [d.id for d in dossiers_liste]
    lignes = (db.session.query(EvenementAudit.entite_id,
                               db.func.max(EvenementAudit.horodatage))
              .filter(EvenementAudit.entite_type == "DossierAMM",
                      EvenementAudit.entite_id.in_(ids),
                      EvenementAudit.nouveau_statut.isnot(None))
              .group_by(EvenementAudit.entite_id).all())
    return dict(lignes)


def contenu(code_file, utilisateur, limite=None):
    """Lignes affichables : dossier, ancienneté, palier, actions ouvertes.

    Les actions jointes à chaque ligne sont celles que la machine ouvre à CET
    utilisateur. Un membre de commission qui consulte la file d'homologation
    voit les dossiers mais aucun bouton : la file informe, elle n'habilite pas.
    """
    liste = dossiers(code_file, limite)
    derniers = _dernier_changement(liste)
    role = getattr(utilisateur, "role_systeme", None)
    maintenant = datetime.utcnow()

    lignes = []
    for d in liste:
        depuis = derniers.get(d.id) or d.date_maj or d.date_depot
        jours = (maintenant - depuis).days if depuis else None
        lignes.append({
            "dossier": d,
            "depuis": depuis,
            "jours": jours,
            "palier": palier(jours),
            "statut": me.libelle(d.statut),
            "couleur": me.couleur(d.statut),
            "actions": me.transitions_autorisees(d, role),
        })
    # Le plus vieux en tête : une file se traite par le bas, pas par le haut.
    lignes.sort(key=lambda l: (l["jours"] is None, -(l["jours"] or 0)))
    return lignes


# ---------------------------------------------------------------------------
# Synthèse — pour les badges et le rafraîchissement
# ---------------------------------------------------------------------------
def compter(code_file):
    """Nombre de dossiers en file, et combien dépassent les seuils."""
    lignes = contenu(code_file, None)
    return {
        "total": len(lignes),
        "attention": sum(1 for l in lignes if l["palier"] == "attention"),
        "alerte": sum(1 for l in lignes if l["palier"] == "alerte"),
        "plus_ancien": max((l["jours"] or 0 for l in lignes), default=0),
    }


def synthese(utilisateur):
    """Compteurs de toutes les files visibles — en-tête et badges du menu."""
    return [{**f, **compter(f["code"])} for f in files_visibles(utilisateur)]


def ma_charge(utilisateur):
    """Nombre de dossiers sur lesquels CET utilisateur peut agir maintenant.

    Distinct du total des files : l'administrateur voit tout mais n'agit sur
    rien, et un chef de bureau ne partage pas toutes les actions du chef de
    service.
    """
    role = getattr(utilisateur, "role_systeme", None)
    statuts = _statuts_stockes(statuts_de(role))
    if not statuts:
        return 0
    return (DossierAMM.query
            .filter(DossierAMM.statut.in_(sorted(statuts))).count())


# ---------------------------------------------------------------------------
# Contrôle de cohérence — support des tests
# ---------------------------------------------------------------------------
def verifier_files():
    """Anomalies : file sans rôle, rôle sans file, statut orphelin."""
    anomalies = []
    codes = set()
    for f in FILES:
        if f["code"] in codes:
            anomalies.append(f"file en double : {f['code']}")
        codes.add(f["code"])
        if not f["roles"]:
            anomalies.append(f"file sans rôle : {f['code']}")
        for role in f["roles"]:
            if not statuts_de(role):
                anomalies.append(
                    f"{role} figure dans la file {f['code']} mais la machine "
                    "à états ne lui ouvre aucune action")

    # Tout rôle régulateur qui peut agir doit avoir une file où le voir : une
    # action ouverte sans file, c'est un dossier qui attend sans que personne
    # ne sache qu'il attend.
    couverts = {r for f in FILES for r in f["roles"]}
    agissants = {r for t in me.TRANSITIONS for r in t["roles"]}
    for role in agissants - couverts - set(me.DEPOSANT) - set(me.ADMIN):
        anomalies.append(f"{role} peut agir mais n'apparaît dans aucune file")

    return anomalies
