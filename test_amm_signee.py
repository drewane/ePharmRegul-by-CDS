"""
Tests des deux documents de fin de circuit, et de l'accès aux pièces.

Trois exigences se recoupent ici :
  * Le CERTIFICAT d'homologation, généré, est un support interne — visible de
    tous les agents, jamais du titulaire.
  * L'AMM SIGNÉE, téléversée par le chef de service, est le seul document
    opposable ; son dépôt fixe la validité et arme le rappel de renouvellement.
  * Les pièces du dossier suivent le circuit d'un bout à l'autre : chaque
    échelon signe au vu du dossier.

Exécution :  venv\\Scripts\\python test_amm_signee.py
"""
import io
import sys
import uuid
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from werkzeug.datastructures import FileStorage

import amm_signee
import app as application
import seed_comptes as sc
import validation_numerique as vn
from erreurs import ErreurWorkflow
from models import (DossierAMM, Etablissement, EtapeValidation, EvenementAudit,
                    Notification, PieceJointe, Personne, Produit, db)

_res = []
_MODELES = (EtapeValidation, PieceJointe, EvenementAudit, DossierAMM, Produit,
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


def _fichier(nom="amm-signee.pdf"):
    return FileStorage(stream=io.BytesIO(b"%PDF-1.4 acte signe"), filename=nom,
                       content_type="application/pdf")


def _dossier():
    s = uuid.uuid4().hex[:6]
    etab = Etablissement(raison_sociale=f"Sig-{s}", type="importateur_exportateur",
                         statut_licence="active")
    db.session.add(etab)
    db.session.flush()
    dep = Personne(nom_complet=f"Déposant {s}", email=f"sig{s}@test.demo",
                   role_systeme="demandeur_externe", statut_compte="actif",
                   etablissement_rattachement_id=etab.id)
    dep.set_password("pw")
    db.session.add(dep)
    db.session.flush()
    p = Produit(nom_commercial=f"P{s}", forme_pharmaceutique="Comprimé",
                nature="chimique", titulaire_amm_id=etab.id)
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=f"AMM-SIG-{s}", produit_id=p.id, demandeur_id=dep.id,
                   statut="evaluation_en_cours")
    db.session.add(d)
    db.session.flush()
    return d, dep


def _circuit_acheve(d):
    """Fait signer les six échelons du circuit AMM."""
    chef = _r("chef_service_amm")
    vn.ouvrir_circuit(d, "amm", chef)
    db.session.flush()
    for role in ("chef_service_amm", "sous_directeur_medicament", "directeur_dpml",
                 "inspecteur_general", "secretaire_general_ms", "ministre_sante"):
        vn.signer(d, _r(role))
        db.session.flush()
    d.statut = "approuve"
    db.session.flush()
    return d


def test_depot_exige_circuit_acheve():
    print("\n[1] Un acte « signé » ne précède pas la signature")
    d, _dep = _dossier()
    chef = _r("chef_service_amm")
    verifier("dépôt refusé tant que le circuit n'est pas achevé",
             leve(lambda: amm_signee.deposer(d, _fichier(), chef, 5),
                  "circuit de validation n'est pas achevé"))
    verifier("aucun acte n'est disponible", not amm_signee.est_disponible(d))


def test_qui_depose():
    print("\n[2] Le dépôt relève du chef de service")
    d, _dep = _dossier()
    _circuit_acheve(d)
    for role in ("ministre_sante", "directeur_dpml", "evaluateur_interne",
                 "demandeur_externe", "usager"):
        verifier(f"« {role} » ne dépose pas l'acte",
                 leve(lambda r=role: amm_signee.deposer(d, _fichier(), _r(r), 5),
                      "chef de service"))
    verifier("le chef de service est autorisé",
             amm_signee.peut_deposer(d, _r("chef_service_amm")))


