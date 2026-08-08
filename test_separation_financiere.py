"""
Tests de la séparation des tâches entre les finances et l'instruction.

La règle éprouvée ici : celui qui constate l'entrée des fonds n'est pas celui
qui instruit le dossier, et l'approbation financière — et elle seule — ouvre la
recevabilité. Les deux moitiés comptent autant : une séparation qui bloquerait
sans jamais débloquer paralyserait la procédure.

Exécution :  venv\\Scripts\\python test_separation_financiere.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import paiements as pmt
import seed_comptes as sc
import suivi
import workflow_instruction as wfi
from erreurs import ErreurWorkflow
from models import (AssignationEvaluation, DossierAMM, Etablissement,
                    EvenementAudit, Notification, Paiement, Personne, Produit, db)
from permissions import a_permission

_res = []
_MODELES = (AssignationEvaluation, EvenementAudit, Paiement, DossierAMM, Produit,
            Notification, Personne, Etablissement)


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def leve(fn, motif=None):
    try:
        fn()
        return False
    except ErreurWorkflow as e:
        return motif is None or motif.lower() in str(e).lower()


def _max_ids():
    return {M: (db.session.query(db.func.max(M.id)).scalar() or 0) for M in _MODELES}


def _nettoyer(reperes):
    for M in _MODELES:
        for obj in M.query.filter(M.id > reperes[M]).all():
            db.session.delete(obj)
    db.session.commit()


def _r(role):
    return Personne.query.filter_by(role_systeme=role).first()


def _dossier_avec_creance():
    """Un dossier soumis, sa preuve de paiement déposée, prêt à être approuvé."""
    s = uuid.uuid4().hex[:6]
    etab = Etablissement(raison_sociale=f"Sep-{s}", type="importateur_exportateur",
                         statut_licence="active")
    db.session.add(etab)
    db.session.flush()
    dep = Personne(nom_complet=f"Déposant {s}", email=f"sep{s}@test.demo",
                   role_systeme="demandeur_externe", statut_compte="actif",
                   etablissement_rattachement_id=etab.id)
    dep.set_password("pw")
    db.session.add(dep)
    db.session.flush()
    p = Produit(nom_commercial=f"P{s}", forme_pharmaceutique="Comprimé",
                nature="chimique", titulaire_amm_id=etab.id)
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=f"AMM-SEP-{s}", produit_id=p.id, demandeur_id=dep.id,
                   statut="soumis")
    db.session.add(d)
    db.session.flush()
    pay = Paiement(numero=f"PAY-SEP-{s}", entite_type="DossierAMM", entite_id=d.id,
                   montant=500000, devise="XAF", statut="preuve_deposee")
    db.session.add(pay)
    db.session.flush()
    return d, dep, pay


def test_role_financier_existe():
    print("\n[1] Le responsable financier est un rôle à part entière")
    from permissions import NIVEAU_PAR_ROLE, ROLES
    verifier("rôle déclaré au référentiel", "responsable_financier" in ROLES)
    verifier("niveau de chef de service",
             NIVEAU_PAR_ROLE["responsable_financier"] == 3)
    verifier("un compte existe", _r("responsable_financier") is not None)
    verifier("il figure au jeu de comptes de démonstration",
             "responsable_financier" in sc.COMPTES)


def test_qui_peut_approuver():
    print("\n[2] Qui peut approuver une recette")
    fin = _r("responsable_financier")
    verifier("le responsable financier approuve",
             a_permission(fin, "confirmer_paiement"))
    for role in ("administrateur_dpml", "directeur_dpml", "chef_service_amm",
                 "ministre_sante", "chef_bureau", "demandeur_externe"):
        verifier(f"« {role} » n'approuve pas",
                 not a_permission(_r(role), "confirmer_paiement"))
    verifier("l'administrateur garde l'exploitation de la plateforme",
             a_permission(_r("administrateur_dpml"), "gerer_paiements"))
    verifier("le ministre n'acquiert pas l'approbation par son rang",
             not a_permission(_r("ministre_sante"), "confirmer_paiement"))


def test_refus_hors_finances():
    print("\n[3] Le moteur refuse l'approbation hors des finances")
    d, _dep, pay = _dossier_avec_creance()
    for role in ("administrateur_dpml", "directeur_dpml", "chef_service_amm",
                 "ministre_sante"):
        verifier(f"« {role} » ne confirme pas au niveau du moteur",
                 leve(lambda r=role: pmt.confirmer(pay, _r(r)),
                      "responsable financier"))
    verifier("le rejet d'une preuve relève aussi des finances",
             leve(lambda: pmt.rejeter(pay, _r("administrateur_dpml"), "motif"),
                  "responsable financier"))
    verifier("la créance reste en attente", pay.statut == "preuve_deposee")


def test_pas_d_auto_approbation():
    print("\n[4] Nul n'approuve sa propre recette")
    d, dep, pay = _dossier_avec_creance()
    fin = _r("responsable_financier")

    # Un financier qui serait lui-même le redevable.
    verifier("le redevable ne s'approuve pas lui-même",
             leve(lambda: pmt.controler_separation(pay, dep),
                  "responsable financier"))

    # Un financier rattaché au même établissement que le redevable.
    ancien = fin.etablissement_rattachement_id
    fin.etablissement_rattachement_id = dep.etablissement_rattachement_id
    db.session.flush()
    verifier("un financier de la société du redevable est écarté",
             leve(lambda: pmt.controler_separation(pay, fin), "établissement"))
    fin.etablissement_rattachement_id = ancien
    db.session.flush()
    verifier("hors de cette société, le contrôle passe",
             pmt.controler_separation(pay, fin))


def test_pas_d_approbation_par_l_evaluateur():
    print("\n[5] L'évaluateur du dossier n'en approuve pas la recette")
    d, _dep, pay = _dossier_avec_creance()
    fin = _r("responsable_financier")
    db.session.add(AssignationEvaluation(dossier_id=d.id, evaluateur_id=fin.id,
                                         assigne_par_id=fin.id, statut="assignee"))
    db.session.flush()
    verifier("un évaluateur assigné ne peut pas approuver",
             leve(lambda: pmt.controler_separation(pay, fin), "évaluateur assigné"))


def test_approbation_debloque_le_chef_de_service():
    print("\n[6] L'approbation ouvre la recevabilité, automatiquement")
    d, dep, pay = _dossier_avec_creance()
    chef = _r("chef_service_amm")
    fin = _r("responsable_financier")

    wfi.enregistrer_checklist(d, chef, {c: True for c in wfi.POINTS_BLOQUANTS})
    db.session.flush()
    verifier("le chef de service ne coche pas la preuve de paiement",
             not (d.checklist_recevabilite or {}).get("preuve_paiement"))
    verifier("il ne peut donc pas prononcer la recevabilité",
             leve(lambda: wfi.prononcer_recevabilite(d, chef, True), "paiement"))
    verifier("le délai légal n'a pas démarré", d.clock_debut is None)

    avant = Notification.query.filter_by(type="recette_approuvee").count()
    pmt.confirmer(pay, fin)
    db.session.flush()

    verifier("la recette est approuvée", pay.statut == "confirme")
    verifier("l'approbation est nominative", pay.confirme_par_id == fin.id)
    verifier("le point « preuve de paiement » est attesté",
             (d.checklist_recevabilite or {}).get("preuve_paiement") is True)
    verifier("plus aucun point bloquant", not wfi.points_manquants(d))
    verifier("le délai légal démarre à l'approbation", d.clock_debut is not None)
    verifier("le service instructeur est averti",
             Notification.query.filter_by(type="recette_approuvee").count() > avant)
    notif = (Notification.query.filter_by(type="recette_approuvee")
             .order_by(Notification.id.desc()).first())
    verifier("le message annonce que la recevabilité peut être prononcée",
             notif is not None and "recevabilité peut être prononcée" in notif.contenu)

    wfi.prononcer_recevabilite(d, chef, True)
    db.session.flush()
    verifier("le chef de service peut alors aller de l'avant",
             d.statut == "evaluation_en_cours")
    verifier("l'état visible du demandeur suit", suivi.etat_visible(d) == "evaluation")


def test_traçabilite():
    print("\n[7] Traçabilité de l'approbation")
    d, _dep, pay = _dossier_avec_creance()
    fin = _r("responsable_financier")
    pmt.confirmer(pay, fin)
    db.session.flush()

    traces = EvenementAudit.query.filter_by(entite_type="Paiement",
                                            entite_id=pay.id).all()
    verifier("l'approbation est journalisée",
             any("Recette approuvée" in e.action for e in traces))
    verifier("elle nomme son auteur",
             any(e.acteur_id == fin.id for e in traces))
    traces_d = EvenementAudit.query.filter_by(entite_type="DossierAMM",
                                              entite_id=d.id).all()
    verifier("l'attestation est journalisée sur le dossier",
             any("attestée par le responsable financier" in e.action
                 for e in traces_d))
    verifier("le départ du délai est journalisé",
             any("Délai légal d'instruction démarré" in e.action for e in traces_d))


def test_attestation_idempotente():
    print("\n[8] Robustesse")
    d, _dep, pay = _dossier_avec_creance()
    fin = _r("responsable_financier")
    pmt.confirmer(pay, fin)
    db.session.flush()
    debut = d.clock_debut

    # Une seconde créance sur le même dossier ne réinitialise pas le décompte.
    pay2 = Paiement(numero=f"PAY-BIS-{uuid.uuid4().hex[:6]}",
                    entite_type="DossierAMM", entite_id=d.id, montant=100000,
                    devise="XAF", statut="preuve_deposee")
    db.session.add(pay2)
    db.session.flush()
    pmt.confirmer(pay2, fin)
    db.session.flush()
    verifier("le délai n'est pas redémarré par une seconde recette",
             d.clock_debut == debut)
    verifier("double approbation de la même créance refusée",
             leve(lambda: pmt.confirmer(pay, fin), "preuve déposée"))

    # Le chef de service ne peut pas décocher ce que les finances ont attesté.
    wfi.enregistrer_checklist(d, _r("chef_service_amm"),
                              {c: False for c in wfi.POINTS_BLOQUANTS})
    db.session.flush()
    verifier("le chef de service ne peut pas décocher l'attestation",
             (d.checklist_recevabilite or {}).get("preuve_paiement") is True)


def test_ecran_d_approbation():
    print("\n[9] Guichet d'approbation")
    client = application.app.test_client()
    courriel = sc.COMPTES["responsable_financier"][1]
    client.post("/login", data={"email": courriel,
                                "password": sc.mot_de_passe_courant(courriel)})
    r = client.get("/paiements/approbation")
    verifier("le responsable financier accède au guichet", r.status_code == 200,
             str(r.status_code))
    page = r.get_data(as_text=True)
    verifier("l'écran annonce l'effet de l'approbation",
             "délai légal" in page and "recevabilité" in page)

    for role in ("administrateur_dpml", "directeur_dpml", "chef_service_amm",
                 "ministre_sante", "demandeur_externe"):
        autre = application.app.test_client()
        adresse = sc.COMPTES[role][1]
        autre.post("/login", data={"email": adresse,
                                   "password": sc.mot_de_passe_courant(adresse)})
        verifier(f"« {role} » n'atteint pas le guichet",
                 autre.get("/paiements/approbation").status_code == 403)

    # L'action elle-même, pas seulement l'écran.
    d, _dep, pay = _dossier_avec_creance()
    db.session.commit()
    admin = application.app.test_client()
    adm = sc.COMPTES["administrateur_dpml"][1]
    admin.post("/login", data={"email": adm,
                               "password": sc.mot_de_passe_courant(adm)})
    verifier("l'administrateur ne peut pas approuver par la route",
             admin.post(f"/paiements/{pay.id}/approuver").status_code == 403)
    db.session.refresh(pay)
    verifier("la créance est restée en attente", pay.statut == "preuve_deposee")


def main():
    print("=" * 70)
    print("Séparation des tâches — finances et instruction")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        reperes = _max_ids()
        for t in (test_role_financier_existe, test_qui_peut_approuver,
                  test_refus_hors_finances, test_pas_d_auto_approbation,
                  test_pas_d_approbation_par_l_evaluateur,
                  test_approbation_debloque_le_chef_de_service,
                  test_traçabilite, test_attestation_idempotente,
                  test_ecran_d_approbation):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False,
                         f"{type(e).__name__}: {e}")
        db.session.rollback()
        _nettoyer(reperes)

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
