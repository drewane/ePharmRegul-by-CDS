"""
Paiements — frais de dossier. Circuit : creer_paiement() (au dépôt du dossier,
montant tiré du paramètre configurable frais_dossier_xaf du module concerné)
→ le demandeur téléverse une preuve de paiement (virement, dépôt mobile
money) via deposer_preuve() → un agent DPML confirme() ou rejette() → le
demandeur est notifié dans les deux cas.

MOYENS DE RÈGLEMENT (plateforme multi-fournisseurs, paquet `paiement/`)
----------------------------------------------------------------------
1. **Mobile money** (MTN MoMo, Orange Money) — demande poussée sur le
   téléphone du payeur, confirmée par notification ou interrogation de statut.
2. **Carte bancaire** — page hébergée du prestataire avec 3-D Secure ; seul le
   webhook signé fait foi, jamais le retour navigateur.
3. **Virement bancaire** — avis de paiement portant une référence unique, puis
   rapprochement sur relevé bancaire (automatique ou par un agent habilité).
4. **Preuve manuelle** (repli) — justificatif téléversé, confirmé par un agent.

Dans tous les cas SIREPH ne stocke AUCUNE donnée de carte ni de compte mobile :
seules des références opaques transitent.

Faits générateurs couverts (barème centralisé dans bareme.py) : homologation,
licence d'établissement, analyse de laboratoire, autorisation d'essai clinique,
inspection réglementaire et libération de lot. Le montant de chacun est
paramétrable ; un montant à 0 signifie « acte gratuit » et aucun paiement
n'est alors créé.
"""
from datetime import datetime

import bareme
import paiement as plateforme
from models import (db, Paiement, DossierAMM, DemandeLicence, Echantillon,
                    Personne)
from audit import enregistrer_audit
from notifications import notifier, notifier_tous
from erreurs import ErreurWorkflow
from numerotation import generer_numero
from pieces import enregistrer_piece

# Libellé lisible du fait générateur, par type d'entité (dérivé du barème)
LIBELLE_OBJET = {ent: lib for _c, (ent, _m, _k, _d, lib) in bareme.BAREME.items()}