def test_depot_et_validite():
    print("\n[3] Le dépôt fixe la validité et prévient le titulaire")
    d, dep = _dossier()
    _circuit_acheve(d)
    chef = _r("chef_service_amm")
    verifier("aucune validité avant le dépôt", d.date_validite_amm is None)

    signature = date.today() - timedelta(days=3)
    piece = amm_signee.deposer(d, _fichier(), chef, 5, signature)
    db.session.flush()

    verifier("la pièce porte le type réservé",
             piece.type_document == amm_signee.TYPE_AMM_SIGNEE)
    verifier("l'acte est disponible", amm_signee.est_disponible(d))
    verifier("échéance = date de signature + durée",
             d.date_validite_amm == signature.replace(year=signature.year + 5),
             str(d.date_validite_amm))
    verifier("le produit devient commercialisable",
             d.produit.statut_amm_courant == "active")
    verifier("le titulaire est prévenu",
             Notification.query.filter_by(destinataire_id=dep.id,
                                          type="amm_signee_disponible").count() == 1)
    notif = Notification.query.filter_by(destinataire_id=dep.id,
                                         type="amm_signee_disponible").first()
    verifier("le message annonce l'échéance et le rappel",
             "six mois" in notif.contenu
             and d.date_validite_amm.strftime("%d/%m/%Y") in notif.contenu)
    verifier("le dépôt est journalisé avec sa durée",
             any("validité 5 an(s)" in e.action for e in
                 EvenementAudit.query.filter_by(entite_type="DossierAMM",
                                                entite_id=d.id).all()))
    verifier("le dépôt ne se propose plus une seconde fois",
             not amm_signee.peut_deposer(d, chef))


def test_duree_controlee():
    print("\n[4] Contrôles de saisie de la durée")
    d, _dep = _dossier()
    _circuit_acheve(d)
    chef = _r("chef_service_amm")
    verifier("durée absente refusée",
             leve(lambda: amm_signee.deposer(d, _fichier(), chef, None), "nombre"))
    verifier("durée non numérique refusée",
             leve(lambda: amm_signee.deposer(d, _fichier(), chef, "cinq"), "nombre"))
    verifier("durée nulle refusée",
             leve(lambda: amm_signee.deposer(d, _fichier(), chef, 0), "comprise"))
    verifier("durée excessive refusée",
             leve(lambda: amm_signee.deposer(d, _fichier(), chef, 99), "comprise"))
    verifier("signature future refusée",
             leve(lambda: amm_signee.deposer(
                 d, _fichier(), chef, 5, date.today() + timedelta(days=1)),
                 "future"))
    verifier("la durée par défaut suit le paramètre du module",
             amm_signee.duree_par_defaut() == 5,
             str(amm_signee.duree_par_defaut()))


def test_rappel_six_mois():
    print("\n[5] Rappel de renouvellement six mois avant l'échéance")
    from delais import DEFAUTS_MA, executer_verifications_delais

    seuils = [int(j) for j in DEFAUTS_MA["rappel_renouvellement_j_avant"][0].split(",")]
    verifier("le premier seuil est le rappel à six mois", max(seuils) == 180,
             str(seuils))

    d, dep = _dossier()
    _circuit_acheve(d)
    amm_signee.deposer(d, _fichier(), _r("chef_service_amm"), 5)
    db.session.flush()

    # On rapproche l'échéance à cinq mois : le seuil des 180 jours est franchi.
    d.date_validite_amm = date.today() + timedelta(days=150)
    d.date_decision = d.date_decision or None
    db.session.commit()

    executer_verifications_delais()
    rappels = Notification.query.filter_by(destinataire_id=dep.id,
                                           type="renouvellement_j180").all()
    verifier("un rappel de renouvellement est émis", len(rappels) == 1,
             f"{len(rappels)} rappel(s)")
    if rappels:
        verifier("le rappel donne la date d'expiration",
                 d.date_validite_amm.strftime("%d/%m/%Y") in rappels[0].contenu)
    executer_verifications_delais()
    verifier("le rappel n'est pas répété à chaque passage",
             Notification.query.filter_by(destinataire_id=dep.id,
                                          type="renouvellement_j180").count() == 1)

    # Une AMM encore loin de l'échéance ne déclenche rien.
    d2, dep2 = _dossier()
    _circuit_acheve(d2)
    amm_signee.deposer(d2, _fichier(), _r("chef_service_amm"), 5)
    db.session.commit()
    executer_verifications_delais()
    verifier("aucun rappel pour une échéance lointaine",
             Notification.query.filter_by(destinataire_id=dep2.id,
                                          type="renouvellement_j180").count() == 0)


