"""
Migration : numero national de suivi et decompte du delai legal.
Idempotent. Usage : venv/Scripts/python migration_suivi.py
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")

COLONNES = [
    ("numero_suivi", "VARCHAR(40)"),
    ("clock_debut", "DATETIME"),
    ("clock_suspendu_depuis", "DATETIME"),
    ("clock_total_suspendu_jours", "INTEGER DEFAULT 0"),
]


def main():
    if not os.path.exists(BASE):
        print("Base introuvable.")
        return
    shutil.copy2(BASE, f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}")
    con = sqlite3.connect(BASE)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(dossier_amm)")
    cols = {r[1] for r in cur.fetchall()}
    for nom, definition in COLONNES:
        if nom in cols:
            print(f"  dossier_amm.{nom} : deja presente")
            continue
        cur.execute(f"ALTER TABLE dossier_amm ADD COLUMN {nom} {definition}")
        print(f"  dossier_amm.{nom} : ajoutee")
    con.commit()
    con.close()

    # Attribution retroactive d'un numero de suivi aux dossiers deja deposes.
    import app as application
    import suivi
    from models import DossierAMM, db
    with application.app.app_context():
        attribues = 0
        for d in DossierAMM.query.filter(DossierAMM.numero_suivi.is_(None)).all():
            d.numero_suivi = suivi.numero_suivi("amm")
            attribues += 1
        db.session.commit()
        print(f"  {attribues} numero(s) de suivi attribue(s) retroactivement")
    print("Migration terminee.")


if __name__ == "__main__":
    main()
