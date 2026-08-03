"""
Migration : nature du produit (pilote les modules CTD obligatoires).

Idempotent. Usage :  venv\Scripts\python migration_ctd.py
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
    cur.execute("PRAGMA table_info(produit)")
    cols = {r[1] for r in cur.fetchall()}
    if "nature" not in cols:
        cur.execute("ALTER TABLE produit ADD COLUMN nature VARCHAR(30)")
        print("  produit.nature : ajoutee")
    else:
        print("  produit.nature : deja presente")
    # Renseigne la nature a partir de la categorie existante
    cur.execute("""UPDATE produit SET nature = CASE categorie
                     WHEN 'vaccin' THEN 'biologique'
                     WHEN 'produit_sanguin' THEN 'biologique'
                     WHEN 'dispositif_medical' THEN 'dispositif_medical'
                     WHEN 'autre' THEN 'autre'
                     ELSE 'chimique' END
                   WHERE nature IS NULL""")
    print(f"  {cur.rowcount} produit(s) classes par nature")
    con.commit()
    con.close()
    print("Migration terminee.")


if __name__ == "__main__":
    main()
