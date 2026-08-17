"""
Remise à zéro des données métier, comptes conservés.

Efface les dossiers, demandes, paiements, cas et traces qu'ils ont produits,
en laissant intacts les comptes, les établissements et les paramètres. On
repart d'une base propre sans perdre de quoi se connecter — vider les comptes
en même temps enfermerait dehors.

    venv\\Scripts\\python vider_donnees.py            # demande confirmation
    venv\\Scripts\\python vider_donnees.py --oui      # sans confirmation

CE QUI EST CONSERVÉ
-------------------
Personne, Etablissement, ParametreModule, SequenceNumerotation. Les
établissements restent parce qu'ils portent le rattachement des comptes : les
supprimer laisserait 38 utilisateurs orphelins, incapables de déposer quoi que
ce soit.

LES SÉQUENCES NE SONT PAS REMISES À ZÉRO
-----------------------------------------
Les compteurs de numérotation (AMM-2026-0001, PAY-2026-0001…) continuent où
ils en étaient. C'est délibéré : un numéro réglementaire déjà communiqué à un
opérateur ne doit jamais désigner un autre dossier, même après un nettoyage de
développement. `--reinitialiser-numeros` force le contraire, pour repartir à 1
sur une base d'essai.
"""
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCUMENTS = os.path.join(BASE_DIR, "static", "documents")


def _modeles_metier():
    """Modèles à vider, ordonnés des enfants vers les parents.

    L'ordre compte : supprimer un dossier avant ses étapes de validation
    laisserait des lignes orphelines pointant sur un identifiant disparu.
    """
    import models as m

    noms = [
        # Traces et pièces, qui référencent tout le reste
        "EvenementAudit", "Notification", "CourrielSortant", "PieceJointe",
        # Validation et instruction
        "EtapeValidation", "AvisCommission", "DossierSession",
        "SessionCommission", "RapportInstruction", "AssignationEvaluation",
        "AvisEvaluationMA",
        # Paiements
        "Paiement",
        # Reliance régionale
        "AlerteTransfrontaliere", "RequeteReliance", "AccordPartage",
        "MessageReliance", "DecisionPubliee",
        # Déclarations d'intérêts
        "Deport", "LienInteret", "DeclarationInteret",
        # Dossiers et demandes
        "AutorisationTemporaire", "DemandeInspection", "DemandeDerogation",
        "VisaTechnique", "DossierAMM", "DemandeLicence",
        "ProtocoleEssaiClinique", "LiberationLot", "SignalementQualite",
        "NotificationVigilance", "Inspection", "Echantillon",
        # Produits et lots, en dernier : tout le reste s'y rattache
        "Lot", "Produit",
    ]
    modeles = []
    for nom in noms:
        modele = getattr(m, nom, None)
        if modele is not None:
            modeles.append(modele)
    return modeles


def _sauvegarder(base):
    if not os.path.exists(base):
        return None
    copie = f"{base}.avant-vidage-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(base, copie)
    return copie


def vider(reinitialiser_numeros=False, vider_fichiers=True):
    """Supprime les données métier. Retourne le décompte par modèle."""
    from models import db

    supprimes = {}
    for modele in _modeles_metier():
        nombre = modele.query.count()
        if nombre:
            modele.query.delete(synchronize_session=False)
            supprimes[modele.__name__] = nombre
    db.session.commit()

    if reinitialiser_numeros:
        from models import SequenceNumerotation
        remises = SequenceNumerotation.query.count()
        SequenceNumerotation.query.delete(synchronize_session=False)
        db.session.commit()
        supprimes["SequenceNumerotation"] = remises

    if vider_fichiers and os.path.isdir(DOCUMENTS):
        effaces = 0
        for racine, _dossiers, fichiers in os.walk(DOCUMENTS):
            for f in fichiers:
                os.remove(os.path.join(racine, f))
                effaces += 1
        # Les répertoires vides ne gênent personne, mais autant les retirer.
        for racine, dossiers, _f in os.walk(DOCUMENTS, topdown=False):
            for d in dossiers:
                try:
                    os.rmdir(os.path.join(racine, d))
                except OSError:
                    pass
        supprimes["fichiers téléversés"] = effaces

    return supprimes


def main():
    import app as application

    sans_confirmation = "--oui" in sys.argv
    numeros = "--reinitialiser-numeros" in sys.argv

    base = application.app.config["SQLALCHEMY_DATABASE_URI"].replace(
        "sqlite:///", "")

    with application.app.app_context():
        from models import Etablissement, Personne

        print("=" * 74)
        print("REMISE À ZÉRO DES DONNÉES MÉTIER")
        print("=" * 74)
        total = sum(m.query.count() for m in _modeles_metier())
        print(f"  À supprimer  : {total} enregistrement(s) métier")
        print(f"  Conservés    : {Personne.query.count()} comptes, "
              f"{Etablissement.query.count()} établissements, "
              "les paramètres et les compteurs de numérotation")
        if numeros:
            print("  Les compteurs de numérotation repartiront à 1.")
        print()

        if not sans_confirmation:
            print("  Relancez avec --oui pour confirmer :")
            print("      venv\\Scripts\\python vider_donnees.py --oui")
            return 1

        copie = _sauvegarder(base)
        if copie:
            print(f"  Sauvegarde   : {os.path.basename(copie)}")

        supprimes = vider(reinitialiser_numeros=numeros)
        for nom, nombre in sorted(supprimes.items(), key=lambda x: -x[1]):
            print(f"    {nom:28} {nombre:6}")
        print()
        print(f"  Base vidée. {Personne.query.count()} comptes intacts — "
              "vous pouvez vous reconnecter immédiatement.")
        print("  Pour recréer un jeu de démonstration : "
              "venv\\Scripts\\python seed.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
