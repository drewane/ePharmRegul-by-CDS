"""
Vérifications du lot 6 : paiement relié au workflow, files d'attente, direct.

Ce que l'on cherche à établir :
  1. une file se DÉDUIT de la machine à états — modifier le modèle change la
     file, sans qu'aucune liste de statuts n'ait à être retouchée ;
  2. les dossiers antérieurs, portant l'ancien vocabulaire, y figurent quand
     même : un dossier invisible est un dossier jamais traité ;
  3. l'approbation d'une recette fait AVANCER le dossier, et son rejet le
     renvoie au déposant ;
  4. le paiement d'une entité sans machine à états ne casse rien ;
  5. l'ancienneté est comptée depuis le dernier changement d'état ;
  6. une file informe sans habiliter : voir un dossier n'est pas pouvoir agir ;
  7. les points d'état du suivi en direct changent d'empreinte quand, et
     seulement quand, quelque chose bouge.
"""
import re
from datetime import datetime, timedelta

import app as application
import files_attente as fa
import machine_etats as me
import paiements
from erreurs import ErreurWorkflow
from models import (DossierAMM, EvenementAudit, Notification, Paiement,
                    Personne, Produit, db)

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
        "paiement": db.session.query(db.func.max(Paiement.id)).scalar() or 0,
    }


def _nettoyer(avant):
    Paiement.query.filter(Paiement.id > avant["paiement"]).delete()
    # Les pièces et les avis se rattachent au dossier par un identifiant nu.
    # Ne pas les purger, c'est les voir resurgir sur un dossier recyclé du run
    # suivant — et fausser silencieusement la garde `dossier_instruit`.
    from models import AvisEvaluationMA, PieceJointe

    survivants = [d.id for d in DossierAMM.query.filter(
        DossierAMM.id > avant["dossier"]).all()]
    if survivants:
        PieceJointe.query.filter(
            PieceJointe.entite_type == "DossierAMM",
            PieceJointe.entite_id.in_(survivants)).delete(
                synchronize_session=False)
        AvisEvaluationMA.query.filter(
            AvisEvaluationMA.dossier_id.in_(survivants)).delete(
                synchronize_session=False)
    EvenementAudit.query.filter(EvenementAudit.id > avant["audit"]).delete()
    Notification.query.filter(Notification.id > avant["notif"]).delete()
    DossierAMM.query.filter(DossierAMM.id > avant["dossier"]).delete()
    Produit.query.filter(Produit.id > avant["produit"]).delete()
    db.session.commit()


def _compte(email):
    return Personne.query.filter_by(email=email).first()


def _dossier(deposant, statut="brouillon"):
    from numerotation import generer_numero

    p = Produit(nom_commercial="Filine 250", forme_pharmaceutique="Comprimé",
                dosage="250 mg", nature="chimique", categorie="medicament")
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=generer_numero("AMM"), produit_id=p.id,
                   demandeur_id=deposant.id, statut=statut,
                   type_procedure="nouvelle_demande",
                   date_depot=datetime.utcnow())
    db.session.add(d)
    db.session.flush()
    return d


def _paiement(dossier, statut="preuve_deposee"):
    from numerotation import generer_numero

    p = Paiement(numero=generer_numero("PAY"), entite_type="DossierAMM",
                 entite_id=dossier.id, montant=250000, devise="XAF",
                 statut=statut)
    db.session.add(p)
    db.session.flush()
    return p


