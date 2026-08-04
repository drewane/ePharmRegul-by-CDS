"""
Tests de l'espace industriel et de la validation numérique.

Deux exigences dominent :
  * CLOISONNEMENT — un titulaire ne voit jamais le portefeuille d'un concurrent.
  * ORDRE HIÉRARCHIQUE — un échelon ne peut pas signer avant le précédent.

Exécution :  venv\\Scripts\\python test_industriel_validation.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import espace_industriel as esp
import validation_numerique as vn
import workflow_demande_inspection as wfdi
from erreurs import ErreurWorkflow
from models import (DemandeInspection, DossierAMM, EtapeValidation, Etablissement,
                    Notification, Personne, Produit, db)

_res = []
_MODELES = (EtapeValidation, DemandeInspection, DossierAMM, Produit, Personne,
            Etablissement, Notification)


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
    for M in reversed(_MODELES):
        for obj in M.query.filter(M.id > reperes[M]).all():
            db.session.delete(obj)
    db.session.commit()


def _societe(nom):
    """Crée une société avec deux collaborateurs et un dossier d'AMM."""
    suffixe = uuid.uuid4().hex[:6]
    etab = Etablissement(raison_sociale=f"{nom}-{suffixe}", type="importateur_exportateur",
                         statut_licence="active")
    db.session.add(etab)
    db.session.flush()
    comptes = []
    for i in (1, 2):
        p = Personne(nom_complet=f"Agent {i} {nom}", email=f"a{i}.{suffixe}@test.demo",
                     role_systeme="demandeur_externe", statut_compte="actif",
                     etablissement_rattachement_id=etab.id)
        p.set_password("pw")
        db.session.add(p)
        comptes.append(p)
    db.session.flush()
    produit = Produit(nom_commercial=f"Produit {nom}", forme_pharmaceutique="Comprimé",
                      denomination_commune_internationale="Testine",
                      titulaire_amm_id=etab.id)
    db.session.add(produit)
    db.session.flush()
    dossier = DossierAMM(numero=f"AMM-T-{suffixe}", produit_id=produit.id,
                         demandeur_id=comptes[0].id, statut="evaluation_en_cours")
    db.session.add(dossier)
    db.session.flush()
    return etab, comptes, dossier


def test_cloisonnement():
    print("\n[1] Cloisonnement par société")
    _e1, upsa, d_upsa = _societe("UPSA")
    _e2, concurrent, d_conc = _societe("CONCURRENT")

    ids_upsa = [d.id for d in esp.dossiers_de_la_societe(upsa[0]).all()]
    verifier("le déposant voit son dossier", d_upsa.id in ids_upsa)
    verifier("le dossier du concurrent est invisible", d_conc.id not in ids_upsa,
             f"{len(ids_upsa)} dossier(s) visibles")

    # Le périmètre est la SOCIÉTÉ, pas l'utilisateur : un collègue voit aussi.
    ids_collegue = [d.id for d in esp.dossiers_de_la_societe(upsa[1]).all()]
    verifier("un collègue de la même société voit le dossier",
             d_upsa.id in ids_collegue)
    verifier("le collègue ne voit pas le concurrent", d_conc.id not in ids_collegue)

    s = esp.synthese(upsa[0])
    verifier("la synthèse ne compte que la société", s["total"] == len(ids_upsa),
             f"total={s['total']}")


def test_synthese_complete():
    print("\n[2] Synthèse — toutes les catégories demandées")
    _e, comptes, dossier = _societe("SYNTH")
    for statut in ("approuve", "rejete", "complement_requis", "cloture_delai_depasse"):
        db.session.add(DossierAMM(numero=f"AMM-{uuid.uuid4().hex[:8]}",
                                  produit_id=dossier.produit_id,
                                  demandeur_id=comptes[0].id, statut=statut))
    db.session.flush()
    s = esp.synthese(comptes[0])
    for cle in ("total", "en_cours", "approuves", "rejetes", "clotures",
                "complement_requis", "a_renouveler", "par_type"):
        verifier(f"indicateur « {cle} » présent", cle in s)
    verifier("AMM en vigueur comptée", s["approuves"] == 1, str(s["approuves"]))
    verifier("dossiers rejetés comptés", s["rejetes"] == 1, str(s["rejetes"]))
    verifier("dossiers clôturés comptés", s["clotures"] == 1, str(s["clotures"]))


def test_demande_inspection():
    print("\n[3] Demande d'inspection + accusé de réception")
    _e, comptes, _d = _societe("INSP")
    avant = Notification.query.filter_by(destinataire_id=comptes[0].id).count()

    d = wfdi.deposer(comptes[0], "Usine de Lomé", "Togo",
                     "Inspection préalable à l'homologation")
    db.session.flush()
    verifier("demande numérotée", d.numero.startswith("DIN-"), d.numero)
    verifier("site à l'étranger détecté", d.a_l_etranger)

    apres = Notification.query.filter_by(destinataire_id=comptes[0].id).count()
    verifier("accusé de réception envoyé au demandeur", apres > avant)
    recu = (Notification.query.filter_by(destinataire_id=comptes[0].id,
                                         type="demande_receptionnee")
            .order_by(Notification.id.desc()).first())
    verifier("le message confirme la prise en charge",
             recu is not None and "réceptionnée" in recu.contenu)

    verifier("champs obligatoires contrôlés",
             leve(lambda: wfdi.deposer(comptes[0], "", "Togo", "motif"), "obligatoire"))

    site_local = wfdi.deposer(comptes[0], "Usine de Douala", "Cameroun", "Routine")
    db.session.flush()
    verifier("site national non marqué « étranger »", not site_local.a_l_etranger)


