"""
Tableau de bord de l'opérateur, conditionné par son profil.

Un grossiste et un laboratoire titulaire n'attendent pas la même chose de leur
page d'accueil. L'un suit des agréments et des rappels de lots, l'autre des
dossiers d'AMM et leur avancement. Plutôt que d'empiler des conditions dans un
gabarit, chaque profil déclare ici ses indicateurs et ses raccourcis, et la
page se contente de les afficher.

DOSSIERS RÉCENTS
----------------
« Récent » veut dire moins de trois mois. Un tableau de bord qui remonte tout
depuis l'origine cesse d'être un tableau de bord : il devient un registre, et
l'utilisateur n'y trouve plus ce qui bouge. Le seuil est un paramètre, pas une
constante enfouie.

PROCHAINE ACTION ATTENDUE
-------------------------
Chaque dossier affiche ce que l'on attend, et de qui. C'est la question que se
pose réellement un déposant devant une liste de statuts. La table ci-dessous
en donne une lecture provisoire, dérivée du statut ; le lot 5 la remplacera
par la machine à états, qui la déduira des transitions ouvertes.
"""
from datetime import datetime, timedelta

FENETRE_RECENTS_JOURS = 90          # trois mois, comme demandé


# ---------------------------------------------------------------------------
# Ce qu'on attend, et de qui
# ---------------------------------------------------------------------------
# statut interne → (à qui de jouer, action attendue)
PROCHAINE_ACTION = {
    "brouillon": ("vous", "Compléter le dossier technique puis le soumettre"),
    "soumis": ("l'administration", "Confirmation du paiement par le service "
                                   "financier"),
    "en_attente_confirmation": ("l'administration",
                                "Confirmation du paiement par le service "
                                "financier"),
    "recevable": ("l'administration", "Examen technique du dossier"),
    "evaluation_en_cours": ("l'administration",
                            "Évaluation et passage en commission"),
    "complement_requis": ("vous", "Fournir les éléments demandés"),
    "irrecevable": (None, "Dossier clos : le dépôt n'était pas recevable"),
    "rejete": (None, "Dossier clos : décision défavorable"),
    "cloture_delai_depasse": (None, "Dossier clos : délai de réponse dépassé"),
    "approuve": ("l'administration",
                 "Mise en ligne de l'AMM signée par le ministre"),
}

ACTION_PAR_DEFAUT = ("l'administration", "Instruction en cours")


def prochaine_action(dossier):
    """(acteur attendu, libellé). `acteur` vaut None si le dossier est clos."""
    import amm_signee

    statut = getattr(dossier, "statut", "") or ""
    if statut == "approuve" and amm_signee.est_disponible(dossier):
        return (None, "Autorisation délivrée — téléchargeable")
    acteur, libelle = PROCHAINE_ACTION.get(statut, ACTION_PAR_DEFAUT)
    return acteur, libelle


def a_vous_de_jouer(dossier):
    """Le dossier attend-il quelque chose du déposant ?"""
    return prochaine_action(dossier)[0] == "vous"


