"""
Migration : tables du volet régional (reliance CEEAC) + amorçage des pays.

Création de tables uniquement — aucune table existante n'est modifiée.
Idempotent : relançable sans risque.

Usage :  venv\\Scripts\\python migration_reliance.py
"""
import os
import shutil
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "sireph.db")

# Les 11 États membres. Modifiable ensuite depuis l'administration : ajouter,
# retirer ou passer un pays en « observateur » ne demande aucune reprise de code.
PAYS_CEEAC = [
    ("AO", "Angola", "membre"),
    ("BI", "Burundi", "membre"),
    ("CM", "Cameroun", "membre"),
    ("CG", "Congo", "membre"),
    ("GA", "Gabon", "membre"),
    ("GQ", "Guinée équatoriale", "membre"),
    ("CF", "République centrafricaine", "membre"),
    ("CD", "République démocratique du Congo", "membre"),
    # Statut rapporté de façon incohérente selon les sources : à confirmer par
    # la DPML, d'où le caractère configurable de cette liste.
    ("RW", "Rwanda", "membre"),
    ("ST", "São Tomé-et-Príncipe", "membre"),
    ("TD", "Tchad", "membre"),
]


def main():
    if not os.path.exists(BASE):
        print(f"Base introuvable : {BASE} — elle sera créée par seed.py.")
        return

    sauvegarde = f"{BASE}.avant-migration-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(BASE, sauvegarde)
    print(f"Sauvegarde : {os.path.basename(sauvegarde)}")

    import app as application
    from models import PaysCEEAC, db

    with application.app.app_context():
        db.create_all()          # ne touche pas aux tables déjà présentes
        print("Tables de reliance créées (ou déjà présentes).")

        ajoutes = 0
        for code, nom, statut in PAYS_CEEAC:
            if not PaysCEEAC.query.filter_by(code_iso=code).first():
                db.session.add(PaysCEEAC(
                    code_iso=code, nom=nom, statut=statut,
                    autorite=f"Autorité nationale de régulation pharmaceutique — {nom}",
                    dans_reliance=True))
                ajoutes += 1
        db.session.commit()
        total = PaysCEEAC.query.count()
        print(f"Pays CEEAC : {ajoutes} ajouté(s), {total} enregistré(s) au total.")


if __name__ == "__main__":
    main()
