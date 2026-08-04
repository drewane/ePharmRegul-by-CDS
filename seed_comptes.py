"""
Jeu de comptes de démonstration : un compte actif par rôle du référentiel.

OBJET
-----
Permettre d'éprouver, en se connectant, chaque niveau d'accès et chaque niveau
de responsabilité — des profils externes (niveau 0) jusqu'au ministre
(niveau 8). Tant qu'un rôle n'a pas de compte, la chaîne de validation reste
théorique : c'est ce qui avait bloqué le circuit de signature avant l'ajout du
chef de service Homologation.

CONVENTION
----------
Tous les comptes partagent le même mot de passe, `MOT_DE_PASSE`. C'est une
commodité de démonstration, et rien d'autre : `verifier_avant_production()`
signale ces comptes comme devant être supprimés ou réinitialisés avant tout
déploiement réel.

IDEMPOTENCE
-----------
Le script se relance sans risque. Il ne recrée pas un compte existant et ne
touche pas au mot de passe d'un compte déjà en base, sauf `--reinitialiser`.

    venv\\Scripts\\python seed_comptes.py
    venv\\Scripts\\python seed_comptes.py --reinitialiser
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import Etablissement, Personne, db
from permissions import LIBELLE_NIVEAU, ROLES, niveau

MOT_DE_PASSE = "demo1234"
DOMAINE_DEMO = ".demo"

# ---------------------------------------------------------------------------
# Établissements de rattachement des profils externes
# ---------------------------------------------------------------------------
# Un opérateur agit toujours au nom d'un établissement : c'est lui, et non la
# personne, qui porte la licence et le cloisonnement des dossiers.
ETABLISSEMENTS = {
    "pharmacam": ("PharmaCam Import SARL", "importateur_exportateur", "active"),
    "grossiste": ("Ateba Distribution SARL", "grossiste_repartiteur", "active"),
    "labo_prive": ("Laboratoire d'Analyses Bastos", "laboratoire_controle", "active"),
    "officine": ("Pharmacie du Centre — Yaoundé", "officine", "active"),
    "promoteur": ("Institut de Recherche Clinique d'Afrique Centrale",
                  "importateur_exportateur", "active"),
}

# ---------------------------------------------------------------------------
# Un compte par rôle : rôle → (nom affiché, e-mail, clé d'établissement)
# ---------------------------------------------------------------------------
# Les adresses déjà utilisées par les jeux de données antérieurs sont
# conservées telles quelles : les renommer casserait les dossiers existants.
COMPTES = {
    # --- Externes (niveau 0) ---------------------------------------------
    "usager": ("Usager Démonstration", "usager@sireph.demo", None),
    "demandeur_externe": ("Demandeur PharmaCam SARL", "demandeur@pharmacam.demo",
                          "pharmacam"),
    "laboratoire_prive": ("Laboratoire d'Analyses Bastos", "labo.prive@sireph.demo",
                          "labo_prive"),
    "grossiste": ("Grossiste Ateba Distribution", "ateba@grossiste-demo.cm",
                  "grossiste"),
    "pharmacien": ("Pharmacien du Centre", "pharmacien@officine.demo", "officine"),
    "promoteur_essai": ("Promoteur d'essai clinique", "promoteur@essai.demo",
                        "promoteur"),

    # --- Niveau 1 : instruction scientifique ------------------------------
    "cadre_dpml": ("Cadre DPML", "cadre@dpml.demo", None),
    "evaluateur_amm": ("Évaluateur AMM", "evaluateur@dpml.demo", None),
    "evaluateur_interne": ("Évaluateur interne 1", "evaluateur1@dpml.demo", None),
    "membre_commission_specialisee": ("Membre commission spécialisée 1",
                                      "commission1@dpml.demo", None),
    "membre_commission_nationale": ("Membre commission nationale 1",
                                    "cnm1@dpml.demo", None),
    "agent_vigilance": ("Agent de pharmacovigilance", "vigilance@dpml.demo", None),
    "inspecteur_igspl": ("Inspecteur IGSPL", "inspecteur@igspl.demo", None),
    "agent_licences": ("Agent Licences", "licences@dpml.demo", None),
    "agent_laboratoire": ("Agent Laboratoire national", "labo@lanacome.demo", None),
    "agent_surveillance_marche": ("Agent Surveillance du marché",
                                  "surveillance@dpml.demo", None),
    "agent_dros": ("Agent DROS (essais cliniques)", "dros@dpml.demo", None),

    # --- Niveau 2 : chef de bureau ----------------------------------------
    "chef_bureau": ("Chef de bureau — Recevabilité", "chefbureau@dpml.demo", None),

    # --- Niveau 3 : chefs de service --------------------------------------
    "chef_service_amm": ("Chef de service Homologation", "chefservice@dpml.demo", None),
    "chef_service_licences": ("Chef de service Licences", "cs.licences@dpml.demo", None),
    "chef_service_inspection": ("Chef de service Inspection",
                                "cs.inspection@dpml.demo", None),
    "chef_service_labo": ("Chef de service Laboratoire", "cs.labo@dpml.demo", None),
    "responsable_qualite_labo": ("Responsable Qualité Laboratoire",
                                 "rq@lanacome.demo", None),

    # --- Niveau 4 : sous-direction ----------------------------------------
    "sous_directeur_medicament": ("Sous-directeur du Médicament",
                                  "sousdirecteur@dpml.demo", None),
    "sous_directeur_etablissements": ("Sous-directeur des Établissements",
                                      "sd.etablissements@dpml.demo", None),

    # --- Niveau 5 : direction ---------------------------------------------
    "directeur_dpml": ("Directeur DPML", "directeur@dpml.demo", None),
    "administrateur_dpml": ("Administrateur DPML", "admin@dpml.demo", None),

    # --- Niveau 6 : inspection générale -----------------------------------
    "inspecteur_general": ("Inspecteur général", "ig@minsante.demo", None),

    # --- Niveau 7 : secrétariat général -----------------------------------
    "secretaire_general_ms": ("Secrétaire général du Ministère", "sg@minsante.demo",
                              None),
    "directeur_general_agence": ("Directeur général de l'Agence",
                                 "dg@agence.demo", None),

    # --- Niveau 8 : ministre ----------------------------------------------
    "ministre_sante": ("Ministre de la Santé publique", "ministre@minsante.demo",
                       None),
}

# ---------------------------------------------------------------------------
# Ce que chaque profil permet d'éprouver — affiché dans l'annuaire
# ---------------------------------------------------------------------------
A_EPROUVER = {
    "usager": "Registre public, déclaration d'effet indésirable, signalement de "
              "produit suspect. Aucun accès aux dossiers.",
    "demandeur_externe": "Dépôt d'AMM, modules CTD, paiement, suivi du dossier, "
                         "demande d'inspection. Cloisonné à sa société.",
    "laboratoire_prive": "Demande d'analyse au laboratoire national, suivi des "
                         "certificats.",
    "grossiste": "Licence d'établissement, rappels de lots, signalement.",
    "pharmacien": "Licence d'officine, alertes de retrait, signalement.",
    "promoteur_essai": "Dépôt de protocole d'essai clinique et suivi de "
                       "l'autorisation.",
    "cadre_dpml": "Instruction scientifique, saisie d'avis. Ne valide rien.",
    "evaluateur_amm": "Évaluation d'un dossier d'AMM qui lui est assigné.",
    "evaluateur_interne": "Réception d'une assignation, remise d'un rapport "
                          "d'évaluation motivé.",
    "membre_commission_specialisee": "Séance de commission, avis individuel, "
                                     "synthèse automatique. Bloqué en cas de "
                                     "conflit d'intérêts déclaré.",
    "membre_commission_nationale": "Commission nationale du médicament.",
    "agent_vigilance": "Traitement des cas de pharmacovigilance.",
    "inspecteur_igspl": "Conduite d'inspection, rapport d'inspection.",
    "agent_licences": "Instruction d'une demande de licence d'établissement.",
    "agent_laboratoire": "Réception d'échantillons, résultats d'analyse.",
    "agent_surveillance_marche": "Signalements du marché, produits suspects.",
    "agent_dros": "Instruction des protocoles d'essai clinique.",
    "chef_bureau": "Recevabilité administrative et attribution des dossiers aux "
                   "évaluateurs. Premier niveau qui engage l'administration.",
    "chef_service_amm": "Recevabilité, attribution, convocation de commission, "
                        "rapport d'instruction, PREMIÈRE SIGNATURE du circuit AMM.",
    "chef_service_licences": "Première signature du circuit Licence.",
    "chef_service_inspection": "Première signature du circuit Inspection.",
    "chef_service_labo": "Première signature du circuit Contrôle qualité.",
    "responsable_qualite_labo": "Validation qualité des analyses de laboratoire.",
    "sous_directeur_medicament": "Deuxième signature (AMM, essais cliniques, "
                                 "contrôle qualité). Vue de synthèse, pas le "
                                 "détail technique.",
    "sous_directeur_etablissements": "Deuxième signature (licences, inspections).",
    "directeur_dpml": "Signature de direction, suspension d'établissement, levée "
                      "de déport. Vue de synthèse.",
    "administrateur_dpml": "Comptes, référentiels, barèmes, paramètres, "
                           "rapprochement des paiements.",
    "inspecteur_general": "Audit d'intégrité transversal ; s'intercale dans le "
                          "circuit AMM après le directeur et clôt le circuit "
                          "d'inspection.",
    "secretaire_general_ms": "Avant-dernière signature de l'AMM, des licences et "
                             "des essais cliniques. Vue parcours seulement.",
    "directeur_general_agence": "Signature en lieu et place du ministre lorsque "
                                "l'Agence succédera à la direction.",
    "ministre_sante": "SIGNATURE FINALE de l'AMM, des licences et des "
                      "autorisations d'essai clinique. Vue parcours seulement.",
}


# ---------------------------------------------------------------------------
def _etablissement(cle):
    """Retourne l'établissement de démonstration, en le créant au besoin."""
    raison, type_etab, statut = ETABLISSEMENTS[cle]
    etab = Etablissement.query.filter_by(raison_sociale=raison).first()
    if not etab:
        etab = Etablissement(raison_sociale=raison, type=type_etab,
                             statut_licence=statut,
                             adresse="Yaoundé, Cameroun")
        db.session.add(etab)
        db.session.flush()
    return etab


