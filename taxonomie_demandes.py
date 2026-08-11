"""
Arborescence des démarches ouvertes à l'opérateur.

Une seule déclaration, ici, décrit l'ensemble : les pages, la barre latérale et
le fil d'Ariane s'en déduisent. C'est la leçon du doublon « Nouvelle demande »
qui avait divergé de l'onglet « Demande » — deux descriptions du même menu
finissent toujours par se contredire.

    Demande
    ├── Homologation ── AMM · Reconnaissance/préqualification · ATU
    │                   · Dérogation · Visa technique
    ├── Inspection
    ├── Essai clinique ── Phase I · Phase II · Phase III
    └── Agréments ── Distribution · Fabrication
                     └── Médicaments · Dispositifs médicaux
                         └── Nouvelle demande · Renouvellement · Suspension

Chaque nœud porte soit des `enfants`, soit un `lien` terminal. Un nœud sans
lien ni enfants serait une impasse : `verifier_arborescence()` le signale, et
le test correspondant échoue.
"""

# Domaines et catégories des agréments d'établissement.
DOMAINES_AGREMENT = {
    "distribution": "Distribution",
    "fabrication": "Fabrication",
}
CATEGORIES_AGREMENT = {
    "medicaments": "Médicaments",
    "dispositifs_medicaux": "Dispositifs médicaux",
}
ACTES_AGREMENT = {
    "nouvelle": ("Nouvelle demande",
                 "Solliciter un agrément que votre établissement ne détient pas."),
    "renouvellement": ("Renouvellement",
                       "Prolonger un agrément en vigueur avant son échéance."),
    "suspension": ("Suspension",
                   "Demander la suspension volontaire de votre agrément — arrêt "
                   "temporaire d'activité, transfert de site, cessation d'une "
                   "ligne de production."),
}


def _feuilles_agrement(domaine, categorie):
    """Les trois actes ouverts sur un couple domaine × catégorie."""
    return [
        {"code": acte, "libelle": libelle, "description": description,
         "icone": {"nouvelle": "bi-plus-circle",
                   "renouvellement": "bi-arrow-repeat",
                   "suspension": "bi-pause-circle"}[acte],
         "couleur": {"nouvelle": "primary", "renouvellement": "info",
                     "suspension": "warning"}[acte],
         "lien": ("/demandes/agrements/" + domaine + "/" + categorie
                  + "/" + acte)}
        for acte, (libelle, description) in ACTES_AGREMENT.items()
    ]


def _categories_agrement(domaine):
    return [
        {"code": categorie, "libelle": libelle,
         "description": ("Produits pharmaceutiques à usage humain."
                         if categorie == "medicaments"
                         else "Dispositifs médicaux et diagnostics in vitro."),
         "icone": ("bi-capsule" if categorie == "medicaments"
                   else "bi-heart-pulse"),
         "couleur": "primary" if categorie == "medicaments" else "success",
         "enfants": _feuilles_agrement(domaine, categorie)}
        for categorie, libelle in CATEGORIES_AGREMENT.items()
    ]


