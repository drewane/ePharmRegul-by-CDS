"""
Moteur des déclarations d'intérêts et des déports.

PRINCIPE
--------
Un agent ou un expert ne doit pas instruire un dossier déposé par un organisme
avec lequel il entretient un lien d'intérêt. Le contrôle ne peut pas reposer
sur la seule vigilance des personnes : il est automatisé et **bloquant**.

TROIS TEMPS
-----------
1. **Déclaration** — chaque agent enregistre ses liens des cinq dernières
   années. L'absence de lien se déclare explicitement (« néant ») : un silence
   ne vaut pas déclaration.
2. **Croisement** — à l'attribution d'un dossier ou à la préparation d'une
   séance, les liens déclarés sont rapprochés du demandeur, du titulaire et du
   fabricant concernés.
3. **Verrouillage** — un lien majeur déclenche un déport : l'accès au dossier
   est refusé, les pièces sont masquées, la participation à la délibération est
   bloquée. Le déport est consigné.

Un lien **mineur** n'empêche pas d'instruire : il est signalé et tracé, mais la
transparence suffit. Seul un lien **majeur** (rémunération, conseil, actions,
participation) impose le déport.
"""
import unicodedata
from datetime import datetime, timedelta

from audit import enregistrer_audit
from erreurs import ErreurWorkflow
from models import (DeclarationInteret, Deport, LienInteret, Personne, db)
from notifications import notifier

# Natures de lien et gravité par défaut
NATURES = {
    "remuneration": ("Rémunération, honoraires, salaire", "majeur"),
    "conseil": ("Activité de conseil, expertise, consultance", "majeur"),
    "actions": ("Détention d'actions ou de parts sociales", "majeur"),
    "participation": ("Participation à un organe de direction", "majeur"),
    "essai_clinique": ("Investigateur ou co-investigateur d'un essai", "majeur"),
    "invitation": ("Invitation à un congrès, prise en charge de frais", "mineur"),
    "parent_proche": ("Lien familial avec un dirigeant ou salarié", "majeur"),
    "autre": ("Autre lien à signaler", "mineur"),
}

# Une DPI se renouvelle chaque année.
VALIDITE_MOIS = 12

# Profils tenus de déclarer : tous ceux qui instruisent, arbitrent ou signent.
PROFILS_ASSUJETTIS = (
    "cadre_dpml", "evaluateur_amm", "evaluateur_interne",
    "membre_commission_specialisee", "membre_commission_nationale",
    "chef_bureau", "chef_service_amm", "chef_service_licences",
    "chef_service_inspection", "chef_service_labo",
    "sous_directeur_medicament", "sous_directeur_etablissements",
    "directeur_dpml", "inspecteur_general", "directeur_general_agence",
    "secretaire_general_ms", "ministre_sante",
)


# ---------------------------------------------------------------------------
# Normalisation — le rapprochement doit résister aux écarts d'écriture
# ---------------------------------------------------------------------------
_MOTS_VIDES = {"sa", "sarl", "sas", "ltd", "llc", "gmbh", "inc", "plc", "spa",
               "laboratoire", "laboratoires", "labo", "pharma", "pharmaceutique",
               "pharmaceutiques", "group", "groupe", "company", "cie", "et", "de",
               "du", "des", "la", "le", "les", "l", "d"}


def normaliser(nom):
    """Forme comparable d'un nom d'organisme.

    Retire accents, ponctuation, casse et mentions juridiques : « Labo Pharma
    SA » et « laboratoires pharma » doivent se rapprocher.
    """
    v = unicodedata.normalize("NFD", (nom or "").strip().lower())
    v = "".join(c for c in v if unicodedata.category(c) != "Mn")
    v = "".join(c if c.isalnum() or c.isspace() else " " for c in v)
    mots = [m for m in v.split() if m and m not in _MOTS_VIDES]
    return " ".join(sorted(mots))


