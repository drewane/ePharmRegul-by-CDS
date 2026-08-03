"""
Validation numérique — circuit de signature hiérarchique.

Un document réglementaire n'est pas signé par une seule personne : il remonte
une chaîne de responsabilité, chaque échelon apposant sa validation. Le
document final n'est produit qu'à la dernière signature.

CIRCUITS
--------
Dérogation et visa technique — signature du Directeur DPML :
    Chef de service Homologation → Sous-directeur du Médicament → Directeur DPML

Autorisation de mise sur le marché — signature du Ministre de la Santé :
    Chef de service → Sous-directeur → Directeur DPML
                    → Secrétaire général du Ministère → Ministre de la Santé

GARANTIES
---------
* L'ordre est garanti par construction : une étape ne s'ouvre que si toutes
  celles qui la précèdent sont validées.
* Chaque signature est nominative, horodatée et porte une empreinte
  vérifiable ; tout est écrit au journal d'audit.
* Un refus à n'importe quel échelon arrête le circuit et renvoie le dossier.
* Le document PDF n'est produit qu'à la signature finale — jamais avant.
"""
import hashlib
from datetime import datetime

from audit import enregistrer_audit
from erreurs import ErreurWorkflow
from models import EtapeValidation, db
from notifications import notifier, notifier_tous
from permissions import ROLES

# Circuits déclaratifs : ajouter un échelon ne demande aucune reprise du moteur.
CIRCUITS = {
    "derogation": ["chef_service_amm", "sous_directeur_medicament", "directeur_dpml"],
    "visa_technique": ["chef_service_amm", "sous_directeur_medicament", "directeur_dpml"],
    "amm": ["chef_service_amm", "sous_directeur_medicament", "directeur_dpml",
            "secretaire_general_ms", "ministre_sante"],
}

LIBELLE_CIRCUIT = {
    "derogation": "Dérogation spéciale",
    "visa_technique": "Visa technique",
    "amm": "Autorisation de mise sur le marché",
}


# ---------------------------------------------------------------------------
# Consultation
# ---------------------------------------------------------------------------
def etapes(entite):
    return (EtapeValidation.query
            .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
            .order_by(EtapeValidation.ordre).all())


def circuit_ouvert(entite):
    return bool(etapes(entite))


def etape_courante(entite):
    """Première étape non encore validée — celle qui attend une signature."""
    for e in etapes(entite):
        if e.statut == "en_attente":
            return e
        if e.statut == "refusee":
            return None          # circuit interrompu
    return None                  # circuit achevé


def circuit_acheve(entite):
    liste = etapes(entite)
    return bool(liste) and all(e.statut == "validee" for e in liste)


def circuit_refuse(entite):
    return any(e.statut == "refusee" for e in etapes(entite))


def progression(entite):
    """(nombre de signatures apposées, nombre total d'échelons)."""
    liste = etapes(entite)
    return sum(1 for e in liste if e.statut == "validee"), len(liste)


def peut_signer(entite, user):
    """Cet utilisateur est-il l'échelon attendu maintenant ?"""
    if user is None:
        return False
    e = etape_courante(entite)
    return e is not None and e.role_requis == user.role_systeme


# ---------------------------------------------------------------------------
# Ouverture du circuit
# ---------------------------------------------------------------------------
def ouvrir_circuit(entite, circuit, acteur, lien=None):
    """Crée les étapes du circuit et alerte le premier échelon."""
    if circuit not in CIRCUITS:
        raise ErreurWorkflow(f"Circuit de validation inconnu : {circuit}")
    if circuit_ouvert(entite):
        raise ErreurWorkflow("Un circuit de validation est déjà ouvert pour ce document.")

    for ordre, role in enumerate(CIRCUITS[circuit], start=1):
        db.session.add(EtapeValidation(
            entite_type=entite.__class__.__name__, entite_id=entite.id,
            circuit=circuit, ordre=ordre, role_requis=role,
            libelle_role=ROLES.get(role, role)))
    db.session.flush()

    enregistrer_audit(
        entite,
        f"Circuit de validation ouvert — {LIBELLE_CIRCUIT.get(circuit, circuit)} "
        f"({len(CIRCUITS[circuit])} échelons)", acteur)
    _alerter_echelon(entite, lien)
    return etapes(entite)


