"""
Catalogue de la grille de contrôle d'inspection (13-RI §5, GrilleItem). Fixe et
partagé par le serveur (initialisation d'une Inspection) et le client (JS de la
page de saisie, qui doit connaître le même référentiel pour fonctionner hors
connexion sans dépendre d'un appel réseau supplémentaire).
"""

SECTIONS = [
    ("locaux", "Locaux", [
        "Propreté et rangement des locaux de stockage",
        "Conditions de température et d'hygrométrie respectées",
        "Zones de stockage séparées (quarantaine / rebut / produits libérés)",
    ]),
    ("personnel", "Personnel", [
        "Pharmacien responsable présent et identifié",
        "Formation du personnel à jour",
        "Tenue et hygiène du personnel conformes",
    ]),
    ("tracabilite", "Traçabilité", [
        "Registre des entrées/sorties de lots tenu à jour",
        "Numéros de lot tracés jusqu'au client",
        "Procédure de rappel de lot formalisée",
    ]),
    ("documentation", "Documentation", [
        "Licence d'exploitation affichée et valide",
        "Procédures opératoires normalisées disponibles",
        "Registre des non-conformités précédentes tenu",
    ]),
]


def grille_initiale():
    """Liste de GrilleItem vierges (réponse=None => "non répondu"), format JSON-sérialisable."""
    items = []
    for code_section, nom_section, libelles in SECTIONS:
        for libelle in libelles:
            items.append({
                "section": nom_section, "item": libelle,
                "reponse": None, "commentaire": "",
            })
    return items


def items_non_repondus(grille):
    return [it for it in grille if not it.get("reponse")]


def calculer_score(grille):
    """Proportion d'items conformes parmi les items applicables (conforme + non_conforme).
    Les items non_applicable ou non répondus sont exclus du dénominateur. Retourne None si
    aucun item applicable (grille entièrement non_applicable/non répondue)."""
    applicables = [it for it in grille if it.get("reponse") in ("conforme", "non_conforme")]
    if not applicables:
        return None
    conformes = sum(1 for it in applicables if it["reponse"] == "conforme")
    return round(100 * conformes / len(applicables))