def creer_comptes(reinitialiser=False):
    """Garantit un compte actif par rôle. Retourne (créés, réactivés, inchangés)."""
    crees, reactives, inchanges = [], [], []

    for role, (nom, email, cle_etab) in COMPTES.items():
        etab = _etablissement(cle_etab) if cle_etab else None
        p = Personne.query.filter_by(email=email).first()

        if p is None:
            p = Personne(nom_complet=nom, email=email, role_systeme=role,
                         statut_compte="actif",
                         etablissement_rattachement_id=etab.id if etab else None)
            p.set_password(MOT_DE_PASSE)
            db.session.add(p)
            crees.append(role)
            continue

        # Compte existant : on ne réécrit que ce qui empêcherait le test.
        modifie = False
        if p.statut_compte != "actif":
            p.statut_compte = "actif"
            modifie = True
        if p.role_systeme != role:
            p.role_systeme = role
            modifie = True
        if etab and p.etablissement_rattachement_id is None:
            p.etablissement_rattachement_id = etab.id
            modifie = True
        # Un compte de démonstration dont le mot de passe diverge n'est pas
        # testable : l'annuaire l'annoncerait à tort. On le réaligne.
        if reinitialiser or not p.check_password(MOT_DE_PASSE):
            p.set_password(MOT_DE_PASSE)
            modifie = True
        (reactives if modifie else inchanges).append(role)

    db.session.commit()
    return crees, reactives, inchanges


