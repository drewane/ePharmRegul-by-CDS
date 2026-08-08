"""
Migration additive : qualification des demandes d'agrément.

Ajoute le domaine (distribution / fabrication), la catégorie de produits
(médicaments / dispositifs médicaux) et le motif exigé pour une suspension.
Les demandes existantes restent valides : les colonnes sont nullables et les
anciennes valeurs de `type_demande` inchangées.

    venv\Scripts\python migration_agrement.py
"""
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COLONNES = [
    ("domaine", "VARCHAR(20)"),
    ("categorie", "VARCHAR(30)"),
    ("motif_demande", "TEXT"),
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
            db.text("PRAGMA table_info(demande_licence)")).fetchall()}
        ajoutees = []
        for nom, type_sql in COLONNES:
            if nom in existantes:
                continue
            db.session.execute(db.text(
                f"ALTER TABLE demande_licence ADD COLUMN {nom} {type_sql}"))
            ajoutees.append(nom)
        db.session.commit()
        print("Colonnes ajoutées : " + (", ".join(ajoutees) or "aucune"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
