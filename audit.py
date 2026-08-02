"""
Piste d'audit universelle (02-regles-transversales.md, section 2).

Règle non négociable : toute création d'entité et toute transition d'état, sur
n'importe quel module, doit produire une entrée EvenementAudit (quoi/qui/quand/
ancien état/nouvel état). C'est la réponse directe au score de 0% en
"suivi-évaluation" relevé dans le diagnostic OMS GBT de la DPML.

RÈGLE DE CODAGE (vérifiable par grep) : aucune route de app.py ne doit affecter
`dossier.statut` directement. Seules les fonctions de workflow_ma.py sont
autorisées à changer un statut, et chacune appelle enregistrer_audit() avant tout
commit(). Exception assumée et documentée dans README.md : les routes admin CRUD
simples (Personne, ParametreModule) appellent enregistrer_audit/enregistrer_creation
directement, faute de couche service dédiée pour ces objets.
"""
from models import db, EvenementAudit


def enregistrer_audit(entite, action, acteur, ancien_statut=None, nouveau_statut=None, commentaire=None):
    """
    Ajoute l'événement à la session SQLAlchemy sans commit — la transaction
    appelante garantit que le changement d'état et sa trace d'audit sont soit
    tous les deux persistés, soit aucun (atomicité).
    """
    evt = EvenementAudit(
        entite_type=entite.__class__.__name__,
        entite_id=entite.id,
        acteur_id=acteur.id if acteur else None,
        action=action,
        ancien_statut=ancien_statut,
        nouveau_statut=nouveau_statut,
        commentaire=commentaire,
    )
    db.session.add(evt)
    return evt


def enregistrer_creation(entite, acteur, libelle_action=None):
    """Cas particulier : création d'une entité (pas de transition de statut)."""
    return enregistrer_audit(
        entite,
        libelle_action or f"Création de {entite.__class__.__name__}",
        acteur,
        ancien_statut=None,
        nouveau_statut=getattr(entite, "statut", None),
    )
