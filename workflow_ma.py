"""
Moteur de workflow — Module MA (Enregistrement/AMM), 11-MA-enregistrement-amm.md.

Machine à états explicite du DossierAMM (§4 du spec). RÈGLE DE CODAGE : c'est la
SEULE couche autorisée à changer `DossierAMM.statut` ou `Produit.statut_amm_courant`.
Aucune route de app.py ne doit le faire directement — chaque fonction ci-dessous
vérifie le statut courant ET le rôle de l'acteur côté serveur (jamais seulement
côté template), puis appelle systématiquement enregistrer_audit() avant tout
commit(), garantissant qu'aucune transition n'échappe à la piste d'audit.

Renouvellement (§3.2), variation (§3.3) et retrait (§3.4) réutilisent EXACTEMENT
cette même machine à états — seule la création initiale diffère (type_procedure,
contenu CTD de départ).
"""
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

import os

from models import db, DossierAMM, Produit, Etablissement, AvisEvaluationMA, PieceJointe
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier, notifier_tous
from delais import get_parametre
from erreurs import ErreurWorkflow  # noqa: F401 — réexporté pour compat (wf.ErreurWorkflow)
from paiements import creer_paiement
from pieces import DOCUMENTS_DIR
import pdf_gen


STATUTS = {
    "brouillon": "Brouillon",
    "soumis": "Soumis",
    "recevable": "Recevable",
    "irrecevable": "Irrecevable",
    "evaluation_en_cours": "Évaluation en cours",
    "complement_requis": "Complément requis",
    "cloture_delai_depasse": "Clôturé (délai dépassé)",
    "approuve": "Approuvé",
    "rejete": "Rejeté",
}

STATUTS_FINAUX = {"irrecevable", "cloture_delai_depasse", "approuve", "rejete"}

TYPES_PROCEDURE = {
    "nouvelle_demande": "Nouvelle demande",
    "renouvellement": "Renouvellement",
    "variation": "Variation",
    "retrait": "Retrait",
}

# Un retrait ne fait pas l'objet de frais (démarche à l'initiative de la DPML/du titulaire,
# pas une nouvelle prestation d'instruction) — pas de clé de paramètre correspondante.
CLES_FRAIS_PAR_TYPE = {
    "nouvelle_demande": "frais_nouvelle_demande_xaf",
    "renouvellement": "frais_renouvellement_xaf",
    "variation": "frais_variation_xaf",
}


def montant_frais(type_procedure):
    """Montant des frais de dossier (XAF) selon le type de procédure ; None si le type
    de procédure ne donne pas lieu à des frais (ex. retrait)."""
    cle = CLES_FRAIS_PAR_TYPE.get(type_procedure)
    if not cle:
        return None
    defauts = {"frais_nouvelle_demande_xaf": 500000, "frais_renouvellement_xaf": 300000,
               "frais_variation_xaf": 150000}
    return int(get_parametre("MA", cle, default=defauts[cle]))

# Statut -> rôle(s) ayant potentiellement une action sur le dossier dans ce statut.
# Utilisé pour décider si un panneau d'action doit être affiché ; l'action précise
# et le contrôle définitif sont toujours revérifiés dans la fonction de transition
# elle-même (défense en profondeur — cf. deposer_avis_evaluation vs decider, qui
# se partagent le statut evaluation_en_cours mais pas le même rôle ni la même action).
ROLE_PAR_STATUT = {
    "brouillon": ["demandeur_externe"],
    "soumis": ["administrateur_dpml"],
    "evaluation_en_cours": ["evaluateur_amm", "directeur_dpml"],
    "complement_requis": ["demandeur_externe"],
}


def peut_agir(dossier, user):
    if user is None:
        return False
    return user.role_systeme in ROLE_PAR_STATUT.get(dossier.statut, [])


