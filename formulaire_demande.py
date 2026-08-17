"""
Formulaire de demande : en-tête commun, puis variant selon le type de produit.

DEUX VARIANTS, UNE SEULE DÉCLARATION
------------------------------------
Le type de produit choisi en tête sélectionne un jeu de champs. Un médicament
chimique, biologique ou un vaccin suivent le variant STANDARD ; un médicament
traditionnel amélioré suit le variant MTA, calqué sur le formulaire officiel
d'homologation des médicaments issus de la pharmacopée traditionnelle.

La différence n'est pas cosmétique. Un MTA ne se décrit pas par « N principes
actifs dosés » mais par une liste de constituants végétaux, chacun avec la
partie de la plante employée. Lui imposer la grille du médicament de synthèse
reviendrait à lui faire déclarer ce qu'il n'a pas, et taire ce qu'il a.

LE TYPE PILOTE AUSSI LE DOSSIER TECHNIQUE
------------------------------------------
`dossier_attendu()` dit quel module de constitution suit l'enregistrement :
CTD/eCTD pour les médicaments conventionnels, dossier MTA pour les autres. La
pré-analyse de recevabilité lira l'indicateur de complétude correspondant.

POURQUOI UNE DÉCLARATION ET NON DES FORMULAIRES ÉCRITS À LA MAIN
-----------------------------------------------------------------
Trois écrans devraient sinon rester d'accord : la saisie, la validation
serveur et le récapitulatif. Ils divergent toujours. Ici les trois lisent
`CHAMPS`, et ajouter un champ obligatoire se fait en une ligne.
"""
import re

import referentiels_pharma as ref

# ---------------------------------------------------------------------------
# En-tête : ce qui précède la description du produit
# ---------------------------------------------------------------------------
NATURES_ACTE = {
    "octroi": "Octroi — première autorisation du produit",
    "renouvellement": "Renouvellement — prolongation d'une AMM en vigueur",
    "variation": "Variation — modification d'un produit déjà autorisé",
}

# Type de produit → (libellé, variant de formulaire, type de dossier technique)
TYPES_PRODUIT = {
    "medicament_chimique": (
        "Médicament chimique (synthèse)", "standard", "ctd"),
    "medicament_biologique": (
        "Médicament biologique", "standard", "ctd"),
    "vaccin": (
        "Vaccin", "standard", "ctd"),
    "medicament_traditionnel_ameliore": (
        "Médicament traditionnel amélioré (MTA)", "mta", "mta"),
    "dispositif_medical": (
        "Dispositif médical", "standard", "ctd"),
    "produit_sante": (
        "Autre produit de santé", "standard", "ctd"),
}

# Correspondance avec la `nature` déjà portée par le produit : le nouveau
# vocabulaire ne remplace pas l'ancien, il s'y raccroche.
NATURE_PRODUIT = {
    "medicament_chimique": "chimique",
    "medicament_biologique": "biologique",
    "vaccin": "biologique",
    "medicament_traditionnel_ameliore": "phytotherapie",
    "dispositif_medical": "dispositif_medical",
    "produit_sante": "autre",
}


def variant(type_produit):
    """Jeu de champs à présenter — « standard » ou « mta »."""
    return TYPES_PRODUIT.get(type_produit, TYPES_PRODUIT["medicament_chimique"])[1]


def dossier_attendu(type_produit):
    """Module de constitution qui suit l'enregistrement : « ctd » ou « mta »."""
    return TYPES_PRODUIT.get(type_produit, TYPES_PRODUIT["medicament_chimique"])[2]


def nature_correspondante(type_produit):
    return NATURE_PRODUIT.get(type_produit, "autre")


# ---------------------------------------------------------------------------
# Description des champs
# ---------------------------------------------------------------------------
# (code, libellé, type, obligatoire, aide)
#
# types : texte · texte_long · nombre · liste · liste_groupee · multiliste
#         · nombre_unite · telephone · courriel · montant
CHAMPS_ENTETE = [
    ("nature_acte", "Nature de l'acte", "liste", True,
     "Ce que vous demandez : une première autorisation, sa prolongation ou "
     "la modification d'un produit déjà autorisé."),
    ("type_produit", "Type de médicament / produit", "liste", True,
     "Détermine les informations demandées ci-dessous et le dossier technique "
     "attendu ensuite."),
]

