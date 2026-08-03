"""
Workflow du volet régional : consentements, requêtes, publications, alertes.

Toute la logique métier vit ici ; les routes n'orchestrent que l'affichage
(convention du projet, cf. README).
"""
from datetime import datetime

import reliance as ctr
from audit import enregistrer_audit, enregistrer_creation
from erreurs import ErreurWorkflow
from models import (AccordPartage, AlerteTransfrontaliere, DecisionPubliee,
                    MessageReliance, PaysCEEAC, RequeteReliance, db)
from notifications import notifier, notifier_tous
from numerotation import generer_numero


# ---------------------------------------------------------------------------
# Pays partenaires
# ---------------------------------------------------------------------------
def pays_partenaires():
    """Pays avec lesquels un échange est possible (hors instance courante)."""
    return (PaysCEEAC.query
            .filter(PaysCEEAC.code_iso != ctr.pays_instance(),
                    PaysCEEAC.dans_reliance.is_(True),
                    PaysCEEAC.statut != "retire")
            .order_by(PaysCEEAC.nom).all())


def _pays_valide(code):
    p = PaysCEEAC.query.filter_by(code_iso=code).first()
    if not p:
        raise ErreurWorkflow(f"Pays inconnu : {code}")
    if p.statut == "retire" or not p.dans_reliance:
        raise ErreurWorkflow(
            f"{p.nom} ne participe pas au réseau de reliance ({p.statut}).")
    return p


# ---------------------------------------------------------------------------
# File d'échange — résilience
# ---------------------------------------------------------------------------
def mettre_en_file(type_message, destinataire, payload,
                    confidentialite="publiable", consentement_ref=None):
    """Construit, signe et met en file. Le contrat refuse ici tout envoi interdit."""
    env = ctr.construire_enveloppe(type_message, destinataire, payload,
                                    confidentialite, consentement_ref)
    msg = MessageReliance(message_id=env["message_id"], sens="sortant",
                          type_message=type_message, destinataire=destinataire,
                          enveloppe=env, statut="en_file")
    db.session.add(msg)
    db.session.flush()
    return msg


def synchroniser(acteur=None, timeout=3.0):
    """Vide la file vers le Hub. Hub injoignable → tout reste en file."""
    resultat = {"transmis": [], "en_attente": [], "erreurs": []}
    en_file = MessageReliance.query.filter_by(sens="sortant", statut="en_file").all()

    if not ctr.hub_raccorde():
        resultat["en_attente"] = [m.message_id for m in en_file]
        resultat["hub_raccorde"] = False
        return resultat

    import requests
    routes = {"decision_publiee": "/registre/decisions", "alerte": "/alertes",
              "requete_reliance": "/routage", "reponse_reliance": "/routage"}
    for msg in en_file:
        chemin = routes.get(msg.type_message)
        if not chemin:
            msg.statut = "echec"
            msg.derniere_erreur = f"Type non routable : {msg.type_message}"
            resultat["erreurs"].append(msg.message_id)
            continue
        try:
            r = requests.post(ctr.url_hub() + chemin, json=msg.enveloppe, timeout=timeout)
            if r.status_code < 300:
                msg.statut = "transmis"
                msg.date_transmission = datetime.utcnow()
                resultat["transmis"].append(msg.message_id)
            else:
                msg.tentatives = (msg.tentatives or 0) + 1
                msg.derniere_erreur = f"HTTP {r.status_code} : {r.text[:200]}"
                resultat["erreurs"].append(msg.message_id)
        except Exception as e:                       # Hub injoignable : on conserve
            msg.tentatives = (msg.tentatives or 0) + 1
            msg.derniere_erreur = str(e)[:200]
            resultat["en_attente"].append(msg.message_id)
    db.session.commit()
    resultat["hub_raccorde"] = True
    return resultat


# ---------------------------------------------------------------------------
# Consentements (protection des ICC)
# ---------------------------------------------------------------------------
def accorder_partage(acteur, objet, pays_destinataire, portee="rapport_evaluation",
                      dossier_amm=None):
    _pays_valide(pays_destinataire)
    if portee not in ctr.PORTEES_ACCORD:
        raise ErreurWorkflow(f"Portée de partage inconnue : {portee}")
    accord = AccordPartage(
        numero=generer_numero("ACC"), objet=objet.strip(),
        dossier_amm_id=dossier_amm.id if dossier_amm else None,
        pays_destinataire=pays_destinataire, portee=portee, accorde_par_id=acteur.id)
    db.session.add(accord)
    db.session.flush()
    enregistrer_creation(
        accord, acteur,
        f"Consentement de partage accordé à {pays_destinataire} "
        f"({ctr.PORTEES_ACCORD[portee]})")
    return accord