# ---------------------------------------------------------------------------
# Composition du tableau de bord, profil par profil
# ---------------------------------------------------------------------------
# `indicateurs` : (clé de la synthèse, libellé, icône, couleur, filtre de lien)
# `sections`    : blocs affichés sous les indicateurs, dans l'ordre
#
# Aucune section « demandes d'inspection » : le cahier des charges la retire du
# tableau de bord, l'inspection ayant sa place sous « Demande ».
COMPOSITION = {
    "demandeur_externe": {
        "titre": "Vos dossiers d'homologation",
        "indicateurs": [
            ("en_cours", "Dossiers en cours", "bi-hourglass-split", "primary", ""),
            ("approuves", "AMM en vigueur", "bi-patch-check", "success", "approuve"),
            ("complement_requis", "Compléments demandés",
             "bi-exclamation-circle", "warning", "complement_requis"),
            ("a_renouveler", "À renouveler", "bi-arrow-repeat", "info", ""),
            ("brouillons", "Brouillons", "bi-pencil", "secondary", "brouillon"),
            ("rejetes", "Rejetés", "bi-x-circle", "danger", "rejete"),
        ],
        "sections": ["a_faire", "recents", "echeances"],
        "raccourcis": [
            ("Déposer une demande d'AMM", "demandes.amm", "bi-plus-circle"),
            ("Suivre mes dossiers", "industriel.suivi_liste", "bi-signpost-split"),
            ("Mon portefeuille", "industriel.portefeuille", "bi-briefcase"),
        ],
    },
    "fabricant": {
        "titre": "Vos agréments de fabrication",
        "indicateurs": [
            ("agrements_en_cours", "Demandes en cours", "bi-hourglass-split",
             "primary", ""),
            ("agrements_actifs", "Agréments en vigueur", "bi-patch-check",
             "success", ""),
            ("inspections", "Inspections demandées", "bi-clipboard-check",
             "info", ""),
        ],
        "sections": ["a_faire", "agrements", "inspections"],
        "raccourcis": [
            ("Demander un agrément de fabrication",
             "demandes.accueil", "bi-building-check"),
            ("Solliciter une inspection de site",
             "industriel.inspections", "bi-clipboard-check"),
        ],
    },
    "grossiste": {
        "titre": "Votre activité de distribution",
        "indicateurs": [
            ("agrements_en_cours", "Demandes en cours", "bi-hourglass-split",
             "primary", ""),
            ("agrements_actifs", "Agréments en vigueur", "bi-patch-check",
             "success", ""),
            ("rappels", "Rappels de lots en cours", "bi-megaphone",
             "danger", ""),
        ],
        "sections": ["a_faire", "agrements", "rappels"],
        "raccourcis": [
            ("Demander un agrément de distribution",
             "demandes.accueil", "bi-truck"),
            ("Consulter les rappels de lots", "mc.rappels_public",
             "bi-megaphone"),
        ],
    },
    "pharmacien": {
        "titre": "Votre officine",
        "indicateurs": [
            ("agrements_en_cours", "Demandes en cours", "bi-hourglass-split",
             "primary", ""),
            ("agrements_actifs", "Licence en vigueur", "bi-patch-check",
             "success", ""),
            ("rappels", "Rappels de lots en cours", "bi-megaphone",
             "danger", ""),
        ],
        "sections": ["a_faire", "agrements", "rappels"],
        "raccourcis": [
            ("Signaler un produit suspect", "mc.public", "bi-flag"),
            ("Déclarer un effet indésirable", "vl.notifier",
             "bi-clipboard2-pulse"),
        ],
    },
    "laboratoire_prive": {
        "titre": "Vos analyses",
        "indicateurs": [
            ("analyses", "Analyses demandées", "bi-eyedropper", "primary", ""),
            ("agrements_actifs", "Agréments en vigueur", "bi-patch-check",
             "success", ""),
        ],
        "sections": ["a_faire", "agrements"],
        "raccourcis": [
            ("Demander une analyse", "demandes.accueil", "bi-eyedropper"),
        ],
    },
    "promoteur_essai": {
        "titre": "Vos essais cliniques",
        "indicateurs": [
            ("protocoles_en_cours", "Protocoles en cours",
             "bi-hourglass-split", "primary", ""),
            ("protocoles_autorises", "Essais autorisés", "bi-patch-check",
             "success", ""),
        ],
        "sections": ["a_faire", "protocoles"],
        "raccourcis": [
            ("Déposer un protocole", "ct.nouveau", "bi-file-earmark-medical"),
            ("Mes protocoles", "ct.registre", "bi-clipboard2-pulse"),
        ],
    },
    "usager": {
        "titre": "Services ouverts au public",
        "indicateurs": [],
        "sections": [],
        "raccourcis": [
            ("Registre public des AMM", "registre_public", "bi-search"),
            ("Déclarer un effet indésirable", "vl.notifier",
             "bi-clipboard2-pulse"),
            ("Signaler un produit suspect", "mc.public", "bi-flag"),
        ],
    },
}


