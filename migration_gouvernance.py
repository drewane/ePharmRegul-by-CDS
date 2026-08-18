"""
Migration : gouvernance des accès (Lot A).

Ajoute à `personne` les colonnes d'inscription/décision et crée les quatre
tables RBAC (categorie, fonctionnalite, role, surcharge_fonctionnalite).
Idempotent — se relance sans risque, sauvegarde la base avant toute écriture.

    venv\\Scripts\\python migration_gouvernance.py      (Windows)
    .venv/bin/python migration_gouvernance.py           (macOS/Linux)
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance",
                    "sireph.db")

# Colonnes ajoutées à `personne` (nullable : aucun impact sur l'existant).
COLONNES_PERSONNE = [
    ("date_inscription", "DATETIME"),
    ("date_decision", "DATETIME"),
    ("decide_par_id", "INTEGER"),
]


def main():
    if not os.path.exists(BASE):
        print("Base introuvable.")
        return
    shutil.copy2(BASE, f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}")

    con = sqlite3.connect(BASE)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(personne)")
    cols = {r[1] for r in cur.fetchall()}
    for nom, ddl in COLONNES_PERSONNE:
        if nom not in cols:
            cur.execute(f"ALTER TABLE personne ADD COLUMN {nom} {ddl}")
            print(f"  personne.{nom} : ajoutée")
        else:
            print(f"  personne.{nom} : déjà présente")
    con.commit()
    con.close()

    # Tables neuves via SQLAlchemy : create_all ne touche pas aux tables
    # existantes, il ne crée que ce qui manque.
    import app as application
    from models import db, Categorie, Fonctionnalite, Role, SurchargeFonctionnalite
    with application.app.app_context():
        db.create_all()
        for M in (Categorie, Fonctionnalite, Role, SurchargeFonctionnalite):
            print(f"  {M.__tablename__:26s} {M.query.count()} enregistrement(s)")
    print("Migration terminée.")


if __name__ == "__main__":
    main()