def test_circuit_amm_ordre():
    print("\n[4] Circuit AMM — 6 échelons, ordre garanti")
    _e, comptes, dossier = _societe("CIRCUIT")
    chef = Personne.query.filter_by(role_systeme="chef_service_amm").first()
    sd = Personne.query.filter_by(role_systeme="sous_directeur_medicament").first()
    dir_ = Personne.query.filter_by(role_systeme="directeur_dpml").first()
    ig = Personne.query.filter_by(role_systeme="inspecteur_general").first()
    sg = Personne.query.filter_by(role_systeme="secretaire_general_ms").first()
    ministre = Personne.query.filter_by(role_systeme="ministre_sante").first()
    if not all((chef, sd, dir_, ig, sg, ministre)):
        verifier("comptes des six échelons disponibles", False,
                 "lancer seed_signataires.py")
        return

    vn.ouvrir_circuit(dossier, "amm", chef)
    db.session.flush()
    verifier("circuit AMM à 6 échelons (audit IG inclus)",
             len(vn.etapes(dossier)) == 6)
    verifier("premier échelon = chef de service",
             vn.etape_courante(dossier).role_requis == "chef_service_amm")

    # Le ministre ne peut pas signer en premier : l'ordre est structurel.
    verifier("le ministre ne peut pas court-circuiter la chaîne",
             leve(lambda: vn.signer(dossier, ministre), "revient au"))
    verifier("un profil hors circuit ne signe pas",
             leve(lambda: vn.signer(dossier, comptes[0]), "revient au"))

    for acteur, attendu in ((chef, "sous_directeur_medicament"),
                            (sd, "directeur_dpml"),
                            (dir_, "inspecteur_general"),
                            (ig, "secretaire_general_ms"),
                            (sg, "ministre_sante")):
        _etape, acheve = vn.signer(dossier, acteur)
        db.session.flush()
        verifier(f"après {acteur.role_systeme} → {attendu}",
                 vn.etape_courante(dossier).role_requis == attendu)
        verifier(f"circuit non achevé après {acteur.role_systeme}", not acheve)

    _etape, acheve = vn.signer(dossier, ministre)
    db.session.flush()
    verifier("signature du ministre = circuit achevé", acheve)
    verifier("les 6 signatures sont apposées", vn.progression(dossier) == (6, 6))
    verifier("chaque signature porte une empreinte",
             all(e.signature for e in vn.etapes(dossier)))
    verifier("chaque signature est nominative",
             all(e.validateur_id for e in vn.etapes(dossier)))


def test_circuit_derogation_et_refus():
    print("\n[5] Circuit dérogation (3 échelons) et refus motivé")
    _e, comptes, dossier = _societe("DEROG")
    chef = Personne.query.filter_by(role_systeme="chef_service_amm").first()
    sd = Personne.query.filter_by(role_systeme="sous_directeur_medicament").first()
    if not (chef and sd):
        verifier("comptes disponibles", False)
        return

    # On réutilise un DossierAMM comme support : le moteur est générique.
    vn.ouvrir_circuit(dossier, "derogation", chef)
    db.session.flush()
    verifier("circuit dérogation à 3 échelons", len(vn.etapes(dossier)) == 3)
    verifier("dernier échelon = directeur DPML",
             vn.etapes(dossier)[-1].role_requis == "directeur_dpml")

    vn.signer(dossier, chef)
    db.session.flush()
    verifier("refus sans motif rejeté",
             leve(lambda: vn.refuser(dossier, sd, ""), "motivé"))
    vn.refuser(dossier, sd, "Pièces justificatives insuffisantes.")
    db.session.flush()
    verifier("circuit interrompu par le refus", vn.circuit_refuse(dossier))
    verifier("plus aucune signature possible",
             leve(lambda: vn.signer(dossier, sd), "interrompu"))

    vn.reinitialiser(dossier, chef)
    db.session.flush()
    verifier("circuit relançable après correction",
             not vn.circuit_refuse(dossier)
             and vn.etape_courante(dossier).role_requis == "chef_service_amm")


def test_double_ouverture():
    print("\n[6] Garde-fous du moteur")
    _e, _c, dossier = _societe("GARDE")
    chef = Personne.query.filter_by(role_systeme="chef_service_amm").first()
    vn.ouvrir_circuit(dossier, "amm", chef)
    db.session.flush()
    verifier("double ouverture refusée",
             leve(lambda: vn.ouvrir_circuit(dossier, "amm", chef), "déjà ouvert"))
    verifier("circuit inconnu refusé",
             leve(lambda: vn.ouvrir_circuit(Produit.query.first(), "inexistant", chef),
                  "inconnu"))


def main():
    print("=" * 70)
    print("Espace industriel & validation numérique — tests")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_cloisonnement, test_synthese_complete, test_demande_inspection,
                  test_circuit_amm_ordre, test_circuit_derogation_et_refus,
                  test_double_ouverture):
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
