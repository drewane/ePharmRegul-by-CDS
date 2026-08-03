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
