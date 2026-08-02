"""
Paramètres configurables et vérification des délais réglementaires
(02-regles-transversales.md, section 7 ; 11-MA §3.1-3.2 et §8).

Tout délai (délai de réponse à un complément, durée de validité d'une AMM,
échéances de rappel de renouvellement) est un paramètre configurable par
l'administrateur, avec une valeur par défaut — jamais une constante codée en
dur sans être signalée comme telle.

LIMITE ASSUMÉE (documentée dans README.md) : pas de vrai scheduler (pas de
Celery/cron) dans ce périmètre. executer_verifications_delais() est appelée à
chaque accès au dashboard et au registre des dossiers — ce qui suffit pour un
usage interne à faible fréquence de connexion, conformément à la mention du
cahier des charges ("job/vérification exécutée par ex. à chaque accès au
dashboard"). La fonction est idempotente : elle peut être appelée plusieurs
fois sans effet de bord, grâce aux gardes de statut et aux vérifications
anti-doublon sur les notifications déjà émises.
"""
from datetime import date, datetime, timedelta

from models import (db, ParametreModule, DossierAMM, Produit, Personne, Notification, NotificationVigilance,
                     Inspection, Etablissement)
from notifications import notifier, notifier_tous

DEFAUTS_MA = {
    "delai_reponse_complement_jours": (
        "90", "Délai (jours) laissé au demandeur pour répondre à une demande de "
        "complément avant clôture automatique du dossier."),
    "duree_validite_amm_annees": (
        "5", "Durée de validité (années) d'une AMM approuvée."),
    "rappel_renouvellement_j_avant": (
        "180,90,30", "Jours avant expiration d'une AMM active où un rappel de "
        "renouvellement est notifié au titulaire (liste séparée par des virgules)."),
    "rappel_complement_j_avant_cloture": (
        "15", "Jours avant clôture automatique où un rappel est notifié au demandeur."),
    "frais_nouvelle_demande_xaf": (
        "500000", "Frais (XAF) exigés pour une nouvelle demande d'AMM (octroi)."),
    "frais_renouvellement_xaf": (
        "300000", "Frais (XAF) exigés pour un renouvellement d'AMM."),
    "frais_variation_xaf": (
        "150000", "Frais (XAF) exigés pour une variation d'AMM."),
    "delai_retrait_document_jours": (
        "10", "Délai (jours calendaires) à partir de la décision favorable pendant lequel le "
        "document physique (certificat AMM) peut être retiré auprès de la DPML."),
}

DEFAUTS_VL = {
    "delai_traitement_grave_jours": (
        "15", "Délai (jours) au-delà duquel un cas grave ou fatal non traité (statut toujours "
        "« reçue ») déclenche une alerte auprès des agents de pharmacovigilance."),
}

DEFAUTS_RI = {
    "seuil_conformite_pourcent": (
        "80", "Score de conformité (%) à partir duquel une inspection est proposée comme "
        "conforme — reste une aide à la décision, jamais une bascule automatique."),
}

DEFAUTS_LI = {
    "duree_validite_licence_annees": (
        "3", "Durée de validité (années) d'une licence d'établissement octroyée."),
    "rappel_expiration_j_avant": (
        "90,30", "Jours avant expiration d'une licence active où un rappel de renouvellement "
        "est notifié au titulaire (liste séparée par des virgules)."),
    "frais_dossier_xaf": (
        "150000", "Frais (XAF) exigés pour le traitement d'une demande de licence."),
}

DEFAUTS_MC = {
    "delai_relance_confirmation_jours": (
        "10", "Délai (jours) au-delà duquel un établissement notifié d'un rappel sans "
        "confirmation de retrait déclenche une relance auprès de l'agent de surveillance."),
}

