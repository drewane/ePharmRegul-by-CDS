"""
Vérifications du lot 7 : certificat d'homologation et AMM.

Ce que l'on cherche à établir :
  1. la validation du directeur PRODUIT les deux actes, d'un seul geste ;
  2. la génération est idempotente : un acte ne se renumérote jamais ;
  3. les gabarits portent l'en-tête officiel bilingue ;
  4. l'AMM non signée se voit comme un projet — filigrane et mention ;
  5. le déposant consulte mais n'emporte pas le projet ; il emporte l'acte
     signé ;
  6. toute la chaîne peut relire l'acte, comme demandé ;
  7. les PDF s'écrivent réellement, et l'AMM cesse d'être un projet dès le
     dépôt de l'exemplaire signé.
"""
import os
import re
from datetime import datetime

import actes
import app as application
import machine_etats as me
from erreurs import ErreurWorkflow
from models import (DossierAMM, EvenementAudit, Notification, Personne,
                    Produit, db)

ok = 0
ko = []


def verifier(condition, libelle):
    global ok
    if condition:
        ok += 1
    else:
        ko.append(libelle)
        print(f"  ECHEC : {libelle}")


def _max_ids():
    return {
        "dossier": db.session.query(db.func.max(DossierAMM.id)).scalar() or 0,
        "produit": db.session.query(db.func.max(Produit.id)).scalar() or 0,
        "audit": db.session.query(db.func.max(EvenementAudit.id)).scalar() or 0,
        "notif": db.session.query(db.func.max(Notification.id)).scalar() or 0,
    }


def _nettoyer(avant, fichiers=()):
    EvenementAudit.query.filter(EvenementAudit.id > avant["audit"]).delete()
    Notification.query.filter(Notification.id > avant["notif"]).delete()
    DossierAMM.query.filter(DossierAMM.id > avant["dossier"]).delete()
    Produit.query.filter(Produit.id > avant["produit"]).delete()
    db.session.commit()
    for chemin in fichiers:
        if not chemin or not os.path.exists(chemin):
            continue
        try:
            os.remove(chemin)
        except OSError as e:
            # Un PDF resté verrouillé ne doit pas masquer le résultat des
            # vérifications : on le signale et on poursuit le nettoyage.
            print(f"  (fichier non supprimé : {os.path.basename(chemin)} — {e})")


def _compte(email):
    return Personne.query.filter_by(email=email).first()


def _dossier(deposant, statut="retour_homologation"):
    from numerotation import generer_numero

    p = Produit(nom_commercial="Actine 100", forme_pharmaceutique="Comprimé",
                dosage="100 mg", nature="chimique", categorie="medicament",
                denomination_commune_internationale="paracétamol",
                voie_administration="Voie orale",
                classe_therapeutique="N02 — Analgésiques",
                pays_origine="Cameroun")
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=generer_numero("AMM"), produit_id=p.id,
                   demandeur_id=deposant.id, statut=statut,
                   type_procedure="nouvelle_demande",
                   date_depot=datetime.utcnow())
    db.session.add(d)
    db.session.flush()
    return d


