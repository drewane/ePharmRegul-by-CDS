"""
Migration additive : demandeur d'une analyse de laboratoire.

Un échantillon reçu sur « demande directe » d'un opérateur donne lieu à une
redevance : il faut donc savoir QUI est redevable. Les échantillons prélevés
d'office par la DPML (inspection, signalement de marché) restent sans
demandeur — et ne sont pas facturés.

Sans Alembic sur ce projet, la migration se fait en SQL additif, sans perte de
données. Idempotent : relançable sans risque.

Usage :  venv\\Scripts\\python migration_demandeur_analyse.py
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")

COLONNES = {
    "echantillon": [
        ("demandeur_id", "INTEGER REFERENCES personne(id)"),
    ],
}


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
    ajoutees = 0
    for table, colonnes in COLONNES.items():
        existantes = colonnes_existantes(cur, table)
        if not existantes:
            print(f"  table « {table} » absente — ignorée")
            continue
        for nom, definition in colonnes:
            if nom in existantes:
                print(f"  {table}.{nom} : déjà présente")
                continue
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")
            print(f"  {table}.{nom} : ajoutée")
            ajoutees += 1
    con.commit()
    con.close()
    print(f"\nMigration terminée — {ajoutees} colonne(s) ajoutée(s).")


if __name__ == "__main__":
    main()
