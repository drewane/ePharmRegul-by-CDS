"""
Initialise la base de données SIREPH et crée des comptes + données de
démonstration couvrant tous les statuts des 9 fonctions réglementaires livrées
(RS, MA, VL, RI, LI, LT, MC, CT, LR), pour pouvoir rejouer immédiatement les
critères d'acceptation du cahier des charges.

Usage : python seed.py
Mot de passe pour tous les comptes de démonstration : demo1234
"""
from datetime import date, datetime, timedelta

from app import app
from models import (db, Personne, Etablissement, Produit, NotificationVigilance, Inspection, DemandeLicence,
                     Echantillon, SignalementQualite, Lot, ProtocoleEssaiClinique, LiberationLot, DossierAMM)
import workflow_ma as wf
import workflow_vl as wfvl
import workflow_ri as wfri
import workflow_li as wfli
import workflow_lt as wflt
import workflow_mc as wfmc
import workflow_ct as wfct
import workflow_lr as wflr
import workflow_derogation as wfd
import workflow_visas as wfv
from grille_ri import grille_initiale
from audit import enregistrer_creation
from delais import initialiser_parametres_defaut
from paiements import lister_paiements, deposer_preuve, confirmer as confirmer_paiement, rejeter as rejeter_paiement

COMPTES = [
    ("Administrateur SIREPH", "admin@dpml.demo", "administrateur_dpml", None),
    ("Évaluateur AMM", "evaluateur@dpml.demo", "evaluateur_amm", None),
    ("Directeur DPML", "directeur@dpml.demo", "directeur_dpml", None),
    ("Agent Pharmacovigilance", "vigilance@dpml.demo", "agent_vigilance", None),
    ("Inspecteur IGSPL", "inspecteur@igspl.demo", "inspecteur_igspl", None),
    ("Agent Licences", "licences@dpml.demo", "agent_licences", None),
    ("Agent Laboratoire", "labo@lanacome.demo", "agent_laboratoire", None),
    ("Responsable Qualité Laboratoire", "rq@lanacome.demo", "responsable_qualite_labo", None),
    ("Agent Surveillance du Marché", "surveillance@dpml.demo", "agent_surveillance_marche", None),
    ("Agent DROS", "dros@dpml.demo", "agent_dros", None),
    ("Demandeur PharmaCam SARL", "demandeur@pharmacam.demo", "demandeur_externe", "PharmaCam Import SARL"),
    ("Demandeur BioSanté Distribution", "demandeur2@biosante.demo", "demandeur_externe", "BioSanté Distribution"),
]


def _get_or_create_compte(nom, email, role, nom_etablissement):
    p = Personne.query.filter_by(email=email).first()
    if p:
        return p
    etab = None
    if nom_etablissement:
        etab = Etablissement.query.filter_by(raison_sociale=nom_etablissement).first()
        if not etab:
            etab = Etablissement(raison_sociale=nom_etablissement, type="importateur_exportateur",
                                  adresse="Douala, Cameroun", statut_licence="active")
            db.session.add(etab)
            db.session.flush()
    p = Personne(nom_complet=nom, email=email, role_systeme=role,
                 etablissement_rattachement_id=etab.id if etab else None)
    p.set_password("demo1234")
    db.session.add(p)
    db.session.flush()
    return p


def _donnees_produit(nom, dci, forme, dosage, fabricant_nom, titulaire_nom):
    return {
        "nom_commercial": nom, "dci": dci, "forme_pharmaceutique": forme, "dosage": dosage,
        "fabricant_nom": fabricant_nom, "fabricant_site": "Zone industrielle, Douala",
        "titulaire_nom": titulaire_nom, "pays_origine": "Cameroun",
        # Champs SECTION 2 du formulaire officiel DPML — valeurs de démonstration génériques.
        "composition_integrale": f"{dci} {dosage or ''} — excipients qsp un {forme.lower() if forme else 'comprimé'} (démo).",
        "classe_therapeutique": "Classe thérapeutique (démo).",
        "indications_therapeutiques": "Indications thérapeutiques usuelles de la DCI (démo).",
        "voie_administration": "Orale",
        "duree_stabilite": "24 mois",
        "prix_grossiste_ht": "2500",
        "representant_local_nom": "Dr. Ngassa (pharmacien interlocuteur, démo)",
        "representant_local_contact": "677 00 00 00 / representant@campharma.demo",
    }


def _fichier_preuve_demo(nom="preuve_virement_demo.pdf"):
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=BytesIO(b"Preuve de paiement (demonstration)"), filename=nom,
                        content_type="application/pdf")


