"""
Dossier technique commun (CTD) : modules, champs à renseigner et obligations.

DEUX NOTIONS DISTINCTES
-----------------------
* La NATURE du produit (chimique, biologique, phytothérapie…) détermine la
  profondeur du dossier attendu : un biosimilaire exige les cinq modules, un
  générique chimique s'en tient aux trois premiers.
* Le TYPE DE DEMANDE (nouvelle demande, renouvellement, variation, retrait)
  module cette exigence : un renouvellement ne redemande pas l'intégralité du
  dossier déjà évalué.

La matrice ci-dessous croise les deux. Elle est déclarative : ajuster une
exigence réglementaire ne demande aucune reprise de code.

⚠ Les combinaisons retenues sont une PROPOSITION DE TRAVAIL, à valider par la
DPML au regard de la réglementation applicable.
"""

# ---------------------------------------------------------------------------
# Nature du produit — pilote la profondeur du dossier
# ---------------------------------------------------------------------------
NATURES_PRODUIT = {
    "chimique": {
        "libelle": "Médicament chimique",
        "description": "Principe actif de synthèse — générique, hybride ou nouvelle "
                       "entité chimique.",
        "icone": "bi-capsule",
    },
    "biologique": {
        "libelle": "Médicament biologique",
        "description": "Vaccin, produit sanguin, biotechnologie ou biosimilaire — "
                       "dossier le plus exigeant.",
        "icone": "bi-virus",
    },
    "phytotherapie": {
        "libelle": "Médicament à base de plantes",
        "description": "Préparation d'origine végétale, usage traditionnel reconnu.",
        "icone": "bi-flower1",
    },
    "dispositif_medical": {
        "libelle": "Dispositif médical",
        "description": "Dispositif, réactif ou consommable médical.",
        "icone": "bi-bandaid",
    },
    "autre": {
        "libelle": "Autre produit de santé",
        "description": "Complément, cosmétique réglementé ou produit non classé "
                       "ci-dessus.",
        "icone": "bi-box",
    },
}

# Correspondance avec la catégorie déjà portée par le produit
CATEGORIE_VERS_NATURE = {
    "medicament": "chimique",
    "vaccin": "biologique",
    "produit_sanguin": "biologique",
    "dispositif_medical": "dispositif_medical",
    "autre": "autre",
}


