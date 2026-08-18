"""
Tests de la gouvernance des accès (Lot A) — résolveur utilisateur_peut et
service de surcharges.

Ce que l'on établit :
  * DÉFAUTS — un rôle détient les fonctionnalités par défaut de son catalogue,
    et rien de plus.
  * REPLI — une clé historique non migrée se résout comme avant (a_permission).
  * SURCHARGE — accorder ajoute, retirer prime sur le défaut du rôle.
  * COMPTE NON ACTIF — en attente, rejeté ou suspendu échoue toujours.
  * ANTI-AUTO-ÉLÉVATION — nul ne s'attribue de fonctionnalité, ni n'en attribue
    sans en avoir le droit ; toute tentative est refusée ET journalisée.

Exécution :  venv\\Scripts\\python test_gouvernance_acces.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import gouvernance as gouv
import seed_comptes as sc
from audit import db
from models import EvenementAudit, Personne, SurchargeFonctionnalite
from permissions import utilisateur_peut

_res = []


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def leve(fn, exc):
    """Vrai si l'appel lève bien l'exception attendue."""
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:                                    # noqa: BLE001
        return False


def _compte(email):
    return Personne.query.filter_by(email=email).first()


def _temp(role, statut="actif"):
    """Crée un compte temporaire committé (nettoyé en fin de suite)."""
    p = Personne(nom_complet=f"Temp {role}",
                 email=f"temp.gouv.{uuid.uuid4().hex[:8]}@test.local",
                 role_systeme=role, statut_compte=statut)
    p.set_password("x")
    db.session.add(p)
    db.session.commit()
    return p


def _refus_audit_depuis(borne_id):
    return EvenementAudit.query.filter(
        EvenementAudit.id > borne_id,
        EvenementAudit.action.like("REFUS%")).count()


def test_defauts_du_role():
    print("\n[1] Défauts du rôle (catalogue)")
    fin = _compte("finances@dpml.demo")        # responsable_financier
    cs = _compte("chefservice@dpml.demo")      # chef_service_amm
    admin = _compte("admin@dpml.demo")         # administrateur_dpml
    evalu = _compte("evaluateur@dpml.demo")    # evaluateur_amm
    verifier("financier a paiement.valider (défaut)",
             utilisateur_peut(fin, "paiement.valider"))
    verifier("financier n'a PAS recevabilite.decider",
             not utilisateur_peut(fin, "recevabilite.decider"))
    verifier("chef de service a recevabilite.decider",
             utilisateur_peut(cs, "recevabilite.decider"))
    verifier("admin a fonctionnalite.attribuer",
             utilisateur_peut(admin, "fonctionnalite.attribuer"))
    verifier("évaluateur n'a PAS paiement.valider",
             not utilisateur_peut(evalu, "paiement.valider"))
    verifier("un code inconnu n'est accordé à personne",
             not utilisateur_peut(admin, "code.inexistant"))


def test_repli_legacy():
    print("\n[2] Repli sur les clés historiques (a_permission)")
    fin = _compte("finances@dpml.demo")
    admin = _compte("admin@dpml.demo")
    evalu = _compte("evaluateur@dpml.demo")
    verifier("financier résout confirmer_paiement (legacy)",
             utilisateur_peut(fin, "confirmer_paiement"))
    verifier("admin résout gerer_referentiels (legacy)",
             utilisateur_peut(admin, "gerer_referentiels"))
    verifier("évaluateur ne résout PAS gerer_referentiels",
             not utilisateur_peut(evalu, "gerer_referentiels"))


def test_surcharges():
    print("\n[3] Surcharges : accordée ajoute, retirée prime")
    admin = _compte("admin@dpml.demo")
    t_eval = _temp("evaluateur_amm")
    t_fin = _temp("responsable_financier")

    verifier("avant surcharge : évaluateur sans paiement.valider",
             not utilisateur_peut(t_eval, "paiement.valider"))
    gouv.accorder(admin, t_eval, "paiement.valider", motif="test accord")
    verifier("surcharge ACCORDÉE : évaluateur obtient paiement.valider",
             utilisateur_peut(t_eval, "paiement.valider"))

    verifier("avant surcharge : financier a paiement.valider (défaut)",
             utilisateur_peut(t_fin, "paiement.valider"))
    gouv.retirer(admin, t_fin, "paiement.valider", motif="test retrait")
    verifier("surcharge RETIRÉE : financier perd paiement.valider",
             not utilisateur_peut(t_fin, "paiement.valider"))


def test_compte_non_actif():
    print("\n[4] Un compte non actif échoue toujours")
    t_susp = _temp("administrateur_dpml", statut="suspendu")
    t_att = _temp("responsable_financier", statut="en_attente_validation")
    t_rej = _temp("responsable_financier", statut="rejete")
    verifier("suspendu : pas de fonctionnalite.attribuer malgré le rôle",
             not utilisateur_peut(t_susp, "fonctionnalite.attribuer"))
    verifier("en attente : pas de paiement.valider malgré le rôle",
             not utilisateur_peut(t_att, "paiement.valider"))
    verifier("rejeté : pas de paiement.valider malgré le rôle",
             not utilisateur_peut(t_rej, "paiement.valider"))


def test_anti_auto_elevation():
    print("\n[5] Anti-auto-élévation (refus + journalisation)")
    admin = _compte("admin@dpml.demo")
    evalu = _compte("evaluateur@dpml.demo")       # non-admin
    t_cible = _temp("evaluateur_amm")

    # a) Le super admin ne s'attribue rien à lui-même.
    borne = db.session.query(db.func.max(EvenementAudit.id)).scalar() or 0
    verifier("admin NE PEUT PAS s'attribuer une fonctionnalité",
             leve(lambda: gouv.accorder(admin, admin, "recevabilite.decider",
                                        motif="soi"), gouv.ErreurGouvernance))
    verifier("le refus (auto-attribution) est journalisé",
             _refus_audit_depuis(borne) >= 1)

    # b) Un non-admin ne peut attribuer à personne.
    borne = db.session.query(db.func.max(EvenementAudit.id)).scalar() or 0
    verifier("un non-admin NE PEUT PAS attribuer une fonctionnalité",
             leve(lambda: gouv.accorder(evalu, t_cible, "paiement.valider",
                                        motif="tentative"),
                  gouv.ErreurGouvernance))
    verifier("le refus (droit absent) est journalisé",
             _refus_audit_depuis(borne) >= 1)
    verifier("aucune surcharge n'a été posée par la tentative refusée",
             SurchargeFonctionnalite.query.filter_by(
                 utilisateur_id=t_cible.id,
                 fonctionnalite_code="paiement.valider").count() == 0)

    # c) Le retrait sur soi-même est également refusé.
    verifier("admin NE PEUT PAS se retirer une fonctionnalité",
             leve(lambda: gouv.retirer(admin, admin, "referentiel.gerer",
                                       motif="soi"), gouv.ErreurGouvernance))

    # d) Contrôle positif : le super admin attribue bien à autrui.
    gouv.accorder(admin, t_cible, "audit.consulter", motif="habilitation")
    verifier("le super admin attribue bien à un TIERS",
             utilisateur_peut(t_cible, "audit.consulter"))


def _nettoyer(bornes):
    """Supprime tout ce que la suite a committé (comptes, surcharges, audit)."""
    db.session.rollback()
    p0, s0, a0 = bornes
    SurchargeFonctionnalite.query.filter(SurchargeFonctionnalite.id > s0).delete()
    EvenementAudit.query.filter(EvenementAudit.id > a0).delete()
    Personne.query.filter(Personne.id > p0).delete()
    db.session.commit()


def main():
    print("=" * 70)
    print("Gouvernance des accès — utilisateur_peut et surcharges")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        bornes = (
            db.session.query(db.func.max(Personne.id)).scalar() or 0,
            db.session.query(db.func.max(SurchargeFonctionnalite.id)).scalar() or 0,
            db.session.query(db.func.max(EvenementAudit.id)).scalar() or 0,
        )
        try:
            for t in (test_defauts_du_role, test_repli_legacy, test_surcharges,
                      test_compte_non_actif, test_anti_auto_elevation):
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
