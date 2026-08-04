"""
Instruction d'un dossier d'AMM, de la recevabilité au rapport de la direction.

PARCOURS
--------
1. Recevabilité — le chef de service coche sa liste de contrôle ; le dossier
   n'est déclaré recevable que si tous les points bloquants sont satisfaits.
   Le déposant est aussitôt informé que son dossier est accepté et en étude.
2. Évaluation interne — le chef de service confie le dossier à un ou plusieurs
   évaluateurs internes, qui préparent les travaux de commission.
3. Commission — le chef de service convoque une séance et y inscrit les
   dossiers. Chaque membre saisit son avis depuis sa tablette, sur une grille.
4. Synthèse — à la clôture, les avis sont consolidés automatiquement.
5. Rapport — le chef de service rédige son rapport et ouvre le circuit de
   signature (directeur → secrétaire général → ministre).
"""
from datetime import datetime, timedelta

from audit import enregistrer_audit
from erreurs import ErreurWorkflow
from models import (AssignationEvaluation, AvisCommission, DossierAMM,
                    DossierSession, Personne, RapportInstruction,
                    SessionCommission, db)
from notifications import notifier, notifier_tous
from numerotation import generer_numero

# ---------------------------------------------------------------------------
# Liste de contrôle de recevabilité
# ---------------------------------------------------------------------------
# `bloquant` : sans ce point, la recevabilité ne peut pas être prononcée.
CHECKLIST_RECEVABILITE = [
    ("identification_produit", "Identification du produit complète "
                               "(nom, DCI, forme, dosage)", True),
    ("titulaire_identifie", "Titulaire et fabricant identifiés", True),
    ("modules_obligatoires", "Modules obligatoires du dossier technique chargés", True),
    ("preuve_paiement", "Preuve de paiement des frais de dossier reçue", True),
    ("representant_local", "Représentant local désigné", False),
    ("langue_documents", "Documents fournis en français ou en anglais", False),
    ("coherence_dossier", "Cohérence d'ensemble du dossier vérifiée", False),
]

POINTS_BLOQUANTS = [c for c, _l, bloquant in CHECKLIST_RECEVABILITE if bloquant]

# Grille d'évaluation soumise aux membres de commission
GRILLE_COMMISSION = [
    ("qualite_pharmaceutique", "La qualité pharmaceutique est-elle démontrée ?"),
    ("securite", "Le profil de sécurité est-il acceptable ?"),
    ("efficacite", "L'efficacité thérapeutique est-elle établie ?"),
    ("rapport_benefice_risque", "Le rapport bénéfice/risque est-il favorable ?"),
    ("etiquetage_notice", "L'étiquetage et la notice sont-ils conformes ?"),
    ("interet_sante_publique", "Le produit présente-t-il un intérêt de santé publique ?"),
]

AVIS = {
    "favorable": "Avis favorable",
    "defavorable": "Avis défavorable",
    "complement_requis": "Complément de dossier requis",
}


# ---------------------------------------------------------------------------
# 1. Recevabilité
# ---------------------------------------------------------------------------
def points_manquants(dossier):
    """Points bloquants de la liste de contrôle non encore satisfaits."""
    coches = dossier.checklist_recevabilite or {}
    return [(code, libelle) for code, libelle, bloquant in CHECKLIST_RECEVABILITE
            if bloquant and not coches.get(code)]


# La recevabilité administrative et l'attribution relèvent du chef de bureau ;
# le chef de service intervient plus tard, sur l'arbitrage technique et la LoQ.
ROLES_RECEVABILITE = ("chef_bureau", "chef_service_amm", "administrateur_dpml")


def enregistrer_checklist(dossier, acteur, coches):
    """Mémorise l'état de la liste de contrôle, sans prononcer la recevabilité."""
    if acteur.role_systeme not in ROLES_RECEVABILITE:
        raise ErreurWorkflow(
            "La recevabilité administrative relève du chef de bureau.")
    dossier.checklist_recevabilite = {
        code: bool(coches.get(code)) for code, _l, _b in CHECKLIST_RECEVABILITE}
    enregistrer_audit(dossier, "Liste de contrôle de recevabilité mise à jour", acteur)
    return dossier


