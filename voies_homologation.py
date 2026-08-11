"""
Voies d'homologation : par quel chemin une AMM est instruite.

Une même autorisation peut s'obtenir de trois manières, qui diffèrent par ce
que l'administration doit évaluer elle-même :

  NATIONALE       évaluation complète du dossier technique par la DPML.
  RECONNAISSANCE  une autorité de référence a déjà évalué le produit ; la DPML
                  s'appuie sur sa décision et son rapport, et concentre son
                  examen sur ce qui reste national.
  PRÉQUALIFICATION  l'OMS a préqualifié le produit ; même logique, la référence
                  étant le rapport public d'évaluation de l'OMS.

CE QUE LA RELIANCE NE DISPENSE PAS D'EXAMINER
----------------------------------------------
S'appuyer sur une évaluation étrangère n'est pas l'accepter les yeux fermés.
Trois choses restent nationales dans tous les cas :

  * l'identité du produit soumis ici doit être CELLE qui a été évaluée là-bas —
    même formule, même site de fabrication, même dossier ;
  * l'étiquetage, la notice et le conditionnement doivent être conformes aux
    exigences camerounaises et à la langue ;
  * la pertinence de santé publique et la surveillance après mise sur le marché
    relèvent de l'autorité nationale, seule.

C'est pourquoi le module 1 (administratif et national) reste exigé en entier
alors que les modules d'efficacité et de sécurité sont allégés.

DISTINCTION AVEC LA RELIANCE CEEAC
-----------------------------------
`reliance.py` organise l'échange entre autorités de la sous-région : requêtes
de rapports, alertes transfrontalières, partage de décisions entre pairs. Ce
module-ci traite d'autre chose : la reconnaissance, par la DPML, d'une décision
prise par une autorité de référence ou par l'OMS. Les deux se complètent et ne
doivent pas être confondus.
"""

# ---------------------------------------------------------------------------
# Autorités de référence admises
# ---------------------------------------------------------------------------
# Autorités dites « de référence » : celles dont l'OMS reconnaît la maturité
# (niveaux 3 et 4 du Global Benchmarking Tool) et dont les décisions peuvent
# fonder une reconnaissance. La liste est un paramètre de politique
# réglementaire : elle s'allonge ou se restreint par décision de la direction,
# d'où sa présence ici plutôt que dans le code des écrans.
AUTORITES_REFERENCE = {
    "ema": ("Agence européenne des médicaments (EMA)", "Union européenne"),
    "us_fda": ("Food and Drug Administration (US FDA)", "États-Unis"),
    "mhra": ("Medicines and Healthcare products Regulatory Agency (MHRA)",
             "Royaume-Uni"),
    "swissmedic": ("Swissmedic", "Suisse"),
    "health_canada": ("Santé Canada", "Canada"),
    "pmda": ("Pharmaceuticals and Medical Devices Agency (PMDA)", "Japon"),
    "tga": ("Therapeutic Goods Administration (TGA)", "Australie"),
    "anvisa": ("ANVISA", "Brésil"),
    "sahpra": ("South African Health Products Regulatory Authority (SAHPRA)",
               "Afrique du Sud"),
    "nafdac": ("National Agency for Food and Drug Administration and Control "
               "(NAFDAC)", "Nigéria"),
}

# Programmes de préqualification de l'OMS : la référence n'est pas une autorité
# nationale mais l'Organisation elle-même.
PROGRAMMES_OMS = {
    "pq_medicaments": "Préqualification OMS — médicaments",
    "pq_vaccins": "Préqualification OMS — vaccins",
    "pq_diagnostics": "Préqualification OMS — diagnostics in vitro",
    "eul": "Liste d'usage d'urgence de l'OMS (EUL)",
}


# ---------------------------------------------------------------------------
# Les trois voies
# ---------------------------------------------------------------------------
VOIES = {
    "nationale": {
        "libelle": "Évaluation nationale complète",
        "description": "La DPML évalue elle-même l'ensemble du dossier "
                       "technique. Voie de droit commun.",
        "delai_jours": 270,
        "reference_exigee": None,
        "icone": "bi-file-earmark-medical",
    },
    "reconnaissance": {
        "libelle": "Reconnaissance d'une AMM de référence",
        "description": "Le produit est déjà autorisé par une autorité de "
                       "référence. La DPML s'appuie sur son évaluation et "
                       "examine ce qui demeure national.",
        "delai_jours": 90,
        "reference_exigee": "autorite",
        "icone": "bi-award",
    },
    "prequalification": {
        "libelle": "Préqualification OMS",
        "description": "Le produit figure sur une liste de préqualification de "
                       "l'OMS. Le rapport public d'évaluation tient lieu de "
                       "dossier d'efficacité et de sécurité.",
        "delai_jours": 90,
        "reference_exigee": "programme",
        "icone": "bi-globe2",
    },
}

VOIE_PAR_DEFAUT = "nationale"


# ---------------------------------------------------------------------------
# Allègement du dossier technique
# ---------------------------------------------------------------------------
# Modules CTD qui restent exigés selon la voie. Le module 1 (administratif,
# étiquetage, représentant local) n'est JAMAIS allégé : c'est précisément la
# part que l'autorité étrangère n'a pas examinée. Le module 3 (qualité) reste
# demandé en reconnaissance, parce que le site de fabrication desservant le
# Cameroun peut différer de celui qu'a inspecté l'autorité de référence.
MODULES_ALLEGES = {
    "nationale": None,                 # aucune règle propre : matrice habituelle
    "reconnaissance": [1, 3],
    "prequalification": [1],
}

