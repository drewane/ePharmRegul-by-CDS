"""
Paiements — frais de dossier. Circuit : creer_paiement() (au dépôt du dossier,
montant tiré du paramètre configurable frais_dossier_xaf du module concerné)
→ le demandeur téléverse une preuve de paiement (virement, dépôt mobile
money) via deposer_preuve() → un agent DPML confirme() ou rejette() → le
demandeur est notifié dans les deux cas.

DEUX VOIES DE RÈGLEMENT
-----------------------
1. **Paiement en ligne** (voie principale) — via paiement_gateway.py : session
   chez un prestataire agréé, notification signée en HMAC, idempotence,
   contrôle du montant. SIREPH ne stocke AUCUNE donnée de carte ni de mobile
   money : seules des références opaques transitent.
2. **Preuve manuelle** (voie de repli) — virement/dépôt : le demandeur
   téléverse un justificatif, un agent DPML confirme ou rejette. Conservée
   car tous les opérateurs n'ont pas accès au paiement en ligne.

Faits générateurs couverts : homologation (DossierAMM), licences
(DemandeLicence) et analyses de laboratoire (Echantillon).
"""
from datetime import datetime

import paiement_gateway as passerelle
from models import db, Paiement, DossierAMM, DemandeLicence, Echantillon, Personne
from audit import enregistrer_audit
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from numerotation import generer_numero
from pieces import enregistrer_piece

# Libellé lisible du fait générateur, par type d'entité
LIBELLE_OBJET = {
    "DossierAMM": "Homologation (AMM)",
    "DemandeLicence": "Licence d'établissement",
    "Echantillon": "Analyse de laboratoire",
}


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
    if paiement.entite_type == "Echantillon":
        ech = Echantillon.query.get(paiement.entite_id)
        return getattr(ech, "demandeur", None) if ech else None
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
    if paiement.entite_type == "Echantillon":
        return f"/laboratoire/echantillons/{paiement.entite_id}"
    return None


# ---------------------------------------------------------------------------
# Paiement en ligne sécurisé
# ---------------------------------------------------------------------------
def initier_en_ligne(paiement, fournisseur, retour_url, acteur):
    """Ouvre une session de paiement chez le prestataire agréé."""
    if paiement.statut == "confirme":
        raise ErreurWorkflow("Ce paiement a déjà été réglé.")
    try:
        session = passerelle.initier(paiement, fournisseur, retour_url)
    except passerelle.ErreurPaiement as e:
        raise ErreurWorkflow(str(e))
    enregistrer_audit(paiement, f"Paiement en ligne initié ({passerelle.FOURNISSEURS[fournisseur]})",
                      acteur, nouveau_statut="initie")
    return session


def traiter_notification(paiement, payload, acteur=None):
    """Applique une notification de paiement signée (webhook / retour prestataire).

    Toute notification invalide (signature, montant, rejeu) est refusée ET tracée :
    une tentative de fraude laisse une trace exploitable.
    """
    ancien = paiement.statut
    try:
        resultat = passerelle.traiter_notification(payload, paiement)
    except passerelle.ErreurPaiement as e:
        enregistrer_audit(paiement, f"Notification de paiement REFUSÉE : {e}", acteur)
        db.session.commit()
        raise ErreurWorkflow(str(e))

    if resultat == "deja_confirme":
        return paiement  # idempotence : aucun double encaissement

    if resultat == "confirme":
        enregistrer_audit(
            paiement,
            f"Paiement confirmé en ligne ({paiement.fournisseur}, "
            f"transaction {paiement.reference_transaction})",
            acteur, ancien_statut=ancien, nouveau_statut="confirme")
        demandeur = _demandeur(paiement)
        if demandeur:
            notifier(demandeur, "paiement_confirme",
                     f"Votre paiement {paiement.numero} de {paiement.montant} "
                     f"{paiement.devise} a été confirmé.", lien=_lien_entite(paiement))
    else:
        enregistrer_audit(paiement, f"Paiement en ligne échoué : {paiement.detail_echec}",
                          acteur, ancien_statut=ancien, nouveau_statut="echoue")
        demandeur = _demandeur(paiement)
        if demandeur:
            notifier(demandeur, "paiement_echoue",
                     f"Votre paiement {paiement.numero} n'a pas abouti. "
                     "Vous pouvez relancer l'opération.", lien=_lien_entite(paiement))
    return paiement


def purger_sessions_expirees():
    """Passe à `expire` les sessions de paiement non abouties. Idempotent."""
    n = 0
    for p in Paiement.query.filter_by(statut="initie").all():
        if passerelle.expirer_si_besoin(p):
            enregistrer_audit(p, "Session de paiement expirée", None,
                              ancien_statut="initie", nouveau_statut="expire")
            n += 1
    if n:
        db.session.commit()
    return n


def lister_paiements(entite):
    return (Paiement.query
            .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
            .order_by(Paiement.date_creation.desc()).all())
