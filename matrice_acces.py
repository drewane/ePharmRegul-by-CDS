"""
Matrice d'accès : qui voit quoi, et pourquoi une entrée est indisponible.

PRINCIPE
--------
Une entrée de menu, une vue, une action : chacune déclare ici les rôles et les
profils qui y ont droit. La navigation, les tableaux de bord et les boutons se
construisent en LISANT cette table. Aucun `if current_user.role_systeme == …`
dans un gabarit — c'est ainsi que des menus finissent par contredire les
contrôles serveur, et qu'un utilisateur voit un bouton qui lui sera refusé.

TROIS ÉTATS, PAS DEUX
---------------------
Une entrée n'est pas seulement « visible » ou « absente ». Elle peut être
INDISPONIBLE : affichée, grisée, non cliquable, avec le motif en infobulle.
C'est ce que demande le cahier des charges — un laboratoire doit voir que
l'essai clinique existe, tout en comprenant qu'il ne le concerne pas. Masquer
appauvrit la lisibilité de l'offre ; griser l'explique.

    ACCESSIBLE    l'utilisateur y a droit
    INDISPONIBLE  l'entrée existe mais ne s'applique pas à son profil
    ABSENTE       l'entrée ne relève pas du tout de son monde

CORRESPONDANCE AVEC LE CAHIER DES CHARGES
------------------------------------------
Le cahier nomme cinq rôles internes et trois profils demandeur. Le référentiel
en compte trente et un, hérités de la hiérarchie MIRA à huit niveaux. Plutôt
que de renommer — ce qui aurait migré trente-huit comptes et réécrit quinze
suites de tests pour un gain de vocabulaire — la table ci-dessous fixe la
correspondance, une fois pour toutes.
"""
from permissions import est_externe, niveau

# Vocabulaire du cahier des charges → rôles réellement en place.
CORRESPONDANCE_ROLES = {
    "financier": "responsable_financier",
    "chef_service_homologation": "chef_service_amm",
    "membre_commission": "membre_commission_specialisee",
    "directeur": "directeur_dpml",
    "admin": "administrateur_dpml",
}

CORRESPONDANCE_PROFILS = {
    "laboratoire_amm": "demandeur_externe",
    "grossiste_repartiteur": "grossiste",
    "fabricant": "fabricant",
}


def role_reel(nom_cahier):
    """Traduit un nom du cahier des charges en rôle du référentiel."""
    return CORRESPONDANCE_ROLES.get(nom_cahier,
                                    CORRESPONDANCE_PROFILS.get(nom_cahier,
                                                               nom_cahier))


# ---------------------------------------------------------------------------
# Ce que chaque profil demandeur vient faire sur la plateforme
# ---------------------------------------------------------------------------
# `actes` : familles de démarches qui le concernent. Une famille absente de
# cette liste n'est pas masquée — elle est grisée, avec le motif.
PROFILS_DEMANDEUR = {
    "demandeur_externe": {
        "libelle": "Laboratoire / Titulaire d'AMM",
        "acte_par_defaut": "amm",
        # L'essai clinique en est absent à dessein : le cahier des charges le
        # cite en exemple de rubrique à griser pour un laboratoire titulaire.
        # Un titulaire qui promeut réellement des essais prend le profil
        # `promoteur_essai` — une ligne suffit à revenir sur ce choix.
        "actes": {"homologation", "inspection"},
        "resume": "Homologation de vos produits, du dépôt à l'AMM signée.",
    },
    "fabricant": {
        "libelle": "Fabricant",
        "acte_par_defaut": "agrement_fabrication",
        "actes": {"agrements", "inspection"},
        "resume": "Agrément de votre site de fabrication et inspections.",
    },
    "grossiste": {
        "libelle": "Grossiste-répartiteur",
        "acte_par_defaut": "agrement_distribution",
        "actes": {"agrements", "inspection"},
        "resume": "Agrément de distribution, licences et rappels de lots.",
    },
    "pharmacien": {
        "libelle": "Pharmacien d'officine",
        "acte_par_defaut": "agrement_distribution",
        "actes": {"agrements"},
        "resume": "Licence d'officine et signalements.",
    },
    "laboratoire_prive": {
        "libelle": "Laboratoire d'analyses",
        "acte_par_defaut": None,
        "actes": {"agrements"},
        "resume": "Analyses au laboratoire national et certificats.",
    },
    "promoteur_essai": {
        "libelle": "Promoteur d'essai clinique",
        "acte_par_defaut": "essai_clinique",
        "actes": {"essai_clinique", "inspection"},
        "resume": "Protocoles de recherche clinique et amendements.",
    },
    "usager": {
        "libelle": "Usager",
        "acte_par_defaut": None,
        "actes": set(),
        "resume": "Registre public, déclarations et signalements.",
    },
}

# Motif affiché en infobulle sur une entrée grisée.
MOTIF_HORS_PROFIL = ("Non applicable à votre profil "
                     "« {profil} » : cette démarche relève d'un autre type "
                     "d'opérateur.")