def etapes_suivi(dossier):
    """Suivi visuel du dossier pour le demandeur (voyants rouge/vert) : 4 étapes fixes,
    chacune dans un état parmi a_venir/en_cours/valide/probleme. Les statuts de branche
    (irrecevable, complement_requis, cloture_delai_depasse, rejete) ne sont pas des
    étapes à part entière mais colorent l'étape concernée en "probleme"."""
    s = dossier.statut
    etapes = [{"cle": "soumission", "libelle": "Soumission"}]
    etapes[0]["etat"] = "en_cours" if s == "brouillon" else "valide"

    etapes.append({"cle": "recevabilite", "libelle": "Recevabilité"})
    if s in ("brouillon",):
        etapes[1]["etat"] = "a_venir"
    elif s == "soumis":
        etapes[1]["etat"] = "en_cours"
    elif s == "irrecevable":
        etapes[1]["etat"] = "probleme"
        etapes[1]["detail"] = "Irrecevable"
    else:
        etapes[1]["etat"] = "valide"

    etapes.append({"cle": "evaluation", "libelle": "Évaluation technique"})
    if s in ("brouillon", "soumis", "irrecevable"):
        etapes[2]["etat"] = "a_venir"
    elif s in ("recevable", "evaluation_en_cours"):
        etapes[2]["etat"] = "en_cours"
    elif s == "complement_requis":
        etapes[2]["etat"] = "probleme"
        etapes[2]["detail"] = "Complément d'information requis"
    elif s == "cloture_delai_depasse":
        etapes[2]["etat"] = "probleme"
        etapes[2]["detail"] = "Clôturé (délai de réponse dépassé)"
    else:
        etapes[2]["etat"] = "valide"

    etapes.append({"cle": "decision", "libelle": "Décision"})
    if s == "approuve":
        etapes[3]["etat"] = "valide"
        etapes[3]["detail"] = "Approuvé"
    elif s == "rejete":
        etapes[3]["etat"] = "probleme"
        etapes[3]["detail"] = "Rejeté"
    else:
        etapes[3]["etat"] = "a_venir"

    return etapes


# ---------------------------------------------------------------------------
# Établissement / Produit — création à la volée depuis le formulaire MA
# ---------------------------------------------------------------------------
def _get_or_create_etablissement(raison_sociale, type_etab, adresse=""):
    raison_sociale = (raison_sociale or "").strip()
    if not raison_sociale:
        return None
    etab = Etablissement.query.filter_by(raison_sociale=raison_sociale).first()
    if etab:
        return etab
    # Simplification assumée (README) : le module LI (licences) n'étant pas livré,
    # tout établissement déclaré via le module MA est considéré "active" faute de
    # pouvoir vérifier une licence réelle.
    etab = Etablissement(raison_sociale=raison_sociale, type=type_etab, adresse=adresse, statut_licence="active")
    db.session.add(etab)
    db.session.flush()
    return etab


def _verifier_etablissements_non_suspendus(*etablissements):
    """Règle de gestion LI (14-LI §7, critère d'acceptation #2) : une licence
    suspendue ou révoquée empêche la création de tout nouveau DossierAMM où cet
    établissement figure comme fabricant ou titulaire — contrôle croisé entre
    modules via le socle commun, vérifié ici plutôt que dans workflow_li pour que
    la règle s'applique à TOUTE création de dossier, quel que soit le point d'entrée."""
    for etab in etablissements:
        if etab and etab.statut_licence in ("suspendue", "revoquee"):
            raise ErreurWorkflow(
                f"La licence de {etab.raison_sociale} est {etab.statut_licence} : impossible de créer "
                "un dossier AMM le désignant comme fabricant ou titulaire."
            )


def _verifier_unicite_dossier_actif(produit_id, type_procedure):
    actif = (
        DossierAMM.query.filter_by(produit_id=produit_id, type_procedure=type_procedure)
        .filter(DossierAMM.statut.notin_(STATUTS_FINAUX))
        .first()
    )
    if actif:
        raise ErreurWorkflow(
            f"Un dossier de type « {TYPES_PROCEDURE.get(type_procedure, type_procedure)} » est déjà "
            f"actif pour ce produit (N° {actif.numero or ('brouillon #' + str(actif.id))}). "
            "Il doit atteindre un statut final avant d'en créer un nouveau du même type."
        )


def creer_dossier_procedure(produit, demandeur, type_procedure):
    _verifier_unicite_dossier_actif(produit.id, type_procedure)
    _verifier_etablissements_non_suspendus(produit.fabricant, produit.titulaire_amm)
    d = DossierAMM(produit_id=produit.id, demandeur_id=demandeur.id, type_procedure=type_procedure, statut="brouillon")
    db.session.add(d)
    db.session.flush()
    if type_procedure in ("renouvellement", "variation"):
        dernier = (
            DossierAMM.query.filter_by(produit_id=produit.id, statut="approuve")
            .order_by(DossierAMM.date_decision.desc()).first()
        )
        if dernier:
            for n in range(1, 6):
                setattr(d, f"module_ctd_{n}_json", getattr(dernier, f"module_ctd_{n}_json"))
    enregistrer_creation(d, demandeur, f"Création du dossier ({TYPES_PROCEDURE.get(type_procedure, type_procedure)})")
    return d


