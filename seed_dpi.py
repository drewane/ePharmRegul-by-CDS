"""
Déclarations d'intérêts des comptes de démonstration.

Sans DPI en vigueur, aucun dossier ne peut être confié : c'est la règle. Les
comptes de démonstration en reçoivent donc une.

Un compte est volontairement doté d'un LIEN D'INTÉRÊT, pour que le blocage
automatique et le déport soient observables en démonstration.

Usage :  venv\Scripts\python seed_dpi.py
"""
import app as application
import dpi
from models import Etablissement, Personne, db


def main():
    with application.app.app_context():
        assujettis = [p for p in Personne.query.all() if dpi.est_assujetti(p)]
        cree = conflit = 0

        # Un laboratoire réel du jeu de démonstration, pour un conflit visible
        labo = Etablissement.query.filter(
            Etablissement.raison_sociale.ilike("%PharmaCam%")).first()

        for p in assujettis:
            if dpi.declaration_en_vigueur(p) is not None:
                continue
            # Le second évaluateur déclare un lien avec un laboratoire déposant :
            # il sera automatiquement déporté de ses dossiers.
            if p.email == "evaluateur2@dpml.demo" and labo is not None:
                dpi.enregistrer_declaration(p, [{
                    "organisme": labo.raison_sociale, "nature": "conseil",
                    "description": "Mission d'expertise ponctuelle (demonstration)",
                    "annee_debut": 2024}], acteur=p)
                conflit += 1
            else:
                dpi.enregistrer_declaration(p, [], aucun_lien=True, acteur=p)
            cree += 1
        db.session.commit()

        print(f"  {len(assujettis)} agent(s) assujetti(s)")
        print(f"  {cree} declaration(s) creee(s), dont {conflit} avec lien d'interet")
        if labo is not None and conflit:
            print(f"  -> evaluateur2@dpml.demo sera deporte des dossiers de "
                  f"{labo.raison_sociale}")


if __name__ == "__main__":
    main()