# ---------------------------------------------------------------------------
# Les cinq modules du CTD, et les champs attendus dans chacun
# ---------------------------------------------------------------------------
# (code, libellé, type) — type : texte | zone | nombre | date | liste:a|b|c
MODULES = {
    1: {
        "titre": "Renseignements administratifs",
        "resume": "Identité du demandeur, du produit et statut réglementaire.",
        "champs": [
            ("denomination_produit", "Dénomination du produit", "texte"),
            ("dci", "Dénomination commune internationale (DCI)", "texte"),
            ("forme_pharmaceutique", "Forme pharmaceutique", "texte"),
            ("dosage", "Dosage / concentration", "texte"),
            ("presentation", "Présentation et conditionnement", "texte"),
            ("classe_therapeutique", "Classe thérapeutique / code ATC", "texte"),
            ("titulaire", "Titulaire de l'AMM", "texte"),
            ("fabricant", "Fabricant et site de fabrication", "zone"),
            ("pays_origine", "Pays d'origine", "texte"),
            ("statut_pays_origine", "Statut de l'AMM dans le pays d'origine",
             "liste:autorisé|en cours|non commercialisé|retiré"),
            ("cpp_numero", "N° du certificat de produit pharmaceutique (CPP)", "texte"),
            ("cpp_date", "Date de délivrance du CPP", "date"),
            ("representant_local", "Représentant local au Cameroun", "texte"),
        ],
    },
    2: {
        "titre": "Résumés du dossier",
        "resume": "Synthèses qualité, non clinique et clinique, et information produit.",
        "champs": [
            ("resume_qualite", "Résumé global de la qualité", "zone"),
            ("apercu_non_clinique", "Aperçu non clinique", "zone"),
            ("apercu_clinique", "Aperçu clinique", "zone"),
            ("rcp", "Résumé des caractéristiques du produit (RCP) proposé", "zone"),
            ("notice", "Notice destinée au patient", "zone"),
            ("etiquetage", "Projet d'étiquetage", "zone"),
        ],
    },
    3: {
        "titre": "Qualité pharmaceutique",
        "resume": "Substance active, produit fini, contrôles et stabilité.",
        "champs": [
            ("substance_fabricant", "Fabricant de la substance active", "texte"),
            ("substance_specifications", "Spécifications de la substance active", "zone"),
            ("substance_methodes", "Méthodes analytiques de la substance active", "zone"),
            ("composition", "Composition qualitative et quantitative", "zone"),
            ("procede_fabrication", "Procédé de fabrication du produit fini", "zone"),
            ("controle_excipients", "Contrôle des excipients", "zone"),
            ("specifications_produit_fini", "Spécifications du produit fini", "zone"),
            ("conditionnement_primaire", "Conditionnement primaire", "texte"),
            ("stabilite_conditions", "Conditions des études de stabilité",
             "liste:zone climatique IVb (30°C/75%HR)|zone climatique IVa|zone II|autre"),
            ("stabilite_duree", "Durée de conservation revendiquée (mois)", "nombre"),
            ("stabilite_resultats", "Résultats des études de stabilité", "zone"),
        ],
    },
    4: {
        "titre": "Rapports non cliniques",
        "resume": "Pharmacologie, pharmacocinétique et toxicologie.",
        "champs": [
            ("pharmacologie", "Pharmacologie primaire et secondaire", "zone"),
            ("pharmacocinetique", "Pharmacocinétique (ADME)", "zone"),
            ("toxicite_dose_unique", "Toxicité à dose unique", "zone"),
            ("toxicite_doses_repetees", "Toxicité à doses répétées", "zone"),
            ("genotoxicite", "Génotoxicité", "zone"),
            ("carcinogenicite", "Carcinogénicité", "zone"),
            ("reprotoxicite", "Toxicité pour la reproduction et le développement", "zone"),
            ("tolerance_locale", "Tolérance locale", "zone"),
        ],
    },
    5: {
        "titre": "Rapports cliniques",
        "resume": "Biodisponibilité, essais cliniques et gestion des risques.",
        "champs": [
            ("bioequivalence", "Études de bioéquivalence / biodisponibilité", "zone"),
            ("etudes_phase_1", "Études de phase I (tolérance)", "zone"),
            ("etudes_phase_2", "Études de phase II (efficacité exploratoire)", "zone"),
            ("etudes_phase_3", "Études de phase III (efficacité confirmatoire)", "zone"),
            ("comparabilite", "Exercice de comparabilité (biosimilaires)", "zone"),
            ("immunogenicite", "Données d'immunogénicité", "zone"),
            ("securite_clinique", "Synthèse de sécurité clinique", "zone"),
            ("plan_gestion_risques", "Plan de gestion des risques", "zone"),
            ("psur", "Rapports périodiques de sécurité (PSUR) disponibles", "zone"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Matrice des modules obligatoires : (nature, type de demande) → modules
# ---------------------------------------------------------------------------
MATRICE = {
    # Médicament chimique
    ("chimique", "nouvelle_demande"): [1, 2, 3],
    ("chimique", "renouvellement"): [1],
    ("chimique", "variation"): [1, 3],
    ("chimique", "retrait"): [1],
    # Médicament biologique — dossier complet exigé
    ("biologique", "nouvelle_demande"): [1, 2, 3, 4, 5],
    ("biologique", "renouvellement"): [1, 3],
    ("biologique", "variation"): [1, 3, 5],
    ("biologique", "retrait"): [1],
    # Plantes — dossier allégé sur le non-clinique
    ("phytotherapie", "nouvelle_demande"): [1, 2, 3],
    ("phytotherapie", "renouvellement"): [1],
    ("phytotherapie", "variation"): [1, 3],
    ("phytotherapie", "retrait"): [1],
    # Dispositifs médicaux — pas de module clinique classique
    ("dispositif_medical", "nouvelle_demande"): [1, 3],
    ("dispositif_medical", "renouvellement"): [1],
    ("dispositif_medical", "variation"): [1, 3],
    ("dispositif_medical", "retrait"): [1],
    # Autres produits
    ("autre", "nouvelle_demande"): [1, 3],
    ("autre", "renouvellement"): [1],
    ("autre", "variation"): [1, 3],
    ("autre", "retrait"): [1],
}

DEFAUT = [1, 2, 3]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def nature_du_produit(produit):
    """Nature retenue pour un produit, dérivée de sa catégorie."""
    if produit is None:
        return "chimique"
    nature = getattr(produit, "nature", None)
    if nature in NATURES_PRODUIT:
        return nature
    return CATEGORIE_VERS_NATURE.get(produit.categorie, "chimique")


def modules_obligatoires(nature, type_demande):
    return MATRICE.get((nature, type_demande), DEFAUT)


def modules_du_dossier(dossier):
    """Modules exigés pour ce dossier précis."""
    return modules_obligatoires(nature_du_produit(dossier.produit),
                                dossier.type_procedure)


def champs(numero):
    return MODULES[numero]["champs"]


def titre(numero):
    return MODULES[numero]["titre"]


def options_liste(type_champ):
    """Options d'un champ de type `liste:a|b|c`."""
    if not type_champ.startswith("liste:"):
        return []
    return type_champ.split(":", 1)[1].split("|")


def module_complet(dossier, numero):
    """Un module est complet si tous ses champs sont renseignés."""
    donnees = lire_module(dossier, numero)
    return all((donnees.get(code) or "").strip()
               for code, _libelle, _type in champs(numero))


def lire_module(dossier, numero):
    import json
    brut = getattr(dossier, f"module_ctd_{numero}_json", None) or "{}"
    try:
        valeur = json.loads(brut)
        return valeur if isinstance(valeur, dict) else {}
    except (ValueError, TypeError):
        return {}


def ecrire_module(dossier, numero, donnees):
    import json
    setattr(dossier, f"module_ctd_{numero}_json",
            json.dumps(donnees, ensure_ascii=False))


def progression(dossier):
    """(modules complétés, modules exigés) pour ce dossier."""
    exiges = modules_du_dossier(dossier)
    faits = sum(1 for n in exiges if module_complet(dossier, n))
    return faits, len(exiges)


def module_suivant(dossier, apres=None):
    """Prochain module exigé restant à compléter."""
    for n in modules_du_dossier(dossier):
        if apres is not None and n <= apres:
            continue
        if not module_complet(dossier, n):
            return n
    return None


def dossier_technique_complet(dossier):
    faits, total = progression(dossier)
    return total > 0 and faits == total


def apercu_matrice():
    """Matrice lisible, pour l'écran d'aide et l'administration."""
    from workflow_ma import TYPES_PROCEDURE
    lignes = []
    for nature, meta in NATURES_PRODUIT.items():
        ligne = {"nature": nature, "libelle": meta["libelle"], "exigences": {}}
        for type_demande in TYPES_PROCEDURE:
            ligne["exigences"][type_demande] = modules_obligatoires(nature, type_demande)
        lignes.append(ligne)
    return lignes
