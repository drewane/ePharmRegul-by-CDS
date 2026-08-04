"""
Migration : déclarations d'intérêts, liens et déports + mention au PV.
Idempotent. Usage : venv\Scripts\python migration_dpi.py
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")


def main():
    if not os.path.exists(BASE):
        print("Base introuvable.")
        return
    shutil.copy2(BASE, f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}")
    con = sqlite3.connect(BASE)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(session_commission)")
    cols = {r[1] for r in cur.fetchall()}
    if "mention_deports" not in cols:
        cur.execute("ALTER TABLE session_commission ADD COLUMN mention_deports TEXT")
        print("  session_commission.mention_deports : ajoutee")
    con.commit()
    con.close()

    import app as application
    from models import db
    with application.app.app_context():
        db.create_all()
        from models import DeclarationInteret, Deport, LienInteret
        for M in (DeclarationInteret, LienInteret, Deport):
            print(f"  {M.__tablename__:24s} {M.query.count()} enregistrement(s)")
    print("Migration terminee.")


if __name__ == "__main__":
    main()
