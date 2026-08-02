"""Exception partagée par tous les moteurs de workflow (workflow_ma, workflow_vl, ...)."""


class ErreurWorkflow(Exception):
    """Violation d'une règle de gestion : à afficher tel quel à l'utilisateur (message explicite)."""
    pass
