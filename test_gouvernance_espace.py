"""
Tests de l'espace super administrateur (Lot A — routes).

On éprouve la protection CÔTÉ SERVEUR (permission_requise → utilisateur_peut) et
les flux des quatre onglets, pas seulement le rendu :
  * un non-admin est refusé (403) sur les onglets sensibles ;
  * validation d'une inscription (statut, décideur, date) ;
  * rejet motivé, et rejet sans motif refusé ;
  * auto-attribution refusée MÊME par la route (défense en profondeur) ;
  * le dernier super admin ne peut être suspendu.

Exécution :  venv\\Scripts\\python test_gouvernance_espace.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import seed_comptes as sc
from models import EvenementAudit, Personne, Role, SurchargeFonctionnalite, db

_res = []


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def _client(email):
    c = application.app.test_client()
    c.post("/login", data={"email": email,
                           "password": sc.mot_de_passe_courant(email)})
    return c


def _temp(role="demandeur_externe", statut="en_attente_validation"):
    p = Personne(nom_complet=f"Temp {role}",
                 email=f"temp.esp.{uuid.uuid4().hex[:8]}@test.local",
                 role_systeme=role, statut_compte=statut)
    p.set_password("x")
    db.session.add(p)
    db.session.commit()
    return p


def test_gating():
    print("\n[1] Protection serveur : non-admin refusé")
    ce = _client("evaluateur@dpml.demo")
    for path in ("/gouvernance/inscriptions", "/gouvernance/roles",
                 "/gouvernance/utilisateurs", "/gouvernance/journal"):
        verifier(f"évaluateur 403 sur {path}", ce.get(path).status_code == 403)


def test_onglets_admin():
    print("\n[2] Les quatre onglets répondent au super admin")
    ca = _client("admin@dpml.demo")
    for path in ("/gouvernance/inscriptions", "/gouvernance/roles",
                 "/gouvernance/utilisateurs", "/gouvernance/journal",
                 "/gouvernance/roles/chef_service_amm"):
        verifier(f"admin 200 sur {path}", ca.get(path).status_code == 200)


def test_valider_rejeter():
    print("\n[3] Valider et rejeter une inscription")
    ca = _client("admin@dpml.demo")
    a1 = _temp(statut="en_attente_validation")
    a2 = _temp(role="grossiste", statut="en_attente_validation")

    ca.post(f"/gouvernance/inscriptions/{a1.id}/valider",
            data={"role_systeme": "demandeur_externe"}, follow_redirects=True)
    a1r = db.session.get(Personne, a1.id)
    verifier("inscription validée → actif", a1r.statut_compte == "actif")
    verifier("décideur et date de décision renseignés",
             a1r.decide_par_id is not None and a1r.date_decision is not None)

    ca.post(f"/gouvernance/inscriptions/{a2.id}/rejeter",
            data={"motif": "Dossier incomplet"}, follow_redirects=True)
    verifier("rejet motivé → rejete",
             db.session.get(Personne, a2.id).statut_compte == "rejete")

    a3 = _temp(statut="en_attente_validation")
    ca.post(f"/gouvernance/inscriptions/{a3.id}/rejeter",
            data={"motif": ""}, follow_redirects=True)
    verifier("rejet sans motif refusé → reste en attente",
             db.session.get(Personne, a3.id).statut_compte == "en_attente_validation")


def test_auto_elevation_par_la_route():
    print("\n[4] Auto-attribution refusée même par la route")
    ca = _client("admin@dpml.demo")
    admin = Personne.query.filter_by(email="admin@dpml.demo").first()
    ca.post(f"/gouvernance/utilisateurs/{admin.id}/fonctionnalite",
            data={"code": "recevabilite.decider", "sens": "accorde",
                  "motif": "tentative"}, follow_redirects=True)
    pose = SurchargeFonctionnalite.query.filter_by(
        utilisateur_id=admin.id, fonctionnalite_code="recevabilite.decider").count()
    verifier("aucune surcharge posée sur soi-même par la route", pose == 0)


def test_dernier_super_admin():
    print("\n[5] Le dernier super admin ne peut être suspendu")
    ca = _client("admin@dpml.demo")
    admin = Personne.query.filter_by(email="admin@dpml.demo").first()
    ca.post(f"/gouvernance/utilisateurs/{admin.id}/suspendre",
            follow_redirects=True)
    verifier("le super admin reste actif",
             db.session.get(Personne, admin.id).statut_compte == "actif")


def test_edition_defauts_role():
    print("\n[6] Édition des défauts d'un rôle (avec restauration)")
    ca = _client("admin@dpml.demo")
    r = db.session.get(Role, "grossiste")
    original = list(r.fonctionnalites_par_defaut)
    nouveau = sorted(set(original) | {"tableau_bord.consulter"})
    ca.post("/gouvernance/roles/grossiste",
            data={"fonctionnalite": nouveau}, follow_redirects=True)
    db.session.expire_all()
    verifier("défauts du rôle mis à jour",
             set(db.session.get(Role, "grossiste").fonctionnalites_par_defaut)
             == set(nouveau))
    # restauration
    db.session.get(Role, "grossiste").fonctionnalites_par_defaut = original
    db.session.commit()


def _nettoyer(bornes):
    db.session.rollback()
    p0, s0, a0 = bornes
    SurchargeFonctionnalite.query.filter(SurchargeFonctionnalite.id > s0).delete()
    EvenementAudit.query.filter(EvenementAudit.id > a0).delete()
    Personne.query.filter(Personne.id > p0).delete()
    db.session.commit()


def main():
    print("=" * 70)
    print("Espace super administrateur — routes et protection serveur")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        bornes = (
            db.session.query(db.func.max(Personne.id)).scalar() or 0,
            db.session.query(db.func.max(SurchargeFonctionnalite.id)).scalar() or 0,
            db.session.query(db.func.max(EvenementAudit.id)).scalar() or 0,
        )
        try:
            for t in (test_gating, test_onglets_admin, test_valider_rejeter,
                      test_auto_elevation_par_la_route, test_dernier_super_admin,
                      test_edition_defauts_role):
                try:
                    t()
                except Exception as e:                   # noqa: BLE001
                    db.session.rollback()
                    verifier(f"{t.__name__} sans exception", False,
                             f"{type(e).__name__}: {e}")
        finally:
            _nettoyer(bornes)

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