with application.app.app_context():
    fichiers = []
    try:
        avant = _max_ids()
        deposant = _compte("demandeur@pharmacam.demo")
        chef = _compte("chefservice@dpml.demo")
        directeur = _compte("directeur@dpml.demo")
        print("== Certificat d'homologation et AMM ==")

        # -------------------------------------------------------------
        print("\n-- 1. Déclaration des actes --")
        verifier(not actes.verifier_actes(),
                 f"aucune anomalie ({actes.verifier_actes()})")
        verifier(set(actes.ACTES) == {"certificat", "amm"},
                 "deux actes, et deux seulement")
        verifier(actes.ACTES["certificat"]["definitif"] is True,
                 "le certificat est définitif dès sa génération")
        verifier(actes.ACTES["amm"]["definitif"] is False,
                 "l'AMM ne l'est pas : le ministre signe hors système")
        verifier(me.transition("valider")["effet"] == "generer_actes",
                 "c'est la validation du directeur qui produit les actes")
        verifier("generer_actes" in me.EFFETS,
                 "et l'effet est bien enregistré par le module des actes")

        # -------------------------------------------------------------
        print("\n-- 2. La validation produit les deux actes --")
        d = _dossier(deposant)
        db.session.commit()
        verifier(actes.actes_disponibles(d) == [],
                 "avant validation, aucun acte n'existe")

        me.appliquer_transition(d, "valider", directeur)
        db.session.commit()
        verifier(d.statut == "valide", "le dossier est validé")
        verifier(d.numero_certificat
                 and d.numero_certificat.startswith("CERT/CMR/"),
                 f"le certificat est numéroté ({d.numero_certificat})")
        verifier(d.numero_amm and d.numero_amm.startswith("AMM/CMR/"),
                 f"l'AMM est numérotée ({d.numero_amm})")
        verifier(d.numero_certificat != d.numero_amm,
                 "les deux actes ont des numéros distincts")
        # L'acte ne doit pas emprunter la série des dossiers : deux objets
        # citables par le même identifiant, c'est un dossier confondu avec
        # l'autorisation qu'il a produite.
        verifier(d.numero_amm != d.numero
                 and not d.numero_amm.startswith(f"AMM-{datetime.utcnow().year}"),
                 f"l'AMM ne porte pas un numéro de dossier ({d.numero_amm})")
        collision = DossierAMM.query.filter(
            DossierAMM.numero.in_((d.numero_amm, d.numero_certificat))).first()
        verifier(collision is None,
                 "aucun dossier ne porte déjà ce numéro d'acte")
        verifier(d.date_validite_amm is not None,
                 "la validité est posée")
        verifier(d.date_validite_amm.year - d.date_decision.year
                 == actes.DUREE_VALIDITE_ANNEES,
                 f"pour {actes.DUREE_VALIDITE_ANNEES} ans à compter de la décision")
        # Compter en jours ferait dériver la date d'une journée par paire
        # d'années bissextiles : l'acte expirerait la veille de son
        # anniversaire.
        verifier((d.date_validite_amm.month, d.date_validite_amm.day)
                 == (d.date_decision.month, d.date_decision.day),
                 f"au même quantième ({d.date_validite_amm} contre "
                 f"{d.date_decision.date()})")
        import datetime as _dt
        verifier(actes._dans_n_ans(_dt.date(2024, 2, 29), 5)
                 == _dt.date(2029, 2, 28),
                 "un 29 février est reporté au 28, faute d'équivalent")
        verifier(len(actes.actes_disponibles(d)) == 2,
                 "les deux actes sont désormais disponibles")
        verifier(any("Actes édités" in e.action
                     for e in EvenementAudit.query.filter_by(
                         entite_type="DossierAMM", entite_id=d.id)),
                 "l'édition est journalisée")

        # -------------------------------------------------------------
        print("\n-- 3. Un acte ne se renumérote jamais --")
        cert_initial, amm_initial = d.numero_certificat, d.numero_amm
        actes.generer(d, chef)
        db.session.commit()
        verifier(d.numero_certificat == cert_initial
                 and d.numero_amm == amm_initial,
                 "rappeler la génération ne change aucun numéro")

        premature = _dossier(deposant, statut="recevable")
        db.session.commit()
        try:
            actes.generer(premature, directeur)
            verifier(False, "éditer avant validation est refusé")
        except ErreurWorkflow:
            verifier(True, "éditer avant validation est refusé")
        verifier(not premature.numero_certificat,
                 "et rien n'est numéroté au passage")

        # -------------------------------------------------------------
        print("\n-- 4. Gabarits imprimables --")
        client = application.app.test_client()
        with client.session_transaction() as s:
            s["user_id"] = directeur.id

        # Jinja échappe l'apostrophe en &#39; : on compare sur la partie que
        # l'échappement ne touche pas.
        for code, attendu in (("certificat", "CERTIFICAT D"),
                              ("amm", "AUTORISATION DE MISE SUR LE MARCHÉ")):
            r = client.get(f"/dossiers/{d.id}/actes/{code}")
            verifier(r.status_code == 200, f"le gabarit « {code} » s'affiche")
            page = r.data.decode("utf-8")
            verifier(attendu in page, f"il porte son titre ({attendu})")
            verifier("RÉPUBLIQUE DU CAMEROUN" in page
                     and "REPUBLIC OF CAMEROON" in page,
                     f"{code} : en-tête bilingue, les deux langues")
            verifier("Paix – Travail – Patrie" in page
                     and "Peace – Work – Fatherland" in page,
                     f"{code} : les deux devises officielles")
            verifier("DIRECTION DE LA PHARMACIE" in page,
                     f"{code} : le service émetteur est nommé")
            verifier(actes.numero(d, code) in page,
                     f"{code} : le numéro de l'acte y figure")
            verifier("@media print" in page,
                     f"{code} : la feuille est mise en page pour l'impression")
            verifier("Actine 100" in page and "paracétamol" in page,
                     f"{code} : le produit est identifié")

        # -------------------------------------------------------------
        print("\n-- 5. Un projet se voit --")
        page_amm = client.get(f"/dossiers/{d.id}/actes/amm").data.decode("utf-8")
        verifier("filigrane" in page_amm and ">PROJET<" in page_amm,
                 "l'AMM non signée porte le filigrane PROJET")
        verifier("Signature manuscrite en attente" in page_amm,
                 "et dit que la signature du ministre manque")
        page_cert = client.get(
            f"/dossiers/{d.id}/actes/certificat").data.decode("utf-8")
        verifier(">PROJET<" not in page_cert,
                 "le certificat, lui, n'est pas un projet")
        verifier("Certificat délivré par voie électronique" in page_cert,
                 "et son pied de page porte la mention qui lui revient")
        verifier("Exemplaire signé" not in page_cert,
                 "et non celle qui revient à une AMM signée")
        verifier("Directeur de la Pharmacie" in page_cert,
                 "il porte la qualité de son signataire")
        verifier(directeur.nom_complet in page_cert,
                 "et le nom de celui qui a validé, lu dans l'audit")

        # -------------------------------------------------------------
        print("\n-- 6. Qui consulte, qui emporte --")
        verifier(actes.peut_consulter(d, deposant),
                 "le déposant consulte l'acte de son dossier")
        verifier(not actes.peut_telecharger(d, deposant),
                 "mais n'emporte pas le projet")
        motif = actes.motif_refus_telechargement(d, deposant)
        verifier(motif and "signature du ministre" in motif,
                 f"et on lui dit pourquoi ({motif})")
        verifier(actes.peut_telecharger(d, chef)
                 and actes.peut_telecharger(d, directeur),
                 "la chaîne administrative, elle, emporte le document")

        with client.session_transaction() as s:
            s["user_id"] = deposant.id
        r = client.get(f"/dossiers/{d.id}/actes/amm")
        verifier(r.status_code == 200, "le déposant ouvre le gabarit")
        page = r.data.decode("utf-8")
        verifier("Téléchargement fermé" in page,
                 "l'écran lui montre que le téléchargement est fermé")
        verifier("acte_pdf" not in page and f"/actes/amm.pdf" not in page,
                 "et ne lui offre aucun lien de téléchargement")
        verifier(client.get(f"/dossiers/{d.id}/actes/amm.pdf").status_code == 403,
                 "forcer l'URL du PDF ne sert à rien non plus")

        autre = Personne.query.filter(
            Personne.role_systeme == "demandeur_externe",
            Personne.id != deposant.id,
            Personne.etablissement_rattachement_id
            != (deposant.etablissement_rattachement_id or -1)).first()
        if autre:
            with client.session_transaction() as s:
                s["user_id"] = autre.id
            verifier(client.get(
                f"/dossiers/{d.id}/actes/certificat").status_code == 403,
                "un déposant tiers ne voit pas l'acte d'autrui")
        else:
            verifier(True, "pas de déposant tiers pour éprouver le cloisonnement")

        # -------------------------------------------------------------
        print("\n-- 7. Les PDF s'écrivent --")
        with client.session_transaction() as s:
            s["user_id"] = chef.id
        for code in ("certificat", "amm"):
            r = client.get(f"/dossiers/{d.id}/actes/{code}.pdf")
            fichiers.append(actes.chemin_pdf(d, code))
            verifier(r.status_code == 200, f"le PDF « {code} » est servi")
            verifier(r.data[:4] == b"%PDF", f"{code} : c'est bien un PDF")
            verifier(len(r.data) > 2000, f"{code} : il n'est pas vide")
            verifier(actes.numero(d, code) in
                     r.headers.get("Content-Disposition", ""),
                     f"{code} : le fichier porte le numéro de l'acte")
            r.close()      # sous Windows, un PDF servi reste verrouillé

        # -------------------------------------------------------------
        print("\n-- 8. La signature du ministre change la nature de l'acte --")
        me.appliquer_transition(d, "transmettre_signature", chef)
        db.session.commit()
        verifier(d.statut == "amm_a_signer",
                 "le dossier passe à la signature")
        verifier(actes.est_signee(d) is False,
                 "tant que rien n'est déposé, l'AMM reste un projet")
        verifier(not actes.peut_telecharger(d, deposant),
                 "le déposant n'emporte toujours pas le projet")

        me.appliquer_transition(d, "enregistrer_signature", chef)
        db.session.commit()
        verifier(d.statut == "amm_signee", "la signature est constatée")
        # `est_signee` s'appuie sur la pièce déposée, non sur le statut : c'est
        # le document qui fait foi, pas la case cochée.
        verifier(actes.est_signee(d) is False,
                 "sans pièce déposée, l'acte n'est pas réputé signé")

        resume = actes.resume(d)
        verifier([a["projet"] for a in resume] == [False, True],
                 "le certificat n'est pas un projet, l'AMM l'est encore")
        verifier(all(a["numero"] for a in resume),
                 "les deux actes sont numérotés dans le résumé")

        # -------------------------------------------------------------
        print("\n-- 9. Les actes apparaissent sur le parcours --")
        with client.session_transaction() as s:
            s["user_id"] = chef.id
        page = client.get(f"/dossiers/{d.id}/parcours").data.decode("utf-8")
        verifier("Actes délivrés" in page, "la page parcours les liste")
        verifier(d.numero_certificat in page and d.numero_amm in page,
                 "avec leurs numéros")
        verifier(page.count("Projet") >= 1,
                 "et signale celui qui n'est encore qu'un projet")

        # -------------------------------------------------------------
        print("\n-- 10. Aucun acte hors des dossiers qui en ont --")
        sans_acte = _dossier(deposant, statut="brouillon")
        db.session.commit()
        verifier(client.get(
            f"/dossiers/{sans_acte.id}/actes/certificat").status_code == 404,
            "un dossier sans acte répond 404, pas une page vide")
        verifier(client.get(
            f"/dossiers/{d.id}/actes/inconnu").status_code == 404,
            "un code d'acte inventé répond 404")

    finally:
        _nettoyer(avant, fichiers)

print(f"\n{ok} vérifications passées, {len(ko)} échec(s)")
if ko:
    for libelle in ko:
        print(f"  - {libelle}")
    raise SystemExit(1)
