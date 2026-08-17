"""
Référentiels pharmaceutiques : formes, unités, voies, classes, indications.

Ces listes remplacent des champs de saisie libre. Le gain n'est pas cosmétique :
tant que la forme pharmaceutique se tape à la main, « comprimé pelliculé »,
« Comprimé Pelliculé » et « cp pelliculé » désignent le même objet sans que
personne ne puisse les rapprocher — ni pour la reliance, ni pour la
pharmacovigilance, ni pour une statistique.

SOURCES
-------
Formes et voies : EDQM Standard Terms, référentiel européen adopté par l'OMS
et par la plupart des autorités africaines. Les intitulés sont donnés en
français, dans la forme retenue par la Pharmacopée européenne.

Classes thérapeutiques : classification ATC de l'OMS, niveau 1 (groupe
anatomique) et niveau 2 (groupe thérapeutique principal). On s'arrête au
niveau 2 : descendre au niveau 5 obligerait le déposant à connaître le code
exact de sa molécule, ce que l'instruction établira de toute façon.

CE QUI EST ASSUMÉ
-----------------
Les listes sont représentatives, non exhaustives : l'EDQM compte plus de mille
termes et l'ATC plusieurs milliers de codes. Elles couvrent ce qu'un dossier
camerounais présente en pratique, et chacune se complète sans toucher au code
qui l'utilise. Un champ « autre, à préciser » évite qu'une forme absente ne
bloque un dépôt légitime.
"""

# ---------------------------------------------------------------------------
# Formes pharmaceutiques (EDQM Standard Terms)
# ---------------------------------------------------------------------------
FORMES_PHARMACEUTIQUES = {
    "Formes orales solides": [
        "Comprimé",
        "Comprimé pelliculé",
        "Comprimé enrobé",
        "Comprimé effervescent",
        "Comprimé orodispersible",
        "Comprimé dispersible",
        "Comprimé sublingual",
        "Comprimé à libération prolongée",
        "Comprimé à libération modifiée",
        "Comprimé gastro-résistant",
        "Gélule",
        "Gélule à libération prolongée",
        "Gélule gastro-résistante",
        "Capsule molle",
        "Granulés",
        "Granulés effervescents",
        "Poudre orale",
        "Poudre pour solution buvable",
        "Poudre pour suspension buvable",
        "Pastille",
        "Gomme à mâcher médicamenteuse",
    ],
    "Formes orales liquides": [
        "Sirop",
        "Solution buvable",
        "Suspension buvable",
        "Émulsion buvable",
        "Gouttes buvables",
        "Solution buvable en sachet-dose",
    ],
    "Formes injectables et perfusions": [
        "Solution injectable",
        "Suspension injectable",
        "Émulsion injectable",
        "Poudre pour solution injectable",
        "Poudre pour suspension injectable",
        "Lyophilisat pour usage parentéral",
        "Solution pour perfusion",
        "Solution à diluer pour perfusion",
        "Poudre pour solution pour perfusion",
    ],
    "Formes ophtalmiques et auriculaires": [
        "Collyre en solution",
        "Collyre en suspension",
        "Pommade ophtalmique",
        "Gel ophtalmique",
        "Solution pour lavage ophtalmique",
        "Gouttes auriculaires",
        "Solution auriculaire",
    ],
    "Formes cutanées": [
        "Pommade",
        "Crème",
        "Gel",
        "Lotion",
        "Solution pour application cutanée",
        "Poudre pour application cutanée",
        "Shampooing médicamenteux",
        "Patch transdermique",
        "Emplâtre médicamenteux",
    ],
    "Formes rectales et vaginales": [
        "Suppositoire",
        "Solution rectale",
        "Pommade rectale",
        "Ovule",
        "Comprimé vaginal",
        "Capsule vaginale",
        "Gel vaginal",
        "Dispositif intra-utérin",
    ],
    "Formes inhalées et nasales": [
        "Poudre pour inhalation",
        "Solution pour inhalation par nébuliseur",
        "Suspension pour inhalation en flacon pressurisé",
        "Aérosol pour inhalation",
        "Spray nasal",
        "Gouttes nasales",
        "Poudre nasale",
    ],
    "Autres formes": [
        "Implant",
        "Solution pour irrigation",
        "Gaz médicinal",
        "Trousse radiopharmaceutique",
        "Autre — à préciser",
    ],
}

# Liste à plat, pour la validation.
FORMES_A_PLAT = [f for groupe in FORMES_PHARMACEUTIQUES.values() for f in groupe]


# ---------------------------------------------------------------------------
# Unités de dosage
# ---------------------------------------------------------------------------
# Groupées par grandeur : mélanger des masses et des volumes dans une même
# liste déroulante conduit à choisir « mL » là où « mg » était attendu.
UNITES_DOSAGE = {
    "Masse": ["ng", "µg", "mg", "g", "kg"],
    "Volume": ["µL", "mL", "L"],
    "Activité biologique": ["UI", "UI/mL", "UFC", "UFC/mL", "Dose vaccinale"],
    "Concentration": ["%", "mg/mL", "mg/g", "µg/mL", "g/L", "mEq", "mmol",
                      "mmol/L"],
    "Par dose": ["µg/dose", "mg/dose", "UI/dose"],
}