def prononcer_recevabilite(dossier, acteur, recevable, motif=None):
    """Déclare le dossier recevable ou irrecevable.

    La recevabilité exige que tous les points bloquants soient cochés : le
    contrôle est fait ici, pas seulement dans l'interface.
    """
    if dossier.statut != "soumis":
        raise ErreurWorkflow(
            "La recevabilité ne s'examine que sur un dossier soumis "
            f"(statut actuel : {dossier.statut}).")
    if acteur.role_systeme not in ROLES_RECEVABILITE:
        raise ErreurWorkflow(
            "La recevabilité administrative relève du chef de bureau.")

    if recevable:
        manquants = points_manquants(dossier)
        if manquants:
            raise ErreurWorkflow(
                "Recevabilité impossible : " +
                ", ".join(libelle for _c, libelle in manquants))
    elif not (motif or "").strip():
        raise ErreurWorkflow("Une décision d'irrecevabilité doit être motivée.")

    ancien = dossier.statut
    dossier.statut = "evaluation_en_cours" if recevable else "irrecevable"
    if not recevable:
        dossier.motif_decision = motif.strip()
        dossier.date_decision = datetime.utcnow()
    enregistrer_audit(
        dossier,
        "Dossier déclaré recevable — évaluation ouverte" if recevable
        else f"Dossier déclaré irrecevable : {dossier.motif_decision}",
        acteur, ancien, dossier.statut)

    if dossier.demandeur:
        if recevable:
            notifier(dossier.demandeur, "dossier_recevable",
                     f"Votre dossier {dossier.numero} a été accepté et est en cours "
                     "d'évaluation par la Direction de la Pharmacie.",
                     lien=f"/dossiers/{dossier.id}")
        else:
            notifier(dossier.demandeur, "dossier_irrecevable",
                     f"Votre dossier {dossier.numero} a été déclaré irrecevable : "
                     f"{dossier.motif_decision}", lien=f"/dossiers/{dossier.id}")
    return dossier


# ---------------------------------------------------------------------------
# 2. Évaluation interne
# ---------------------------------------------------------------------------
def evaluateurs_disponibles():
    return (Personne.query
            .filter_by(role_systeme="evaluateur_interne", statut_compte="actif")
            .order_by(Personne.nom_complet).all())


def assigner(dossier, evaluateur, acteur, consigne=None, delai_jours=15):
    if dossier.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Seul un dossier en évaluation peut être assigné.")
    if acteur.role_systeme not in ROLES_RECEVABILITE:
        raise ErreurWorkflow("L'attribution des dossiers relève du chef de bureau.")
    if evaluateur.role_systeme != "evaluateur_interne":
        raise ErreurWorkflow(
            "Le dossier ne peut être confié qu'à un évaluateur interne.")
    if AssignationEvaluation.query.filter_by(
            dossier_id=dossier.id, evaluateur_id=evaluateur.id).first():
        raise ErreurWorkflow(
            f"{evaluateur.nom_complet} est déjà assigné à ce dossier.")

    # Croisement obligatoire avec les déclarations d'intérêts. Un lien majeur
    # ferme l'attribution ET prononce le déport : le contrôle ne se contourne pas.
    import dpi
    majeurs = dpi.controler_avant_attribution(evaluateur, dossier, acteur)
    if majeurs:
        organismes = ", ".join(sorted({l.organisme for l in majeurs}))
        raise ErreurWorkflow(
            f"Attribution impossible : {evaluateur.nom_complet} a déclaré un lien "
            f"d'intérêt avec {organismes}. Un déport a été prononcé et l'accès au "
            "dossier lui est fermé.")
    if dpi.est_assujetti(evaluateur) and dpi.declaration_en_vigueur(evaluateur) is None:
        raise ErreurWorkflow(
            f"{evaluateur.nom_complet} n'a pas de déclaration d'intérêts en vigueur. "
            "Le dossier ne peut pas lui être confié tant qu'elle n'est pas déposée.")

    a = AssignationEvaluation(
        dossier_id=dossier.id, evaluateur_id=evaluateur.id, assigne_par_id=acteur.id,
        consigne=(consigne or "").strip() or None,
        date_echeance=datetime.utcnow() + timedelta(days=delai_jours))
    db.session.add(a)
    db.session.flush()
    enregistrer_audit(dossier,
                      f"Dossier assigné à {evaluateur.nom_complet} pour évaluation interne",
                      acteur)
    notifier(evaluateur, "dossier_assigne",
             f"Le dossier {dossier.numero} vous est confié pour évaluation interne "
             f"(échéance : {a.date_echeance.strftime('%d/%m/%Y')}).",
             lien=f"/instruction/assignations/{a.id}")
    return a


