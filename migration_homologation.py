"""
Migration additive : voies d'homologation et autorisations temporaires.

Ajoute au dossier d'AMM la voie suivie (nationale, reconnaissance d'une AMM de
référence, préqualification OMS) et les données de la décision invoquée. Crée
la table des autorisations temporaires d'utilisation.

Rien n'est retiré ni renommé : les dossiers existants restent en voie
nationale, valeur par défaut, et continuent de se comporter exactement comme
avant.

    venv\Scripts\python migration_homologation.py
"""
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COLONNES_DOSSIER = [
    ("voie_homologation", "VARCHAR(30) DEFAULT 'nationale'"),
    ("autorite_reference", "VARCHAR(30)"),
    ("programme_oms", "VARCHAR(30)"),
    ("reference_etrangere", "VARCHAR(120)"),
    ("date_reference", "DATE"),
]


def main():
    import app as application
    from models import db

    base = application.app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    if os.path.exists(base):
        copie = f"{base}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(base, copie)
        print(f"Sauvegarde : {os.path.basename(copie)}")

    with application.app.app_context():
        existantes = {r[1] for r in db.session.execute(
            db.text("PRAGMA table_info(dossier_amm)")).fetchall()}
        ajoutees = []
        for nom, type_sql in COLONNES_DOSSIER:
            if nom in existantes:
                continue
            db.session.execute(db.text(
                f"ALTER TABLE dossier_amm ADD COLUMN {nom} {type_sql}"))
            ajoutees.append(nom)
        db.session.commit()
        print("Colonnes ajoutées à dossier_amm : "
              + (", ".join(ajoutees) or "aucune"))

        # Les dossiers antérieurs relèvent tous de la voie nationale : c'est la
        # seule qui existait, et les laisser à NULL fausserait les statistiques.
        maj = db.session.execute(db.text(
            "UPDATE dossier_amm SET voie_homologation = 'nationale' "
            "WHERE voie_homologation IS NULL")).rowcount
        db.session.commit()
        print(f"Dossiers rattachés à la voie nationale : {maj}")

        db.create_all()
        tables = {r[0] for r in db.session.execute(db.text(
            "SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        print("Table autorisation_temporaire : "
              + ("créée" if "autorisation_temporaire" in tables else "ABSENTE"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