def revoquer_partage(accord, acteur, motif):
    if accord.revoque:
        raise ErreurWorkflow("Ce consentement est déjà révoqué.")
    accord.revoque = True
    accord.motif_revocation = (motif or "").strip() or None
    accord.date_revocation = datetime.utcnow()
    enregistrer_audit(accord, f"Consentement de partage révoqué : {accord.motif_revocation or '—'}",
                      acteur, "actif", "revoque")
    return accord


# ---------------------------------------------------------------------------
# Consultation régionale
# ---------------------------------------------------------------------------
def consulter_registre(dci=None, produit=None, pays=None):
    """Ce produit est-il déjà homologué chez un pair ?

    Interroge le registre régional local (alimenté par le Hub) : reste
    utilisable même Hub injoignable.
    """
    q = DecisionPubliee.query.filter(DecisionPubliee.pays_origine != ctr.pays_instance())
    if pays:
        q = q.filter(DecisionPubliee.pays_origine == pays)
    if dci:
        q = q.filter(DecisionPubliee.dci.ilike(f"%{dci.strip()}%"))
    if produit:
        q = q.filter(DecisionPubliee.produit_nom.ilike(f"%{produit.strip()}%"))
    return q.order_by(DecisionPubliee.date_publication.desc()).all()


def produits_apparies(produit):
    """Décisions étrangères portant sur « le même produit » (clé pivot)."""
    cle = ctr.cle_pivot(produit.denomination_commune_internationale,
                        produit.forme_pharmaceutique, produit.dosage)
    if not cle:
        return []
    return (DecisionPubliee.query
            .filter(DecisionPubliee.cle_pivot == cle,
                    DecisionPubliee.pays_origine != ctr.pays_instance())
            .order_by(DecisionPubliee.date_publication.desc()).all())


# ---------------------------------------------------------------------------
# Requêtes formelles
# ---------------------------------------------------------------------------
def creer_requete(acteur, pays_partenaire, objet, type_requete="rapport_evaluation",
                   produit=None, delai_jours=30):
    _pays_valide(pays_partenaire)
    if type_requete not in ctr.TYPES_REQUETE:
        raise ErreurWorkflow(f"Type de requête inconnu : {type_requete}")
    req = RequeteReliance(
        numero=generer_numero("REL"), sens="sortante", pays_partenaire=pays_partenaire,
        type_requete=type_requete, objet=objet.strip(),
        produit_id=produit.id if produit else None, statut="brouillon",
        demandeur_id=acteur.id, delai_jours=delai_jours)
    db.session.add(req)
    db.session.flush()
    enregistrer_creation(req, acteur,
                         f"Requête de reliance créée à destination de {pays_partenaire}")
    return req


def transmettre_requete(requete, acteur):
    if requete.sens != "sortante":
        raise ErreurWorkflow("Seule une requête sortante peut être transmise.")
    if requete.statut != "brouillon":
        raise ErreurWorkflow("Cette requête a déjà été transmise.")
    # Une requête ne contient qu'une demande : donnée publiable.
    mettre_en_file("requete_reliance", requete.pays_partenaire,
                   {"numero": requete.numero, "type": requete.type_requete,
                    "objet": requete.objet, "delai_jours": requete.delai_jours},
                   confidentialite="publiable")
    ancien = requete.statut
    requete.statut = "transmise"
    requete.date_transmission = datetime.utcnow()
    enregistrer_audit(requete, f"Requête transmise à {requete.pays_partenaire}",
                      acteur, ancien, requete.statut)
    return requete


def repondre_requete(requete, acteur, contenu, accord=None):
    """Répond à une requête entrante.

    Un rapport d'évaluation ne peut sortir qu'avec un consentement actif : la
    protection des informations commerciales confidentielles est vérifiée ici,
    puis à nouveau par le contrat au moment de construire l'enveloppe.
    """
    if requete.sens != "entrante":
        raise ErreurWorkflow("Seule une requête entrante appelle une réponse.")
    if requete.statut not in ("recue", "transmise"):
        raise ErreurWorkflow(f"Requête non répondable dans l'état « {requete.statut} ».")

    exige_accord = requete.type_requete in ("rapport_evaluation",)
    if exige_accord:
        if accord is None:
            raise ErreurWorkflow(
                "Consentement requis : établissez un accord de partage avant de "
                "transmettre un rapport d'évaluation (protection des ICC).")
        if accord.revoque:
            raise ErreurWorkflow("Cet accord de partage a été révoqué — transmission refusée.")
        if accord.pays_destinataire != requete.pays_partenaire:
            raise ErreurWorkflow(
                f"L'accord vise {accord.pays_destinataire}, la requête vient de "
                f"{requete.pays_partenaire} — transmission refusée.")

    mettre_en_file(
        "reponse_reliance", requete.pays_partenaire,
        {"requete": requete.numero, "contenu": contenu},
        confidentialite="partageable_sous_accord" if exige_accord else "publiable",
        consentement_ref=accord.numero if accord else None)

    ancien = requete.statut
    requete.statut = "repondue"
    requete.reponse = contenu
    requete.accord_id = accord.id if accord else None
    requete.date_reponse = datetime.utcnow()
    enregistrer_audit(
        requete,
        f"Réponse transmise à {requete.pays_partenaire}"
        + (f" sous accord {accord.numero}" if accord else ""),
        acteur, ancien, requete.statut)
    return requete


