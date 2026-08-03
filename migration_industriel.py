"""
Migration : circuit de validation numérique + demandes d'inspection.

Création de tables uniquement, aucune table existante n'est modifiée.
Idempotent : relançable sans risque.

Usage :  venv\Scripts\python migration_industriel.py
"""
import os
import shutil
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")


def main():
    if not os.path.exists(BASE):
        print(f"Base introuvable : {BASE} — elle sera creee par seed.py.")
        return
    sauvegarde = f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(BASE, sauvegarde)
    print(f"Sauvegarde : {os.path.basename(sauvegarde)}")

    import app as application
    from models import db

    with application.app.app_context():
        db.create_all()
        from models import DemandeInspection, EtapeValidation
        print(f"  etape_validation   : {EtapeValidation.query.count()} enregistrement(s)")
        print(f"  demande_inspection : {DemandeInspection.query.count()} enregistrement(s)")
    print("Migration terminee.")


if __name__ == "__main__":
    main()