def remettre_evaluation(assignation, acteur, rapport, conclusion):
    if assignation.evaluateur_id != acteur.id:
        raise ErreurWorkflow("Seul l'évaluateur assigné peut remettre ce rapport.")
    if assignation.statut == "terminee":
        raise ErreurWorkflow("Cette évaluation a déjà été remise.")
    if conclusion not in AVIS:
        raise ErreurWorkflow("Conclusion inconnue.")
    if not (rapport or "").strip():
        raise ErreurWorkflow("Le rapport d'évaluation est obligatoire.")

    assignation.rapport = rapport.strip()
    assignation.conclusion = conclusion
    assignation.statut = "terminee"
    assignation.date_remise = datetime.utcnow()
    enregistrer_audit(assignation.dossier,
                      f"Évaluation interne remise par {acteur.nom_complet} "
                      f"({AVIS[conclusion]})", acteur)
    notifier(assignation.assigne_par, "evaluation_remise",
             f"{acteur.nom_complet} a remis son évaluation du dossier "
             f"{assignation.dossier.numero} : {AVIS[conclusion]}.",
             lien=f"/instruction/dossiers/{assignation.dossier_id}")
    return assignation


# ---------------------------------------------------------------------------
# 3. Commission
# ---------------------------------------------------------------------------
def convoquer_commission(acteur, intitule, type_commission="specialisee",
                          date_seance=None, lieu=None):
    if acteur.role_systeme not in ("chef_service_amm", "administrateur_dpml"):
        raise ErreurWorkflow("Seul le chef de service convoque une commission.")
    if type_commission not in ("specialisee", "nationale"):
        raise ErreurWorkflow("Type de commission inconnu.")
    if not (intitule or "").strip():
        raise ErreurWorkflow("L'intitulé de la séance est obligatoire.")

    s = SessionCommission(
        numero=generer_numero("COM"), type_commission=type_commission,
        intitule=intitule.strip(), date_seance=date_seance, lieu=(lieu or "").strip() or None,
        convoquee_par_id=acteur.id, statut="convoquee")
    db.session.add(s)
    db.session.flush()
    enregistrer_audit(s, f"Commission {type_commission} convoquée : {s.intitule}", acteur)
    notifier_tous(s.role_membre, "commission_convoquee",
                  f"Séance {s.numero} convoquée : {s.intitule}"
                  + (f" — {date_seance.strftime('%d/%m/%Y')}" if date_seance else ""),
                  lien=f"/instruction/commissions/{s.id}")
    return s


def controler_deports_seance(session, acteur):
    """Croise les membres avec les dossiers inscrits, avant la séance."""
    import dpi
    prononces = dpi.controler_seance(session, acteur)
    if prononces:
        enregistrer_audit(
            session,
            f"{len(prononces)} déport(s) prononcé(s) au titre des liens d'intérêts",
            acteur)
    return prononces