CHAMPS_STANDARD = [
    ("nom_commercial", "Dénomination du produit", "texte", True, ""),
    ("dci", "Dénomination commune internationale (DCI)", "texte", True, ""),
    ("forme_pharmaceutique", "Forme pharmaceutique", "liste_groupee", True, ""),
    ("dosage", "Dosage", "nombre_unite", True,
     "Le nombre et l'unité se saisissent séparément."),
    ("nombre_principes_actifs", "Nombre de principes actifs", "nombre", True,
     "Chaque principe actif fera l'objet d'un groupe de champs."),
    ("classe_therapeutique", "Classe thérapeutique", "liste_groupee", True,
     "Classification ATC de l'OMS."),
    ("voie_administration", "Voie d'administration", "liste", True, ""),
    ("indications", "Indications thérapeutiques", "multiliste", True,
     "Plusieurs indications possibles."),
    ("duree_stabilite", "Durée de stabilité", "nombre_unite", True, ""),
    ("conditionnement", "Conditionnement primaire", "liste", False, ""),
    ("pays_origine", "Pays d'origine", "texte", False, ""),
    ("code_atc", "Code ATC complet", "texte", False,
     "Si vous le connaissez ; l'instruction le confirmera."),
    ("pharmacien_telephone", "Téléphone du pharmacien interlocuteur",
     "telephone", True, ""),
    ("pharmacien_email", "Adresse e-mail du pharmacien interlocuteur",
     "courriel", True, ""),
]

CHAMPS_MTA = [
    ("nom_commercial", "Dénomination spéciale du produit", "texte", True,
     "Nom commercial sous lequel le médicament sera présenté."),
    ("dci", "Dénomination(s) commune(s) / constituants principaux", "texte",
     True, "Noms botaniques ou DCI, séparés par des virgules."),
    ("forme_pharmaceutique", "Forme pharmaceutique", "liste_groupee", True, ""),
    ("dosage", "Dosage", "nombre_unite", True, ""),
    ("conditionnement", "Conditionnement primaire", "liste", True, ""),
    ("quantite", "Quantité par conditionnement", "texte", True,
     "Par exemple : 30 comprimés, 100 mL."),
    ("voie_administration", "Voie d'administration", "liste", True, ""),
    ("nombre_constituants", "Nombre de constituants", "nombre", True,
     "Chaque constituant fera l'objet d'un groupe de champs."),
    ("excipients", "Excipients", "texte_long", False, ""),
    ("categorie_mta", "Catégorie du médicament", "liste", True, ""),
    ("classe_therapeutique", "Classe(s) thérapeutique(s)", "liste_groupee",
     True, ""),
    ("indications", "Indications thérapeutiques", "multiliste", True, ""),
    ("mecanisme_action", "Mécanisme d'action du produit", "texte_long", True,
     "Décrivez le mode d'action revendiqué et les données qui l'appuient."),
    ("adresse_fabricant", "Adresse complète du fabricant", "texte_long", True, ""),
    ("adresse_site_fabrication",
     "Adresse du site de fabrication et de conditionnement", "texte_long",
     True, ""),
    ("adresse_controle_qualite", "Adresse du site de contrôle qualité",
     "texte_long", True, ""),
    ("adresse_demandeur", "Adresse complète du demandeur / futur titulaire",
     "texte_long", True, ""),
    ("exploitant", "Nom et adresse de l'exploitant", "texte_long", True, ""),
    ("representant_cameroun",
     "Nom et adresse du représentant du demandeur au Cameroun", "texte_long",
     True, ""),
    ("duree_stabilite", "Durée de vie du produit", "nombre_unite", True, ""),
    ("prix_grossiste", "Prix grossiste hors taxe du pays d'origine (FCFA)",
     "montant", True, ""),
    ("prix_public", "Prix public au Cameroun (FCFA)", "montant", True, ""),
    ("pharmacien_telephone", "Téléphone du pharmacien interlocuteur",
     "telephone", True, ""),
    ("pharmacien_email", "Adresse e-mail du pharmacien interlocuteur",
     "courriel", True, ""),
]

CHAMPS = {"standard": CHAMPS_STANDARD, "mta": CHAMPS_MTA}

# Référentiel associé à chaque champ de type liste.
REFERENTIELS = {
    "nature_acte": NATURES_ACTE,
    "type_produit": {c: v[0] for c, v in TYPES_PRODUIT.items()},
    "forme_pharmaceutique": ref.FORMES_PHARMACEUTIQUES,
    "classe_therapeutique": None,          # construit par classes_par_groupe()
    "voie_administration": ref.VOIES_ADMINISTRATION,
    "indications": ref.INDICATIONS,
    "conditionnement": ref.CONDITIONNEMENTS,
    "categorie_mta": ref.CATEGORIES_MTA,
}