def annuaire():
    """Les comptes de démonstration, groupés par niveau de responsabilité.

    Construit depuis la base : ce qui est affiché est ce qui existe réellement,
    et non la déclaration d'intention du présent fichier.
    """
    groupes = {}
    for role, (_nom, email, _e) in COMPTES.items():
        p = Personne.query.filter_by(email=email).first()
        if p is None:
            continue
        n = niveau(role)
        groupes.setdefault(n, []).append({
            "role": role,
            "libelle": ROLES.get(role, role),
            "nom": p.nom_complet,
            "email": p.email,
            "etablissement": p.etablissement.raison_sociale if p.etablissement else None,
            "actif": p.statut_compte == "actif",
            "a_eprouver": A_EPROUVER.get(role, ""),
        })
    return [{"niveau": n, "libelle": LIBELLE_NIVEAU.get(n, str(n)),
             "comptes": sorted(groupes[n], key=lambda c: c["libelle"])}
            for n in sorted(groupes)]


def roles_sans_compte():
    """Rôles du référentiel qui n'ont aucun compte : un trou dans le test."""
    manquants = []
    for role in ROLES:
        if role not in COMPTES:
            manquants.append(role)
            continue
        if Personne.query.filter_by(email=COMPTES[role][1]).first() is None:
            manquants.append(role)
    return manquants


def verifier_avant_production():
    """Comptes à supprimer ou réinitialiser avant tout déploiement réel.

    Le mot de passe partagé est acceptable sur un poste de démonstration ; il
    ne l'est nulle part ailleurs. La fonction existe pour que l'oubli soit
    détectable par un contrôle automatisé plutôt que par un incident.
    """
    return [p.email for p in Personne.query.all()
            if p.email.endswith(DOMAINE_DEMO) or p.email.endswith("-demo.cm")]


def main():
    import app as application

    reinit = "--reinitialiser" in sys.argv
    with application.app.app_context():
        crees, reactives, inchanges = creer_comptes(reinit)

        print("=" * 78)
        print("COMPTES DE DÉMONSTRATION — un par rôle du référentiel")
        print("=" * 78)
        print(f"  créés : {len(crees)}   ajustés : {len(reactives)}   "
              f"inchangés : {len(inchanges)}")
        if crees:
            print("  nouveaux rôles dotés d'un compte : " + ", ".join(crees))
        if reinit:
            print("  mots de passe réinitialisés.")

        for groupe in annuaire():
            print()
            print(f"── Niveau {groupe['niveau']} — {groupe['libelle']} "
                  + "─" * max(0, 40 - len(groupe["libelle"])))
            for c in groupe["comptes"]:
                marque = "" if c["actif"] else "  [INACTIF]"
                print(f"   {c['email']:34} {c['libelle']}{marque}")

        manquants = roles_sans_compte()
        print()
        if manquants:
            print("  ATTENTION — rôles sans compte : " + ", ".join(manquants))
        else:
            print(f"  Les {len(ROLES)} rôles du référentiel ont un compte actif.")
        print(f"  Mot de passe commun : {MOT_DE_PASSE}")
        print("  Ces comptes sont réservés à la démonstration ; "
              "à supprimer avant tout déploiement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
