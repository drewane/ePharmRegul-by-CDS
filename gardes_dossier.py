"""
Conditions de fond opposables à une décision sur un dossier.

CE QUE CE MODULE N'EST PAS
---------------------------
Ce n'est pas un contrôle de droits. `machine_etats` sait déjà qui a qualité
pour agir. Ici on répond à l'autre question : la CHOSE est-elle en état de
recevoir la décision ? Le directeur a bien qualité pour valider — mais pas un
dossier vide, et c'est arrivé.

POURQUOI CE MODULE EXISTE
--------------------------
Un dossier a été validé sans une seule pièce jointe et sans le moindre avis
d'évaluation, et le système l'a laissé faire. L'écran n'affichait ni pièces ni
avis, donc rien n'avertissait ; et rien, côté serveur, ne s'y opposait. On
corrige les deux : l'écran montre le dossier, et le moteur refuse.

Le refus est ici et non dans le gabarit. Un garde-fou qui ne tient qu'à un
écran tombe au premier appel direct — et une autorisation de mise sur le
marché délivrée par une requête forgée reste une autorisation délivrée.

CE QUI EST EXIGÉ
----------------
Deux conditions cumulatives pour la validation finale :

  1. au moins une pièce au dossier — on ne délivre pas une AMM sur un dossier
     dont aucun document n'a été déposé ;
  2. au moins un avis d'évaluation FAVORABLE — l'évaluation technique doit
     avoir conclu, et conclu positivement. Un avis de rejet ou un avis
     demandant un complément ne vaut pas approbation.

Une recommandation de rejet non levée bloque également : laisser passer une
validation par-dessus un avis défavorable, sans que personne l'ait retiré ou
contredit, serait exactement le genre de silence qu'une piste d'audit ne
rattrape pas.
"""
import machine_etats as me


def _pieces(dossier):
    from models import PieceJointe

    return (PieceJointe.query
            .filter_by(entite_type=dossier.__class__.__name__,
                       entite_id=dossier.id).count())


def _avis(dossier):
    from models import AvisEvaluationMA

    return AvisEvaluationMA.query.filter_by(dossier_id=dossier.id).all()


def dossier_instruit(dossier):
    """Empêchements à la validation finale. Liste vide = rien ne s'y oppose.

    Les messages s'affichent tels quels au décideur : ils disent ce qui
    manque, et donc ce qu'il faut obtenir.
    """
    manques = []

    if not _pieces(dossier):
        manques.append(
            "aucune pièce n'est jointe au dossier — une autorisation ne se "
            "délivre pas sur un dossier vide ;")

    avis = _avis(dossier)
    if not avis:
        manques.append(
            "aucun avis d'évaluation n'a été rendu — l'évaluation technique "
            "n'a pas conclu ;")
    else:
        if not any(a.valeur == "favorable" for a in avis):
            manques.append(
                "aucun avis favorable n'a été rendu : un avis demandant un "
                "complément ou recommandant le rejet ne vaut pas approbation ;")
        defavorables = [a for a in avis if a.valeur == "recommandation_rejet"]
        if defavorables:
            manques.append(
                f"{len(defavorables)} avis recommande(nt) le rejet et n'a(ont) "
                "pas été levé(s) ;")

    if manques:
        # La dernière puce se termine par un point, pas par un point-virgule.
        manques[-1] = manques[-1].rstrip(" ;") + "."
    return manques


me.enregistrer_garde("dossier_instruit", dossier_instruit)