def profil(utilisateur):
    """Fiche du profil demandeur, ou None pour un agent."""
    if utilisateur is None:
        return None
    return PROFILS_DEMANDEUR.get(utilisateur.role_systeme)


def acte_concerne(utilisateur, code_acte):
    """Cette famille de démarche relève-t-elle du profil de l'utilisateur ?

    Un agent de l'administration n'a pas de « profil demandeur » : tout le
    concerne, et rien ne lui est grisé à ce titre.
    """
    fiche = profil(utilisateur)
    if fiche is None:
        return True
    return code_acte in fiche["actes"]


def motif_indisponible(utilisateur):
    fiche = profil(utilisateur)
    return MOTIF_HORS_PROFIL.format(
        profil=fiche["libelle"] if fiche else "—")


# ---------------------------------------------------------------------------
# Entrées de navigation
# ---------------------------------------------------------------------------
# Chaque entrée déclare :
#   endpoint / href   où elle mène
#   roles             rôles internes admis ; () = aucun agent
#   profils           profils demandeur admis ; () = aucun externe
#   niveau_min        seuil hiérarchique alternatif aux rôles nommés
#   acte              famille de démarche, pour le grisage par profil
#   condition         nom d'un drapeau calculé par le contexte (app.py)
#   compteur          nom d'une pastille numérique
#   enfants           sous-entrées, dépliables en accordéon
NAVIGATION = [
    {"code": "tableau_bord", "libelle": "Tableau de bord",
     "icone": "bi-speedometer2", "endpoint": "dashboard",
     "roles": ("*",), "profils": ("*",)},

    # Ouvert à tout opérateur qui détient un objet réglementaire : dossiers
    # d'AMM pour le titulaire, agréments pour le fabricant et le grossiste.
    {"code": "portefeuille", "libelle": "Mon portefeuille",
     "icone": "bi-briefcase", "endpoint": "industriel.portefeuille",
     "roles": (), "profils": ("demandeur_externe", "fabricant", "grossiste",
                              "pharmacien", "laboratoire_prive")},

    {"code": "suivi", "libelle": "Suivi de mes dossiers",
     "icone": "bi-signpost-split", "endpoint": "industriel.suivi_liste",
     "roles": (), "profils": ("demandeur_externe",)},

    # « Demande » porte désormais l'inspection en sous-onglet : elle ne figure
    # plus au menu principal, conformément au cahier des charges.
    {"code": "demande", "libelle": "Demande", "icone": "bi-plus-circle",
     "endpoint": "demandes.accueil", "roles": (),
     "profils": ("demandeur_externe", "fabricant", "grossiste", "pharmacien",
                 "laboratoire_prive", "promoteur_essai"),
     "enfants": "taxonomie"},

    {"code": "paiements", "libelle": "Mes paiements",
     "icone": "bi-person-badge", "endpoint": "profils.mon_espace",
     "roles": (), "profils": ("*externe*",), "compteur": "paiements_dus"},

    {"code": "dossiers_amm", "libelle": "Dossiers AMM",
     "icone": "bi-journal-medical", "endpoint": "dossiers_registre",
     "roles": ("*",), "profils": ("demandeur_externe",),
     "acte": "homologation", "condition": "demandeur_a_amm"},

    {"code": "essais", "libelle": "Essais cliniques",
     "icone": "bi-clipboard2-pulse", "endpoint": None,
     "roles": ("administrateur_dpml", "agent_dros", "directeur_dpml"),
     "profils": ("demandeur_externe", "promoteur_essai"),
     "acte": "essai_clinique",
     "enfants": [{"code": "protocoles", "libelle": "Protocoles",
                  "icone": "bi-file-earmark-medical", "endpoint": "ct.registre",
                  "acte": "essai_clinique"}]},

    {"code": "derogations", "libelle": "Dérogations spéciales",
     "icone": "bi-shield-exclamation", "endpoint": None,
     "roles": ("administrateur_dpml", "directeur_dpml"),
     "profils": ("demandeur_externe",), "acte": "homologation",
     "enfants": [{"code": "derogations_liste",
                  "libelle": "Demandes de dérogation",
                  "icone": "bi-shield-exclamation",
                  "endpoint": "derogation.registre",
                  "acte": "homologation"}]},

    {"code": "visas", "libelle": "Visas techniques", "icone": "bi-stamp",
     "endpoint": None,
     "roles": ("administrateur_dpml", "directeur_dpml"),
     "profils": ("demandeur_externe",), "acte": "homologation",
     "enfants": [{"code": "visas_liste", "libelle": "Visas techniques",
                  "icone": "bi-stamp", "endpoint": "visas.registre",
                  "acte": "homologation"}]},
]