UNITES_A_PLAT = [u for groupe in UNITES_DOSAGE.values() for u in groupe]


# ---------------------------------------------------------------------------
# Voies d'administration (EDQM)
# ---------------------------------------------------------------------------
VOIES_ADMINISTRATION = [
    "Orale",
    "Sublinguale",
    "Buccogingivale",
    "Intraveineuse",
    "Intramusculaire",
    "Sous-cutanée",
    "Intradermique",
    "Intrathécale",
    "Intra-articulaire",
    "Intrapéritonéale",
    "Cutanée",
    "Transdermique",
    "Ophtalmique",
    "Auriculaire",
    "Nasale",
    "Inhalée",
    "Rectale",
    "Vaginale",
    "Urétrale",
    "Intravésicale",
    "Épidurale",
    "Autre — à préciser",
]


# ---------------------------------------------------------------------------
# Classes thérapeutiques (ATC, niveaux 1 et 2)
# ---------------------------------------------------------------------------
# code → (libellé, groupe anatomique de niveau 1)
CLASSES_ATC = {
    "A02": ("Antiacides, antiulcéreux et antiflatulents", "A — Voies digestives et métabolisme"),
    "A03": ("Antispasmodiques et anticholinergiques", "A — Voies digestives et métabolisme"),
    "A06": ("Laxatifs", "A — Voies digestives et métabolisme"),
    "A07": ("Antidiarrhéiques et anti-infectieux intestinaux", "A — Voies digestives et métabolisme"),
    "A10": ("Antidiabétiques", "A — Voies digestives et métabolisme"),
    "A11": ("Vitamines", "A — Voies digestives et métabolisme"),
    "A12": ("Suppléments minéraux", "A — Voies digestives et métabolisme"),
    "B01": ("Antithrombotiques", "B — Sang et organes hématopoïétiques"),
    "B02": ("Antihémorragiques", "B — Sang et organes hématopoïétiques"),
    "B03": ("Antianémiques", "B — Sang et organes hématopoïétiques"),
    "B05": ("Substituts du sang et solutions de perfusion", "B — Sang et organes hématopoïétiques"),
    "C01": ("Médicaments en cardiologie", "C — Système cardiovasculaire"),
    "C02": ("Antihypertenseurs", "C — Système cardiovasculaire"),
    "C03": ("Diurétiques", "C — Système cardiovasculaire"),
    "C07": ("Bêtabloquants", "C — Système cardiovasculaire"),
    "C08": ("Inhibiteurs calciques", "C — Système cardiovasculaire"),
    "C09": ("Médicaments agissant sur le système rénine-angiotensine", "C — Système cardiovasculaire"),
    "C10": ("Hypolipidémiants", "C — Système cardiovasculaire"),
    "D01": ("Antifongiques à usage dermatologique", "D — Dermatologie"),
    "D06": ("Antibiotiques et chimiothérapie à usage dermatologique", "D — Dermatologie"),
    "D07": ("Corticoïdes à usage dermatologique", "D — Dermatologie"),
    "G01": ("Anti-infectieux et antiseptiques gynécologiques", "G — Système génito-urinaire"),
    "G03": ("Hormones sexuelles", "G — Système génito-urinaire"),
    "G04": ("Médicaments urologiques", "G — Système génito-urinaire"),
    "H02": ("Corticoïdes à usage systémique", "H — Hormones systémiques"),
    "H03": ("Traitement de la thyroïde", "H — Hormones systémiques"),
    "J01": ("Antibactériens à usage systémique", "J — Anti-infectieux à usage systémique"),
    "J02": ("Antimycosiques à usage systémique", "J — Anti-infectieux à usage systémique"),
    "J04": ("Antimycobactériens (antituberculeux, antilépreux)", "J — Anti-infectieux à usage systémique"),
    "J05": ("Antiviraux à usage systémique", "J — Anti-infectieux à usage systémique"),
    "J06": ("Immunsérums et immunoglobulines", "J — Anti-infectieux à usage systémique"),
    "J07": ("Vaccins", "J — Anti-infectieux à usage systémique"),
    "L01": ("Antinéoplasiques", "L — Antinéoplasiques et immunomodulateurs"),
    "L02": ("Thérapeutique endocrine", "L — Antinéoplasiques et immunomodulateurs"),
    "L03": ("Immunostimulants", "L — Antinéoplasiques et immunomodulateurs"),
    "L04": ("Immunosuppresseurs", "L — Antinéoplasiques et immunomodulateurs"),
    "M01": ("Anti-inflammatoires et antirhumatismaux", "M — Muscle et squelette"),
    "M02": ("Topiques pour douleurs articulaires", "M — Muscle et squelette"),
    "M03": ("Myorelaxants", "M — Muscle et squelette"),
    "M04": ("Antigoutteux", "M — Muscle et squelette"),
    "N01": ("Anesthésiques", "N — Système nerveux"),
    "N02": ("Analgésiques", "N — Système nerveux"),
    "N03": ("Antiépileptiques", "N — Système nerveux"),
    "N05": ("Psycholeptiques", "N — Système nerveux"),
    "N06": ("Psychoanaleptiques", "N — Système nerveux"),
    "P01": ("Antiprotozoaires (dont antipaludiques)", "P — Antiparasitaires"),
    "P02": ("Anthelminthiques", "P — Antiparasitaires"),
    "P03": ("Ectoparasiticides", "P — Antiparasitaires"),
    "R01": ("Préparations nasales", "R — Système respiratoire"),
    "R03": ("Médicaments pour les syndromes obstructifs des voies aériennes", "R — Système respiratoire"),
    "R05": ("Médicaments du rhume et de la toux", "R — Système respiratoire"),
    "R06": ("Antihistaminiques à usage systémique", "R — Système respiratoire"),
    "S01": ("Médicaments ophtalmologiques", "S — Organes sensoriels"),
    "S02": ("Médicaments otologiques", "S — Organes sensoriels"),
    "V03": ("Autres produits thérapeutiques", "V — Divers"),
    "V08": ("Produits de contraste", "V — Divers"),
}


