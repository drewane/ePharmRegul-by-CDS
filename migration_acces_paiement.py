"""
Migration additive de la base existante : colonnes du paiement en ligne.

Sans Alembic sur ce projet, la migration se fait en SQL additif (ALTER TABLE
ADD COLUMN), sans perte de données. Idempotent : relançable sans risque.

Usage :  venv\\Scripts\\python migration_acces_paiement.py
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")

COLONNES_PAIEMENT = [
    ("mode", "VARCHAR(20) NOT NULL DEFAULT 'preuve_manuelle'"),
    ("fournisseur", "VARCHAR(30)"),
    ("reference_marchande", "VARCHAR(64)"),
    ("reference_transaction", "VARCHAR(80)"),
    ("date_initiation", "DATETIME"),
    ("date_expiration", "DATETIME"),
    ("signature_notification", "VARCHAR(120)"),
    ("detail_echec", "TEXT"),
]


def colonnes_existantes(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}


def main():
    if not os.path.exists(BASE):
        print(f"Base introuvable : {BASE} — rien à migrer (elle sera créée par seed.py).")
        return

    sauvegarde = f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(BASE, sauvegarde)
    print(f"Sauvegarde : {os.path.basename(sauvegarde)}")

    con = sqlite3.connect(BASE)
    cur = con.cursor()

    presentes = colonnes_existantes(cur, "paiement")
    ajoutees = []
    for nom, definition in COLONNES_PAIEMENT:
        if nom not in presentes:
            cur.execute(f"ALTER TABLE paiement ADD COLUMN {nom} {definition}")
            ajoutees.append(nom)

    # Index unique sur la référence marchande (idempotence des notifications).
    # Partiel : n'indexe que les valeurs renseignées, pour ne pas heurter les
    # lignes historiques dont la référence est nulle.
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ix_paiement_ref_marchande
                   ON paiement(reference_marchande)
                   WHERE reference_marchande IS NOT NULL""")

    con.commit()
    con.close()

    if ajoutees:
        print("Colonnes ajoutées à `paiement` : " + ", ".join(ajoutees))
    else:
        print("Schéma déjà à jour — aucune colonne ajoutée.")
    print("Index unique sur reference_marchande : en place.")
    print("Migration terminée.")


if __name__ == "__main__":
    main()