# Libellé affichable d'un statut de paiement : le redevable n'a pas à décoder
# notre vocabulaire interne.
LIBELLE_STATUT = {
    "en_attente": "À régler",
    "initie": "Paiement en cours",
    "preuve_deposee": "Preuve déposée, en vérification",
    "confirme": "Encaissé",
    "rejete": "Preuve rejetée",
    "echoue": "Paiement échoué",
    "expire": "Expiré",
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
        ech = db.session.get(Echantillon, paiement.entite_id)
        return getattr(ech, "demandeur", None) if ech else None
    if paiement.entite_type == "ProtocoleEssaiClinique":
        from models import ProtocoleEssaiClinique
        p = db.session.get(ProtocoleEssaiClinique, paiement.entite_id)
        return p.promoteur if p else None
    if paiement.entite_type == "Inspection":
        # Redevable : l'établissement inspecté, via son représentant déclaré.
        from models import Inspection
        insp = db.session.get(Inspection, paiement.entite_id)
        return _representant_etablissement(insp.etablissement_id) if insp else None
    if paiement.entite_type == "LiberationLot":
        # Redevable : le titulaire de l'AMM du produit concerné.
        from models import LiberationLot
        lib = db.session.get(LiberationLot, paiement.entite_id)
        etab_id = getattr(getattr(lib, "produit", None), "titulaire_amm_id", None) if lib else None
        return _representant_etablissement(etab_id) if etab_id else None
    return None


# Profils externes habilités à représenter un établissement pour un paiement.
_PROFILS_REPRESENTANTS = ("demandeur_externe", "grossiste", "pharmacien",
                          "laboratoire_prive", "promoteur_essai")


def _representant_etablissement(etablissement_id):
    """Interlocuteur externe rattaché à l'établissement, quel que soit son profil."""
    return (Personne.query
            .filter(Personne.etablissement_rattachement_id == etablissement_id,
                    Personne.role_systeme.in_(_PROFILS_REPRESENTANTS),
                    Personne.statut_compte == "actif")
            .first())


def exiger_paiement(entite, destinataires, lien, libelle_acte=None, devise="XAF"):
    """Crée la créance exigible pour un acte et en informe le ou les redevables.

    Point d'entrée unique des workflows : le montant vient du barème, un acte
    non facturé (montant 0) ne crée rien et ne notifie personne. Renvoie le
    paiement créé, ou None si l'acte est gratuit.
    """
    paiement = creer_paiement_bareme(entite, devise=devise)
    if paiement is None:
        return None
    acte = libelle_acte or LIBELLE_OBJET.get(entite.__class__.__name__, "cet acte")
    for dest in destinataires or []:
        if dest is None:
            continue
        notifier(dest, "paiement_attendu",
                 f"Frais de {paiement.montant} {paiement.devise} à régler pour "
                 f"{acte} ({paiement.numero}). Réglez en ligne depuis votre espace "
                 "— mobile money, carte bancaire ou virement.",
                 lien=lien)
    return paiement


def creer_paiement_bareme(entite, devise="XAF"):
    """Crée le paiement exigible pour une entité, montant tiré du barème.

    Renvoie None si l'acte n'est pas facturé (montant 0) ou si un paiement non
    annulé existe déjà — appelable sans risque depuis un workflow.
    """
    montant = bareme.montant_pour(entite)
    if montant <= 0:
        return None
    existant = (Paiement.query
                .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
                .filter(Paiement.statut != "rejete").first())
    if existant:
        return existant
    return creer_paiement(entite, montant, devise)


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
    notifier_tous(ROLE_FINANCIER, "paiement_a_confirmer",
                  f"Preuve de paiement déposée pour {paiement.numero} — "
                  "à approuver.", lien="/paiements/approbation")
    return paiement


ROLE_FINANCIER = "responsable_financier"


def controler_separation(paiement, acteur):
    """Vérifie que l'approbateur est bien étranger à l'instruction du dossier.

    Trois interdits, dans l'ordre où ils se rencontrent :
      1. approuver sans être le responsable financier ;
      2. approuver sa propre créance, ou celle de sa société ;
      3. approuver la recette d'un dossier que l'on instruit soi-même.

    Le contrôle est ici, dans le moteur, et non seulement dans la route : une
    règle de séparation des tâches qui ne tient qu'à un décorateur de vue tombe
    au premier script d'import ou à la première console d'administration.
    """
    if acteur is None or acteur.role_systeme != ROLE_FINANCIER:
        raise ErreurWorkflow(
            "L'approbation d'une recette relève du responsable financier. "
            "Instruire un dossier et constater son paiement ne peuvent pas "
            "relever de la même personne.")

    redevable = _demandeur(paiement)
    if redevable is not None:
        if redevable.id == acteur.id:
            raise ErreurWorkflow(
                "Vous ne pouvez pas approuver votre propre paiement.")
        meme_societe = (acteur.etablissement_rattachement_id is not None
                        and acteur.etablissement_rattachement_id
                        == redevable.etablissement_rattachement_id)
        if meme_societe:
            raise ErreurWorkflow(
                "Vous ne pouvez pas approuver le paiement d'un redevable "
                "rattaché à votre propre établissement.")

    entite = _entite_du_paiement(paiement)
    if entite is not None and entite.__class__.__name__ == "DossierAMM":
        from models import AssignationEvaluation
        assigne = (AssignationEvaluation.query
                   .filter_by(dossier_id=entite.id, evaluateur_id=acteur.id)
                   .first())
        if assigne is not None:
            raise ErreurWorkflow(
                "Vous êtes évaluateur assigné sur ce dossier : vous ne pouvez "
                "pas en approuver la recette.")
    return True


def confirmer(paiement, acteur):
    """Approuve l'encaissement — acte du responsable financier.

    L'approbation est le point de bascule de la procédure : elle démarre le
    délai légal et libère la recevabilité. C'est pourquoi elle est isolée de
    l'instruction.
    """
    if paiement.statut != "preuve_deposee":
        raise ErreurWorkflow("Seul un paiement avec preuve déposée peut être confirmé.")
    controler_separation(paiement, acteur)
    paiement.statut = "confirme"
    paiement.date_confirmation = datetime.utcnow()
    paiement.confirme_par_id = acteur.id
    enregistrer_audit(paiement,
                      f"Recette approuvée par le responsable financier "
                      f"({acteur.nom_complet})", acteur,
                      ancien_statut="preuve_deposee", nouveau_statut="confirme")
    demandeur = _demandeur(paiement)
    if demandeur:
        notifier(demandeur, "paiement_confirme",
                 f"Votre paiement {paiement.numero} de {paiement.montant} {paiement.devise} a été confirmé.",
                 lien=_lien_entite(paiement))
    _apres_approbation(paiement, acteur)
    return paiement


def rejeter(paiement, acteur, motif):
    if paiement.statut != "preuve_deposee":
        raise ErreurWorkflow("Seul un paiement avec preuve déposée peut être rejeté.")
    controler_separation(paiement, acteur)
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
    entite = _entite_du_paiement(paiement)
    if entite is not None and entite.__class__.__name__ == "DossierAMM":
        _avancer_machine(entite, "rejeter_paiement", acteur, motif.strip())
    return paiement


def _lien_entite(paiement):
    if paiement.entite_type == "DossierAMM":
        return f"/dossiers/{paiement.entite_id}"
    if paiement.entite_type == "DemandeLicence":
        return f"/licences/{paiement.entite_id}"
    if paiement.entite_type == "Echantillon":
        return f"/laboratoire/echantillons/{paiement.entite_id}"
    if paiement.entite_type == "ProtocoleEssaiClinique":
        return f"/essais-cliniques/{paiement.entite_id}"
    if paiement.entite_type == "Inspection":
        return f"/inspections/{paiement.entite_id}"
    if paiement.entite_type == "LiberationLot":
        return f"/liberations/{paiement.entite_id}"
    return None


def paiements_du_redevable(personne):
    """Tous les paiements dont cette personne est redevable, tous modules confondus.

    Alimente l'espace « Mes paiements » des profils externes.
    """
    resultat = []
    for p in Paiement.query.order_by(Paiement.date_creation.desc()).all():
        d = _demandeur(p)
        if d and d.id == personne.id:
            resultat.append(p)
    return resultat


# ---------------------------------------------------------------------------
# Paiement en ligne sécurisé
# ---------------------------------------------------------------------------
def initier_en_ligne(paiement, code_fournisseur, contexte, acteur):
    """Ouvre une session de paiement auprès du moyen choisi.

    `contexte` porte les URL de retour/notification et, pour le mobile money,
    le numéro du payeur. Renvoie une `Initiation` (cf. paiement/base.py).
    """
    if paiement.statut == "confirme":
        raise ErreurWorkflow("Ce paiement a déjà été réglé.")
    fournisseur = plateforme.obtenir(code_fournisseur)
    if not paiement.reference_marchande:
        paiement.reference_marchande = plateforme.nouvelle_reference(
            getattr(fournisseur, "prefixe_ref", "MRC"))
    try:
        initiation = fournisseur.initier(paiement, contexte)
    except plateforme.ErreurPaiement as e:
        raise ErreurWorkflow(str(e))

    paiement.mode = "en_ligne" if fournisseur.flux != "hors_ligne" else "virement"
    paiement.fournisseur = fournisseur.code
    paiement.reference_marchande = initiation.reference_marchande
    paiement.statut = "initie"
    paiement.date_initiation = datetime.utcnow()
    paiement.date_expiration = initiation.expire_le
    paiement.detail_echec = None
    enregistrer_audit(paiement, f"Paiement initié — {fournisseur.libelle}",
                      acteur, nouveau_statut="initie")
    return initiation


def _entite_du_paiement(paiement):
    """L'objet métier auquel se rattache la créance."""
    from models import (DemandeLicence, DossierAMM, Echantillon, Inspection,
                        LiberationLot, ProtocoleEssaiClinique)
    modeles = {"DossierAMM": DossierAMM, "DemandeLicence": DemandeLicence,
               "Echantillon": Echantillon, "Inspection": Inspection,
               "LiberationLot": LiberationLot,
               "ProtocoleEssaiClinique": ProtocoleEssaiClinique}
    modele = modeles.get(paiement.entite_type)
    return db.session.get(modele, paiement.entite_id) if modele else None


def _demarrer_delai_legal(paiement, acteur):
    """Déclenche le décompte du délai sur l'entité concernée, si elle le porte."""
    entite = _entite_du_paiement(paiement)
    if entite is None or not hasattr(entite, "clock_debut"):
        return
    import suivi
    suivi.demarrer_delai(entite, acteur,
                         motif=f"paiement {paiement.numero} confirmé")


def _apres_approbation(paiement, acteur):
    """Ce que l'approbation de la recette débloque, sans intervention humaine.

    L'approbation financière n'est pas une formalité comptable isolée : c'est
    elle qui saisit l'administration. Elle produit donc trois effets d'un seul
    tenant, pour qu'aucun dossier ne reste en attente d'un geste oublié :

      1. le délai légal démarre (Clock Start) ;
      2. le point « preuve de paiement » de la recevabilité est ATTESTÉ — le
         chef de service n'a plus à le cocher, et ne le peut plus ;
      3. le dossier AVANCE dans la machine à états, vers la recevabilité ;
      4. le service instructeur est averti qu'il peut aller de l'avant.
    """
    _demarrer_delai_legal(paiement, acteur)

    entite = _entite_du_paiement(paiement)
    if entite is None or entite.__class__.__name__ != "DossierAMM":
        return

    import workflow_instruction as wfi
    wfi.attester_paiement(entite, acteur, paiement.numero)
    _avancer_machine(entite, "valider_paiement", acteur)

    reference = getattr(entite, "numero_suivi", None) or entite.numero
    restants = wfi.points_manquants(entite)
    if restants:
        message = (f"Recette approuvée pour {reference}. Reste à satisfaire "
                   "avant recevabilité : "
                   + ", ".join(libelle for _c, libelle in restants) + ".")
    else:
        message = (f"Recette approuvée pour {reference}. La recevabilité peut "
                   "être prononcée.")
    for role in wfi.ROLES_RECEVABILITE:
        notifier_tous(role, "recette_approuvee", message,
                      lien=f"/instruction/dossiers/{entite.id}")


def _avancer_machine(dossier, action, acteur, motif=None):
    """Répercute une décision financière sur l'état du dossier.

    Le paiement et le dossier avaient jusqu'ici deux vies parallèles : la
    recette était constatée sans que le dossier bouge, et c'est le chef de
    service qui devait s'apercevoir qu'il pouvait avancer. On relie les deux —
    par la machine à états, pas en écrivant `dossier.statut` ici, faute de
    quoi on recréerait le second workflow qu'on cherche à supprimer.

    Silencieux si la transition n'est pas ouverte : un dossier déjà recevable
    dont on rapproche un virement tardif ne doit pas reculer, et un paiement
    portant sur une licence ou un échantillon n'a pas de machine à faire
    avancer.
    """
    import machine_etats as me

    if not any(t["action"] == action
               for t in me.transitions_autorisees(dossier, acteur.role_systeme)):
        return False
    me.appliquer_transition(dossier, action, acteur, motif)
    return True


def _appliquer_resultat(paiement, resultat, acteur, origine):
    """Applique une issue de paiement (notification, interrogation, rapprochement)."""
    ancien = paiement.statut
    if resultat.etat == "deja_confirme":
        return paiement                      # idempotence : aucun double encaissement
    if resultat.etat == "en_cours":
        return paiement

    fournisseur = plateforme.FOURNISSEURS.get(paiement.fournisseur)
    libelle_f = fournisseur.libelle if fournisseur else (paiement.fournisseur or "—")

    if resultat.etat == "confirme":
        paiement.statut = "confirme"
        paiement.date_confirmation = datetime.utcnow()
        paiement.reference_transaction = resultat.reference_transaction
        # Clock Start et libération de la recevabilité : un encaissement
        # constaté par la plateforme vaut approbation, le prestataire faisant
        # foi de l'entrée des fonds.
        _apres_approbation(paiement, acteur)
        enregistrer_audit(
            paiement,
            f"Paiement confirmé — {libelle_f} ({origine}, transaction "
            f"{paiement.reference_transaction})",
            acteur, ancien_statut=ancien, nouveau_statut="confirme")
        demandeur = _demandeur(paiement)
        if demandeur:
            notifier(demandeur, "paiement_confirme",
                     f"Votre paiement {paiement.numero} de {paiement.montant} "
                     f"{paiement.devise} a été confirmé.", lien=_lien_entite(paiement))
    else:
        paiement.statut = "echoue"
        paiement.detail_echec = resultat.detail or "Paiement non abouti."
        enregistrer_audit(paiement, f"Paiement échoué — {libelle_f} : {paiement.detail_echec}",
                          acteur, ancien_statut=ancien, nouveau_statut="echoue")
        demandeur = _demandeur(paiement)
        if demandeur:
            notifier(demandeur, "paiement_echoue",
                     f"Votre paiement {paiement.numero} n'a pas abouti. "
                     "Vous pouvez relancer l'opération.", lien=_lien_entite(paiement))
    return paiement


def traiter_notification(paiement, payload, acteur=None):
    """Applique une notification signée (webhook prestataire).

    Toute notification invalide (signature, montant, rejeu) est refusée ET
    tracée : une tentative de fraude laisse une trace exploitable.
    """
    fournisseur = plateforme.FOURNISSEURS.get(paiement.fournisseur)
    if fournisseur is None:
        raise ErreurWorkflow("Aucun moyen de paiement engagé pour cette créance.")
    try:
        resultat = fournisseur.traiter_notification(payload, paiement)
    except plateforme.ErreurPaiement as e:
        enregistrer_audit(paiement, f"Notification de paiement REFUSÉE : {e}", acteur)
        db.session.commit()
        raise ErreurWorkflow(str(e))
    if resultat.etat == "confirme":
        paiement.signature_notification = str(payload.get("signature", ""))[:120]
    return _appliquer_resultat(paiement, resultat, acteur, "notification")


def interroger_statut(paiement, acteur=None):
    """Interroge le prestataire (mobile money : le payeur a-t-il validé ?)."""
    fournisseur = plateforme.FOURNISSEURS.get(paiement.fournisseur)
    if fournisseur is None or paiement.statut not in ("initie",):
        return paiement
    try:
        resultat = fournisseur.interroger(paiement)
    except plateforme.ErreurPaiement as e:
        enregistrer_audit(paiement, f"Interrogation de statut refusée : {e}", acteur)
        db.session.commit()
        raise ErreurWorkflow(str(e))
    return _appliquer_resultat(paiement, resultat, acteur, "interrogation")


def rapprocher_virement(paiement, ligne_releve, acteur):
    """Rapproche un virement bancaire avec la créance (contrôle strict du montant)."""
    fournisseur = plateforme.obtenir("virement")
    try:
        resultat = fournisseur.rapprocher(paiement, ligne_releve)
    except plateforme.ErreurPaiement as e:
        enregistrer_audit(paiement, f"Rapprochement bancaire REFUSÉ : {e}", acteur)
        db.session.commit()
        raise ErreurWorkflow(str(e))
    return _appliquer_resultat(paiement, resultat, acteur, "rapprochement bancaire")


def purger_sessions_expirees():
    """Passe à `expire` les sessions de paiement non abouties. Idempotent."""
    n = 0
    maintenant = datetime.utcnow()
    for p in Paiement.query.filter_by(statut="initie").all():
        if p.date_expiration and maintenant > p.date_expiration:
            p.statut = "expire"
            p.detail_echec = "Session de paiement expirée sans confirmation."
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