def classes_par_groupe():
    """Classes ATC groupées par groupe anatomique, pour l'affichage."""
    groupes = {}
    for code, (libelle, groupe) in CLASSES_ATC.items():
        groupes.setdefault(groupe, []).append((code, f"{code} — {libelle}"))
    return dict(sorted(groupes.items()))


# ---------------------------------------------------------------------------
# Indications thérapeutiques
# ---------------------------------------------------------------------------
# Liste amorçable, rattachable à la CIM le jour où le référentiel sera chargé.
# Les priorités de santé publique camerounaises viennent en tête : ce sont
# celles qu'un déposant rencontrera le plus souvent.
INDICATIONS = [
    "Paludisme",
    "Tuberculose",
    "Infection à VIH",
    "Hépatite virale B",
    "Hépatite virale C",
    "Infections bactériennes",
    "Infections fongiques",
    "Parasitoses intestinales",
    "Diarrhée aiguë",
    "Déshydratation",
    "Malnutrition",
    "Anémie",
    "Drépanocytose",
    "Hypertension artérielle",
    "Insuffisance cardiaque",
    "Diabète de type 1",
    "Diabète de type 2",
    "Asthme",
    "Bronchopneumopathie chronique obstructive",
    "Douleur aiguë",
    "Douleur chronique",
    "Fièvre",
    "Inflammation",
    "Épilepsie",
    "Troubles anxieux",
    "Dépression",
    "Troubles psychotiques",
    "Ulcère gastroduodénal",
    "Reflux gastro-œsophagien",
    "Cancers",
    "Immunodépression",
    "Contraception",
    "Prééclampsie",
    "Hémorragie du post-partum",
    "Carences vitaminiques",
    "Affections dermatologiques",
    "Affections ophtalmologiques",
    "Prévention vaccinale",
    "Autre — à préciser",
]


# ---------------------------------------------------------------------------
# Unités de durée
# ---------------------------------------------------------------------------
UNITES_DUREE = ["jours", "semaines", "mois", "années"]


# ---------------------------------------------------------------------------
# Conditionnements primaires
# ---------------------------------------------------------------------------
CONDITIONNEMENTS = [
    "Plaquette thermoformée (blister)",
    "Flacon en verre",
    "Flacon en polyéthylène",
    "Ampoule",
    "Seringue préremplie",
    "Sachet",
    "Tube",
    "Pot",
    "Poche",
    "Boîte",
    "Autre — à préciser",
]


# ---------------------------------------------------------------------------
# Parties utilisées — spécifique aux médicaments traditionnels améliorés
# ---------------------------------------------------------------------------
PARTIES_UTILISEES = [
    "Feuille",
    "Écorce de tige",
    "Écorce de racine",
    "Racine",
    "Rhizome",
    "Tige",
    "Fleur",
    "Fruit",
    "Graine",
    "Bulbe",
    "Plante entière",
    "Latex",
    "Résine",
    "Huile essentielle",
    "Extrait total",
    "Autre — à préciser",
]

# Catégories réglementaires des médicaments traditionnels améliorés.
CATEGORIES_MTA = [
    "Catégorie 1 — usage traditionnel documenté, sans transformation",
    "Catégorie 2 — préparation améliorée, forme galénique standardisée",
    "Catégorie 3 — extrait standardisé, dosage en marqueur défini",
    "Catégorie 4 — substance isolée d'origine végétale",
]


def valider_choix(valeur, liste, champ):
    """Vérifie qu'une valeur appartient au référentiel. Retourne un message ou None.

    Le contrôle se fait au serveur et pas seulement dans la liste déroulante :
    un formulaire se contourne, et une valeur hors référentiel réintroduirait
    exactement la saisie libre qu'on cherche à supprimer.
    """
    if valeur in liste:
        return None
    return (f"« {valeur} » n'appartient pas au référentiel {champ}. "
            "Choisissez une valeur dans la liste.")