def creer_dossier_nouvelle_demande(demandeur, donnees):
    """
    donnees : dict issu de l'écran "Nouvelle demande" — nom_commercial, dci,
    forme_pharmaceutique, dosage, fabricant_nom, fabricant_site, titulaire_nom,
    pays_origine, composition_integrale, classe_therapeutique,
    indications_therapeutiques, voie_administration, duree_stabilite,
    prix_grossiste_ht, representant_local_nom, representant_local_contact
    (champs SECTION 2 du formulaire officiel DPML — tous facultatifs sauf
    nom_commercial/dci, complétables ensuite tant que le dossier est en brouillon).
    """
    if not donnees.get("nom_commercial", "").strip() or not donnees.get("dci", "").strip():
        raise ErreurWorkflow("Le produit et la DCI doivent être renseignés avant la création du dossier.")
    if demandeur is None:
        raise ErreurWorkflow("Le demandeur doit être identifié avant la création du dossier.")

    fabricant = _get_or_create_etablissement(donnees.get("fabricant_nom", ""), "fabricant",
                                              adresse=donnees.get("fabricant_site", ""))
    titulaire_nom = donnees.get("titulaire_nom", "").strip() or donnees.get("fabricant_nom", "")
    titulaire = _get_or_create_etablissement(titulaire_nom, "importateur_exportateur")
    _verifier_etablissements_non_suspendus(fabricant, titulaire)

    prix = donnees.get("prix_grossiste_ht", "")
    produit = Produit(
        denomination_commune_internationale=donnees["dci"].strip(),
        nom_commercial=donnees["nom_commercial"].strip(),
        forme_pharmaceutique=donnees.get("forme_pharmaceutique", "").strip(),
        dosage=donnees.get("dosage", "").strip(),
        fabricant_id=fabricant.id if fabricant else None,
        titulaire_amm_id=titulaire.id if titulaire else None,
        pays_origine=donnees.get("pays_origine", "").strip(),
        statut_amm_courant="en_cours",
        composition_integrale=donnees.get("composition_integrale", "").strip() or None,
        classe_therapeutique=donnees.get("classe_therapeutique", "").strip() or None,
        indications_therapeutiques=donnees.get("indications_therapeutiques", "").strip() or None,
        voie_administration=donnees.get("voie_administration", "").strip() or None,
        duree_stabilite=donnees.get("duree_stabilite", "").strip() or None,
        prix_grossiste_ht=int(prix) if str(prix).strip().isdigit() else None,
    )
    db.session.add(produit)
    db.session.flush()
    enregistrer_creation(produit, demandeur, "Création de la fiche produit")

    dossier = creer_dossier_procedure(produit, demandeur, "nouvelle_demande")
    dossier.representant_local_nom = donnees.get("representant_local_nom", "").strip() or None
    dossier.representant_local_contact = donnees.get("representant_local_contact", "").strip() or None
    return dossier


def modifier_produit_brouillon(dossier, acteur, donnees):
    if dossier.statut != "brouillon":
        raise ErreurWorkflow("Les informations produit ne sont modifiables que tant que le dossier est en brouillon.")
    if acteur.id != dossier.demandeur_id:
        raise ErreurWorkflow("Seul le demandeur propriétaire peut modifier ce dossier.")
    p = dossier.produit
    for champ in ("denomination_commune_internationale", "nom_commercial", "forme_pharmaceutique",
                  "dosage", "pays_origine", "composition_integrale", "classe_therapeutique",
                  "indications_therapeutiques", "voie_administration", "duree_stabilite"):
        if champ in donnees:
            setattr(p, champ, donnees[champ].strip() or None)
    if "prix_grossiste_ht" in donnees:
        valeur = donnees["prix_grossiste_ht"]
        p.prix_grossiste_ht = int(valeur) if str(valeur).strip().isdigit() else None
    for champ in ("representant_local_nom", "representant_local_contact"):
        if champ in donnees:
            setattr(dossier, champ, donnees[champ].strip() or None)