DEFAUTS_CT = {
    "delai_reponse_complement_jours": (
        "60", "Délai (jours) laissé au promoteur pour répondre à une demande de complément "
        "avant clôture automatique du protocole."),
    "rappel_rapport_etape_j_avant": (
        "15", "Jours avant l'échéance d'un rapport d'étape où un rappel est notifié au "
        "promoteur et à l'agent DROS."),
    "duree_validite_annees": (
        "3", "Durée de validité (années) de l'autorisation d'un protocole d'essai clinique."),
}


def get_parametre(module, cle, default=None):
    p = ParametreModule.query.filter_by(module=module, cle=cle).first()
    return p.valeur if p else default


def initialiser_parametres_defaut():
    """Appelée par seed.py : crée les ParametreModule MA, VL et RI s'ils n'existent pas déjà."""
    for module, defauts in (("MA", DEFAUTS_MA), ("VL", DEFAUTS_VL), ("RI", DEFAUTS_RI), ("LI", DEFAUTS_LI),
                             ("MC", DEFAUTS_MC), ("CT", DEFAUTS_CT)):
        for cle, (valeur, description) in defauts.items():
            if not ParametreModule.query.filter_by(module=module, cle=cle).first():
                db.session.add(ParametreModule(module=module, cle=cle, valeur=valeur, description=description))
    db.session.commit()


def executer_verifications_delais():
    # Import différé pour éviter un import circulaire (workflow_ma importe get_parametre
    # depuis ce module ; ce module a besoin de la transition de clôture de workflow_ma).
    from workflow_ma import cloturer_si_delai_depasse

    # 1. Clôture automatique des compléments en retard (critère d'acceptation MA #3).
    for d in DossierAMM.query.filter_by(statut="complement_requis").all():
        cloturer_si_delai_depasse(d)

    # 2. Rappel à J-N avant clôture (une notification par dossier, garde anti-doublon).
    rappel_jours = int(get_parametre("MA", "rappel_complement_j_avant_cloture", default=15))
    seuil = datetime.utcnow() + timedelta(days=rappel_jours)
    for d in DossierAMM.query.filter_by(statut="complement_requis") \
            .filter(DossierAMM.date_limite_reponse_complement.isnot(None)) \
            .filter(DossierAMM.date_limite_reponse_complement <= seuil).all():
        deja_notifie = Notification.query.filter_by(
            destinataire_id=d.demandeur_id, type="rappel_complement"
        ).filter(Notification.contenu.contains(d.numero or f"dossier #{d.id}")).first()
        if not deja_notifie:
            notifier(d.demandeur, "rappel_complement",
                     f"Rappel : il vous reste {rappel_jours} jours ou moins pour répondre "
                     f"au complément demandé sur le dossier {d.numero}.",
                     lien=f"/dossiers/{d.id}")

    # 3. Rappels de renouvellement d'AMM active à J-180/J-90/J-30 (configurable).
    jours_liste = sorted(
        (int(j) for j in get_parametre("MA", "rappel_renouvellement_j_avant", default="180,90,30").split(",")),
        reverse=True,
    )
    for p in Produit.query.filter_by(statut_amm_courant="active").all():
        dernier_approuve = (
            DossierAMM.query.filter_by(produit_id=p.id, statut="approuve")
            .order_by(DossierAMM.date_decision.desc()).first()
        )
        if not dernier_approuve or not dernier_approuve.date_validite_amm:
            continue
        jours_restants = (dernier_approuve.date_validite_amm - date.today()).days
        if jours_restants < 0:
            continue
        seuil_declenche = next((j for j in jours_liste if jours_restants <= j), None)
        if seuil_declenche is None:
            continue
        type_notif = f"renouvellement_j{seuil_declenche}"
        destinataires = Personne.query.filter_by(
            etablissement_rattachement_id=p.titulaire_amm_id, role_systeme="demandeur_externe"
        ).all()
        for dest in destinataires:
            deja = Notification.query.filter_by(destinataire_id=dest.id, type=type_notif) \
                .filter(Notification.contenu.contains(f"produit #{p.id}")).first()
            if not deja:
                notifier(dest, type_notif,
                         f"L'AMM du produit {p.libelle} (produit #{p.id}) expire le "
                         f"{dernier_approuve.date_validite_amm.strftime('%d/%m/%Y')} "
                         f"({jours_restants} jours restants). Pensez à engager le renouvellement.",
                         lien=f"/dossiers/{dernier_approuve.id}")
    db.session.commit()