ARBORESCENCE = [
    {
        "code": "homologation",
        "libelle": "Homologation",
        "description": "Autoriser la mise sur le marché d'un produit, ou faire "
                       "viser un acte qui s'y rattache.",
        "icone": "bi-file-earmark-medical", "couleur": "primary",
        "enfants": [
            {"code": "amm", "libelle": "AMM",
             "description": "Autorisation de mise sur le marché : nouvelle "
                            "demande, renouvellement, variation ou retrait.",
             "icone": "bi-patch-check", "couleur": "primary",
             "lien": "/demandes/amm"},
            {"code": "reconnaissance", "libelle": "Reconnaissance et "
                                        "préqualification",
             "description": "S'appuyer sur l'autorisation délivrée par une "
                            "autorité de référence, ou sur la préqualification "
                            "de l'OMS. Dossier allégé, délai raccourci.",
             "icone": "bi-award", "couleur": "info",
             "lien": "/homologation/voies"},
            {"code": "atu", "libelle": "Autorisation temporaire d'utilisation",
             "description": "Accéder à un produit dépourvu d'AMM pour un "
                            "patient nommément désigné, ou pour une cohorte, "
                            "lorsque aucun traitement approprié n'existe.",
             "icone": "bi-heart-pulse", "couleur": "danger",
             "lien": "/atu/"},
            {"code": "derogation", "libelle": "Dérogation",
             "description": "Dérogation à titre exceptionnel : importation "
                            "d'urgence, produit non homologué, situation "
                            "sanitaire particulière.",
             "icone": "bi-shield-exclamation", "couleur": "warning",
             "lien": "/derogations/nouvelle"},
            {"code": "visa_technique", "libelle": "Visa technique",
             "description": "Faire viser un document technique par la Direction "
                            "de la Pharmacie.",
             "icone": "bi-stamp", "couleur": "success",
             "lien": "/visas/nouvelle"},
        ],
    },
    {
        "code": "inspection",
        "libelle": "Inspection",
        "description": "Solliciter la venue de l'autorité sur un site de "
                       "fabrication, au Cameroun ou à l'étranger.",
        "icone": "bi-clipboard-check", "couleur": "success",
        "lien": "/industriel/inspections",
    },
    {
        "code": "essai_clinique",
        "libelle": "Essai clinique",
        "description": "Déposer un protocole de recherche clinique. Les pièces "
                       "attendues dépendent de la phase.",
        "icone": "bi-clipboard2-pulse", "couleur": "info",
        "enfants": [
            {"code": "phase-1", "libelle": "Phase I",
             "description": "Première administration à l'être humain : "
                            "tolérance, sécurité, pharmacocinétique.",
             "icone": "bi-1-circle", "couleur": "danger",
             "lien": "/demandes/essai-clinique/phase-1"},
            {"code": "phase-2", "libelle": "Phase II",
             "description": "Recherche de la dose efficace et première "
                            "évaluation de l'efficacité.",
             "icone": "bi-2-circle", "couleur": "warning",
             "lien": "/demandes/essai-clinique/phase-2"},
            {"code": "phase-3", "libelle": "Phase III",
             "description": "Confirmation de l'efficacité sur un large "
                            "effectif, comparaison au traitement de référence.",
             "icone": "bi-3-circle", "couleur": "info",
             "lien": "/demandes/essai-clinique/phase-3"},
        ],
    },
    {
        "code": "agrements",
        "libelle": "Agréments",
        "description": "Agrément d'établissement, par domaine d'activité et "
                       "par catégorie de produits.",
        "icone": "bi-building-check", "couleur": "secondary",
        "enfants": [
            {"code": domaine, "libelle": libelle,
             "description": ("Importation, stockage et distribution en gros."
                             if domaine == "distribution"
                             else "Production, conditionnement et contrôle en "
                                  "site industriel."),
             "icone": ("bi-truck" if domaine == "distribution"
                       else "bi-gear-wide-connected"),
             "couleur": "secondary",
             "enfants": _categories_agrement(domaine)}
            for domaine, libelle in DOMAINES_AGREMENT.items()
        ],
    },
]


# ---------------------------------------------------------------------------
# Parcours de l'arborescence
# ---------------------------------------------------------------------------
def noeud(chemin):
    """Nœud désigné par une suite de codes, ou None. `chemin` : liste de codes."""
    niveau, trouve = ARBORESCENCE, None
    for code in chemin:
        trouve = next((n for n in niveau if n["code"] == code), None)
        if trouve is None:
            return None
        niveau = trouve.get("enfants", [])
    return trouve


def enfants_avec_liens(chemin):
    """Enfants d'un nœud, chacun muni de l'adresse où le suivre.

    Un nœud terminal porte son propre lien ; un nœud intermédiaire renvoie vers
    la page de rubrique correspondante. Résoudre cela ici plutôt que dans le
    gabarit évite d'y recopier la règle.
    """
    niveau = ARBORESCENCE if not chemin else (noeud(chemin) or {}).get("enfants", [])
    resultat = []
    for n in niveau:
        copie = dict(n)
        copie["href"] = n.get("lien") or (
            "/demandes/rubrique/" + "/".join(chemin + [n["code"]]))
        copie["terminal"] = not n.get("enfants")
        resultat.append(copie)
    return resultat


def fil_ariane(chemin):
    """Suite (libellé, url) des ancêtres, du plus général au nœud courant."""
    fil, courant = [], []
    for code in chemin:
        courant.append(code)
        n = noeud(courant)
        if n is None:
            break
        fil.append((n["libelle"],
                    n.get("lien") or "/demandes/rubrique/" + "/".join(courant)))
    return fil


def feuilles(noeuds=None):
    """Toutes les démarches terminales, à plat — support des tests et du contrôle."""
    resultat = []
    for n in (ARBORESCENCE if noeuds is None else noeuds):
        if n.get("enfants"):
            resultat.extend(feuilles(n["enfants"]))
        else:
            resultat.append(n)
    return resultat


def verifier_arborescence():
    """Anomalies structurelles : impasses, doublons, liens manquants."""
    anomalies = []

    def parcourir(noeuds, prefixe):
        codes = [n["code"] for n in noeuds]
        for code in set(codes):
            if codes.count(code) > 1:
                anomalies.append(f"code dupliqué : {'/'.join(prefixe + [code])}")
        for n in noeuds:
            chemin = prefixe + [n["code"]]
            if not n.get("enfants") and not n.get("lien"):
                anomalies.append(f"impasse : {'/'.join(chemin)}")
            if n.get("enfants") and n.get("lien"):
                anomalies.append(
                    f"nœud à la fois intermédiaire et terminal : {'/'.join(chemin)}")
            if not n.get("libelle") or not n.get("description"):
                anomalies.append(f"libellé ou description manquant : {'/'.join(chemin)}")
            parcourir(n.get("enfants", []), chemin)

    parcourir(ARBORESCENCE, [])
    return anomalies