def inscrire_dossier(session, dossier, acteur):
    if session.statut == "close":
        raise ErreurWorkflow("Cette séance est close.")
    if dossier.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Seul un dossier en évaluation s'inscrit à l'ordre du jour.")
    if DossierSession.query.filter_by(session_id=session.id,
                                      dossier_id=dossier.id).first():
        raise ErreurWorkflow("Ce dossier est déjà inscrit à cette séance.")
    ds = DossierSession(session_id=session.id, dossier_id=dossier.id)
    db.session.add(ds)
    db.session.flush()
    enregistrer_audit(dossier, f"Dossier inscrit à l'ordre du jour de {session.numero}",
                      acteur)
    return ds


def saisir_avis(dossier_session, membre, reponses, avis, motif=None):
    """Avis d'un membre, saisi en séance."""
    session = dossier_session.session
    if session.statut == "close":
        raise ErreurWorkflow("La séance est close : plus aucun avis ne peut être saisi.")
    if membre.role_systeme != session.role_membre:
        raise ErreurWorkflow(
            "Votre profil ne vous permet pas de siéger à cette commission.")
    # Un membre déporté ne délibère pas : le blocage vaut aussi en séance.
    # Nom distinct de `motif` : celui-ci porte la motivation de l'avis du membre.
    import dpi
    autorise, motif_refus_acces = dpi.acces_autorise(membre, dossier_session.dossier)
    if not autorise:
        raise ErreurWorkflow(
            f"Vous ne pouvez pas vous prononcer sur ce dossier. {motif_refus_acces}")
    if avis not in AVIS:
        raise ErreurWorkflow("Avis inconnu.")
    if avis in ("defavorable", "complement_requis") and not (motif or "").strip():
        raise ErreurWorkflow("Un avis défavorable ou un complément doit être motivé.")

    existant = AvisCommission.query.filter_by(
        dossier_session_id=dossier_session.id, membre_id=membre.id).first()
    if existant:
        existant.reponses = reponses or {}
        existant.avis = avis
        existant.motif = (motif or "").strip() or None
        existant.date_saisie = datetime.utcnow()
        a = existant
    else:
        a = AvisCommission(dossier_session_id=dossier_session.id, membre_id=membre.id,
                           reponses=reponses or {}, avis=avis,
                           motif=(motif or "").strip() or None)
        db.session.add(a)
    if session.statut == "convoquee":
        session.statut = "en_cours"
    db.session.flush()
    enregistrer_audit(dossier_session.dossier,
                      f"Avis de commission saisi par {membre.nom_complet} ({AVIS[avis]})",
                      membre)
    return a


def synthetiser(dossier_session):
    """Consolide automatiquement les avis des membres.

    Règle retenue : l'avis global suit la majorité ; à égalité, ou dès qu'un
    membre demande un complément sans majorité favorable, le complément prime —
    on ne tranche jamais au bénéfice du doute.
    """
    avis = AvisCommission.query.filter_by(
        dossier_session_id=dossier_session.id).all()
    if not avis:
        return None

    comptes = {cle: sum(1 for a in avis if a.avis == cle) for cle in AVIS}
    total = len(avis)
    majoritaire = max(comptes, key=lambda c: comptes[c])
    if comptes[majoritaire] * 2 <= total and comptes["complement_requis"]:
        majoritaire = "complement_requis"

    motifs = [f"• {a.membre.nom_complet} ({AVIS[a.avis]}) : {a.motif}"
              for a in avis if a.motif]
    lignes = [f"{total} avis exprimé(s) — " +
              ", ".join(f"{AVIS[c].lower()} : {n}" for c, n in comptes.items() if n)]
    if motifs:
        lignes.append("")
        lignes.append("Observations des membres :")
        lignes.extend(motifs)

    dossier_session.avis_global = majoritaire
    dossier_session.synthese = "\n".join(lignes)
    return dossier_session