def modifier_ctd(dossier, acteur, donnees_ctd):
    if not dossier.est_editable_par_demandeur:
        raise ErreurWorkflow("Le dossier technique n'est plus modifiable dans le statut actuel.")
    if acteur.id != dossier.demandeur_id:
        raise ErreurWorkflow("Seul le demandeur propriétaire peut modifier ce dossier.")
    for n in range(1, 6):
        cle = f"module_ctd_{n}"
        if cle in donnees_ctd:
            # Passe par la propriété (pas la colonne _json directement) pour que
            # l'encodage JSON reste cohérent avec le getter — cf. models.DossierAMM.
            setattr(dossier, cle, donnees_ctd[cle])


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
def soumettre(dossier, acteur):
    if dossier.statut != "brouillon":
        raise ErreurWorkflow("Seul un dossier en brouillon peut être soumis.")
    if acteur.id != dossier.demandeur_id:
        raise ErreurWorkflow("Seul le demandeur propriétaire peut soumettre ce dossier.")
    if not dossier.produit.denomination_commune_internationale.strip():
        raise ErreurWorkflow("La Dénomination Commune Internationale (DCI) doit être renseignée avant soumission.")

    from numerotation import generer_numero
    ancien = dossier.statut
    dossier.numero = generer_numero("AMM")
    # Numéro national de suivi communiqué au demandeur (CMR-AMM-2026-00123)
    attribuer_numero_suivi(dossier)
    dossier.statut = "soumis"
    dossier.date_depot = datetime.utcnow()
    if dossier.produit.statut_amm_courant == "aucune":
        dossier.produit.statut_amm_courant = "en_cours"
    enregistrer_audit(dossier, "Dossier soumis", acteur, ancien, dossier.statut)
    notifier_tous("administrateur_dpml", "recevabilite_a_traiter",
                  f"Nouveau dossier {dossier.numero} à instruire (contrôle de recevabilité).",
                  lien=f"/dossiers/{dossier.id}")
    notifier(dossier.demandeur, "dossier_soumis",
             f"Votre dossier {dossier.numero} a été soumis avec succès. Vous serez notifié à chaque étape.",
             lien=f"/dossiers/{dossier.id}")
    montant = montant_frais(dossier.type_procedure)
    if montant:
        paiement = creer_paiement(dossier, montant)
        notifier(dossier.demandeur, "paiement_attendu",
                 f"Frais de dossier de {montant} XAF à régler pour {dossier.numero} (paiement {paiement.numero}). "
                 "Déposez votre preuve de paiement depuis la fiche du dossier.",
                 lien=f"/dossiers/{dossier.id}")


def attribuer_numero_suivi(dossier):
    """Numéro national communiqué au demandeur, attribué une seule fois."""
    if getattr(dossier, "numero_suivi", None):
        return dossier.numero_suivi
    import suivi
    dossier.numero_suivi = suivi.numero_suivi("amm")
    return dossier.numero_suivi


def _generer_accuse_reception(dossier):
    """Accusé de Réception généré par le système/DPML (formulaire officiel DPML,
    Section 3) — distinct de la preuve de paiement fournie par le demandeur.
    Attaché directement comme PieceJointe (pas via pieces.enregistrer_piece, qui
    suppose un fichier téléversé par un utilisateur, pas un document généré)."""
    sous_dossier = os.path.join(DOCUMENTS_DIR, "DossierAMM", str(dossier.id))
    os.makedirs(sous_dossier, exist_ok=True)
    nom_fichier = f"accuse_reception_{dossier.numero}.pdf"
    pdf_gen.generer_accuse_reception(dossier, os.path.join(sous_dossier, nom_fichier))
    taille = os.path.getsize(os.path.join(sous_dossier, nom_fichier))
    piece = PieceJointe(
        entite_type="DossierAMM", entite_id=dossier.id, type_document="Accusé de Réception (DPML)",
        nom_fichier=nom_fichier, chemin_fichier="/".join(["DossierAMM", str(dossier.id), nom_fichier]),
        taille_octets=taille, televerse_par_id=None,
    )
    db.session.add(piece)
    return piece


