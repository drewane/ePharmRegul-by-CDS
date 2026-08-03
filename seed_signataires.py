"""
Comptes de démonstration des échelons de signature.

Le circuit AMM remonte jusqu'au ministre : il faut donc un compte par échelon
pour dérouler la chaîne de bout en bout. Idempotent.

Usage :  venv\Scripts\python seed_signataires.py
"""
import app as application
from models import Personne, db

COMPTES = [
    # Premier échelon du circuit : le rôle existait sans compte titulaire.
    ("chefservice@dpml.demo", "Chef de service Homologation", "chef_service_amm"),
    ("sousdirecteur@dpml.demo", "Dr Sous-directeur du Médicament",
     "sous_directeur_medicament"),
    ("sg@minsante.demo", "Secrétaire général MINSANTE", "secretaire_general_ms"),
    ("ministre@minsante.demo", "Ministre de la Santé publique", "ministre_sante"),
    # Agence du médicament : le directeur général pourra signer l'AMM en lieu
    # et place du ministre lorsque la direction deviendra une agence.
    ("dg@agence.demo", "Directeur général de l'Agence du Médicament",
     "directeur_general_agence"),
    # Instruction : évaluateurs internes puis membres de commission.
    ("evaluateur1@dpml.demo", "Dr Évaluateur interne 1", "evaluateur_interne"),
    ("evaluateur2@dpml.demo", "Dr Évaluateur interne 2", "evaluateur_interne"),
    ("commission1@dpml.demo", "Pr Membre commission spécialisée 1",
     "membre_commission_specialisee"),
    ("commission2@dpml.demo", "Pr Membre commission spécialisée 2",
     "membre_commission_specialisee"),
    ("commission3@dpml.demo", "Pr Membre commission spécialisée 3",
     "membre_commission_specialisee"),
    ("cnm1@dpml.demo", "Pr Membre commission nationale", "membre_commission_nationale"),
    # Autres services (le circuit est le même pour licences, inspection, labo).
    ("cs.licences@dpml.demo", "Chef de service Licences", "chef_service_licences"),
    ("cs.inspection@dpml.demo", "Chef de service Inspection", "chef_service_inspection"),
    ("cs.labo@dpml.demo", "Chef de service Laboratoire", "chef_service_labo"),
    ("sd.etablissements@dpml.demo", "Sous-directeur des Établissements",
     "sous_directeur_etablissements"),
    ("cadre@dpml.demo", "Cadre DPML", "cadre_dpml"),
]


def main():
    with application.app.app_context():
        cree = 0
        for email, nom, role in COMPTES:
            if Personne.query.filter_by(email=email).first():
                print(f"  {email} : deja present")
                continue
            p = Personne(nom_complet=nom, email=email, role_systeme=role,
                         statut_compte="actif")
            p.set_password("demo1234")
            db.session.add(p)
            cree += 1
            print(f"  {email} : cree ({role})")
        db.session.commit()
        print(f"\n{cree} compte(s) cree(s). Mot de passe : demo1234")


if __name__ == "__main__":
    main()