def clore_seance(session, acteur):
    if acteur.role_systeme not in ("chef_service_amm", "administrateur_dpml"):
        raise ErreurWorkflow("Seul le chef de service clôt une séance.")
    if session.statut == "close":
        raise ErreurWorkflow("Cette séance est déjà close.")
    for ds in session.inscriptions:
        synthetiser(ds)
    # Le procès-verbal doit porter mention des déports constatés.
    import dpi
    session.mention_deports = dpi.mention_proces_verbal(session)
    session.statut = "close"
    session.date_cloture = datetime.utcnow()
    enregistrer_audit(session, f"Séance {session.numero} close — avis synthétisés", acteur)
    notifier(session.convoquee_par, "commission_close",
             f"La séance {session.numero} est close ; les avis ont été synthétisés.",
             lien=f"/instruction/commissions/{session.id}")
    return session


# ---------------------------------------------------------------------------
# 4. Rapport du chef de service → circuit de signature
# ---------------------------------------------------------------------------
def rediger_rapport(dossier, acteur, avis_propose, synthese=None, motif=None):
    """Consolide l'instruction et ouvre le circuit de signature."""
    if acteur.role_systeme not in ("chef_service_amm", "administrateur_dpml"):
        raise ErreurWorkflow("Seul le chef de service rédige ce rapport.")
    if dossier.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Le dossier doit être en évaluation.")
    if avis_propose not in AVIS:
        raise ErreurWorkflow("Avis inconnu.")
    if avis_propose != "favorable" and not (motif or "").strip():
        raise ErreurWorkflow(
            "Un avis défavorable ou un complément de dossier doit être motivé.")
    if RapportInstruction.query.filter_by(dossier_id=dossier.id).first():
        raise ErreurWorkflow("Un rapport a déjà été transmis pour ce dossier.")

    r = RapportInstruction(dossier_id=dossier.id, redige_par_id=acteur.id,
                           avis_propose=avis_propose,
                           motif=(motif or "").strip() or None,
                           synthese=(synthese or "").strip() or None)
    db.session.add(r)
    db.session.flush()
    enregistrer_audit(dossier,
                      f"Rapport d'instruction transmis à la direction ({AVIS[avis_propose]})",
                      acteur)

    # Un complément de dossier retourne au déposant sans mobiliser la direction.
    if avis_propose == "complement_requis":
        from delais import get_parametre
        ancien = dossier.statut
        dossier.statut = "complement_requis"
        jours = int(get_parametre("MA", "delai_reponse_complement_jours", default=90))
        dossier.date_limite_reponse_complement = datetime.utcnow() + timedelta(days=jours)
        # Clock Stop : le temps de réponse du demandeur ne s'impute pas sur le
        # délai de l'administration.
        import suivi
        try:
            suivi.suspendre_delai(dossier, acteur,
                                  motif="complément de dossier demandé")
        except ErreurWorkflow:
            pass          # le délai n'avait pas démarré : rien à suspendre
        enregistrer_audit(dossier, "Complément de dossier demandé au déposant", acteur,
                          ancien, dossier.statut)
        if dossier.demandeur:
            notifier(dossier.demandeur, "complement_requis",
                     f"Un complément est requis sur le dossier {dossier.numero} : "
                     f"{r.motif}. Délai de réponse : {jours} jours.",
                     lien=f"/dossiers/{dossier.id}")
        return r

    # Avis favorable ou défavorable : la direction est saisie par le circuit.
    import validation_numerique as vn
    vn.ouvrir_circuit(dossier, "amm", acteur,
                      lien=f"/validation/DossierAMM/{dossier.id}")
    return r


# ---------------------------------------------------------------------------
# Vue d'ensemble d'un dossier en instruction
# ---------------------------------------------------------------------------
def etat_instruction(dossier):
    assignations = AssignationEvaluation.query.filter_by(dossier_id=dossier.id).all()
    inscriptions = DossierSession.query.filter_by(dossier_id=dossier.id).all()
    rapport = RapportInstruction.query.filter_by(dossier_id=dossier.id).first()
    return {
        "assignations": assignations,
        "evaluations_remises": sum(1 for a in assignations if a.statut == "terminee"),
        "inscriptions": inscriptions,
        "rapport": rapport,
        "points_manquants": points_manquants(dossier),
    }