def _client(email):
    c = application.app.test_client()
    c.post("/login", data={"email": email,
                           "password": sc.mot_de_passe_courant(email)})
    return c


def test_certificat_reserve_aux_agents():
    print("\n[6] Le certificat d'homologation ne sort pas de l'administration")
    d, dep = _dossier()
    _circuit_acheve(d)
    dep.set_password(sc.mot_de_passe_courant(dep.email))
    db.session.commit()
    url = f"/validation/DossierAMM/{d.id}/document"

    for role in ("chef_service_amm", "cadre_dpml", "sous_directeur_medicament",
                 "inspecteur_general", "secretaire_general_ms", "ministre_sante"):
        code = _client(sc.COMPTES[role][1]).get(url).status_code
        verifier(f"« {role} » obtient le certificat", code == 200, str(code))

    code = _client(dep.email).get(url).status_code
    verifier("le titulaire du dossier ne l'obtient pas", code == 403, str(code))
    for role in ("usager", "pharmacien", "grossiste"):
        verifier(f"« {role} » ne l'obtient pas",
                 _client(sc.COMPTES[role][1]).get(url).status_code == 403)


def test_acte_signe_telechargeable_par_le_titulaire():
    print("\n[7] L'acte signé, lui, est remis au titulaire")
    d, dep = _dossier()
    _circuit_acheve(d)
    piece = amm_signee.deposer(d, _fichier(), _r("chef_service_amm"), 5)
    dep.set_password(sc.mot_de_passe_courant(dep.email))
    db.session.commit()

    url = f"/documents/{piece.id}/telecharger"
    verifier("le titulaire télécharge son AMM",
             _client(dep.email).get(url).status_code == 200)
    verifier("le chef de service aussi",
             _client(sc.COMPTES["chef_service_amm"][1]).get(url).status_code == 200)
    verifier("un concurrent ne le peut pas",
             _client(sc.COMPTES["demandeur_externe"][1]).get(url).status_code == 404)
    verifier("un usager ne le peut pas",
             _client(sc.COMPTES["usager"][1]).get(url).status_code == 404)

    page = _client(dep.email).get(f"/industriel/suivi/{d.id}")
    verifier("le suivi du titulaire propose le téléchargement",
             page.status_code == 200
             and "Télécharger mon AMM" in page.get_data(as_text=True))


def test_pieces_visibles_dans_la_chaine():
    print("\n[8] Les pièces suivent le circuit d'un bout à l'autre")
    from pieces import enregistrer_piece

    d, dep = _dossier()
    piece = enregistrer_piece(d, _fichier("module-qualite.pdf"),
                              "Module 3 — Qualité", dep)
    _circuit_acheve(d)
    dep.set_password(sc.mot_de_passe_courant(dep.email))
    db.session.commit()

    url = f"/documents/{piece.id}/telecharger"
    for role in ("cadre_dpml", "evaluateur_interne", "chef_bureau",
                 "chef_service_amm", "sous_directeur_medicament", "directeur_dpml",
                 "inspecteur_general", "secretaire_general_ms", "ministre_sante"):
        code = _client(sc.COMPTES[role][1]).get(url).status_code
        verifier(f"« {role} » consulte la pièce du dossier", code == 200, str(code))

    verifier("le titulaire consulte sa propre pièce",
             _client(dep.email).get(url).status_code == 200)
    verifier("un concurrent ne la consulte pas",
             _client(sc.COMPTES["demandeur_externe"][1]).get(url).status_code == 404)

    # Et elles sont présentées sur l'écran du circuit, pas seulement joignables.
    page = _client(sc.COMPTES["ministre_sante"][1]).get(
        f"/validation/DossierAMM/{d.id}")
    corps = page.get_data(as_text=True)
    verifier("l'écran de signature liste les pièces",
             "Pièces du dossier" in corps and "module-qualite.pdf" in corps)


def main():
    print("=" * 70)
    print("Certificat d'homologation, AMM signée et accès aux pièces")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        reperes = _max_ids()
        for t in (test_depot_exige_circuit_acheve, test_qui_depose,
                  test_depot_et_validite, test_duree_controlee,
                  test_rappel_six_mois, test_certificat_reserve_aux_agents,
                  test_acte_signe_telechargeable_par_le_titulaire,
                  test_pieces_visibles_dans_la_chaine):
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