def refuser_requete(requete, acteur, motif):
    if requete.sens != "entrante":
        raise ErreurWorkflow("Seule une requête entrante peut être refusée.")
    if not (motif or "").strip():
        raise ErreurWorkflow("Un refus doit être motivé.")
    ancien = requete.statut
    requete.statut = "refusee"
    requete.motif_refus = motif.strip()
    requete.date_reponse = datetime.utcnow()
    mettre_en_file("reponse_reliance", requete.pays_partenaire,
                   {"requete": requete.numero, "refus": requete.motif_refus},
                   confidentialite="publiable")
    enregistrer_audit(requete, f"Requête refusée : {requete.motif_refus}",
                      acteur, ancien, requete.statut)
    return requete


# ---------------------------------------------------------------------------
# Publication au registre régional
# ---------------------------------------------------------------------------
def publier_decision(dossier, acteur, resume="", rapport_partageable=False):
    """Publie une décision d'AMM au registre régional (donnée publiable).

    Ne publie que le fait de la décision : jamais une pièce du dossier.
    """
    if dossier.statut not in ("amm_octroyee", "octroye", "autorise"):
        raise ErreurWorkflow(
            "Seule une AMM octroyée peut être publiée au registre régional "
            f"(statut actuel : {dossier.statut}).")
    produit = dossier.produit
    deja = DecisionPubliee.query.filter_by(
        dossier_amm_id=dossier.id, pays_origine=ctr.pays_instance()).first()
    if deja:
        raise ErreurWorkflow("Cette décision est déjà publiée au registre régional.")

    dec = DecisionPubliee(
        pays_origine=ctr.pays_instance(),
        produit_nom=produit.nom_commercial or produit.libelle,
        dci=produit.denomination_commune_internationale,
        forme=produit.forme_pharmaceutique, dosage=produit.dosage,
        titulaire=produit.titulaire_amm.raison_sociale if produit.titulaire_amm else None,
        cle_pivot=ctr.cle_pivot(produit.denomination_commune_internationale,
                                produit.forme_pharmaceutique, produit.dosage),
        type_decision="amm", reference_nationale=dossier.numero,
        resume=(resume or "").strip() or None,
        rapport_partageable=bool(rapport_partageable),
        dossier_amm_id=dossier.id, date_decision=datetime.utcnow())
    db.session.add(dec)
    db.session.flush()

    msg = mettre_en_file("decision_publiee", "REGIONAL", {
        "produit_nom": dec.produit_nom, "dci": dec.dci, "forme": dec.forme,
        "dosage": dec.dosage, "titulaire": dec.titulaire, "cle_pivot": dec.cle_pivot,
        "type_decision": dec.type_decision, "reference": dec.reference_nationale,
        "resume": dec.resume, "rapport_partageable": dec.rapport_partageable,
    }, confidentialite="publiable")
    dec.signature = msg.enveloppe["signature"][:200]

    enregistrer_creation(dec, acteur,
                         f"Décision {dossier.numero} publiée au registre régional CEEAC")
    return dec


# ---------------------------------------------------------------------------
# Alertes transfrontalières
# ---------------------------------------------------------------------------
def emettre_alerte(acteur, type_alerte, produit_nom, message, numero_lot=None,
                    niveau_risque=None, signalement=None):
    """Diffuse une alerte à toutes les ARN du réseau."""
    if type_alerte not in ctr.TYPES_ALERTE:
        raise ErreurWorkflow(f"Type d'alerte inconnu : {type_alerte}")
    if not (message or "").strip():
        raise ErreurWorkflow("Le message de l'alerte est obligatoire.")

    alerte = AlerteTransfrontaliere(
        numero=generer_numero("ALR"), sens="emise", pays_emetteur=ctr.pays_instance(),
        type_alerte=type_alerte, produit_nom=produit_nom.strip(),
        numero_lot=(numero_lot or "").strip() or None, niveau_risque=niveau_risque,
        message=message.strip(),
        signalement_id=signalement.id if signalement else None)
    db.session.add(alerte)
    db.session.flush()

    msg = mettre_en_file("alerte", "REGIONAL", {
        "numero": alerte.numero, "type_alerte": type_alerte,
        "produit_nom": alerte.produit_nom, "numero_lot": alerte.numero_lot,
        "niveau_risque": niveau_risque, "message": alerte.message,
    }, confidentialite="publiable")
    alerte.signature = msg.enveloppe["signature"][:200]

    enregistrer_creation(
        alerte, acteur,
        f"Alerte transfrontalière émise ({ctr.TYPES_ALERTE[type_alerte]}) "
        f"vers les ARN de la CEEAC")
    return alerte


