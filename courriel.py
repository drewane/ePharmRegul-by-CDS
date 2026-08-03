"""
Envoi des notifications par courriel.

Une notification dans l'application ne suffit pas : un industriel ne se
connecte pas tous les jours, et certaines échéances sont contraignantes. Les
messages importants partent donc aussi par courriel.

RACCORDEMENT
------------
    SIREPH_SMTP_HOTE        serveur SMTP (ex. smtp.gmail.com)
    SIREPH_SMTP_PORT        587 par défaut
    SIREPH_SMTP_UTILISATEUR identifiant
    SIREPH_SMTP_MOTDEPASSE  mot de passe ou jeton d'application
    SIREPH_SMTP_EXPEDITEUR  adresse d'expédition affichée
    SIREPH_SMTP_TLS         "1" (défaut) pour STARTTLS

Sans configuration SMTP, les courriels sont ÉCRITS DANS UN JOURNAL plutôt
qu'envoyés : l'application reste utilisable en démonstration, et personne ne
croit à tort qu'un message est parti. Le journal est consultable par
l'administrateur, ce qui permet de vérifier ce qui aurait été adressé.
"""
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

from models import CourrielSortant, db

# Types de notification qui justifient un courriel. Tout n'a pas à sortir de
# l'application : on n'inonde pas la boîte du destinataire.
TYPES_A_ENVOYER = {
    # Suivi d'un dossier par son déposant
    "dossier_receptionne": "Accusé de réception de votre dossier",
    "dossier_recevable": "Votre dossier est recevable et en cours d'évaluation",
    "dossier_irrecevable": "Votre dossier a été déclaré irrecevable",
    "complement_requis": "Un complément est requis sur votre dossier",
    "amm_octroyee": "Votre autorisation de mise sur le marché a été signée",
    "document_signe": "Votre document a été signé",
    "demande_receptionnee": "Accusé de réception de votre demande",
    "din_decision": "Décision sur votre demande d'inspection",
    "din_planifiee": "Votre inspection a été planifiée",
    # Paiements
    "paiement_attendu": "Frais à régler",
    "paiement_confirme": "Votre paiement a été confirmé",
    "paiement_echoue": "Votre paiement n'a pas abouti",
    # Instruction et signature
    "dossier_assigne": "Un dossier vous est confié pour évaluation",
    "validation_attendue": "Votre validation est attendue",
    "commission_convoquee": "Convocation à une séance de commission",
    "compte_a_valider": "Une inscription attend votre validation",
}

SUJET_DEFAUT = "Notification SIREPH"


def _configure():
    return bool(os.getenv("SIREPH_SMTP_HOTE") and os.getenv("SIREPH_SMTP_UTILISATEUR"))


def _expediteur():
    return (os.getenv("SIREPH_SMTP_EXPEDITEUR")
            or os.getenv("SIREPH_SMTP_UTILISATEUR")
            or "no-reply@sireph.local")


def _corps(destinataire, contenu, lien):
    base = os.getenv("SIREPH_URL_PUBLIQUE", "http://localhost:5000").rstrip("/")
    lignes = [
        f"Bonjour {destinataire.nom_complet},",
        "",
        contenu,
    ]
    if lien:
        lignes += ["", f"Consulter : {base}{lien}"]
    lignes += [
        "",
        "—",
        "SIREPH — Système Intégré de Régulation Pharmaceutique",
        "Direction de la Pharmacie, du Médicament et des Laboratoires",
        "Ce message est automatique ; merci de ne pas y répondre.",
    ]
    return "\n".join(lignes)


def envoyer(destinataire, type_notif, contenu, lien=None):
    """Prépare et envoie un courriel. Retourne le CourrielSortant créé, ou None.

    Un échec d'envoi n'interrompt jamais le traitement métier : le dossier ne
    doit pas rester bloqué parce qu'un serveur de messagerie est indisponible.
    L'échec est consigné et le message reste rejouable.
    """
    if type_notif not in TYPES_A_ENVOYER:
        return None
    adresse = (getattr(destinataire, "email", "") or "").strip()
    if not adresse:
        return None

    sujet = f"[SIREPH] {TYPES_A_ENVOYER[type_notif]}"
    corps = _corps(destinataire, contenu, lien)
    courriel = CourrielSortant(
        destinataire_id=getattr(destinataire, "id", None), adresse=adresse,
        sujet=sujet, corps=corps, type_notification=type_notif,
        statut="journalise" if not _configure() else "en_attente")
    db.session.add(courriel)

    if not _configure():
        # Mode démonstration : rien n'est envoyé, et cela se voit.
        return courriel

    try:
        message = EmailMessage()
        message["Subject"] = sujet
        message["From"] = _expediteur()
        message["To"] = adresse
        message.set_content(corps)

        hote = os.environ["SIREPH_SMTP_HOTE"]
        port = int(os.getenv("SIREPH_SMTP_PORT", "587"))
        with smtplib.SMTP(hote, port, timeout=15) as serveur:
            if os.getenv("SIREPH_SMTP_TLS", "1") == "1":
                serveur.starttls(context=ssl.create_default_context())
            serveur.login(os.environ["SIREPH_SMTP_UTILISATEUR"],
                          os.environ["SIREPH_SMTP_MOTDEPASSE"])
            serveur.send_message(message)
        courriel.statut = "envoye"
        courriel.date_envoi = datetime.utcnow()
    except Exception as e:                                # noqa: BLE001
        courriel.statut = "echec"
        courriel.erreur = str(e)[:400]
    return courriel


def rejouer_echecs(limite=50):
    """Réexpédie les courriels en échec — utile après un incident de messagerie."""
    if not _configure():
        return {"rejoues": 0, "smtp_configure": False}
    from models import Personne

    rejoues = 0
    for c in (CourrielSortant.query.filter_by(statut="echec")
              .order_by(CourrielSortant.id).limit(limite).all()):
        destinataire = (db.session.get(Personne, c.destinataire_id)
                        if c.destinataire_id else None)
        if destinataire is None:
            continue
        nouveau = envoyer(destinataire, c.type_notification, c.corps, None)
        if nouveau is not None and nouveau.statut == "envoye":
            c.statut = "rejoue"
            rejoues += 1
    db.session.commit()
    return {"rejoues": rejoues, "smtp_configure": True}


def etat():
    """État du service, pour l'écran d'administration."""
    return {
        "configure": _configure(),
        "hote": os.getenv("SIREPH_SMTP_HOTE", "—"),
        "expediteur": _expediteur(),
        "types_couverts": len(TYPES_A_ENVOYER),
    }