def _admis(entree, utilisateur, drapeaux):
    """L'entrée relève-t-elle du monde de cet utilisateur ? (avant grisage)"""
    if utilisateur is None:
        return False
    role = utilisateur.role_systeme
    externe = est_externe(role)

    if externe:
        profils = entree.get("profils", ())
        if not profils:
            return False
        if "*" not in profils and "*externe*" not in profils \
                and role not in profils:
            return False
    else:
        roles = entree.get("roles", ())
        if not roles:
            return False
        if "*" not in roles and role not in roles:
            minimum = entree.get("niveau_min")
            if minimum is None or niveau(role) < minimum:
                return False

    # Une condition nommée permet de n'afficher une rubrique que si le
    # demandeur y a effectivement un dossier — sans quoi son menu annoncerait
    # des espaces vides.
    condition = entree.get("condition")
    if condition and externe and not drapeaux.get(condition):
        return False
    return True


def entrees(utilisateur, drapeaux=None, chemin=""):
    """Menu latéral prêt à l'affichage, grisage compris.

    Retourne une liste de dictionnaires portant `accessible`, `motif` et
    `enfants`. Le gabarit n'a plus qu'à parcourir : il ne décide de rien.
    """
    from flask import url_for

    drapeaux = drapeaux or {}
    resultat = []
    for entree in NAVIGATION:
        if not _admis(entree, utilisateur, drapeaux):
            continue

        accessible = acte_concerne(utilisateur, entree["attribut_acte"]) \
            if "attribut_acte" in entree else acte_concerne(
                utilisateur, entree.get("acte")) if entree.get("acte") else True

        href = None
        if entree.get("endpoint"):
            try:
                href = url_for(entree["endpoint"])
            except Exception:                            # noqa: BLE001
                href = None

        enfants = []
        if entree.get("enfants") == "taxonomie":
            enfants = _enfants_taxonomie(utilisateur, chemin)
        elif isinstance(entree.get("enfants"), list):
            for enfant in entree["enfants"]:
                try:
                    lien = url_for(enfant["endpoint"])
                except Exception:                        # noqa: BLE001
                    continue
                ok = (acte_concerne(utilisateur, enfant["acte"])
                      if enfant.get("acte") else True)
                enfants.append({
                    "code": enfant["code"], "libelle": enfant["libelle"],
                    "icone": enfant.get("icone", "bi-dot"), "href": lien,
                    "accessible": ok and accessible,
                    "motif": None if ok else motif_indisponible(utilisateur),
                    "actif": chemin == lien,
                })

        resultat.append({
            "code": entree["code"], "libelle": entree["libelle"],
            "icone": entree["icone"], "href": href,
            "accessible": accessible,
            "motif": None if accessible else motif_indisponible(utilisateur),
            "compteur": drapeaux.get(entree.get("compteur")) or 0,
            "enfants": enfants,
            "actif": bool(href) and chemin == href,
            "ouvert": bool(enfants) and any(e["actif"] for e in enfants),
        })
    return resultat


def _enfants_taxonomie(utilisateur, chemin=""):
    """Sous-onglets de « Demande », déduits de l'arborescence déclarée.

    L'inspection y figure comme n'importe quelle autre famille : c'est ce qui
    la retire du menu principal sans la rendre inaccessible.
    """
    import taxonomie_demandes as tax

    enfants = []
    for famille in tax.enfants_avec_liens([]):
        ok = acte_concerne(utilisateur, famille["code"])
        enfants.append({
            "code": famille["code"], "libelle": famille["libelle"],
            "icone": famille["icone"], "href": famille["href"],
            "accessible": ok,
            "motif": None if ok else motif_indisponible(utilisateur),
            # Une rubrique est « active » dès que l'on est quelque part sous
            # elle, pas seulement sur sa page d'accueil : c'est ce qui garde
            # le groupe ouvert pendant qu'on navigue dedans.
            "actif": bool(chemin) and (chemin == famille["href"]
                                       or chemin.startswith(
                                           famille["href"].rstrip("/") + "/")),
        })
    return enfants


def profils_admis(code_entree):
    """Profils demandeur admis sur une entrée de navigation.

    Les routes s'y réfèrent au lieu de recopier une liste : c'est ce qui
    empêche le menu d'offrir ce que le serveur refuse. Le contrôle a manqué
    une fois — le menu proposait « Demande » au fabricant, la route répondait
    403 — et le test de concordance l'a révélé.
    """
    for entree in NAVIGATION:
        if entree["code"] == code_entree:
            return tuple(entree.get("profils", ()))
    return ()


def verifier_matrice():
    """Anomalies de déclaration — support du test, pas de l'exécution."""
    anomalies = []
    codes = [e["code"] for e in NAVIGATION]
    for code in set(codes):
        if codes.count(code) > 1:
            anomalies.append(f"code de navigation dupliqué : {code}")
    for entree in NAVIGATION:
        if not entree.get("roles") and not entree.get("profils"):
            anomalies.append(f"{entree['code']} n'est ouvert à personne")
        if not entree.get("endpoint") and not entree.get("enfants"):
            anomalies.append(f"{entree['code']} ne mène nulle part")
        if not entree.get("libelle") or not entree.get("icone"):
            anomalies.append(f"{entree['code']} sans libellé ou sans icône")
    for code, fiche in PROFILS_DEMANDEUR.items():
        if not fiche.get("libelle") or "actes" not in fiche:
            anomalies.append(f"profil {code} incomplet")
    return anomalies