def cas_vigilance_en_retard(cas):
    """Un cas grave/fatal encore au statut `recue` au-delà du délai configuré (12-VL §8).
    Fonction pure, réutilisée par le registre pour la mise en évidence visuelle ET par
    la vérification de délais ci-dessous — pas de duplication du calcul."""
    if cas.statut != "recue" or cas.gravite not in ("grave", "fatal"):
        return False
    delai = int(get_parametre("VL", "delai_traitement_grave_jours", default=15))
    return (datetime.utcnow() - cas.date_notification).days > delai


def executer_verifications_delais_vl():
    """Alerte les agents de vigilance (et l'administrateur) sur les cas grave/fatal non
    traités au-delà du délai réglementaire configuré. Même limite assumée que pour MA :
    pas de vrai scheduler, vérification à chaque accès au tableau de bord/registre VL."""
    for cas in NotificationVigilance.query.filter_by(statut="recue").all():
        if not cas_vigilance_en_retard(cas):
            continue
        deja_alerte = Notification.query.filter_by(type="vl_delai_depasse") \
            .filter(Notification.contenu.contains(cas.numero)).first()
        if deja_alerte:
            continue
        notifier_tous("agent_vigilance", "vl_delai_depasse",
                       f"Cas {cas.numero} ({cas.gravite_label}) non traité au-delà du délai réglementaire.",
                       lien=f"/vigilance/cas/{cas.id}")
        notifier_tous("administrateur_dpml", "vl_delai_depasse",
                       f"Cas {cas.numero} ({cas.gravite_label}) non traité au-delà du délai réglementaire.",
                       lien=f"/vigilance/cas/{cas.id}")
    db.session.commit()


def plan_action_en_retard(inspection):
    """Un plan d'action dont l'échéance est dépassée sans que l'inspection ait été
    clôturée ou suivie (13-RI §6 « Suivi des plans d'action »)."""
    if inspection.statut != "plan_action_en_cours" or not inspection.date_echeance_plan_action:
        return False
    return date.today() > inspection.date_echeance_plan_action


def executer_verifications_delais_ri():
    """Alerte l'administrateur sur les plans d'action dont l'échéance est dépassée.
    Même limite assumée que MA/VL : vérification à chaque accès, pas de scheduler réel."""
    for insp in Inspection.query.filter_by(statut="plan_action_en_cours").all():
        if not plan_action_en_retard(insp):
            continue
        deja_alerte = Notification.query.filter_by(type="ri_echeance_depassee") \
            .filter(Notification.contenu.contains(insp.numero)).first()
        if deja_alerte:
            continue
        notifier_tous("administrateur_dpml", "ri_echeance_depassee",
                       f"Échéance du plan d'action dépassée pour l'inspection {insp.numero} "
                       f"({insp.etablissement.raison_sociale}).",
                       lien=f"/inspections/{insp.id}")
    db.session.commit()


