"""
Seed de la gouvernance des accès (Lot A) : catégories, catalogue de
fonctionnalités, rôles et leurs défauts.

SOURCE
------
Lit `catalogue_fonctionnalites.py`. Les défauts par rôle y sont DÉDUITS des
actions réelles (permissions.PERMISSIONS_TRANSVERSES + roles des transitions),
pas saisis à la main.

IDEMPOTENCE / ENVIRONNEMENT
---------------------------
Se relance sans risque (met à jour au lieu de dupliquer). Comme les comptes de
démonstration, il est CONDITIONNÉ À UN ENVIRONNEMENT NON-PRODUCTION : refuse de
s'exécuter si SIREPH_ENV vaut prod/production.

    .venv/bin/python seed_gouvernance.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import catalogue_fonctionnalites as cat
from models import Categorie, Fonctionnalite, Personne, Role, db
from permissions import ROLES


def _est_production():
    return os.environ.get("SIREPH_ENV", "dev").lower() in ("prod", "production")


def seed_gouvernance():
    """Écrit catégories, fonctionnalités et rôles+défauts. Idempotent."""
    for code, libelle in cat.CATEGORIES.items():
        c = db.session.get(Categorie, code)
        if c is None:
            db.session.add(Categorie(code=code, libelle=libelle))
        else:
            c.libelle = libelle

    for f in cat.FONCTIONNALITES:
        obj = db.session.get(Fonctionnalite, f["code"])
        if obj is None:
            db.session.add(Fonctionnalite(
                code=f["code"], libelle=f["libelle"], module=f["module"],
                description=f.get("description"),
                sensible=bool(f.get("sensible", False))))
        else:
            obj.libelle = f["libelle"]
            obj.module = f["module"]
            obj.description = f.get("description")
            obj.sensible = bool(f.get("sensible", False))

    for code in ROLES:
        r = db.session.get(Role, code)
        if r is None:
            r = Role(code=code, libelle=ROLES[code],
                     categorie_code=cat.categorie_de(code))
            db.session.add(r)
        else:
            r.libelle = ROLES[code]
            r.categorie_code = cat.categorie_de(code)
        r.fonctionnalites_par_defaut = cat.defauts_role(code)

    db.session.commit()


def compter_super_admins_actifs():
    """Nombre de super administrateurs actifs (administrateur_dpml).

    La garantie « au moins un actif » est posée par seed_comptes.py (bootstrap) ;
    ce compteur permet de la CONTRÔLER après seed.
    """
    return Personne.query.filter_by(role_systeme="administrateur_dpml",
                                    statut_compte="actif").count()


def main():
    import app as application

    with application.app.app_context():
        if _est_production():
            print("SIREPH_ENV=production : seed de gouvernance IGNORÉ "
                  "(le catalogue de démonstration ne s'exécute jamais en prod).")
            return 0

        anomalies = cat.verifier_catalogue()
        if anomalies:
            print("Catalogue incohérent — seed interrompu :")
            for a in anomalies:
                print(f"  - {a}")
            return 1

        seed_gouvernance()

        n_admin = compter_super_admins_actifs()
        sensibles = Fonctionnalite.query.filter_by(sensible=True).count()
        print("=" * 70)
        print("GOUVERNANCE DES ACCÈS — catalogue amorcé")
        print("=" * 70)
        print(f"  catégories          : {Categorie.query.count()}")
        print(f"  fonctionnalités     : {Fonctionnalite.query.count()} "
              f"(dont {sensibles} sensibles 🔒)")
        print(f"  rôles catalogués    : {Role.query.count()} / {len(ROLES)}")
        print(f"  super admins actifs : {n_admin}"
              + ("   ⚠ AUCUN — lancez seed_comptes.py" if n_admin == 0 else ""))
        print()
        print("  Rappel : ce catalogue n'est pas encore branché sur "
              "l'autorisation (Étape 3).")
        return 0 if n_admin else 2


if __name__ == "__main__":
    sys.exit(main())