with app.app_context():
    db.create_all()

    for nom, email, role, structure in COMPTES:
        _get_or_create_compte(nom, email, role, structure)
    db.session.commit()

    admin = Personne.query.filter_by(email="admin@dpml.demo").first()
    evaluateur = Personne.query.filter_by(email="evaluateur@dpml.demo").first()
    directeur = Personne.query.filter_by(email="directeur@dpml.demo").first()
    agent_vig = Personne.query.filter_by(email="vigilance@dpml.demo").first()
    inspecteur = Personne.query.filter_by(email="inspecteur@igspl.demo").first()
    agent_lic = Personne.query.filter_by(email="licences@dpml.demo").first()
    agent_lab = Personne.query.filter_by(email="labo@lanacome.demo").first()
    resp_q = Personne.query.filter_by(email="rq@lanacome.demo").first()
    agent_surv = Personne.query.filter_by(email="surveillance@dpml.demo").first()
    agent_dros = Personne.query.filter_by(email="dros@dpml.demo").first()
    demandeur1 = Personne.query.filter_by(email="demandeur@pharmacam.demo").first()
    demandeur2 = Personne.query.filter_by(email="demandeur2@biosante.demo").first()

    initialiser_parametres_defaut()

    if not Produit.query.first():
        # a) Brouillon SANS DCI : reproduit le critère d'acceptation #1 (soumission bloquée).
        #    Création directe (pas via creer_dossier_nouvelle_demande, qui exige la DCI dès
        #    la création) pour pouvoir laisser volontairement ce champ vide.
        p_sans_dci = Produit(nom_commercial="Produit test (sans DCI)", denomination_commune_internationale="",
                              forme_pharmaceutique="Comprimé", statut_amm_courant="en_cours")
        db.session.add(p_sans_dci)
        db.session.flush()
        enregistrer_creation(p_sans_dci, demandeur1, "Création de la fiche produit (démo)")
        wf.creer_dossier_procedure(p_sans_dci, demandeur1, "nouvelle_demande")

        # b) Soumis : en attente de recevabilité.
        d_soumis = wf.creer_dossier_nouvelle_demande(
            demandeur1, _donnees_produit("Doliprane 500", "Paracétamol", "Comprimé", "500 mg",
                                          "Laboratoires CamPharma SA", "PharmaCam Import SARL"))
        wf.soumettre(d_soumis, demandeur1)

        # c) Évaluation en cours : permet de vérifier que evaluateur_amm ne peut pas approuver.
        d_evaluation = wf.creer_dossier_nouvelle_demande(
            demandeur1, _donnees_produit("Efferalgan 1000", "Paracétamol", "Comprimé effervescent", "1000 mg",
                                          "Laboratoires CamPharma SA", "PharmaCam Import SARL"))
        wf.soumettre(d_evaluation, demandeur1)
        wf.marquer_recevabilite(d_evaluation, admin, "recevable")

        # d) Complément requis, délai DÉJÀ dépassé : clôture automatique au premier accès dashboard.
        d_complement = wf.creer_dossier_nouvelle_demande(
            demandeur1, _donnees_produit("Fervex Adulte", "Paracétamol/Phéniramine/Vitamine C", "Poudre pour solution buvable", "-",
                                          "Laboratoires CamPharma SA", "PharmaCam Import SARL"))
        wf.soumettre(d_complement, demandeur1)
        wf.marquer_recevabilite(d_complement, admin, "recevable")
        wf.deposer_avis_evaluation(d_complement, evaluateur, "module3",
                                    "complement_requis", "Bulletin de contrôle du produit fini manquant (démo).")
        d_complement.date_limite_reponse_complement = datetime.utcnow() - timedelta(days=1)

        # e) Approuvé, AMM valide encore 25 jours : déclenche un rappel de renouvellement dès le dashboard.
        d_approuve = wf.creer_dossier_nouvelle_demande(
            demandeur1, _donnees_produit("Amodex 250", "Amoxicilline", "Gélule", "250 mg",
                                          "Laboratoires CamPharma SA", "PharmaCam Import SARL"))
        wf.soumettre(d_approuve, demandeur1)
        wf.marquer_recevabilite(d_approuve, admin, "recevable")
        wf.deposer_avis_evaluation(d_approuve, evaluateur, "global", "favorable", "Dossier conforme (démo).")
        wf.decider(d_approuve, directeur, "approuve")
        d_approuve.date_validite_amm = date.today() + timedelta(days=25)

        # f) Rejeté.
        d_rejete = wf.creer_dossier_nouvelle_demande(
            demandeur1, _donnees_produit("Xyladex (test rejet)", "Xylométazoline", "Solution nasale", "0,1%",
                                          "Laboratoires CamPharma SA", "PharmaCam Import SARL"))
        wf.soumettre(d_rejete, demandeur1)
        wf.marquer_recevabilite(d_rejete, admin, "recevable")
        wf.deposer_avis_evaluation(d_rejete, evaluateur, "module4", "recommandation_rejet",
                                    "Données non cliniques insuffisantes (démo).")
        wf.decider(d_rejete, directeur, "rejete", "Non-conformité substantielle du Module 4 (démo).")

        # g) Irrecevable.
        d_irrecevable = wf.creer_dossier_nouvelle_demande(
            demandeur1, _donnees_produit("Test Irrecevable", "Ibuprofène", "Comprimé", "400 mg",
                                          "Laboratoires CamPharma SA", "PharmaCam Import SARL"))
        wf.soumettre(d_irrecevable, demandeur1)
        wf.marquer_recevabilite(d_irrecevable, admin, "irrecevable",
                                 "Certificat de Produit Pharmaceutique absent du dossier (démo).")

        # h) Un dossier appartenant au second demandeur, pour vérifier l'isolement des portées
        #    (demandeur1 ne doit pas voir ce dossier, et réciproquement).
        wf.creer_dossier_nouvelle_demande(
            demandeur2, _donnees_produit("Bioflux (démo demandeur 2)", "Métronidazole", "Comprimé", "250 mg",
                                          "BioSanté Manufacturing", "BioSanté Distribution"))

        # i) Paiement des frais confirmé (dossier approuvé) et paiement rejeté (dossier
        #    soumis) : illustre le circuit preuve de paiement → validation DPML au complet.
        paiement_approuve = lister_paiements(d_approuve)[0]
        deposer_preuve(paiement_approuve, _fichier_preuve_demo(), demandeur1)
        confirmer_paiement(paiement_approuve, admin)

        paiement_soumis = lister_paiements(d_soumis)[0]
        deposer_preuve(paiement_soumis, _fichier_preuve_demo("preuve_incomplete_demo.pdf"), demandeur1)
        rejeter_paiement(paiement_soumis, admin, "Montant viré inférieur aux frais exigés (démo).")

        db.session.commit()
        print("Données de démonstration MA créées.")
    else:
        print("Des produits existent déjà — données de démonstration MA non recréées (comptes seulement).")

    if not NotificationVigilance.query.first():
        produit_efferalgan = Produit.query.filter_by(nom_commercial="Efferalgan 1000").first()
        produit_doliprane = Produit.query.filter_by(nom_commercial="Doliprane 500").first()
        produit_amodex = Produit.query.filter_by(nom_commercial="Amodex 250").first()

        # a) Cas GRAVE encore « reçue », au-delà du délai réglementaire (15 jours par défaut) :
        #    déclenche l'alerte de dépassement dès le premier accès au tableau de bord/registre.
        cas_retard = wfvl.creer_notification({
            "description_effet": "Réaction anaphylactique sévère survenue peu après administration (démo).",
            "gravite": "grave", "source": "professionnel_sante",
            "produit_id": produit_efferalgan.id if produit_efferalgan else None,
            "patient_age": 34, "patient_sexe": "F",
            "notificateur_nom": "Dr. Ekedi (démo)", "notificateur_contact": "ekedi@hopital.demo",
        })
        cas_retard.date_notification = datetime.utcnow() - timedelta(days=20)

        # b) En évaluation.
        cas_eval = wfvl.creer_notification({
            "description_effet": "Éruption cutanée modérée, sans gravité (démo).",
            "gravite": "non_grave", "source": "patient",
            "produit_id": produit_doliprane.id if produit_doliprane else None,
            "patient_age": 45, "patient_sexe": "M",
        })
        wfvl.prendre_en_charge(cas_eval, agent_vig)

        # c) Signal détecté, en attente d'arbitrage du directeur (teste l'écran d'arbitrage
        #    et, si l'utilisateur choisit "retrait", l'intégration automatique avec le module MA).
        cas_signal = wfvl.creer_notification({
            "description_effet": "Troisième cas similaire de tachycardie rapporté sur ce produit (démo).",
            "gravite": "grave", "source": "industriel",
            "produit_id": produit_amodex.id if produit_amodex else None,
            "patient_age": 60, "patient_sexe": "M",
        })
        wfvl.prendre_en_charge(cas_signal, agent_vig)
        wfvl.decider_suivi(cas_signal, agent_vig, "signal_detecte",
                            "Accumulation de cas similaires sur ce produit (démo).")

        # d) Clôturé, cas isolé, transmis à VigiFlow (référence E2B consultable).
        cas_cloture = wfvl.creer_notification({
            "description_effet": "Nausées transitoires, résolues sans séquelle (démo).",
            "gravite": "non_grave", "source": "patient", "patient_age": 28, "patient_sexe": "F",
        })
        wfvl.prendre_en_charge(cas_cloture, agent_vig)
        wfvl.decider_suivi(cas_cloture, agent_vig, "cloturer")
        wfvl.transmettre_vigiflow(cas_cloture, agent_vig)

        db.session.commit()
        print("Données de démonstration VL créées.")
    else:
        print("Des cas de vigilance existent déjà — données de démonstration VL non recréées.")

    if not Inspection.query.first():
        etab_campharma = Etablissement.query.filter_by(raison_sociale="Laboratoires CamPharma SA").first()
        etab_pharmacam = Etablissement.query.filter_by(raison_sociale="PharmaCam Import SARL").first()
        etab_biosante_mfg = Etablissement.query.filter_by(raison_sociale="BioSanté Manufacturing").first()
        etab_biosante_dist = Etablissement.query.filter_by(raison_sociale="BioSanté Distribution").first()

        def grille_notee(reponses):
            """reponses : liste de valeurs conforme/non_conforme/non_applicable/None dans
            l'ordre du catalogue, appliquée sur une grille vierge fraîchement générée."""
            g = grille_initiale()
            for item, val in zip(g, reponses):
                item["reponse"] = val
                if val == "non_conforme":
                    item["commentaire"] = "Point à corriger (démo)."
            return g

        # a) Planifiée — pas encore démarrée.
        wfri.planifier(etab_campharma, inspecteur, admin, type_insp="routine",
                        date_planifiee=date.today() + timedelta(days=7))

        # b) En cours — grille partiellement saisie (simule une saisie de terrain
        #    hors connexion pas encore terminée).
        insp_en_cours = wfri.planifier(etab_pharmacam, inspecteur, admin, type_insp="routine",
                                        date_planifiee=date.today())
        wfri.demarrer(insp_en_cours, inspecteur)
        grille_partielle = grille_initiale()
        for item in grille_partielle[:5]:
            item["reponse"] = "conforme"
        wfri.synchroniser_grille(insp_en_cours, inspecteur, grille_partielle)

        # c) Conforme (circuit complet jusqu'à la décision finale).
        insp_conforme = wfri.planifier(etab_biosante_mfg, inspecteur, admin, type_insp="routine",
                                        date_planifiee=date.today() - timedelta(days=3))
        wfri.demarrer(insp_conforme, inspecteur)
        wfri.cloturer_visite(insp_conforme, inspecteur, grille_notee(["conforme"] * 12))
        wfri.decider_conformite(insp_conforme, inspecteur, "conforme")

        # d) Non conforme, plan d'action en cours avec échéance DÉJÀ dépassée : teste
        #    l'alerte automatique du suivi des plans d'action dès le tableau de bord.
        insp_retard = wfri.planifier(etab_biosante_dist, inspecteur, admin, type_insp="routine",
                                      date_planifiee=date.today() - timedelta(days=20))
        wfri.demarrer(insp_retard, inspecteur)
        wfri.cloturer_visite(insp_retard, inspecteur,
                              grille_notee(["conforme"] * 6 + ["non_conforme"] * 4 + ["non_applicable"] * 2))
        wfri.decider_conformite(insp_retard, inspecteur, "non_conforme", non_conforme_grave=False)
        wfri.soumettre_plan_action(insp_retard, inspecteur, "Réorganisation de la zone de quarantaine (démo).",
                                    date.today() - timedelta(days=5))

        # e) Non conforme GRAVE, plan d'action en cours (échéance future) : teste l'écran
        #    de proposition de suspension pour le directeur, sans dépendre du cas (d).
        insp_grave = wfri.planifier(etab_campharma, inspecteur, admin, type_insp="declenchee_signalement",
                                     date_planifiee=date.today() - timedelta(days=1))
        wfri.demarrer(insp_grave, inspecteur)
        wfri.cloturer_visite(insp_grave, inspecteur,
                              grille_notee(["non_conforme"] * 8 + ["conforme"] * 4))
        wfri.decider_conformite(insp_grave, admin, "non_conforme", non_conforme_grave=True)
        wfri.soumettre_plan_action(insp_grave, inspecteur, "Mise en conformité complète des locaux (démo).",
                                    date.today() + timedelta(days=30))

        db.session.commit()
        print("Données de démonstration RI créées.")
    else:
        print("Des inspections existent déjà — données de démonstration RI non recréées.")

    if not DemandeLicence.query.first():
        # a) Établissement neuf, demande de licence tout juste déposée.
        etab_bafoussam = Etablissement.query.filter_by(raison_sociale="Pharmacie Bafoussam Centre").first()
        if not etab_bafoussam:
            etab_bafoussam = Etablissement(raison_sociale="Pharmacie Bafoussam Centre", type="officine",
                                            adresse="Bafoussam, Cameroun", statut_licence="en_instruction")
            db.session.add(etab_bafoussam)
            db.session.flush()
        demandeur3 = Personne.query.filter_by(email="demandeur3@bafoussam.demo").first()
        if not demandeur3:
            demandeur3 = Personne(nom_complet="Demandeur Pharmacie Bafoussam", email="demandeur3@bafoussam.demo",
                                   role_systeme="demandeur_externe", etablissement_rattachement_id=etab_bafoussam.id)
            demandeur3.set_password("demo1234")
            db.session.add(demandeur3)
            db.session.flush()
        wfli.deposer_demande(etab_bafoussam, demandeur3, type_demande="nouvelle",
                              pieces_justificatives="Statuts juridiques, CV du pharmacien responsable (démo).")

        # b) Demande instruite puis approuvée (circuit complet).
        etab_biosante_mfg = Etablissement.query.filter_by(raison_sociale="BioSanté Manufacturing").first()
        demande_approuvee = wfli.deposer_demande(etab_biosante_mfg, admin, type_demande="nouvelle",
                                                  pieces_justificatives="Dossier complet (démo).")
        wfli.instruire(demande_approuvee, agent_lic)
        wfli.decider(demande_approuvee, directeur, "approuve")

        # c) Demande refusée.
        etab_refuse = Etablissement(raison_sociale="Dépôt Sanaga (test refus)", type="depot",
                                     adresse="Édéa, Cameroun", statut_licence="en_instruction")
        db.session.add(etab_refuse)
        db.session.flush()
        demande_refusee = wfli.deposer_demande(etab_refuse, admin, type_demande="nouvelle",
                                                pieces_justificatives="Dossier incomplet (démo).")
        wfli.instruire(demande_refusee, agent_lic)
        wfli.decider(demande_refusee, directeur, "refuse", motif="Pharmacien responsable non identifié (démo).")

        # d) Licence active mais échue, sans renouvellement engagé : teste l'expiration
        #    automatique (critère d'acceptation LI #1) dès le premier accès au tableau de bord.
        etab_expire = Etablissement(raison_sociale="Grossiste Sahel Nord", type="grossiste_repartiteur",
                                     adresse="Garoua, Cameroun", statut_licence="active",
                                     date_expiration_licence=date.today() - timedelta(days=2))
        db.session.add(etab_expire)

        # e) Établissement suspendu directement (données de démo, sans passer par une
        #    inspection) : permet de vérifier immédiatement le blocage croisé côté MA
        #    (critère d'acceptation LI #2) sans dépendre du scénario RI.
        etab_suspendu = Etablissement(raison_sociale="Suspendu Test SARL", type="fabricant",
                                       adresse="Douala, Cameroun", statut_licence="suspendue")
        db.session.add(etab_suspendu)

        db.session.commit()
        print("Données de démonstration LI créées.")
    else:
        print("Des demandes de licence existent déjà — données de démonstration LI non recréées.")

    if not Echantillon.query.first():
        produit_doliprane = Produit.query.filter_by(nom_commercial="Doliprane 500").first()
        produit_efferalgan = Produit.query.filter_by(nom_commercial="Efferalgan 1000").first()
        produit_amodex = Produit.query.filter_by(nom_commercial="Amodex 250").first()
        dossier_amodex = wf.DossierAMM.query.filter_by(numero="AMM-2026-0004").first()

        # a) Reçu.
        wflt.creer_echantillon(produit_doliprane, admin, origine="demande_directe")

        # b) En analyse.
        ech_analyse = wflt.creer_echantillon(produit_efferalgan, admin, origine="demande_directe")
        wflt.prendre_en_charge(ech_analyse, agent_lab)

        # c) Résultat saisi, en attente de validation (circuit normal).
        ech_attente = wflt.creer_echantillon(produit_amodex, admin, origine="demande_directe")
        wflt.prendre_en_charge(ech_attente, agent_lab)
        wflt.saisir_resultats(ech_attente, agent_lab, [
            {"parametre": "Teneur en principe actif (%)", "methode": "HPLC", "resultat_mesure": "99.1",
             "specification": "95-105"},
            {"parametre": "Aspect", "methode": "Visuel", "resultat_mesure": "Conforme", "specification": "Conforme"},
        ])

        # d) Cas limite pour la double validation : l'analyste EST le compte responsable
        #    qualité (scénario artificiel construit directement, hors du circuit normal où
        #    seul agent_laboratoire peut prendre en charge un échantillon) — permet de
        #    vérifier que le contrôle d'identité bloque même quand rôle et account coïncident,
        #    conformément au critère d'acceptation LT ("même s'il détient également ce rôle
        #    sur d'autres échantillons").
        ech_meme_personne = wflt.creer_echantillon(produit_doliprane, admin, origine="demande_directe")
        ech_meme_personne.analyste_id = resp_q.id
        ech_meme_personne.statut = "en_analyse"
        wflt.saisir_resultats(ech_meme_personne, resp_q, [
            {"parametre": "Aspect", "methode": "Visuel", "resultat_mesure": "Conforme", "specification": "Conforme"},
        ])

        # e) Circuit complet conforme, rattaché au dossier AMM approuvé d'Amodex 250 —
        #    teste la consultation croisée depuis la fiche du DossierAMM.
        if dossier_amodex:
            ech_conforme = wflt.creer_echantillon(produit_amodex, admin, origine="dossier_amm",
                                                   origine_reference_id=dossier_amodex.id)
            wflt.prendre_en_charge(ech_conforme, agent_lab)
            wflt.saisir_resultats(ech_conforme, agent_lab, [
                {"parametre": "Teneur en principe actif (%)", "methode": "HPLC", "resultat_mesure": "101.2",
                 "specification": "95-105"},
            ])
            wflt.valider_resultats(ech_conforme, resp_q, "valide", conclusion="conforme")
            wflt.emettre_certificat(ech_conforme, resp_q)

        # f) Circuit complet non conforme — déclenche l'alerte vers le module MC (stand-in
        #    tant que MC n'est pas livré ; devient un signalement réel une fois MC construit
        #    et ce script relancé).
        ech_non_conforme = wflt.creer_echantillon(produit_efferalgan, admin, origine="demande_directe")
        wflt.prendre_en_charge(ech_non_conforme, agent_lab)
        wflt.saisir_resultats(ech_non_conforme, agent_lab, [
            {"parametre": "Teneur en principe actif (%)", "methode": "HPLC", "resultat_mesure": "78.4",
             "specification": "95-105"},
        ])
        wflt.valider_resultats(ech_non_conforme, resp_q, "valide", conclusion="non_conforme")
        wflt.emettre_certificat(ech_non_conforme, resp_q)

        db.session.commit()
        print("Données de démonstration LT créées.")
    else:
        print("Des échantillons existent déjà — données de démonstration LT non recréées.")

    if SignalementQualite.query.count() <= 1:
        # (<=1 car l'émission du certificat LT non conforme ci-dessus a pu créer
        # automatiquement un premier signalement réel via l'intégration LT → MC.)
        produit_doliprane = Produit.query.filter_by(nom_commercial="Doliprane 500").first()
        produit_amodex = Produit.query.filter_by(nom_commercial="Amodex 250").first()
        etab_campharma = Etablissement.query.filter_by(raison_sociale="Laboratoires CamPharma SA").first()

        # Lots nécessaires pour dériver automatiquement les établissements à notifier.
        lot_doliprane = Lot.query.filter_by(produit_id=produit_doliprane.id, numero_lot="DOL-2026-A1").first()
        if not lot_doliprane:
            lot_doliprane = Lot(produit_id=produit_doliprane.id, numero_lot="DOL-2026-A1",
                                 fabricant_id=etab_campharma.id, statut="en_circulation")
            db.session.add(lot_doliprane)
            db.session.flush()

        # a) Niveau III, rappel déjà engagé et notifié (circuit complet agent seul).
        sig_niveau3 = wfmc.signaler(produit_doliprane, admin, "Défaut d'étiquetage détecté sur ce lot (démo).",
                                     origine="titulaire_amm", numeros_lots=["DOL-2026-A1"])
        wfmc.evaluer(sig_niveau3, agent_surv, "III")
        wfmc.engager_rappel(sig_niveau3, agent_surv)

        # b) Niveau I, évalué, EN ATTENTE de validation du directeur — teste le critère
        #    d'acceptation MC (bouton désactivé pour agent_surveillance_marche seul).
        sig_niveau1 = wfmc.signaler(produit_amodex, admin, "Suspicion de contamination croisée (démo).",
                                     origine="module_ri")
        wfmc.evaluer(sig_niveau1, agent_surv, "I")

        # c) Sans suite.
        sig_sans_suite = wfmc.signaler(produit_doliprane, admin, "Odeur inhabituelle signalée (démo).",
                                        origine="signalement_public")
        wfmc.evaluer(sig_sans_suite, agent_surv, "III")
        wfmc.classer_sans_suite(sig_sans_suite, agent_surv, "Analyse complémentaire : conforme aux spécifications (démo).")

        db.session.commit()
        print("Données de démonstration MC créées.")
    else:
        print("Des signalements existent déjà — données de démonstration MC non recréées.")

    if not ProtocoleEssaiClinique.query.first():
        produit_amodex = Produit.query.filter_by(nom_commercial="Amodex 250").first()

        # a) Déposé.
        wfct.deposer(demandeur1, "Étude de bioéquivalence — Amodex 250 (démo)", produit_etudie=produit_amodex)

        # b) En évaluation, avis éthique encore en attente — teste le blocage de
        #    l'autorisation tant que l'avis n'est pas favorable (critère d'acceptation CT).
        proto_attente = wfct.deposer(demandeur1, "Essai clinique Phase III — Doliprane pédiatrique (démo)")
        wfct.marquer_recevabilite(proto_attente, agent_dros, "recevable")

        # c) En évaluation, avis éthique favorable renseigné — prêt à être autorisé en direct.
        proto_pret = wfct.deposer(demandeur1, "Essai clinique Phase II — Efferalgan nouvelle formulation (démo)",
                                   reference_comite_ethique="CNE-2026-014")
        wfct.marquer_recevabilite(proto_pret, agent_dros, "recevable")
        wfct.mettre_a_jour_avis_ethique(proto_pret, agent_dros, "favorable", reference="CNE-2026-014")

        # d) Autorisé, avec un rapport d'étape déjà attendu — teste amendements et rapports.
        proto_autorise = wfct.deposer(demandeur1, "Essai clinique Phase I — Nouvelle molécule antipaludique (démo)",
                                       reference_comite_ethique="CNE-2026-009")
        wfct.marquer_recevabilite(proto_autorise, agent_dros, "recevable")
        wfct.mettre_a_jour_avis_ethique(proto_autorise, agent_dros, "favorable", reference="CNE-2026-009")
        wfct.decider(proto_autorise, directeur, "autorise",
                      rapports_attendus=[{"titre": "Rapport intermédiaire M6", "echeance": "2026-12-31"}])

        # e) Rejeté.
        proto_rejete = wfct.deposer(demandeur1, "Essai clinique non conforme (test rejet, démo)")
        wfct.marquer_recevabilite(proto_rejete, agent_dros, "recevable")
        wfct.decider(proto_rejete, directeur, "rejete", motif="Méthodologie insuffisante (démo).")

        # f) Irrecevable.
        proto_irrecevable = wfct.deposer(demandeur1, "Essai clinique dossier incomplet (test irrecevable, démo)")
        wfct.marquer_recevabilite(proto_irrecevable, agent_dros, "irrecevable",
                                   motif="Référence du comité d'éthique absente du dossier (démo).")

        db.session.commit()
        print("Données de démonstration CT créées.")
    else:
        print("Des protocoles d'essais cliniques existent déjà — données de démonstration CT non recréées.")

    if not LiberationLot.query.first():
        etab_campharma = Etablissement.query.filter_by(raison_sociale="Laboratoires CamPharma SA").first()

        def _produit_vaccin(nom, dci, statut_amm):
            p = Produit.query.filter_by(nom_commercial=nom).first()
            if not p:
                p = Produit(nom_commercial=nom, denomination_commune_internationale=dci,
                            forme_pharmaceutique="Solution injectable", categorie="vaccin",
                            fabricant_id=etab_campharma.id, titulaire_amm_id=etab_campharma.id,
                            pays_origine="Cameroun", statut_amm_courant=statut_amm)
                db.session.add(p)
                db.session.flush()
                enregistrer_creation(p, admin, "Création de la fiche produit (démo, vaccin)")
            return p

        # a) Circuit complet jusqu'à la libération (AMM active, contrôle labo conforme).
        produit_vax1 = _produit_vaccin("VaxiFièvre Jaune", "Vaccin fièvre jaune vivant atténué", "active")
        lot_vax1 = Lot(produit_id=produit_vax1.id, numero_lot="VAX-2026-001", fabricant_id=etab_campharma.id,
                        statut="en_circulation")
        db.session.add(lot_vax1)
        db.session.flush()
        lib1 = wflr.recevoir_dossier_lot(produit_vax1, lot_vax1, admin,
                                          dossier_fabricant="Certificat d'analyse fabricant (démo).")
        wflr.controler_documentaire(lib1, admin, "valide")
        wflr.lancer_controle_laboratoire(lib1, agent_lab)
        wflt.prendre_en_charge(lib1.echantillon_lt, agent_lab)
        wflt.saisir_resultats(lib1.echantillon_lt, agent_lab, [
            {"parametre": "Titre viral", "methode": "Titrage", "resultat_mesure": "4.5", "specification": "3-6"},
        ])
        wflt.valider_resultats(lib1.echantillon_lt, resp_q, "valide", conclusion="conforme")
        wflt.emettre_certificat(lib1.echantillon_lt, resp_q)
        wflr.decider_liberation(lib1, directeur, "libere")

        # b) Produit SANS AMM active : reçu, mais bloqué à l'entrée du contrôle documentaire
        #    (critère d'acceptation LR #1) — laissé volontairement au statut "reçu".
        produit_vax2 = _produit_vaccin("VaxiRougeole", "Vaccin rougeole vivant atténué", "aucune")
        lot_vax2 = Lot(produit_id=produit_vax2.id, numero_lot="VAX-2026-002", fabricant_id=etab_campharma.id,
                        statut="en_circulation")
        db.session.add(lot_vax2)
        db.session.flush()
        wflr.recevoir_dossier_lot(produit_vax2, lot_vax2, admin, dossier_fabricant="Dossier fabricant (démo).")

        # c) Rejeté après contrôle laboratoire non conforme, lot déjà partiellement
        #    distribué — teste l'intégration automatique avec le module MC.
        produit_sang = _produit_vaccin("BioPlasma Standard", "Plasma sanguin traité", "active")
        produit_sang.categorie = "produit_sanguin"
        lot_sang = Lot(produit_id=produit_sang.id, numero_lot="SANG-2026-001", fabricant_id=etab_campharma.id,
                        statut="en_circulation")
        db.session.add(lot_sang)
        db.session.flush()
        lib3 = wflr.recevoir_dossier_lot(produit_sang, lot_sang, admin,
                                          dossier_fabricant="Certificat d'analyse fabricant (démo).")
        wflr.controler_documentaire(lib3, admin, "valide")
        wflr.lancer_controle_laboratoire(lib3, agent_lab)
        wflt.prendre_en_charge(lib3.echantillon_lt, agent_lab)
        wflt.saisir_resultats(lib3.echantillon_lt, agent_lab, [
            {"parametre": "Stérilité", "methode": "Culture", "resultat_mesure": "Positif", "specification": "Négatif"},
        ])
        wflt.valider_resultats(lib3.echantillon_lt, resp_q, "valide", conclusion="non_conforme")
        wflt.emettre_certificat(lib3.echantillon_lt, resp_q)
        wflr.decider_liberation(lib3, directeur, "rejete", motif="Contamination détectée (démo).",
                                 deja_distribue=True)

        db.session.commit()
        print("Données de démonstration LR créées.")
    else:
        print("Des dossiers de libération de lot existent déjà — données de démonstration LR non recréées.")

    # Dérogations spéciales et visas techniques : démonstration des deux nouveaux onglets.
    from models import DemandeDerogation, VisaTechnique
    if not DemandeDerogation.query.first():
        dossier_approuve = DossierAMM.query.filter_by(statut="approuve").first()
        if dossier_approuve:
            der1 = wfd.deposer(
                dossier_approuve.demandeur,
                "Délai de dépôt du bulletin de contrôle des matières premières",
                "Le fournisseur de matière première n'a pu transmettre le bulletin à temps en raison d'un "
                "incident logistique (démo). Demande d'un délai supplémentaire de 30 jours.",
                dossier_approuve,
            )
            wfd.instruire(der1, admin)
            wfd.decider(der1, directeur, "approuve", motif="Délai supplémentaire de 30 jours accordé (démo).")

            der2 = wfd.deposer(
                demandeur2, "Exemption de certificat GMP à jour",
                "Le certificat GMP actuel expire dans 15 jours ; renouvellement en cours auprès de l'autorité "
                "du pays d'origine (démo).",
            )
            wfd.instruire(der2, admin)

            if dossier_approuve.produit.statut_amm_courant == "active":
                visa1 = wfv.demander(dossier_approuve.demandeur, dossier_approuve.produit,
                                      "Importation de 5000 unités depuis le site de fabrication (démo).")
                wfv.decider(visa1, admin, "delivre")

                visa2 = wfv.demander(dossier_approuve.demandeur, dossier_approuve.produit,
                                      "Importation urgente hors calendrier habituel (démo).")
                wfv.decider(visa2, admin, "refuse", motif="Quota annuel déjà atteint pour ce produit (démo).")
        db.session.commit()
        print("Données de démonstration Dérogations/Visas créées.")

    # Compte auto-inscrit en attente de validation (grossiste-répartiteur, parcours public
    # /licences/nouvelle) : démontre l'écran de validation des inscriptions dès le premier lancement.
    if not Personne.query.filter_by(email="attente@nouveaugrossiste.demo").first():
        etab_attente = Etablissement.query.filter_by(raison_sociale="Nouveau Grossiste Attente SARL").first()
        if not etab_attente:
            etab_attente = Etablissement(raison_sociale="Nouveau Grossiste Attente SARL", type="grossiste_repartiteur",
                                          adresse="Bafang, Cameroun", categorie_activite="medicaments",
                                          statut_licence="en_instruction")
            db.session.add(etab_attente)
            db.session.flush()
        p_attente = Personne(nom_complet="Demandeur en attente de validation", email="attente@nouveaugrossiste.demo",
                              role_systeme="demandeur_externe", etablissement_rattachement_id=etab_attente.id,
                              statut_compte="en_attente_validation")
        p_attente.set_password("demo1234")
        db.session.add(p_attente)
        db.session.flush()
        enregistrer_creation(p_attente, p_attente, "Auto-inscription en tant que laboratoire")
        wfli.deposer_demande(etab_attente, p_attente, type_demande="nouvelle",
                              pieces_justificatives="Statuts juridiques (démo).")
        db.session.commit()
        print("Compte de démonstration en attente de validation créé.")

    print(f"OK — {Personne.query.count()} compte(s) en base. Mot de passe pour tous : demo1234")