def marquer_recevabilite(dossier, acteur, decision, motif=None):
    if dossier.statut != "soumis":
        raise ErreurWorkflow("Le contrôle de recevabilité n'est possible que sur un dossier soumis.")
    if acteur.role_systeme != "administrateur_dpml":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")

    ancien = dossier.statut
    if decision == "recevable":
        dossier.statut = "recevable"
        enregistrer_audit(dossier, "Dossier déclaré recevable", acteur, ancien, dossier.statut)
        _generer_accuse_reception(dossier)
        notifier(dossier.demandeur, "accuse_reception",
                 f"Accusé de Réception disponible pour le dossier {dossier.numero} (généré par la DPML) — "
                 "consultable depuis la fiche du dossier, rubrique Documents.",
                 lien=f"/dossiers/{dossier.id}")
        # Transition automatique immédiate — actée séparément (acteur=None) pour que la
        # piste d'audit distingue clairement la décision humaine de la bascule système.
        ancien2 = dossier.statut
        dossier.statut = "evaluation_en_cours"
        enregistrer_audit(dossier, "Passage automatique en évaluation technique", None, ancien2, dossier.statut)
        notifier_tous("evaluateur_amm", "evaluation_a_traiter",
                      f"Dossier {dossier.numero} recevable, à évaluer.", lien=f"/dossiers/{dossier.id}")
    elif decision == "irrecevable":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour déclarer un dossier irrecevable.")
        dossier.statut = "irrecevable"
        dossier.motif_decision = motif.strip()
        dossier.date_decision = datetime.utcnow()
        enregistrer_audit(dossier, "Dossier déclaré irrecevable", acteur, ancien, dossier.statut, commentaire=motif)
        notifier(dossier.demandeur, "irrecevable",
                 f"Dossier {dossier.numero} déclaré irrecevable : {motif}", lien=f"/dossiers/{dossier.id}")
    else:
        raise ErreurWorkflow("Décision de recevabilité inconnue.")


def deposer_avis_evaluation(dossier, acteur, module_concerne, valeur, commentaire):
    if dossier.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Un avis d'évaluation ne peut être déposé que sur un dossier en évaluation.")
    if acteur.role_systeme != "evaluateur_amm":
        raise ErreurWorkflow("Rôle non autorisé pour cette action.")
    if valeur == "complement_requis" and not (commentaire and commentaire.strip()):
        raise ErreurWorkflow("Un motif détaillé est obligatoire pour demander un complément.")
    if valeur not in ("favorable", "complement_requis", "recommandation_rejet"):
        raise ErreurWorkflow("Valeur d'avis inconnue.")

    avis = AvisEvaluationMA(dossier_id=dossier.id, evaluateur_id=acteur.id,
                             module_concerne=module_concerne, valeur=valeur, commentaire=commentaire)
    db.session.add(avis)
    db.session.flush()
    enregistrer_audit(dossier, f"Avis d'évaluation déposé ({module_concerne} : {valeur})",
                       acteur, dossier.statut, dossier.statut, commentaire=commentaire)

    if valeur == "complement_requis":
        ancien = dossier.statut
        dossier.statut = "complement_requis"
        jours = int(get_parametre("MA", "delai_reponse_complement_jours", default=90))
        dossier.date_limite_reponse_complement = datetime.utcnow() + timedelta(days=jours)
        enregistrer_audit(dossier, "Passage en complément requis", acteur, ancien, dossier.statut, commentaire=commentaire)
        notifier(dossier.demandeur, "complement_requis",
                 f"Complément requis sur le dossier {dossier.numero} ({module_concerne}) : {commentaire}. "
                 f"Délai de réponse : {jours} jours.",
                 lien=f"/dossiers/{dossier.id}")
    # Si "favorable" ou "recommandation_rejet" : le dossier reste en evaluation_en_cours ;
    # c'est decider() (directeur_dpml) qui statue sur la base des avis consignés — jamais
    # l'évaluateur seul (séparation des rôles, règle transversale n°6).


