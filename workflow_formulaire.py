"""
Enregistrement d'une demande saisie au formulaire enrichi.

Ce module prend une saisie validée et en fait un produit et un dossier. Il ne
valide pas lui-même — `formulaire_demande.valider` s'en charge — mais il
refuse d'écrire une saisie invalide : un contrôle qui ne tient qu'à l'appelant
finit par être contourné.

NUMÉRO ET DATE DE DÉPÔT
-----------------------
Ni l'un ni l'autre ne sont saisissables. Le numéro vient du compteur national,
la date de l'horloge du serveur. Laisser le déposant les renseigner, c'est
accepter qu'il antidate sa demande — et le délai légal se compte à partir de
là.
"""
from datetime import datetime

import formulaire_demande as fd
import referentiels_pharma as ref
from audit import enregistrer_creation
from erreurs import ErreurWorkflow
from models import DossierAMM, Produit, db
from numerotation import generer_numero


def _entier(valeur):
    try:
        return int(float(str(valeur).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def enregistrer(acteur, donnees):
    """Crée le produit et le dossier à partir de la saisie. Retourne le dossier."""
    erreurs = fd.valider(donnees)
    if erreurs:
        raise ErreurWorkflow(
            "La demande comporte des champs invalides ou manquants : "
            + " ".join(list(erreurs.values())[:3]))

    type_produit = donnees["type_produit"].strip()
    est_mta = fd.variant(type_produit) == "mta"

    produit = Produit(
        nom_commercial=donnees["nom_commercial"].strip(),
        denomination_commune_internationale=(donnees.get("dci") or "").strip(),
        forme_pharmaceutique=donnees["forme_pharmaceutique"].strip(),
        dosage=fd.dosage_complet(donnees),
        dosage_valeur=(donnees.get("dosage") or "").strip(),
        dosage_unite=(donnees.get("dosage_unite") or "").strip(),
        nature=fd.nature_correspondante(type_produit),
        categorie=("medicament" if not est_mta else "medicament"),
        titulaire_amm_id=acteur.etablissement_rattachement_id,
        pays_origine=(donnees.get("pays_origine") or "").strip() or None,
        composition_integrale=fd.composition_lisible(type_produit, donnees),
        classe_therapeutique=_libelle_classe(donnees.get("classe_therapeutique")),
        code_atc=(donnees.get("code_atc") or "").strip() or None,
        indications_therapeutiques=_indications(donnees),
        voie_administration=(donnees.get("voie_administration") or "").strip(),
        duree_stabilite=fd.dosage_complet(donnees, "duree_stabilite"),
        conditionnement=(donnees.get("conditionnement") or "").strip() or None,
        quantite_conditionnement=(donnees.get("quantite") or "").strip() or None,
        pharmacien_telephone=(donnees.get("pharmacien_telephone") or "").strip(),
        pharmacien_email=(donnees.get("pharmacien_email") or "").strip(),
    )

    if est_mta:
        produit.categorie_mta = (donnees.get("categorie_mta") or "").strip()
        produit.mecanisme_action = (donnees.get("mecanisme_action") or "").strip()
        produit.excipients = (donnees.get("excipients") or "").strip() or None
        produit.adresse_fabricant = (donnees.get("adresse_fabricant") or "").strip()
        produit.adresse_site_fabrication = (
            donnees.get("adresse_site_fabrication") or "").strip()
        produit.adresse_controle_qualite = (
            donnees.get("adresse_controle_qualite") or "").strip()
        produit.adresse_demandeur = (donnees.get("adresse_demandeur") or "").strip()
        produit.exploitant = (donnees.get("exploitant") or "").strip()
        produit.representant_cameroun = (
            donnees.get("representant_cameroun") or "").strip()
        produit.prix_grossiste_ht = _entier(donnees.get("prix_grossiste"))
        produit.prix_public_cameroun = _entier(donnees.get("prix_public"))

    db.session.add(produit)
    db.session.flush()

    # Le numéro et la date de dépôt sont posés par le système, jamais saisis.
    dossier = DossierAMM(
        numero=generer_numero("AMM"),
        produit_id=produit.id,
        demandeur_id=acteur.id,
        statut="brouillon",
        nature_acte=donnees["nature_acte"].strip(),
        type_produit=type_produit,
        type_dossier=fd.dossier_attendu(type_produit),
        type_procedure=_procedure(donnees["nature_acte"].strip()),
        date_depot=datetime.utcnow(),
    )
    db.session.add(dossier)
    db.session.flush()

    enregistrer_creation(
        dossier, acteur,
        f"Demande enregistrée — {fd.NATURES_ACTE[dossier.nature_acte]}, "
        f"{fd.TYPES_PRODUIT[type_produit][0]}")
    return dossier


# La nature de l'acte du cahier des charges se rattache au type de procédure
# déjà porté par le dossier : on n'introduit pas un second vocabulaire pour
# désigner la même chose.
_PROCEDURES = {
    "octroi": "nouvelle_demande",
    "renouvellement": "renouvellement",
    "variation": "variation",
}


def _procedure(nature_acte):
    return _PROCEDURES.get(nature_acte, "nouvelle_demande")


def _libelle_classe(code):
    """Le code ATC est stocké avec son intitulé : un code seul est illisible
    dans un certificat ou un courrier au déposant."""
    if not code:
        return None
    entree = ref.CLASSES_ATC.get(code.strip())
    return f"{code.strip()} — {entree[0]}" if entree else code.strip()


def _indications(donnees):
    choix = donnees.get("indications") or []
    if isinstance(choix, str):
        choix = [choix]
    return " ; ".join(c for c in choix if c) or None


def url_dossier_technique(dossier):
    """Où diriger le déposant après l'enregistrement.

    Le type de produit pilote le module de constitution : CTD pour les
    médicaments conventionnels, dossier MTA pour la pharmacopée
    traditionnelle. Tant que le module MTA n'est pas livré, on renvoie vers le
    sommaire CTD en le signalant, plutôt que vers une page inexistante.
    """
    from flask import url_for

    sommaire = url_for("ctd.sommaire", dossier_id=dossier.id)
    # Le module MTA fait l'objet d'une livraison distincte. En attendant, on
    # dirige vers le sommaire technique EN LE SIGNALANT : envoyer vers une
    # page inexistante serait pire, et masquer la différence ferait croire
    # qu'un MTA se constitue comme un dossier CTD.
    return sommaire, dossier.type_dossier == "mta"
