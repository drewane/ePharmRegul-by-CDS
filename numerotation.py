"""
Numérotation des identifiants métier (02-regles-transversales.md, section 3) :
{CODE_MODULE}-{ANNÉE}-{SÉQUENCE sur 4 chiffres}. La séquence est continue par
module et par année, jamais réutilisée même en cas d'annulation — d'où un
compteur persistant dédié (SequenceNumerotation) plutôt qu'un MAX(id) ou un
parsing de numéro existant.

LIMITE ASSUMÉE : SQLite ne verrouille pas réellement la ligne au sens d'un
SELECT ... FOR UPDATE. Le risque de concurrence est faible pour ce périmètre
(usage interne à faible volume) ; documenté dans README.md avec pointeur vers
la migration PostgreSQL cible (cf. ARCHITECTURE.md du prototype voisin).
"""
from datetime import datetime

from models import db, SequenceNumerotation


def generer_numero(module):
    annee = datetime.utcnow().year
    seq = SequenceNumerotation.query.filter_by(module=module, annee=annee).first()
    if not seq:
        seq = SequenceNumerotation(module=module, annee=annee, dernier_numero=0)
        db.session.add(seq)
        db.session.flush()
    seq.dernier_numero += 1
    db.session.flush()
    return f"{module}-{annee}-{seq.dernier_numero:04d}"