def _correspond(a, b):
    """Deux organismes désignent-ils vraisemblablement la même entité ?"""
    na, nb = normaliser(a), normaliser(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Recouvrement significatif des mots porteurs
    ma, mb = set(na.split()), set(nb.split())
    if not ma or not mb:
        return False
    commun = ma & mb
    return len(commun) >= 1 and len(commun) >= min(len(ma), len(mb)) * 0.6


# ---------------------------------------------------------------------------
# Déclarations
# ---------------------------------------------------------------------------
def declaration_en_vigueur(personne):
    return (DeclarationInteret.query
            .filter_by(personne_id=personne.id, en_vigueur=True)
            .order_by(DeclarationInteret.version.desc()).first())


def est_assujetti(personne):
    return personne is not None and personne.role_systeme in PROFILS_ASSUJETTIS


def situation(personne):
    """État déclaratif d'une personne — pour l'écran d'administration."""
    d = declaration_en_vigueur(personne)
    if d is None:
        return {"etat": "manquante", "declaration": None,
                "libelle": "Aucune déclaration enregistrée"}
    if d.expiree:
        return {"etat": "expiree", "declaration": d,
                "libelle": f"Déclaration expirée le "
                           f"{d.date_expiration.strftime('%d/%m/%Y')}"}
    return {"etat": "a_jour", "declaration": d,
            "libelle": f"À jour — {len(d.liens)} lien(s) déclaré(s)"
                       if not d.aucun_lien else "À jour — déclaration néant"}


def enregistrer_declaration(personne, liens, aucun_lien=False, commentaire=None,
                             acteur=None):
    """Enregistre une nouvelle version de la DPI. L'ancienne est conservée."""
    if not aucun_lien and not liens:
        raise ErreurWorkflow(
            "Déclarez au moins un lien, ou cochez explicitement « aucun lien ». "
            "Une déclaration vide n'a pas de valeur.")

    precedente = declaration_en_vigueur(personne)
    if precedente:
        precedente.en_vigueur = False
    version = (precedente.version + 1) if precedente else 1

    d = DeclarationInteret(
        personne_id=personne.id, version=version, en_vigueur=True,
        aucun_lien=bool(aucun_lien), commentaire=(commentaire or "").strip() or None,
        date_expiration=datetime.utcnow() + timedelta(days=30 * VALIDITE_MOIS))
    db.session.add(d)
    db.session.flush()

    if not aucun_lien:
        for l in liens:
            nature = l.get("nature", "autre")
            if nature not in NATURES:
                raise ErreurWorkflow(f"Nature de lien inconnue : {nature}")
            organisme = (l.get("organisme") or "").strip()
            if not organisme:
                raise ErreurWorkflow("Chaque lien doit désigner un organisme.")
            db.session.add(LienInteret(
                declaration_id=d.id, organisme=organisme,
                organisme_normalise=normaliser(organisme),
                nature=nature, description=(l.get("description") or "").strip() or None,
                montant_indicatif=l.get("montant") or None,
                annee_debut=l.get("annee_debut") or None,
                annee_fin=l.get("annee_fin") or None,
                gravite=l.get("gravite") or NATURES[nature][1]))
    db.session.flush()
    enregistrer_audit(d, f"Déclaration d'intérêts v{version} enregistrée"
                         + (" (néant)" if aucun_lien else f" — {len(liens)} lien(s)"),
                      acteur or personne)
    return d


# ---------------------------------------------------------------------------
# Croisement
# ---------------------------------------------------------------------------
def organismes_du_dossier(dossier):
    """Organismes en cause dans un dossier : demandeur, titulaire, fabricant."""
    noms = []
    demandeur = getattr(dossier, "demandeur", None)
    if demandeur is not None and getattr(demandeur, "etablissement", None):
        noms.append(demandeur.etablissement.raison_sociale)
    produit = getattr(dossier, "produit", None)
    if produit is not None:
        for attribut in ("titulaire_amm", "fabricant"):
            etab = getattr(produit, attribut, None)
            if etab is not None:
                noms.append(etab.raison_sociale)
    return [n for n in noms if n]


def conflits(personne, dossier):
    """Liens d'intérêt de cette personne avec les organismes de ce dossier."""
    d = declaration_en_vigueur(personne)
    if d is None or d.aucun_lien:
        return []
    cibles = organismes_du_dossier(dossier)
    if not cibles:
        return []
    return [l for l in d.liens if any(_correspond(l.organisme, c) for c in cibles)]


def conflits_majeurs(personne, dossier):
    return [l for l in conflits(personne, dossier) if l.gravite == "majeur"]


# ---------------------------------------------------------------------------
# Déports
# ---------------------------------------------------------------------------
def deport_actif(personne, entite):
    return (Deport.query
            .filter_by(personne_id=personne.id,
                       entite_type=entite.__class__.__name__,
                       entite_id=entite.id, leve=False).first())


def prononcer_deport(personne, entite, motif, lien=None, origine="automatique",
                      acteur=None):
    """Écarte une personne d'un dossier ou d'une séance. Idempotent."""
    existant = deport_actif(personne, entite)
    if existant:
        return existant
    d = Deport(personne_id=personne.id, entite_type=entite.__class__.__name__,
               entite_id=entite.id, lien_interet_id=lien.id if lien else None,
               motif=motif, origine=origine)
    db.session.add(d)
    db.session.flush()
    reference = getattr(entite, "numero", f"#{entite.id}")
    enregistrer_audit(entite,
                      f"Déport prononcé — {personne.nom_complet} écarté(e) : {motif}",
                      acteur or personne)
    notifier(personne, "deport_prononce",
             f"Vous êtes déporté(e) du dossier {reference} : {motif} "
             "L'accès à ce dossier vous est fermé.",
             lien=None)
    return d


def controler_avant_attribution(personne, dossier, acteur=None):
    """Croisement obligatoire avant de confier un dossier.

    Renvoie la liste des liens majeurs détectés. S'il y en a, un déport est
    prononcé et l'attribution doit être refusée par l'appelant.
    """
    majeurs = conflits_majeurs(personne, dossier)
    if not majeurs:
        return []
    motif = ("Lien d'intérêt déclaré avec "
             + ", ".join(sorted({l.organisme for l in majeurs})))
    prononcer_deport(personne, dossier, motif, lien=majeurs[0],
                     origine="automatique", acteur=acteur)
    return majeurs


def controler_seance(session_commission, acteur=None):
    """Croise les membres d'une commission avec les dossiers à l'ordre du jour.

    Renvoie la liste des déports prononcés, à consigner au procès-verbal.
    """
    membres = Personne.query.filter_by(role_systeme=session_commission.role_membre,
                                       statut_compte="actif").all()
    prononces = []
    for inscription in session_commission.inscriptions:
        for membre in membres:
            majeurs = conflits_majeurs(membre, inscription.dossier)
            if not majeurs:
                continue
            motif = ("Lien d'intérêt avec "
                     + ", ".join(sorted({l.organisme for l in majeurs}))
                     + f" — dossier {inscription.dossier.numero}")
            prononcer_deport(membre, inscription.dossier, motif, lien=majeurs[0],
                             origine="automatique", acteur=acteur)
            prononces.append({"membre": membre, "dossier": inscription.dossier,
                              "liens": majeurs})
    return prononces


def lever_deport(deport, acteur, motif):
    """Lève un déport après examen — la levée est elle-même tracée."""
    if deport.leve:
        raise ErreurWorkflow("Ce déport est déjà levé.")
    if not (motif or "").strip():
        raise ErreurWorkflow("La levée d'un déport doit être motivée.")
    from permissions import a_niveau
    if not a_niveau(acteur, 5):
        raise ErreurWorkflow(
            "Seule la direction peut lever un déport, au vu d'un examen motivé.")
    deport.leve = True
    deport.motif_levee = motif.strip()
    deport.leve_par_id = acteur.id
    deport.date_levee = datetime.utcnow()
    enregistrer_audit(deport, f"Déport levé par {acteur.nom_complet} : {motif}", acteur)
    return deport


# ---------------------------------------------------------------------------
# Contrôle d'accès — appelé par la GED et les écrans de dossier
# ---------------------------------------------------------------------------
def acces_autorise(personne, entite):
    """La personne peut-elle accéder à ce dossier ?

    Un déport actif ferme l'accès, quel que soit le rôle : c'est le point du
    dispositif qui doit résister à toutes les exceptions.
    """
    if personne is None:
        return False, "Authentification requise."
    d = deport_actif(personne, entite)
    if d is not None:
        return False, (f"Accès fermé : vous êtes déporté(e) de ce dossier. {d.motif}")
    return True, None


def deports_du_dossier(entite):
    return (Deport.query
            .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
            .order_by(Deport.id).all())


def mention_proces_verbal(session_commission):
    """Texte à porter au procès-verbal de séance."""
    lignes = []
    for inscription in session_commission.inscriptions:
        for d in deports_du_dossier(inscription.dossier):
            if d.leve:
                continue
            lignes.append(
                f"• {d.personne.nom_complet} s'est déporté(e) de l'examen du dossier "
                f"{inscription.dossier.numero} — {d.motif}")
    if not lignes:
        return "Aucun déport n'a été constaté pour cette séance."
    return ("Déports constatés :\n" + "\n".join(lignes))
