"""
Migration : tables d'instruction (assignations, commissions, avis, rapports)
+ colonne checklist_recevabilite sur le dossier d'AMM.

Idempotent : relançable sans risque.
Usage :  venv\Scripts\python migration_instruction.py
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")


def main():
    if not os.path.exists(BASE):
        print("Base introuvable — elle sera creee par seed.py.")
        return
    sauvegarde = f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(BASE, sauvegarde)
    print(f"Sauvegarde : {os.path.basename(sauvegarde)}")

    con = sqlite3.connect(BASE)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(dossier_amm)")
    colonnes = {r[1] for r in cur.fetchall()}
    if "checklist_recevabilite" not in colonnes:
        cur.execute("ALTER TABLE dossier_amm ADD COLUMN checklist_recevabilite JSON")
        print("  dossier_amm.checklist_recevabilite : ajoutee")
    else:
        print("  dossier_amm.checklist_recevabilite : deja presente")
    con.commit()
    con.close()

    import app as application
    from models import db
    with application.app.app_context():
        db.create_all()
        from models import (AssignationEvaluation, AvisCommission, DossierSession,
                            RapportInstruction, SessionCommission)
        for M in (AssignationEvaluation, SessionCommission, DossierSession,
                  AvisCommission, RapportInstruction):
            print(f"  {M.__tablename__:26s} {M.query.count()} enregistrement(s)")
    print("Migration terminee.")


if __name__ == "__main__":
    main()