# Bornes de saisie. Un « nombre de principes actifs » à 400 n'est pas une
# composition : c'est une faute de frappe qui ferait naître 400 groupes de
# champs et rendrait la page inutilisable.
MAX_PRINCIPES_ACTIFS = 20
MAX_CONSTITUANTS = 30


def champs(type_produit):
    """En-tête puis champs du variant correspondant au type de produit."""
    return CHAMPS_ENTETE + CHAMPS[variant(type_produit)]


def champs_obligatoires(type_produit):
    return [c for c, _l, _t, obligatoire, _a in champs(type_produit)
            if obligatoire]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
_TELEPHONE = re.compile(r"^\+?[0-9][0-9\s().-]{6,19}$")
_COURRIEL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _nombre(valeur):
    try:
        return float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None


def valider(donnees):
    """Contrôle une saisie complète. Retourne {code_champ: message}.

    La validation est ici, au serveur, et pas seulement dans le navigateur :
    un formulaire HTML se contourne, et le cahier des charges demande que
    l'enregistrement soit BLOQUÉ si un champ obligatoire manque — pas
    seulement signalé.
    """
    type_produit = (donnees.get("type_produit") or "").strip()
    erreurs = {}

    if type_produit not in TYPES_PRODUIT:
        return {"type_produit": "Choisissez le type de médicament ou de produit."}
    if (donnees.get("nature_acte") or "").strip() not in NATURES_ACTE:
        erreurs["nature_acte"] = "Choisissez la nature de l'acte demandé."

    for code, libelle, type_champ, obligatoire, _aide in champs(type_produit):
        if code in ("nature_acte", "type_produit"):
            continue
        brut = donnees.get(code)
        valeur = (brut or "").strip() if isinstance(brut, str) else brut

        if type_champ == "nombre_unite":
            _valider_nombre_unite(code, libelle, donnees, obligatoire, erreurs)
            continue
        if type_champ == "multiliste":
            choix = donnees.get(code) or []
            if isinstance(choix, str):
                choix = [choix]
            if obligatoire and not choix:
                erreurs[code] = f"{libelle} : sélectionnez au moins une valeur."
            else:
                hors = [c for c in choix if c not in ref.INDICATIONS]
                if hors:
                    erreurs[code] = (f"{libelle} : valeur hors référentiel "
                                     f"({hors[0]}).")
            continue

        if obligatoire and not valeur:
            erreurs[code] = f"{libelle} est obligatoire."
            continue
        if not valeur:
            continue

        message = _valider_valeur(code, libelle, type_champ, valeur)
        if message:
            erreurs[code] = message

    erreurs.update(_valider_composition(type_produit, donnees))
    return erreurs


def _valider_valeur(code, libelle, type_champ, valeur):
    if type_champ == "telephone" and not _TELEPHONE.match(valeur):
        return (f"{libelle} : numéro invalide. Attendu par exemple "
                "+237 6 99 00 00 00.")
    if type_champ == "courriel" and not _COURRIEL.match(valeur):
        return f"{libelle} : adresse e-mail invalide."
    if type_champ in ("nombre", "montant"):
        nombre = _nombre(valeur)
        if nombre is None:
            return f"{libelle} : saisissez un nombre."
        if nombre < 0:
            return f"{libelle} : la valeur ne peut pas être négative."
    if type_champ == "liste_groupee" and code == "forme_pharmaceutique":
        return ref.valider_choix(valeur, ref.FORMES_A_PLAT,
                                 "des formes pharmaceutiques")
    if type_champ == "liste_groupee" and code == "classe_therapeutique":
        return ref.valider_choix(valeur, list(ref.CLASSES_ATC),
                                 "des classes thérapeutiques")
    if type_champ == "liste":
        listes = {"voie_administration": ref.VOIES_ADMINISTRATION,
                  "conditionnement": ref.CONDITIONNEMENTS,
                  "categorie_mta": ref.CATEGORIES_MTA}
        if code in listes:
            return ref.valider_choix(valeur, listes[code], f"« {libelle} »")
    return None


def _valider_nombre_unite(code, libelle, donnees, obligatoire, erreurs):
    """Un dosage se compose d'un nombre ET d'une unité : l'un sans l'autre ne
    veut rien dire, et « 500 » seul se lit indifféremment mg ou mL."""
    valeur = (donnees.get(code) or "").strip()
    unite = (donnees.get(f"{code}_unite") or "").strip()
    if not valeur and not unite:
        if obligatoire:
            erreurs[code] = f"{libelle} est obligatoire."
        return
    if not valeur:
        erreurs[code] = f"{libelle} : indiquez la valeur numérique."
        return
    if _nombre(valeur) is None:
        erreurs[code] = f"{libelle} : saisissez un nombre."
        return
    if _nombre(valeur) <= 0:
        erreurs[code] = f"{libelle} : la valeur doit être positive."
        return
    if not unite:
        erreurs[code] = f"{libelle} : choisissez l'unité."
        return
    admises = (ref.UNITES_DUREE if code == "duree_stabilite"
               else ref.UNITES_A_PLAT)
    message = ref.valider_choix(unite, admises, f"des unités de {libelle}")
    if message:
        erreurs[code] = message