def _alerter_echelon(entite, lien=None):
    e = etape_courante(entite)
    if e is None:
        return
    reference = getattr(entite, "numero", f"#{entite.id}")
    notifier_tous(e.role_requis, "validation_attendue",
                  f"Votre validation est attendue sur {reference} "
                  f"({LIBELLE_CIRCUIT.get(e.circuit, e.circuit)}).", lien=lien)


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------
def _empreinte(entite, etape, acteur, horodatage):
    """Empreinte de la signature : identifie le signataire, l'échelon et l'instant."""
    base = (f"{entite.__class__.__name__}#{entite.id}|{etape.ordre}|"
            f"{acteur.email}|{horodatage.isoformat()}")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def signer(entite, acteur, commentaire=None, lien=None):
    """Appose la signature de l'échelon courant.

    Renvoie (étape signée, circuit_achevé). Le document final est produit par
    l'appelant lorsque le circuit est achevé — c'est lui qui sait quel document
    générer.
    """
    e = etape_courante(entite)
    if e is None:
        if circuit_refuse(entite):
            raise ErreurWorkflow("Ce circuit a été interrompu par un refus.")
        raise ErreurWorkflow("Aucune signature n'est attendue sur ce document.")
    if e.role_requis != acteur.role_systeme:
        raise ErreurWorkflow(
            f"Cette signature revient au « {e.libelle_role} ». "
            f"Votre profil ne permet pas d'apposer cet échelon.")

    maintenant = datetime.utcnow()
    e.statut = "validee"
    e.validateur_id = acteur.id
    e.commentaire = (commentaire or "").strip() or None
    e.date_validation = maintenant
    e.signature = _empreinte(entite, e, acteur, maintenant)

    faits, total = progression(entite)
    enregistrer_audit(
        entite,
        f"Validation numérique {faits}/{total} apposée par {acteur.nom_complet} "
        f"({e.libelle_role})", acteur)

    acheve = circuit_acheve(entite)
    if not acheve:
        _alerter_echelon(entite, lien)
    return e, acheve


def refuser(entite, acteur, motif, lien=None):
    """Interrompt le circuit. Le motif est obligatoire : un refus se justifie."""
    e = etape_courante(entite)
    if e is None:
        raise ErreurWorkflow("Aucune signature n'est attendue sur ce document.")
    if e.role_requis != acteur.role_systeme:
        raise ErreurWorkflow(
            f"Seul le « {e.libelle_role} » peut se prononcer à cet échelon.")
    if not (motif or "").strip():
        raise ErreurWorkflow("Un refus de validation doit être motivé.")

    e.statut = "refusee"
    e.validateur_id = acteur.id
    e.commentaire = motif.strip()
    e.date_validation = datetime.utcnow()
    enregistrer_audit(
        entite, f"Validation REFUSÉE par {acteur.nom_complet} ({e.libelle_role}) : "
                f"{e.commentaire}", acteur)
    return e


def reinitialiser(entite, acteur):
    """Rouvre un circuit interrompu, après correction du dossier."""
    if not circuit_refuse(entite):
        raise ErreurWorkflow("Seul un circuit interrompu par un refus peut être relancé.")
    for e in etapes(entite):
        e.statut = "en_attente"
        e.validateur_id = None
        e.commentaire = None
        e.signature = None
        e.date_validation = None
    enregistrer_audit(entite, "Circuit de validation relancé après correction", acteur)
    _alerter_echelon(entite)
    return etapes(entite)
