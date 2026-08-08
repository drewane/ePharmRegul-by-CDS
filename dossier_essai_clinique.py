"""
Besoin documentaire d'une demande d'autorisation d'essai clinique.

Le dossier n'est pas le même selon la phase, et c'est la seule chose qui
compte pour le promoteur au moment de préparer sa soumission. Un tronc commun
s'applique à toute recherche sur l'être humain ; s'y ajoutent les pièces
propres au risque particulier de chaque phase.

    Phase I    première administration à l'homme — le risque est toxicologique,
               le dossier porte sur le préclinique et la justification de la
               première dose.
    Phase II   recherche de dose — le dossier porte sur ce qu'a montré la
               phase I et sur la manière dont l'efficacité sera mesurée.
    Phase III  confirmation sur large effectif — le dossier porte sur la
               puissance statistique, la surveillance indépendante et la
               conduite multicentrique.

RÉFÉRENTIEL : ICH E6 (bonnes pratiques cliniques), ICH E8, et déclaration
d'Helsinki pour le volet éthique. Les intitulés sont ceux que l'agent DROS
retrouvera dans un dossier soumis à une autorité de référence — le but est
qu'un promoteur déjà passé devant l'EMA ou la FDA reconnaisse sa liste.
"""

PHASES = {
    "phase-1": {
        "numero": "I",
        "libelle": "Phase I",
        "objet": "Première administration à l'être humain : tolérance, "
                 "sécurité, pharmacocinétique.",
        "population": "Volontaires sains, ou patients lorsque la toxicité "
                      "attendue l'impose (oncologie, thérapies innovantes).",
        "effectif": "20 à 100 participants",
        "duree": "quelques mois",
        "risque": "Le plus élevé du développement : aucune donnée humaine "
                  "n'existe encore. L'instruction porte avant tout sur la "
                  "solidité du préclinique et sur la justification de la "
                  "première dose.",
    },
    "phase-2": {
        "numero": "II",
        "libelle": "Phase II",
        "objet": "Recherche de la dose efficace et première évaluation de "
                 "l'efficacité thérapeutique.",
        "population": "Patients atteints de la pathologie visée.",
        "effectif": "100 à 300 participants",
        "duree": "quelques mois à deux ans",
        "risque": "Modéré : la tolérance humaine est établie. L'instruction "
                  "porte sur la pertinence du schéma posologique et sur les "
                  "critères de jugement retenus.",
    },
    "phase-3": {
        "numero": "III",
        "libelle": "Phase III",
        "objet": "Confirmation de l'efficacité sur un large effectif et "
                 "comparaison au traitement de référence.",
        "population": "Patients, en conditions proches de la pratique "
                      "courante, souvent sur plusieurs sites.",
        "effectif": "300 à plusieurs milliers de participants",
        "duree": "un à quatre ans",
        "risque": "Faible par participant, mais l'exposition collective est "
                  "large. L'instruction porte sur la puissance statistique, la "
                  "surveillance indépendante et la conduite multicentrique.",
    },
}

# (code, intitulé, obligatoire, précision)
EXIGENCES_COMMUNES = [
    ("lettre_demande", "Lettre de demande d'autorisation signée du promoteur",
     True, "Datée, avec identification complète du promoteur et de son "
           "représentant au Cameroun."),
    ("protocole", "Protocole de recherche, daté et versionné", True,
     "Objectifs, schéma, critères d'inclusion et d'exclusion, critères de "
     "jugement, analyse statistique, gestion des données."),
    ("resume_protocole", "Résumé du protocole en français", True,
     "Deux pages au plus, compréhensibles par un non-spécialiste."),
    ("brochure_investigateur", "Brochure de l'investigateur", True,
     "Synthèse des données précliniques et cliniques disponibles sur le "
     "produit, à jour à la date du dépôt."),
    ("consentement", "Formulaire d'information et de consentement éclairé",
     True, "En français et, le cas échéant, dans la langue véhiculaire du "
           "site. Mention explicite du droit de retrait sans justification."),
    ("avis_ethique", "Avis du comité national d'éthique de la recherche", True,
     "Avis favorable exigé : l'autorisation ne peut être délivrée sans lui."),
    ("cv_investigateurs", "CV datés et signés des investigateurs principaux",
     True, "Avec justificatif de formation aux bonnes pratiques cliniques."),
    ("sites", "Liste des sites d'investigation et attestation d'aptitude",
     True, "Plateau technique, personnel, capacité de prise en charge des "
           "urgences."),
    ("assurance", "Attestation d'assurance couvrant les participants", True,
     "Valable au Cameroun, couvrant la durée de l'essai et la période de "
     "suivi."),
    ("impd", "Dossier du médicament expérimental", True,
     "Qualité pharmaceutique : composition, fabrication, contrôle, stabilité."),
    ("etiquetage", "Modèle d'étiquetage du produit expérimental", True,
     "Mention « à usage exclusif de recherche clinique »."),
    ("vigilance", "Procédure de notification des événements indésirables graves",
     True, "Délais et destinataires, conformes aux obligations de "
           "pharmacovigilance."),
    ("financement", "Sources de financement et conventions avec les sites",
     False, "Y compris les indemnités versées aux participants."),
]