def _valider_composition(type_produit, donnees):
    """Groupes dynamiques : principes actifs (standard) ou constituants (MTA)."""
    if variant(type_produit) == "mta":
        return _valider_groupes(
            donnees, "nombre_constituants", "constituant", MAX_CONSTITUANTS,
            [("nom", "Dénomination du constituant", True),
             ("partie", "Partie utilisée", True),
             ("quantite", "Quantité", True),
             ("unite", "Unité", True)])
    return _valider_groupes(
        donnees, "nombre_principes_actifs", "pa", MAX_PRINCIPES_ACTIFS,
        [("dci", "Dénomination (DCI)", True),
         ("dosage", "Dosage", True),
         ("unite", "Unité", True)])


def _valider_groupes(donnees, champ_nombre, prefixe, maximum, sous_champs):
    erreurs = {}
    nombre = _nombre(donnees.get(champ_nombre))
    if nombre is None:
        return erreurs                      # déjà signalé par la boucle générale
    nombre = int(nombre)
    if nombre < 1:
        erreurs[champ_nombre] = "Il faut au moins un élément de composition."
        return erreurs
    if nombre > maximum:
        erreurs[champ_nombre] = (f"Au-delà de {maximum} éléments, joignez la "
                                 "composition en pièce séparée.")
        return erreurs

    for i in range(1, nombre + 1):
        for code, libelle, obligatoire in sous_champs:
            cle = f"{prefixe}_{i}_{code}"
            valeur = (donnees.get(cle) or "").strip()
            if obligatoire and not valeur:
                erreurs[cle] = f"Élément {i} — {libelle} est obligatoire."
                continue
            if not valeur:
                continue
            if code in ("dosage", "quantite") and _nombre(valeur) is None:
                erreurs[cle] = f"Élément {i} — {libelle} : saisissez un nombre."
            if code == "unite":
                message = ref.valider_choix(valeur, ref.UNITES_A_PLAT,
                                            "des unités")
                if message:
                    erreurs[cle] = f"Élément {i} — {message}"
            if code == "partie":
                message = ref.valider_choix(valeur, ref.PARTIES_UTILISEES,
                                            "des parties utilisées")
                if message:
                    erreurs[cle] = f"Élément {i} — {message}"
    return erreurs


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def composition_lisible(type_produit, donnees):
    """Composition mise en phrase, telle qu'elle figurera sur les documents."""
    est_mta = variant(type_produit) == "mta"
    champ_nombre = "nombre_constituants" if est_mta else "nombre_principes_actifs"
    prefixe = "constituant" if est_mta else "pa"
    nombre = _nombre(donnees.get(champ_nombre))
    if nombre is None:
        return ""
    lignes = []
    for i in range(1, int(nombre) + 1):
        if est_mta:
            nom = (donnees.get(f"constituant_{i}_nom") or "").strip()
            partie = (donnees.get(f"constituant_{i}_partie") or "").strip()
            quantite = (donnees.get(f"constituant_{i}_quantite") or "").strip()
            unite = (donnees.get(f"constituant_{i}_unite") or "").strip()
            if nom:
                detail = f" ({partie})" if partie else ""
                lignes.append(f"{nom}{detail} — {quantite} {unite}".strip())
        else:
            dci = (donnees.get(f"pa_{i}_dci") or "").strip()
            dosage = (donnees.get(f"pa_{i}_dosage") or "").strip()
            unite = (donnees.get(f"pa_{i}_unite") or "").strip()
            if dci:
                lignes.append(f"{dci} — {dosage} {unite}".strip())
    excipients = (donnees.get("excipients") or "").strip()
    if excipients:
        lignes.append(f"Excipients : {excipients}")
    return " ; ".join(lignes)


def dosage_complet(donnees, prefixe="dosage"):
    """« 500 mg » à partir du nombre et de l'unité saisis séparément."""
    valeur = (donnees.get(prefixe) or "").strip()
    unite = (donnees.get(f"{prefixe}_unite") or "").strip()
    return f"{valeur} {unite}".strip()