def accuser_reception_alerte(alerte, acteur):
    if alerte.sens != "recue":
        raise ErreurWorkflow("Seule une alerte reçue appelle un accusé de réception.")
    if alerte.accuse_le:
        return alerte
    alerte.accuse_le = datetime.utcnow()
    enregistrer_audit(alerte, "Accusé de réception de l'alerte transfrontalière", acteur)
    return alerte


def marquer_alerte_traitee(alerte, acteur):
    if alerte.sens != "recue":
        raise ErreurWorkflow("Seule une alerte reçue se clôture ainsi.")
    alerte.traitee = True
    if not alerte.accuse_le:
        alerte.accuse_le = datetime.utcnow()
    enregistrer_audit(alerte, "Alerte transfrontalière traitée au niveau national", acteur)
    return alerte


# ---------------------------------------------------------------------------
# Réception (messages entrants relevés auprès du Hub)
# ---------------------------------------------------------------------------
def traiter_message_entrant(env):
    """Applique une enveloppe entrante après vérification du contrat.

    Idempotent : un message déjà reçu est ignoré.
    """
    ctr.valider_enveloppe_entrante(env)
    if MessageReliance.query.filter_by(message_id=env["message_id"]).first():
        return None                                   # déjà traité

    db.session.add(MessageReliance(
        message_id=env["message_id"], sens="entrant", type_message=env["type"],
        destinataire=ctr.pays_instance(), enveloppe=env, statut="recu"))
    p = env.get("payload") or {}
    emetteur = env["emetteur"]
    cree = None

    if env["type"] == "requete_reliance":
        cree = RequeteReliance(
            numero=generer_numero("REL"), sens="entrante", pays_partenaire=emetteur,
            type_requete=p.get("type", "rapport_evaluation"),
            objet=p.get("objet", "(sans objet)"), statut="recue",
            delai_jours=p.get("delai_jours", 30))
        db.session.add(cree)
        notifier_tous("administrateur_dpml", "reliance_requete_entrante",
                      f"Requête de reliance reçue de {emetteur} : {cree.objet[:80]}",
                      lien="/reliance/requetes")

    elif env["type"] == "alerte":
        cree = AlerteTransfrontaliere(
            numero=generer_numero("ALR"), sens="recue", pays_emetteur=emetteur,
            type_alerte=p.get("type_alerte", "rappel_lot"),
            produit_nom=p.get("produit_nom", "(produit non précisé)"),
            numero_lot=p.get("numero_lot"), niveau_risque=p.get("niveau_risque"),
            message=p.get("message", ""), signature=env["signature"][:200])
        db.session.add(cree)
        for role in ("administrateur_dpml", "agent_surveillance_marche"):
            notifier_tous(role, "reliance_alerte_entrante",
                          f"Alerte {ctr.TYPES_ALERTE.get(cree.type_alerte, cree.type_alerte)} "
                          f"reçue de {emetteur} — {cree.produit_nom}",
                          lien="/reliance/alertes")

    elif env["type"] == "decision_publiee":
        cree = DecisionPubliee(
            pays_origine=emetteur, produit_nom=p.get("produit_nom", ""),
            dci=p.get("dci"), forme=p.get("forme"), dosage=p.get("dosage"),
            titulaire=p.get("titulaire"), cle_pivot=p.get("cle_pivot"),
            type_decision=p.get("type_decision", "amm"),
            reference_nationale=p.get("reference"), resume=p.get("resume"),
            rapport_partageable=bool(p.get("rapport_partageable")),
            signature=env["signature"][:200])
        db.session.add(cree)

    elif env["type"] == "reponse_reliance":
        req = RequeteReliance.query.filter_by(numero=p.get("requete"),
                                              sens="sortante").first()
        if req:
            req.statut = "refusee" if p.get("refus") else "repondue"
            req.reponse = p.get("contenu")
            req.motif_refus = p.get("refus")
            req.date_reponse = datetime.utcnow()
            if req.demandeur:
                notifier(req.demandeur, "reliance_reponse",
                         f"Réponse reçue de {emetteur} pour la requête {req.numero}.",
                         lien="/reliance/requetes")
            cree = req

    db.session.commit()
    return cree