EXIGENCES_PAR_PHASE = {
    "phase-1": [
        ("precliniques", "Dossier préclinique complet", True,
         "Toxicologie à dose unique et répétée, génotoxicité, pharmacologie "
         "de sécurité, tolérance locale."),
        ("premiere_dose", "Justification de la dose de départ chez l'homme",
         True, "Calcul à partir de la NOAEL et de la dose équivalente humaine, "
               "avec le facteur de sécurité retenu."),
        ("escalade", "Plan d'escalade de dose et règles d'arrêt", True,
         "Paliers, intervalle entre participants, critères d'arrêt individuel "
         "et d'arrêt de l'essai."),
        ("unite_phase1", "Attestation d'aptitude de l'unité de phase I", True,
         "Surveillance continue, matériel de réanimation, proximité d'un "
         "service d'urgence."),
        ("gestion_risque", "Plan initial de gestion des risques", True,
         "Risques identifiés à partir du préclinique et mesures de "
         "minimisation."),
    ],
    "phase-2": [
        ("resultats_phase1", "Rapport complet des essais de phase I", True,
         "Tolérance observée, pharmacocinétique, doses explorées."),
        ("justification_dose", "Justification du schéma posologique retenu",
         True, "Lien explicite avec les données de phase I."),
        ("criteres_efficacite", "Définition des critères de jugement "
                                "d'efficacité", True,
         "Critère principal unique, critères secondaires hiérarchisés."),
        ("dsmb_phase2", "Charte du comité indépendant de surveillance", False,
         "Exigée si l'essai comporte une analyse intermédiaire ou un risque "
         "particulier."),
    ],
    "phase-3": [
        ("resultats_phase2", "Rapport complet des essais de phase II", True,
         "Dose retenue et signal d'efficacité observé."),
        ("plan_statistique", "Plan d'analyse statistique détaillé", True,
         "Rédigé et daté avant la levée d'aveugle."),
        ("effectif", "Calcul d'effectif et justification de la puissance",
         True, "Hypothèses, risque alpha, puissance, taille d'effet attendue."),
        ("dsmb_phase3", "Charte du comité indépendant de surveillance des "
                        "données", True,
         "Obligatoire : composition, indépendance, règles d'arrêt prématuré."),
        ("multicentrique", "Organisation multicentrique", True,
         "Coordination, uniformité des procédures, monitoring, gestion "
         "centralisée des données."),
        ("gestion_risque_3", "Plan de gestion des risques actualisé", True,
         "Intégrant les signaux observés en phases I et II."),
        ("acces_post_essai", "Modalités d'accès au traitement après l'essai",
         False, "Attendu pour les pathologies graves sans alternative."),
    ],
}


def exigences(phase):
    """Liste complète pour une phase : tronc commun puis pièces spécifiques."""
    if phase not in PHASES:
        raise ValueError(f"Phase inconnue : {phase}")
    def _format(source, origine):
        return [{"code": c, "intitule": i, "obligatoire": o, "precision": p,
                 "origine": origine}
                for c, i, o, p in source]
    return (_format(EXIGENCES_COMMUNES, "commun")
            + _format(EXIGENCES_PAR_PHASE[phase], "phase"))


def compte(phase):
    """(pièces obligatoires, pièces au total) — affiché en tête de page."""
    liste = exigences(phase)
    return sum(1 for e in liste if e["obligatoire"]), len(liste)
