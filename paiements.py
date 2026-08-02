"""
Paiements — frais de dossier. Circuit : creer_paiement() (au dépôt du dossier,
montant tiré du paramètre configurable frais_dossier_xaf du module concerné)
→ le demandeur téléverse une preuve de paiement (virement, dépôt mobile
money) via deposer_preuve() → un agent DPML confirme() ou rejette() → le
demandeur est notifié dans les deux cas.

NOTE IMPORTANTE (contrainte assumée, cf. README) : SIREPH ne traite, ne
stocke ni ne transmet aucune donnée de carte bancaire ou de mobile money —
il n'y a pas de passerelle de paiement en ligne dans ce prototype. L'ajout
d'un agrégateur de paiement réel (ex. Orange Money, MTN MoMo, carte
bancaire via un prestataire agréé) est une phase ultérieure distincte,
nécessitant des identifiants fournis par un prestataire agréé.
"""
from datetime import datetime

from models import db, Paiement, DossierAMM, DemandeLicence, Personne
from audit import enregistrer_audit
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from numerotation import generer_numero
from pieces import enregistrer_piece


def _demandeur(paiement):
    if paiement.entite_type == "DossierAMM":
        d = DossierAMM.query.get(paiement.entite_id)
        return d.demandeur if d else None
    if paiement.entite_type == "DemandeLicence":
        demande = DemandeLicence.query.get(paiement.entite_id)
        if not demande:
            return None
        return Personne.query.filter_by(
            etablissement_rattachement_id=demande.etablissement_id, role_systeme="demandeur_externe").first()
    return None


def creer_paiement(entite, montant, devise="XAF"):
    """Crée le paiement attendu pour un dossier/une demande (statut en_attente).
    N'effectue pas le commit — appelée depuis un workflow déjà dans une transaction."""
    paiement = Paiement(
        numero=generer_numero("PAY"), entite_type=entite.__class__.__name__, entite_id=entite.id,
        montant=montant, devise=devise,
    )
    db.session.add(paiement)
    enregistrer_audit(entite, f"Frais de dossier générés ({montant} {devise})", None)
    return paiement


def deposer_preuve(paiement, fichier_werkzeug, acteur):
    if paiement.statut not in ("en_attente", "rejete"):
        raise ErreurWorkflow("Une preuve de paiement a déjà été déposée pour ce dossier.")
    ancien = paiement.statut
    piece = enregistrer_piece(paiement, fichier_werkzeug, "Preuve de paiement", acteur)
    # Affectation par relation (pas .piece_jointe_id = piece.id) : piece.id n'est pas
    # encore attribué à ce stade (pas de flush), SQLAlchemy résout la FK au flush suivant.
    paiement.piece_jointe = piece
    paiement.motif_rejet = None
    paiement.statut = "preuve_deposee"
    enregistrer_audit(paiement, "Preuve de paiement déposée", acteur,
                       ancien_statut=ancien, nouveau_statut="preuve_deposee")
    notifier_tous("administrateur_dpml", "paiement_a_confirmer",
                  f"Preuve de paiement déposée pour {paiement.numero} — à vérifier.",
                  lien=_lien_entite(paiement))
    return paiement


def confirmer(paiement, acteur):
    if paiement.statut != "preuve_deposee":
        raise ErreurWorkflow("Seul un paiement avec preuve déposée peut être confirmé.")
    paiement.statut = "confirme"
    paiement.date_confirmation = datetime.utcnow()
    paiement.confirme_par_id = acteur.id
    enregistrer_audit(paiement, "Paiement confirmé", acteur,
                       ancien_statut="preuve_deposee", nouveau_statut="confirme")
    demandeur = _demandeur(paiement)
    if demandeur:
        notifier(demandeur, "paiement_confirme",
                 f"Votre paiement {paiement.numero} de {paiement.montant} {paiement.devise} a été confirmé.",
                 lien=_lien_entite(paiement))
    return paiement


def rejeter(paiement, acteur, motif):
    if paiement.statut != "preuve_deposee":
        raise ErreurWorkflow("Seul un paiement avec preuve déposée peut être rejeté.")
    if not motif or not motif.strip():
        raise ErreurWorkflow("Un motif est obligatoire pour rejeter une preuve de paiement.")
    paiement.statut = "rejete"
    paiement.motif_rejet = motif.strip()
    enregistrer_audit(paiement, "Preuve de paiement rejetée", acteur,
                       ancien_statut="preuve_deposee", nouveau_statut="rejete", commentaire=motif.strip())
    demandeur = _demandeur(paiement)
    if demandeur:
        notifier(demandeur, "paiement_rejete",
                 f"Votre preuve de paiement {paiement.numero} a été rejetée : {motif.strip()} "
                 "Merci de déposer une nouvelle preuve.",
                 lien=_lien_entite(paiement))
    return paiement


def _lien_entite(paiement):
    if paiement.entite_type == "DossierAMM":
        return f"/dossiers/{paiement.entite_id}"
    if paiement.entite_type == "DemandeLicence":
        return f"/licences/{paiement.entite_id}"
    return None


def lister_paiements(entite):
    return (Paiement.query
            .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
            .order_by(Paiement.date_creation.desc()).all())