def decider(dossier, acteur, decision, motif=None):
    if dossier.statut != "evaluation_en_cours":
        raise ErreurWorkflow("Une décision ne peut être prise que sur un dossier en évaluation.")
    if acteur.role_systeme != "directeur_dpml":
        # Contrôle serveur strict : evaluateur_amm ne doit jamais pouvoir approuver/rejeter,
        # même par appel direct de route (critère d'acceptation MA #2).
        raise ErreurWorkflow("Seul le directeur DPML peut approuver ou rejeter un dossier.")

    ancien = dossier.statut
    if decision == "approuve":
        dossier.statut = "approuve"
        dossier.date_decision = datetime.utcnow()
        if dossier.type_procedure == "retrait":
            dossier.produit.statut_amm_courant = "retiree"
            enregistrer_audit(dossier, "Dossier de retrait approuvé", acteur, ancien, dossier.statut)
            notifier(dossier.demandeur, "decision",
                     f"Retrait du produit {dossier.produit.libelle} approuvé ({dossier.numero}).",
                     lien=f"/dossiers/{dossier.id}")
            # Point d'extension documenté : notification destinée au futur module MC
            # (suivi de la présence résiduelle du produit sur le marché), non livré ici —
            # adressée pour l'instant à administrateur_dpml pour ne pas la perdre.
            notifier_tous("administrateur_dpml", "retrait_a_suivre",
                          f"Produit {dossier.produit.libelle} retiré ({dossier.numero}) — "
                          f"suivi de présence résiduelle sur le marché à assurer (module MC non livré).",
                          lien=f"/dossiers/{dossier.id}")
        else:
            annees = int(get_parametre("MA", "duree_validite_amm_annees", default=5))
            dossier.date_validite_amm = date.today() + relativedelta(years=annees)
            dossier.produit.statut_amm_courant = "active"
            jours_retrait = int(get_parametre("MA", "delai_retrait_document_jours", default=10))
            date_limite_retrait = date.today() + timedelta(days=jours_retrait)
            dossier.date_limite_retrait_document = date_limite_retrait
            enregistrer_audit(dossier, "Dossier approuvé", acteur, ancien, dossier.statut)
            notifier(dossier.demandeur, "decision",
                     f"Dossier {dossier.numero} approuvé. AMM valide jusqu'au "
                     f"{dossier.date_validite_amm.strftime('%d/%m/%Y')}. Le document physique (certificat AMM) "
                     f"peut être retiré à la DPML jusqu'au {date_limite_retrait.strftime('%d/%m/%Y')} "
                     f"({jours_retrait} jours).",
                     lien=f"/dossiers/{dossier.id}")
    elif decision == "rejete":
        if not motif or not motif.strip():
            raise ErreurWorkflow("Un motif est obligatoire pour rejeter un dossier.")
        dossier.statut = "rejete"
        dossier.motif_decision = motif.strip()
        dossier.date_decision = datetime.utcnow()
        enregistrer_audit(dossier, "Dossier rejeté", acteur, ancien, dossier.statut, commentaire=motif)
        notifier(dossier.demandeur, "decision", f"Dossier {dossier.numero} rejeté : {motif}",
                 lien=f"/dossiers/{dossier.id}")
    else:
        raise ErreurWorkflow("Décision inconnue.")


def deposer_reponse_complement(dossier, acteur, donnees_ctd=None):
    if dossier.statut != "complement_requis":
        raise ErreurWorkflow("Une réponse ne peut être déposée que sur un dossier en complément requis.")
    if acteur.id != dossier.demandeur_id:
        raise ErreurWorkflow("Seul le demandeur propriétaire peut répondre à ce complément.")
    if donnees_ctd:
        modifier_ctd(dossier, acteur, donnees_ctd)
    ancien = dossier.statut
    dossier.statut = "evaluation_en_cours"
    dossier.date_limite_reponse_complement = None
    # Le délai légal repart : le temps de réponse du demandeur ne s'impute pas
    # sur celui de l'administration.
    import suivi
    suivi.reprendre_delai(dossier, acteur, motif="réponse au complément déposée")
    enregistrer_audit(dossier, "Réponse au complément déposée, retour en évaluation", acteur, ancien, dossier.statut)
    notifier_tous("evaluateur_amm", "reponse_complement_recue",
                  f"Réponse au complément reçue sur le dossier {dossier.numero}.", lien=f"/dossiers/{dossier.id}")


def cloturer_si_delai_depasse(dossier):
    """Action système (acteur=None) — appelée par delais.executer_verifications_delais()."""
    if dossier.statut != "complement_requis" or not dossier.date_limite_reponse_complement:
        return False
    if datetime.utcnow() <= dossier.date_limite_reponse_complement:
        return False
    ancien = dossier.statut
    dossier.statut = "cloture_delai_depasse"
    enregistrer_audit(dossier, "Clôture automatique : délai de réponse au complément dépassé",
                       None, ancien, dossier.statut)
    notifier(dossier.demandeur, "cloture_delai_depasse",
             f"Dossier {dossier.numero} clôturé automatiquement : le délai de réponse au "
             "complément a été dépassé.", lien=f"/dossiers/{dossier.id}")
    return True
