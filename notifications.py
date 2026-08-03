"""
Notifications (02-regles-transversales.md, section 4) : évènement déclencheur →
règle → destinataire(s) → canal. Canal in-app uniquement dans ce périmètre
(email/SMS = choix d'implémentation futur). Persistées en base, consultables et
marquables lues par l'utilisateur — jamais un simple message éphémère.

Appelées exclusivement depuis workflow_ma.py (ou delais.py pour les évènements
déclenchés par une vérification de délai), jamais directement depuis app.py, afin
de garder la logique "évènement → notification" à un seul endroit.
"""
from models import db, Personne, Notification


def notifier(destinataire, type_notif, contenu, lien=None):
    """Notifie dans l'application et, si le type le justifie, par courriel.

    L'envoi du courriel ne doit jamais faire échouer le traitement métier : une
    messagerie indisponible ne bloque pas un dossier.
    """
    n = Notification(destinataire_id=destinataire.id, type=type_notif, contenu=contenu, lien=lien)
    db.session.add(n)
    try:
        import courriel
        courriel.envoyer(destinataire, type_notif, contenu, lien)
    except Exception:                                     # noqa: BLE001
        pass
    return n


def notifier_tous(role_systeme, type_notif, contenu, lien=None):
    personnes = Personne.query.filter_by(role_systeme=role_systeme, statut_compte="actif").all()
    return [notifier(p, type_notif, contenu, lien) for p in personnes]