# Pièces propres à la voie, en plus du dossier technique.
PIECES_PAR_VOIE = {
    "nationale": [],
    "reconnaissance": [
        ("decision_reference", "Décision d'autorisation de l'autorité de "
                               "référence, datée et en cours de validité", True),
        ("rapport_evaluation", "Rapport public d'évaluation de l'autorité de "
                               "référence", True),
        ("cpp", "Certificat de produit pharmaceutique (modèle OMS) délivré par "
                "le pays de référence", True),
        ("attestation_identite", "Attestation d'identité du produit : formule, "
                                 "site de fabrication et dossier identiques à "
                                 "ceux évalués par l'autorité de référence", True),
        ("rcp_notice", "Résumé des caractéristiques du produit et notice, "
                       "adaptés au Cameroun", True),
        ("variations_depuis", "Liste des variations approuvées depuis "
                              "l'autorisation initiale", True),
        ("mesures_restrictives", "Déclaration de toute mesure restrictive prise "
                                 "par une autorité, où que ce soit", True),
        ("pgr", "Plan de gestion des risques, adapté au contexte national", False),
    ],
    "prequalification": [
        ("attestation_pq", "Attestation de préqualification en cours de "
                           "validité, avec son numéro de référence", True),
        ("rapport_pq", "Rapport public d'évaluation de l'OMS (WHOPAR)", True),
        ("attestation_identite", "Attestation d'identité du produit : formule et "
                                 "site de fabrication identiques à ceux "
                                 "préqualifiés", True),
        ("rcp_notice", "Étiquetage et notice adaptés au Cameroun", True),
        ("variations_depuis", "Variations approuvées par l'OMS depuis la "
                              "préqualification", True),
        ("pgr", "Plan de gestion des risques, adapté au contexte national", False),
    ],
}

# Ce que l'instruction doit vérifier, quelle que soit la confiance accordée à
# la référence. Ces points figurent sur l'écran de l'évaluateur : la
# reconnaissance abrège l'examen, elle ne le supprime pas.
CONTROLES_NATIONAUX = [
    "La décision de référence est-elle authentique, en cours de validité et "
    "non restreinte ?",
    "Le produit soumis est-il identique à celui qu'a évalué la référence "
    "(formule, dosage, forme, site de fabrication) ?",
    "L'étiquetage, la notice et le conditionnement sont-ils conformes aux "
    "exigences nationales et linguistiques ?",
    "Le produit répond-il à un besoin de santé publique au Cameroun ?",
    "Le titulaire dispose-t-il d'un représentant local identifié et joignable ?",
    "Les engagements de pharmacovigilance sont-ils souscrits pour le "
    "territoire national ?",
]


def voie_valide(code):
    return code in VOIES


def libelle_reference(voie, autorite=None, programme=None):
    """Désignation lisible de la décision sur laquelle on s'appuie."""
    if voie == "reconnaissance" and autorite in AUTORITES_REFERENCE:
        nom, pays = AUTORITES_REFERENCE[autorite]
        return f"{nom} — {pays}"
    if voie == "prequalification" and programme in PROGRAMMES_OMS:
        return PROGRAMMES_OMS[programme]
    return None


def modules_exiges(voie, nature, type_procedure):
    """Modules CTD à fournir, une fois l'allègement de la voie appliqué.

    L'allègement ne peut qu'ENLEVER des modules à la matrice nationale, jamais
    en ajouter : une voie abrégée qui exigerait davantage serait un
    contresens, et le contrôle évite qu'une modification de la matrice ne
    produise cet effet par inadvertance.
    """
    import modules_ctd as ctd

    base = ctd.modules_obligatoires(nature, type_procedure)
    autorises = MODULES_ALLEGES.get(voie)
    if autorises is None:
        return base
    return [m for m in base if m in autorises]


def pieces_exigees(voie):
    """Pièces propres à la voie, sous forme de dictionnaires affichables."""
    return [{"code": c, "intitule": i, "obligatoire": o}
            for c, i, o in PIECES_PAR_VOIE.get(voie, [])]


def delai_legal(voie):
    """Délai d'instruction annoncé pour cette voie, en jours."""
    return VOIES.get(voie, VOIES[VOIE_PAR_DEFAUT])["delai_jours"]


def verifier_reference(voie, autorite=None, programme=None):
    """Contrôle la cohérence entre la voie choisie et la référence invoquée.

    Retourne un message d'erreur, ou None si tout est cohérent. Une voie de
    reconnaissance sans décision de référence n'a pas d'objet : elle vaudrait
    dispense d'évaluation sans contrepartie.
    """
    exigee = VOIES.get(voie, {}).get("reference_exigee")
    if exigee == "autorite":
        if autorite not in AUTORITES_REFERENCE:
            return ("Indiquez l'autorité de référence dont vous invoquez la "
                    "décision.")
    elif exigee == "programme":
        if programme not in PROGRAMMES_OMS:
            return "Indiquez le programme de préqualification de l'OMS concerné."
    return None