with application.app.app_context():
    # Le nettoyage doit avoir lieu même si une vérification lève : un run
    # interrompu laisserait des dossiers derrière lui, qui fausseraient les
    # comptes et les tris du run suivant.
    try:
        avant = _max_ids()
        deposant = _compte("demandeur@pharmacam.demo")
        financier = _compte("finances@dpml.demo")
        chef = _compte("chefservice@dpml.demo")
        directeur = _compte("directeur@dpml.demo")
        print("== Files d'attente, paiement et suivi en direct ==")

        # -----------------------------------------------------------------
        print("\n-- 1. Les files se déduisent de la machine à états --")
        verifier(not fa.verifier_files(),
                 f"aucune anomalie de déclaration ({fa.verifier_files()})")

        for f in fa.FILES:
            attendus = set()
            for role in f["roles"]:
                attendus |= {t["depuis"] for t in me.TRANSITIONS
                             if role in t["roles"]}
            verifier(fa.statuts_de_la_file(f["code"]) == attendus,
                     f"la file « {f['code']} » couvre exactement les états où ses "
                     "rôles peuvent agir")

        verifier(fa.statuts_de_la_file("financier") == {"en_attente_confirmation"},
                 "le financier n'attend que la confirmation de paiement")
        verifier("retour_homologation" in fa.statuts_de_la_file("direction"),
                 "la direction attend les dossiers consolidés")
        verifier("brouillon" not in fa.statuts_de_la_file("homologation"),
                 "un brouillon n'encombre la file de personne")

        # Preuve que rien n'est codé en dur : on ajoute une transition au modèle,
        # la file doit s'en apercevoir seule.
        factice = {"depuis": "brouillon", "action": "essai_temporaire",
                   "vers": "rejete", "libelle": "Essai", "roles": ("directeur_dpml",),
                   "motif_requis": True, "notifie": (), "ton": "secondary",
                   "aide": ""}
        me.TRANSITIONS.append(factice)
        try:
            verifier("brouillon" in fa.statuts_de_la_file("direction"),
                     "ajouter une transition peuple la file sans la retoucher")
        finally:
            me.TRANSITIONS.remove(factice)
        verifier("brouillon" not in fa.statuts_de_la_file("direction"),
                 "la retirer la vide de même")

        # -----------------------------------------------------------------
        print("\n-- 2. Les dossiers de l'ancien vocabulaire y figurent --")
        ancien = _dossier(deposant, statut="soumis")     # avant la machine à états
        db.session.commit()
        ids_financier = {l["dossier"].id for l in fa.contenu("financier", financier)}
        verifier(ancien.id in ids_financier,
                 "un dossier « soumis » apparaît dans la file du financier")
        ligne = next(l for l in fa.contenu("financier", financier)
                     if l["dossier"].id == ancien.id)
        verifier(ligne["statut"] == "En attente de confirmation du paiement",
                 "il y est présenté dans le vocabulaire canonique")
        verifier([t["action"] for t in ligne["actions"]]
                 == ["valider_paiement", "rejeter_paiement"],
                 "avec les deux décisions que le financier peut prendre")

        # -----------------------------------------------------------------
        print("\n-- 3. Une file informe, elle n'habilite pas --")
        membre = Personne.query.filter_by(
            role_systeme="membre_commission_specialisee",
            statut_compte="actif").first()
        verifier(membre is not None, "un membre de commission a un compte actif")
        ligne_membre = next((l for l in fa.contenu("financier", membre)
                             if l["dossier"].id == ancien.id), None)
        verifier(ligne_membre is not None and ligne_membre["actions"] == [],
                 "il voit le dossier du financier mais aucun bouton")

        codes_visibles = {f["code"] for f in fa.files_visibles(financier)}
        verifier(codes_visibles == {"financier"},
                 "le financier ne voit que sa file")
        admin = Personne.query.filter_by(role_systeme="administrateur_dpml",
                                         statut_compte="actif").first()
        verifier(len(fa.files_visibles(admin)) == len(fa.FILES),
                 "l'administrateur les voit toutes")
        verifier(all(l["actions"] == [] for l in fa.contenu("direction", admin)),
                 "sans hériter du pouvoir de décider pour autrui")

        # -----------------------------------------------------------------
        print("\n-- 4. Ancienneté comptée depuis le dernier changement d'état --")
        vieux = _dossier(deposant, statut="en_attente_confirmation")
        db.session.flush()
        db.session.add(EvenementAudit(
            entite_type="DossierAMM", entite_id=vieux.id,
            horodatage=datetime.utcnow() - timedelta(days=20),
            acteur_id=deposant.id, action="Dossier soumis",
            ancien_statut="brouillon", nouveau_statut="en_attente_confirmation"))
        db.session.commit()

        l_vieux = next(l for l in fa.contenu("financier", financier)
                       if l["dossier"].id == vieux.id)
        verifier(l_vieux["jours"] >= 20, f"vingt jours comptés ({l_vieux['jours']})")
        verifier(l_vieux["palier"] == "alerte", "au-delà du seuil, la file alerte")
        verifier(fa.palier(0) == "normal" and fa.palier(fa.SEUIL_ATTENTION) == "attention"
                 and fa.palier(fa.SEUIL_ALERTE) == "alerte",
                 "les trois paliers se déclenchent aux seuils déclarés")

        lignes = fa.contenu("financier", financier)
        ages = [l["jours"] for l in lignes]
        verifier(ages == sorted(ages, reverse=True),
                 f"la file est ordonnée du plus ancien au plus récent ({ages})")
        rangs = {l["dossier"].id: i for i, l in enumerate(lignes)}
        verifier(rangs[vieux.id] < rangs[ancien.id],
                 "un dossier de vingt jours passe devant un dossier du jour")
        compte = fa.compter("financier")
        verifier(compte["total"] == len(lignes) and compte["alerte"] >= 1,
                 "les compteurs concordent avec le contenu")
        verifier(compte["plus_ancien"] >= 20, "le plus ancien est remonté")

        # -----------------------------------------------------------------
        print("\n-- 5. L'approbation de la recette fait avancer le dossier --")
        d = _dossier(deposant, statut="en_attente_confirmation")
        p = _paiement(d)
        db.session.commit()

        paiements.confirmer(p, financier)
        db.session.commit()
        verifier(p.statut == "confirme", "la recette est constatée")
        verifier(d.statut == "en_attente_recevabilite",
                 f"et le dossier avance seul (obtenu {d.statut})")
        verifier(any(e.nouveau_statut == "en_attente_recevabilite"
                     for e in me.historique(d)),
                 "l'avancement est journalisé comme une transition, pas en douce")
        verifier(d.clock_debut is not None, "le délai légal a démarré")
        verifier(d.id in {l["dossier"].id for l in fa.contenu("homologation", chef)},
                 "le dossier a changé de file, sans geste supplémentaire")
        verifier(d.id not in {l["dossier"].id
                              for l in fa.contenu("financier", financier)},
                 "et a quitté celle du financier")

        # -----------------------------------------------------------------
        print("\n-- 6. Le rejet d'une preuve renvoie le dossier au déposant --")
        d2 = _dossier(deposant, statut="en_attente_confirmation")
        p2 = _paiement(d2)
        db.session.commit()

        try:
            paiements.rejeter(p2, financier, "  ")
            verifier(False, "un rejet de preuve sans motif est refusé")
        except ErreurWorkflow:
            verifier(True, "un rejet de preuve sans motif est refusé")
        verifier(d2.statut == "en_attente_confirmation",
                 "le dossier n'a pas bougé sur un refus")

        repere = db.session.query(db.func.max(Notification.id)).scalar() or 0
        paiements.rejeter(p2, financier, "Virement introuvable sur le relevé.")
        db.session.commit()
        verifier(p2.statut == "rejete", "la preuve est rejetée")
        verifier(d2.statut == "brouillon",
                 f"et le dossier revient au déposant (obtenu {d2.statut})")
        envoyees = Notification.query.filter(Notification.id > repere).all()
        verifier(all(n.destinataire_id == deposant.id for n in envoyees),
                 "seul le déposant est prévenu du rejet")
        verifier(any("Virement introuvable" in n.contenu for n in envoyees),
                 "le motif lui est transmis")

        # -----------------------------------------------------------------
        print("\n-- 7. Un paiement sans machine à états ne casse rien --")
        orphelin = Paiement(numero="PAY-TEST-ORPHELIN", entite_type="Echantillon",
                            entite_id=999999, montant=50000, devise="XAF",
                            statut="preuve_deposee")
        db.session.add(orphelin)
        db.session.flush()
        try:
            paiements.confirmer(orphelin, financier)
            db.session.commit()
            verifier(orphelin.statut == "confirme",
                     "une recette sur une entité sans workflow se confirme quand même")
        except Exception as e:                                  # noqa: BLE001
            db.session.rollback()
            verifier(False, f"une entité sans workflow lève : {e}")

        # Un dossier déjà recevable ne doit pas reculer si un virement tardif est
        # rapproché après coup.
        d3 = _dossier(deposant, statut="recevable")
        p3 = _paiement(d3)
        db.session.commit()
        paiements.confirmer(p3, financier)
        db.session.commit()
        verifier(d3.statut == "recevable",
                 "un paiement tardif ne fait pas reculer un dossier recevable")

        # -----------------------------------------------------------------
        print("\n-- 8. Suivi en direct --")
        client = application.app.test_client()
        d4 = _dossier(deposant, statut="retour_homologation")
        db.session.commit()
        id4 = d4.id

        with client.session_transaction() as s:
            s["user_id"] = deposant.id
        r = client.get(f"/dossiers/{id4}/etat.json")
        verifier(r.status_code == 200, "le point d'état répond au déposant")
        etat1 = r.get_json()
        verifier(etat1["statut"] == "retour_homologation"
                 and etat1["libelle"] == "Retour au service d'homologation",
                 "il rend le statut canonique et son libellé")
        verifier(etat1["termine"] is False, "il dit que le dossier n'est pas clos")
        verifier(any("Directeur" in a for a in etat1["attendu_de"]),
                 f"et de qui l'on attend une décision ({etat1['attendu_de']})")

        inchange = client.get(f"/dossiers/{id4}/etat.json").get_json()
        verifier(inchange["empreinte"] == etat1["empreinte"],
                 "l'empreinte ne bouge pas si rien ne bouge")

        # La garde exige un dossier instruit : on le rend validable, sinon on
        # n'éprouverait plus le suivi en direct mais la garde elle-même.
        from models import AvisEvaluationMA, PieceJointe
        db.session.add(PieceJointe(
            entite_type="DossierAMM", entite_id=id4,
            nom_fichier="dossier-technique.pdf",
            chemin_fichier="/faux/chemin.pdf", type_document="module_ctd_3",
            televerse_par_id=deposant.id))
        db.session.add(AvisEvaluationMA(
            dossier_id=id4, evaluateur_id=chef.id, module_concerne="global",
            valeur="favorable", commentaire="Conforme."))
        db.session.commit()
        me.appliquer_transition(db.session.get(DossierAMM, id4), "valider", directeur)
        db.session.commit()
        apres = client.get(f"/dossiers/{id4}/etat.json").get_json()
        verifier(apres["empreinte"] != etat1["empreinte"],
                 "elle change dès que le dossier avance")
        verifier(apres["libelle"] == "Validé par la direction",
                 "et le nouvel état est rendu")
        verifier(apres["maj"] is not None, "avec l'horodatage du dernier passage")

        # -----------------------------------------------------------------
        print("\n-- 9. Écrans des files --")
        with client.session_transaction() as s:
            s["user_id"] = financier.id
        r = client.get("/files/")
        verifier(r.status_code in (200, 302),
                 "l'accueil des files répond au financier")
        r = client.get("/files/financier", follow_redirects=True)
        verifier(r.status_code == 200, "sa file s'affiche")
        page = r.data.decode("utf-8")
        verifier("Valider le paiement" in page,
                 "elle lui propose de valider un paiement")
        verifier("Suivi en direct" in page, "et annonce le suivi en direct")
        verifier(client.get("/files/direction").status_code == 403,
                 "il ne peut pas ouvrir la file de la direction")
        verifier(client.get("/files/inexistante").status_code == 403,
                 "ni une file qui n'existe pas")

        # Une file affiche plusieurs lignes portant la même action. Si les
        # boîtes de dialogue partageaient un identifiant, le navigateur
        # ouvrirait toujours la première et le motif partirait sur le mauvais
        # dossier — sans qu'aucune erreur ne soit levée nulle part.
        ids = re.findall(r'<div class="modal fade" id="([^"]+)"', page)
        verifier(len(ids) == len(set(ids)),
                 f"aucun identifiant de boîte de dialogue en double ({ids})")
        multiples = [l for l in fa.contenu("financier", financier)]
        verifier(len(multiples) >= 2,
                 f"la file compte au moins deux lignes pour l'éprouver "
                 f"({len(multiples)})")
        for l in multiples:
            attendu = f'motif-{l["dossier"].id}-rejeter_paiement'
            verifier(attendu in ids,
                     f"la ligne {l['dossier'].numero} a sa propre boîte")

        r = client.get("/files/financier/synthese.json")
        verifier(r.status_code == 200 and "empreinte" in r.get_json(),
                 "la synthèse JSON de sa file lui est ouverte")
        verifier(client.get("/files/direction/synthese.json").status_code == 403,
                 "celle des autres, non")

        with client.session_transaction() as s:
            s["user_id"] = deposant.id
        verifier(client.get("/files/financier").status_code == 403,
                 "un déposant n'accède à aucune file")

        with client.session_transaction() as s:
            s["user_id"] = admin.id
        r = client.get("/files/", follow_redirects=True)
        verifier(r.status_code == 200 and "Files d'attente" in r.data.decode("utf-8"),
                 "l'administrateur obtient la synthèse des quatre files")

        # -----------------------------------------------------------------
        print("\n-- 10. Concordance menu / serveur --")
        import matrice_acces as ma

        entree = next(e for e in ma.NAVIGATION if e["code"] == "files")
        for role in entree["roles"]:
            personne = Personne.query.filter_by(role_systeme=role,
                                                statut_compte="actif").first()
            if personne is None:
                continue
            with client.session_transaction() as s:
                s["user_id"] = personne.id
            code = client.get("/files/", follow_redirects=True).status_code
            verifier(code == 200,
                     f"le menu promet la file à {role}, le serveur la sert "
                     f"(HTTP {code})")

        roles_du_menu = set(entree["roles"])
        roles_des_files = {r for f in fa.FILES for r in f["roles"]}
        verifier(roles_des_files <= roles_du_menu,
                 f"tout rôle ayant une file la voit au menu "
                 f"({roles_des_files - roles_du_menu})")
    finally:
        _nettoyer(avant)


print(f"\n{ok} vérifications passées, {len(ko)} échec(s)")
if ko:
    for libelle in ko:
        print(f"  - {libelle}")
    raise SystemExit(1)
