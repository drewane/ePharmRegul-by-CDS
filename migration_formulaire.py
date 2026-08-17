"""
Migration additive : champs du formulaire de demande enrichi.

Ajoute au produit les champs du variant standard et du variant MTA, et au
dossier la nature de l'acte, le type de produit et le type de dossier attendu.

Rien n'est retiré ni renommé. `dosage` reste la forme composée que tout le
reste de l'application lit déjà ; `dosage_valeur` et `dosage_unite` la
complètent sans la remplacer, pour que la saisie séparée n'oblige pas à
réécrire les écrans existants.

    venv\Scripts\python migration_formulaire.py
"""
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COLONNES_PRODUIT = [
    ("dosage_valeur", "VARCHAR(40)"),
    ("dosage_unite", "VARCHAR(20)"),
    ("code_atc", "VARCHAR(10)"),
    ("conditionnement", "VARCHAR(120)"),
    ("quantite_conditionnement", "VARCHAR(80)"),
    ("pharmacien_telephone", "VARCHAR(40)"),
    ("pharmacien_email", "VARCHAR(150)"),
    ("categorie_mta", "VARCHAR(120)"),
    ("mecanisme_action", "TEXT"),
    ("excipients", "TEXT"),
    ("adresse_fabricant", "TEXT"),
    ("adresse_site_fabrication", "TEXT"),
    ("adresse_controle_qualite", "TEXT"),
    ("adresse_demandeur", "TEXT"),
    ("exploitant", "TEXT"),
    ("representant_cameroun", "TEXT"),
    ("prix_public_cameroun", "INTEGER"),
]

COLONNES_DOSSIER = [
    ("nature_acte", "VARCHAR(20)"),
    ("type_produit", "VARCHAR(40)"),
    ("type_dossier", "VARCHAR(10)"),
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
        for table, colonnes in (("produit", COLONNES_PRODUIT),
                                ("dossier_amm", COLONNES_DOSSIER)):
            ajoutees = _ajouter(db, table, colonnes)
            print(f"{table} : " + (", ".join(ajoutees) or "aucune colonne ajoutée"))

        # Les dossiers antérieurs relèvent tous du CTD : c'était la seule voie.
        maj = db.session.execute(db.text(
            "UPDATE dossier_amm SET type_dossier = 'ctd' "
            "WHERE type_dossier IS NULL")).rowcount
        db.session.commit()
        print(f"Dossiers rattachés au dossier CTD : {maj}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
