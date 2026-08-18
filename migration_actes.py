"""
Migration additive : numéros du certificat d'homologation et de l'AMM.

Le dossier portait un seul numéro, le sien. Les actes délivrés en ont chacun
un, distinct et propre à sa série : un certificat et une AMM ne se citent pas
par le numéro du dossier qui les a produits.

Rien n'est retiré ni renommé. Les dossiers antérieurs gardent leurs colonnes à
NULL — ils n'ont pas d'acte au nouveau format, et `actes.existe()` le dit sans
se tromper.

    venv\\Scripts\\python migration_actes.py
"""
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COLONNES_DOSSIER = [
    ("numero_certificat", "VARCHAR(30)"),
    ("numero_amm", "VARCHAR(30)"),
]


def _ajouter(db, table, colonnes):
    existantes = {r[1] for r in db.session.execute(
        db.text(f"PRAGMA table_info({table})")).fetchall()}
    ajoutees = []
    for nom, type_sql in colonnes:
        if nom in existantes:
            continue
        db.session.execute(db.text(
            f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}"))
        ajoutees.append(nom)
    db.session.commit()
    return ajoutees


def main():
    import app as application
    from models import db

    base = application.app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    if os.path.exists(base):
        copie = f"{base}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(base, copie)
        print(f"Sauvegarde : {os.path.basename(copie)}")

    with application.app.app_context():
        ajoutees = _ajouter(db, "dossier_amm", COLONNES_DOSSIER)
        print("dossier_amm : " + (", ".join(ajoutees) or "aucune colonne ajoutée"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