def composition(utilisateur):
    """Composition du tableau de bord pour ce profil, ou None pour un agent."""
    if utilisateur is None:
        return None
    return COMPOSITION.get(utilisateur.role_systeme)


# ---------------------------------------------------------------------------
# Alimentation
# ---------------------------------------------------------------------------
def _depuis(jours):
    return datetime.utcnow() - timedelta(days=jours)


def dossiers_recents(utilisateur, jours=FENETRE_RECENTS_JOURS, limite=10):
    """Dossiers touchés dans les trois derniers mois, du plus récent au plus ancien.

    Le filtre porte sur la dernière mise à jour et non sur la création : un
    dossier déposé il y a six mois et instruit hier reste d'actualité, et le
    masquer donnerait l'impression qu'il ne se passe rien.
    """
    import espace_industriel as esp
    from models import DossierAMM

    return (esp.dossiers_de_la_societe(utilisateur)
            .filter(DossierAMM.date_maj >= _depuis(jours))
            .order_by(DossierAMM.date_maj.desc()).limit(limite).all())


def a_faire(utilisateur, limite=5):
    """Dossiers qui attendent une action DU DÉPOSANT — le bloc le plus utile."""
    import espace_industriel as esp

    en_attente = [d for d in esp.dossiers_de_la_societe(utilisateur).all()
                  if a_vous_de_jouer(d)]
    en_attente.sort(key=lambda d: d.date_maj or datetime.min, reverse=True)
    return en_attente[:limite]


def indicateurs(utilisateur):
    """Chiffres attendus par le profil, calculés à la demande.

    Chaque clé n'est calculée que si la composition du profil la réclame :
    un pharmacien n'a pas à payer le coût d'un décompte de protocoles.
    """
    import espace_industriel as esp

    fiche = composition(utilisateur)
    if not fiche:
        return {}
    voulues = {cle for cle, *_ in fiche["indicateurs"]}
    valeurs = {}

    if voulues & {"en_cours", "approuves", "complement_requis", "a_renouveler",
                  "brouillons", "rejetes"}:
        valeurs.update(esp.synthese(utilisateur))

    if "agrements_en_cours" in voulues or "agrements_actifs" in voulues:
        from models import DemandeLicence
        etab = utilisateur.etablissement_rattachement_id
        ouvertes = (DemandeLicence.query
                    .filter(DemandeLicence.etablissement_id == etab,
                            DemandeLicence.statut.in_(("deposee",
                                                       "en_instruction")))
                    .count() if etab else 0)
        valeurs["agrements_en_cours"] = ouvertes
        valeurs["agrements_actifs"] = (
            1 if utilisateur.etablissement
            and utilisateur.etablissement.statut_licence == "active" else 0)

    if "inspections" in voulues:
        valeurs["inspections"] = len(esp.demandes_inspection(utilisateur))

    if "rappels" in voulues:
        # Un rappel n'est pas une entité à part : c'est un signalement qualité
        # passé au statut « rappel_engage ». Le distributeur doit le voir même
        # s'il n'en est pas à l'origine — c'est lui qui retire les lots.
        from models import SignalementQualite
        valeurs["rappels"] = SignalementQualite.query.filter(
            SignalementQualite.statut == "rappel_engage").count()

    if "analyses" in voulues:
        from models import Echantillon
        etab = utilisateur.etablissement_rattachement_id
        valeurs["analyses"] = (Echantillon.query
                               .filter_by(demandeur_id=utilisateur.id).count()
                               if etab else 0)

    if "protocoles_en_cours" in voulues or "protocoles_autorises" in voulues:
        from models import ProtocoleEssaiClinique
        ids = esp.personnes_de_la_societe(utilisateur)
        base = ProtocoleEssaiClinique.query.filter(
            ProtocoleEssaiClinique.promoteur_id.in_(ids))
        valeurs["protocoles_autorises"] = base.filter(
            ProtocoleEssaiClinique.statut == "autorise").count()
        valeurs["protocoles_en_cours"] = base.filter(
            ProtocoleEssaiClinique.statut.notin_(
                ("autorise", "refuse", "clos"))).count()

    return valeurs