def executer_verifications_delais_li():
    """Expiration automatique des licences échues (critère d'acceptation LI #1) et
    rappels de renouvellement à J-90/J-30. Même limite assumée : vérification à
    chaque accès, pas de vrai scheduler."""
    from workflow_li import expirer_si_echue  # import différé, cf. note dans workflow_ma/delais

    for etab in Etablissement.query.filter_by(statut_licence="active").all():
        expirer_si_echue(etab)

    jours_liste = [int(j) for j in get_parametre("LI", "rappel_expiration_j_avant", default="90,30").split(",")]
    for etab in Etablissement.query.filter_by(statut_licence="active").all():
        if not etab.date_expiration_licence:
            continue
        jours_restants = (etab.date_expiration_licence - date.today()).days
        if jours_restants < 0:
            continue
        seuil = next((j for j in sorted(jours_liste, reverse=True) if jours_restants <= j), None)
        if seuil is None:
            continue
        type_notif = f"li_rappel_j{seuil}"
        destinataires = Personne.query.filter_by(etablissement_rattachement_id=etab.id,
                                                   role_systeme="demandeur_externe").all()
        for dest in destinataires:
            deja = Notification.query.filter_by(destinataire_id=dest.id, type=type_notif) \
                .filter(Notification.contenu.contains(f"établissement #{etab.id}")).first()
            if not deja:
                notifier(dest, type_notif,
                         f"La licence de {etab.raison_sociale} (établissement #{etab.id}) expire le "
                         f"{etab.date_expiration_licence.strftime('%d/%m/%Y')} ({jours_restants} jours "
                         "restants). Pensez à engager le renouvellement.",
                         lien=f"/etablissements/{etab.id}")
    db.session.commit()


def executer_verifications_delais_mc():
    """Relance des établissements notifiés d'un rappel sans confirmation de retrait
    au-delà du délai configuré (§8 : « relance nécessaire »)."""
    from models import SignalementQualite, RappelStatutEtablissement
    delai = int(get_parametre("MC", "delai_relance_confirmation_jours", default=10))
    seuil = datetime.utcnow() - timedelta(days=delai)
    for sig in SignalementQualite.query.filter(SignalementQualite.statut.in_(("notifie", "suivi"))).all():
        for rappel in sig.statuts_etablissements.filter_by(statut="notifie").all():
            if sig.date_maj > seuil:
                continue
            deja = Notification.query.filter_by(type="mc_relance") \
                .filter(Notification.contenu.contains(sig.numero)).filter(
                    Notification.contenu.contains(rappel.etablissement.raison_sociale)).first()
            if deja:
                continue
            notifier_tous("agent_surveillance_marche", "mc_relance",
                          f"Relance nécessaire : {rappel.etablissement.raison_sociale} n'a pas confirmé le "
                          f"retrait du rappel {sig.numero}.", lien=f"/signalements/{sig.id}")
    db.session.commit()


def executer_verifications_delais_ct():
    """Clôture automatique des protocoles en complément non répondu au-delà du délai
    configuré, et rappel avant l'échéance d'un rapport d'étape attendu."""
    from workflow_ct import cloturer_si_delai_depasse
    from models import ProtocoleEssaiClinique

    for protocole in ProtocoleEssaiClinique.query.filter_by(statut="complement_requis").all():
        cloturer_si_delai_depasse(protocole)

    rappel_jours = int(get_parametre("CT", "rappel_rapport_etape_j_avant", default=15))
    for protocole in ProtocoleEssaiClinique.query.filter_by(statut="autorise").all():
        for rapport in protocole.rapports_etape:
            if rapport.get("statut") != "attendu":
                continue
            try:
                echeance = datetime.strptime(rapport["echeance"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            jours_restants = (echeance - date.today()).days
            if jours_restants < 0:
                type_notif, message = "ct_rapport_en_retard", (
                    f"Rapport d'étape « {rapport.get('titre')} » du protocole {protocole.numero} "
                    "en retard (échéance dépassée).")
            elif jours_restants <= rappel_jours:
                type_notif, message = "ct_rapport_bientot_du", (
                    f"Rapport d'étape « {rapport.get('titre')} » du protocole {protocole.numero} "
                    f"attendu dans {jours_restants} jour(s).")
            else:
                continue
            deja = Notification.query.filter_by(type=type_notif) \
                .filter(Notification.contenu.contains(protocole.numero)) \
                .filter(Notification.contenu.contains(rapport.get("titre", ""))).first()
            if deja:
                continue
            notifier(protocole.promoteur, type_notif, message, lien=f"/protocoles/{protocole.id}")
            notifier_tous("agent_dros", type_notif, message, lien=f"/protocoles/{protocole.id}")
    db.session.commit()
