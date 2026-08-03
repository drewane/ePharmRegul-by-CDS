"""
Tests du circuit d'instruction, de la recevabilité au rapport de direction.

Exécution :  venv\\Scripts\\python test_instruction.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import validation_numerique as vn
import workflow_instruction as wfi
from erreurs import ErreurWorkflow
from models import (AssignationEvaluation, AvisCommission, DossierAMM,
                    DossierSession, Etablissement, EtapeValidation, Notification,
                    Personne, Produit, RapportInstruction, SessionCommission, db)

_res = []
_MODELES = (AvisCommission, DossierSession, SessionCommission, RapportInstruction,
            AssignationEvaluation, EtapeValidation, DossierAMM, Produit, Notification,
            Personne, Etablissement)


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


def _dossier_soumis():
    s = uuid.uuid4().hex[:6]
    etab = Etablissement(raison_sociale=f"Labo-{s}", type="importateur_exportateur",
                         statut_licence="active")
    db.session.add(etab)
    db.session.flush()
    dep = Personne(nom_complet=f"Déposant {s}", email=f"d{s}@test.demo",
                   role_systeme="demandeur_externe", statut_compte="actif",
                   etablissement_rattachement_id=etab.id)
    dep.set_password("pw")
    db.session.add(dep)
    db.session.flush()
    p = Produit(nom_commercial=f"Produit {s}", forme_pharmaceutique="Comprimé",
                denomination_commune_internationale="Testine", titulaire_amm_id=etab.id)
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=f"AMM-T-{s}", produit_id=p.id, demandeur_id=dep.id,
                   statut="soumis")
    db.session.add(d)
    db.session.flush()
    return d, dep


def _r(role):
    return Personne.query.filter_by(role_systeme=role).first()


def test_recevabilite_checklist():
    print("\n[1] Recevabilité — liste de contrôle bloquante")
    d, dep = _dossier_soumis()
    chef = _r("chef_service_amm")

    verifier("points bloquants identifiés",
             len(wfi.points_manquants(d)) == len(wfi.POINTS_BLOQUANTS),
             f"{len(wfi.POINTS_BLOQUANTS)} points")
    verifier("recevabilité refusée si la liste est incomplète",
             leve(lambda: wfi.prononcer_recevabilite(d, chef, True),
                  "Recevabilité impossible"))

    # On coche tout sauf la preuve de paiement : toujours bloquant.
    partiel = {c: True for c in wfi.POINTS_BLOQUANTS if c != "preuve_paiement"}
    wfi.enregistrer_checklist(d, chef, partiel)
    db.session.flush()
    verifier("un seul point bloquant manquant suffit à refuser",
             leve(lambda: wfi.prononcer_recevabilite(d, chef, True), "paiement"))

    wfi.enregistrer_checklist(d, chef, {c: True for c in wfi.POINTS_BLOQUANTS})
    db.session.flush()
    avant = Notification.query.filter_by(destinataire_id=dep.id).count()
    wfi.prononcer_recevabilite(d, chef, True)
    db.session.flush()
    verifier("dossier recevable → évaluation ouverte", d.statut == "evaluation_en_cours")
    verifier("le déposant est informé de l'acceptation",
             Notification.query.filter_by(destinataire_id=dep.id).count() > avant)
    notif = (Notification.query.filter_by(destinataire_id=dep.id,
                                          type="dossier_recevable")
             .order_by(Notification.id.desc()).first())
    verifier("le message annonce l'évaluation en cours",
             notif is not None and "évaluation" in notif.contenu)


def test_irrecevabilite_motivee():
    print("\n[2] Irrecevabilité motivée")
    d, _dep = _dossier_soumis()
    chef = _r("chef_service_amm")
    verifier("irrecevabilité sans motif refusée",
             leve(lambda: wfi.prononcer_recevabilite(d, chef, False, ""), "motivée"))
    wfi.prononcer_recevabilite(d, chef, False, "Dossier technique incomplet.")
    db.session.flush()
    verifier("dossier déclaré irrecevable", d.statut == "irrecevable")
    verifier("motif conservé", "incomplet" in (d.motif_decision or ""))


def _recevable():
    d, dep = _dossier_soumis()
    chef = _r("chef_service_amm")
    wfi.enregistrer_checklist(d, chef, {c: True for c in wfi.POINTS_BLOQUANTS})
    wfi.prononcer_recevabilite(d, chef, True)
    db.session.flush()
    return d, dep, chef


def test_evaluation_interne():
    print("\n[3] Évaluation interne")
    d, _dep, chef = _recevable()
    ev1, ev2 = _r("evaluateur_interne"), Personne.query.filter_by(
        role_systeme="evaluateur_interne").offset(1).first()
    if not (ev1 and ev2):
        verifier("deux évaluateurs internes disponibles", False)
        return

    a = wfi.assigner(d, ev1, chef, "Examiner la partie qualité")
    db.session.flush()
    verifier("dossier assigné", a.statut == "assignee")
    verifier("échéance fixée", a.date_echeance is not None)
    verifier("double assignation du même évaluateur refusée",
             leve(lambda: wfi.assigner(d, ev1, chef), "déjà assigné"))
    verifier("assignation à un non-évaluateur refusée",
             leve(lambda: wfi.assigner(d, chef, chef), "évaluateur interne"))
    wfi.assigner(d, ev2, chef)
    db.session.flush()
    verifier("plusieurs évaluateurs possibles",
             len(wfi.etat_instruction(d)["assignations"]) == 2)

    verifier("un autre évaluateur ne peut pas remettre ce rapport",
             leve(lambda: wfi.remettre_evaluation(a, ev2, "x", "favorable"),
                  "évaluateur assigné"))
    verifier("rapport vide refusé",
             leve(lambda: wfi.remettre_evaluation(a, ev1, "", "favorable")))
    wfi.remettre_evaluation(a, ev1, "Qualité conforme.", "favorable")
    db.session.flush()
    verifier("évaluation remise", a.statut == "terminee")
    verifier("le chef de service est informé",
             Notification.query.filter_by(destinataire_id=chef.id,
                                          type="evaluation_remise").count() >= 1)
    verifier("double remise refusée",
             leve(lambda: wfi.remettre_evaluation(a, ev1, "x", "favorable"), "déjà"))


def test_commission_et_synthese():
    print("\n[4] Commission — avis des membres et synthèse automatique")
    d, _dep, chef = _recevable()
    membres = Personne.query.filter_by(
        role_systeme="membre_commission_specialisee").limit(3).all()
    if len(membres) < 3:
        verifier("trois membres de commission disponibles", False)
        return

    s = wfi.convoquer_commission(chef, "Séance de test")
    db.session.flush()
    verifier("séance convoquée", s.numero.startswith("COM-"), s.numero)
    verifier("les membres sont convoqués",
             Notification.query.filter_by(type="commission_convoquee").count() >= 1)

    ds = wfi.inscrire_dossier(s, d, chef)
    db.session.flush()
    verifier("dossier inscrit à l'ordre du jour", ds.id is not None)
    verifier("double inscription refusée",
             leve(lambda: wfi.inscrire_dossier(s, d, chef), "déjà inscrit"))

    reponses = {code: "oui" for code, _q in wfi.GRILLE_COMMISSION}
    wfi.saisir_avis(ds, membres[0], reponses, "favorable")
    wfi.saisir_avis(ds, membres[1], reponses, "favorable")
    wfi.saisir_avis(ds, membres[2], reponses, "defavorable",
                    "Données de stabilité insuffisantes.")
    db.session.flush()
    verifier("trois avis saisis",
             AvisCommission.query.filter_by(dossier_session_id=ds.id).count() == 3)
    verifier("avis défavorable sans motif refusé",
             leve(lambda: wfi.saisir_avis(ds, membres[0], reponses, "defavorable"),
                  "motivé"))
    verifier("un non-membre ne peut pas siéger",
             leve(lambda: wfi.saisir_avis(ds, chef, reponses, "favorable"), "profil"))

    # Un membre peut corriger son avis tant que la séance est ouverte
    wfi.saisir_avis(ds, membres[0], reponses, "favorable", "Avis confirmé.")
    db.session.flush()
    verifier("un membre ne crée pas de doublon en se corrigeant",
             AvisCommission.query.filter_by(dossier_session_id=ds.id).count() == 3)

    wfi.clore_seance(s, chef)
    db.session.flush()
    verifier("séance close", s.statut == "close")
    verifier("avis global majoritaire retenu", ds.avis_global == "favorable",
             str(ds.avis_global))
    verifier("synthèse produite automatiquement", bool(ds.synthese))
    verifier("la synthèse reprend les motifs",
             "stabilité" in (ds.synthese or "").lower())
    verifier("plus aucun avis après clôture",
             leve(lambda: wfi.saisir_avis(ds, membres[0], reponses, "favorable"),
                  "close"))


def test_synthese_prudente():
    print("\n[5] Synthèse — le complément prime en l'absence de majorité")
    d, _dep, chef = _recevable()
    membres = Personne.query.filter_by(
        role_systeme="membre_commission_specialisee").limit(2).all()
    s = wfi.convoquer_commission(chef, "Séance partagée")
    ds = wfi.inscrire_dossier(s, d, chef)
    db.session.flush()
    wfi.saisir_avis(ds, membres[0], {}, "favorable")
    wfi.saisir_avis(ds, membres[1], {}, "complement_requis", "Manque la bioéquivalence.")
    db.session.flush()
    wfi.clore_seance(s, chef)
    db.session.flush()
    verifier("à égalité, le complément l'emporte",
             ds.avis_global == "complement_requis", str(ds.avis_global))


def test_rapport_ouvre_le_circuit():
    print("\n[6] Rapport du chef de service → circuit de signature")
    d, _dep, chef = _recevable()
    verifier("avis défavorable sans motif refusé",
             leve(lambda: wfi.rediger_rapport(d, chef, "defavorable"), "motivé"))

    wfi.rediger_rapport(d, chef, "favorable", "Instruction complète, avis favorable.")
    db.session.flush()
    verifier("rapport enregistré",
             RapportInstruction.query.filter_by(dossier_id=d.id).first() is not None)
    verifier("circuit de signature ouvert", vn.circuit_ouvert(d))
    verifier("circuit AMM à 5 échelons", len(vn.etapes(d)) == 5)
    verifier("premier échelon = chef de service",
             vn.etape_courante(d).role_requis == "chef_service_amm")
    verifier("double rapport refusé",
             leve(lambda: wfi.rediger_rapport(d, chef, "favorable"), "déjà"))


def test_rapport_complement_retourne_au_deposant():
    print("\n[7] Complément de dossier — retour au déposant sans saisir la direction")
    d, dep, chef = _recevable()
    wfi.rediger_rapport(d, chef, "complement_requis", None,
                        "Rapport de stabilité manquant.")
    db.session.flush()
    verifier("dossier repassé en complément requis", d.statut == "complement_requis")
    verifier("délai de réponse fixé", d.date_limite_reponse_complement is not None)
    verifier("la direction n'est pas saisie", not vn.circuit_ouvert(d))
    verifier("le déposant est informé",
             Notification.query.filter_by(destinataire_id=dep.id,
                                          type="complement_requis").count() >= 1)


def main():
    print("=" * 70)
    print("Instruction des dossiers — tests")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_recevabilite_checklist, test_irrecevabilite_motivee,
                  test_evaluation_interne, test_commission_et_synthese,
                  test_synthese_prudente, test_rapport_ouvre_le_circuit,
                  test_rapport_complement_retourne_au_deposant):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False, f"{type(e).__name__}: {e}")
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
