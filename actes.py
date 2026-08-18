"""
Certificat d'homologation et autorisation de mise sur le marché.

DEUX ACTES, UN SEUL GESTE
-------------------------
La validation du directeur ne « permet » pas d'éditer les actes : elle les
produit. Séparer la décision de son édition, c'est accepter qu'un dossier
reste validé pendant des semaines sans que l'acte existe — l'attente que le
système est censé supprimer. Les deux documents naissent donc ensemble, à la
seconde où la décision est prise, et portent la même date.

CE QUI EST DÉFINITIF, ET CE QUI NE L'EST PAS
---------------------------------------------
Le certificat d'homologation est un acte de la DPML : le directeur le signe,
il est complet dès sa génération. L'AMM est un acte du ministre, qui signe
hors système : le document produit ici en est le PROJET, marqué comme tel,
jusqu'à ce que le service dépose l'exemplaire signé. Un projet d'AMM qui ne se
distinguerait pas d'une AMM signée est une invitation à l'usage abusif.

QUI PEUT QUOI
-------------
Tout le monde dans la chaîne CONSULTE — c'était la demande explicite : un acte
invisible aux échelons qui l'ont instruit n'est pas traçable. Mais le déposant
ne TÉLÉCHARGE pas le projet : il ne peut se prévaloir que de l'acte signé.
"""
import os
from datetime import datetime, timedelta

import machine_etats as me
import pdf_actes
import pdf_gen
from audit import enregistrer_audit
from erreurs import ErreurWorkflow
from models import db

# ---------------------------------------------------------------------------
# Les deux actes, déclarés
# ---------------------------------------------------------------------------
# code → libellé (fr/en) · signataire · définitif dès génération ? · gabarit
ACTES = {
    "certificat": {
        "libelle": "Certificat d'homologation",
        "libelle_en": "Certificate of Marketing Authorization",
        "signataire": "Le Directeur de la Pharmacie, du Médicament "
                      "et des Laboratoires",
        "signataire_en": "The Director of Pharmacy, Drugs and Laboratories",
        "definitif": True,
        "gabarit": "actes/certificat.html",
        "mention": "Certificat délivré par voie électronique — "
                   "ePharmRegul by CDS.",
    },
    "amm": {
        "libelle": "Autorisation de mise sur le marché",
        "libelle_en": "Marketing Authorization",
        "signataire": "Le Ministre de la Santé publique",
        "signataire_en": "The Minister of Public Health",
        # Signé hors système : ce que l'on produit ici est un projet.
        "definitif": False,
        "gabarit": "actes/amm.html",
        "mention": "PROJET — sans valeur tant que la signature du ministre "
                   "n'est pas déposée.",
        "mention_signee": "Exemplaire signé du ministre déposé au dossier.",
    },
}

ORDRE = ("certificat", "amm")


def _numeroter(code_acte):
    """Numéro d'acte, tiré d'une série propre à l'acte.

    L'AMM ne peut pas emprunter la série des dossiers : `generer_numero("AMM")`
    alimente le compteur des DOSSIERS, et l'acte se retrouverait à porter un
    numéro de la même forme et de la même suite qu'un dossier — deux objets
    distincts que l'on citerait pareillement. La série de l'acte est donc
    séparée, et sa forme aussi : « AMM/CMR/2026/00001 » ne se confond avec
    aucun « AMM-2026-0198 ».
    """
    from models import SequenceNumerotation

    annee = datetime.utcnow().year
    cle = f"ACTE_{code_acte.upper()}"
    seq = SequenceNumerotation.query.filter_by(module=cle, annee=annee).first()
    if seq is None:
        seq = SequenceNumerotation(module=cle, annee=annee, dernier_numero=0)
        db.session.add(seq)
        db.session.flush()
    seq.dernier_numero += 1
    db.session.flush()
    if code_acte == "amm":
        return f"AMM/CMR/{annee}/{seq.dernier_numero:05d}"
    return f"CERT/CMR/{annee}/{seq.dernier_numero:05d}"


DUREE_VALIDITE_ANNEES = 5

# Statuts à partir desquels les actes existent.
STATUTS_AVEC_ACTES = ("valide", "amm_a_signer", "amm_signee", "approuve")


def _dans_n_ans(depart, annees):
    """Même quantième, n années plus tard.

    Compter en jours ferait dériver la date d'autant de fois qu'il y a
    d'années bissextiles dans l'intervalle : une AMM de cinq ans expirerait
    la veille de son anniversaire. Le 29 février, sans équivalent l'année
    d'arrivée, est reporté au 28.
    """
    try:
        return depart.replace(year=depart.year + annees)
    except ValueError:
        return depart.replace(year=depart.year + annees, day=28)


def _repertoire():
    from flask import current_app

    chemin = os.path.join(current_app.instance_path, "actes")
    os.makedirs(chemin, exist_ok=True)
    return chemin


def chemin_pdf(dossier, code_acte):
    return os.path.join(_repertoire(),
                        f"{dossier.numero}-{code_acte}.pdf")


def numero(dossier, code_acte):
    """Numéro de l'acte, tel qu'il figure sur le document."""
    if code_acte == "certificat":
        return dossier.numero_certificat
    return dossier.numero_amm


def existe(dossier, code_acte):
    return bool(numero(dossier, code_acte))


def actes_disponibles(dossier):
    """Les actes existants, dans l'ordre de présentation."""
    return [(code, ACTES[code]) for code in ORDRE if existe(dossier, code)]


def resume(dossier):
    """Ce qu'il faut pour lister les actes à l'écran, calculé une seule fois."""
    signee = est_signee(dossier)
    return [{"code": code, "libelle": a["libelle"],
             "numero": numero(dossier, code),
             "projet": not a["definitif"] and not signee}
            for code, a in actes_disponibles(dossier)]


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------
def generer(dossier, acteur, _transition=None):
    """Produit les deux actes. Branché sur la transition « valider ».

    Idempotent : rappelée sur un dossier qui a déjà ses numéros, elle ne les
    renumérote pas. Un acte renuméroté est un acte que l'on ne retrouve plus.
    """
    if dossier.statut not in STATUTS_AVEC_ACTES:
        raise ErreurWorkflow(
            "Les actes ne s'éditent qu'après la validation de la direction "
            f"(statut actuel : {me.libelle(dossier)}).")

    nouveaux = []
    if not dossier.numero_certificat:
        dossier.numero_certificat = _numeroter("certificat")
        nouveaux.append("certificat")
    if not dossier.numero_amm:
        dossier.numero_amm = _numeroter("amm")
        nouveaux.append("amm")

    if not dossier.date_decision:
        dossier.date_decision = datetime.utcnow()
    if not dossier.date_validite_amm:
        # Validité comptée depuis la décision, non depuis la signature : le
        # délai de cabinet ne doit pas raccourcir le droit du titulaire.
        dossier.date_validite_amm = _dans_n_ans(dossier.date_decision.date(),
                                                DUREE_VALIDITE_ANNEES)

    if nouveaux:
        enregistrer_audit(
            dossier,
            "Actes édités — certificat "
            f"{dossier.numero_certificat}, AMM {dossier.numero_amm}",
            acteur)
    return nouveaux


# La machine à états ne connaît pas ce module : elle ne nomme que l'effet.
me.enregistrer_effet("generer_actes", generer)


def ecrire_pdf(dossier, code_acte, base_url=""):
    """Écrit le PDF de l'acte sur disque et retourne son chemin."""
    if not existe(dossier, code_acte):
        raise ErreurWorkflow("Cet acte n'a pas encore été édité.")

    chemin = chemin_pdf(dossier, code_acte)
    signataire = _signataire(dossier)
    if code_acte == "certificat":
        pdf_actes.generer_certificat(dossier, chemin, signataire,
                                     base_url=base_url)
    else:
        pdf_actes.generer_amm(dossier, chemin, base_url=base_url,
                              signee=est_signee(dossier))
    return chemin


def _signataire(dossier):
    """Qui a validé : lu dans l'audit, pas deviné."""
    from models import EvenementAudit

    evt = (EvenementAudit.query
           .filter(EvenementAudit.entite_type == "DossierAMM",
                   EvenementAudit.entite_id == dossier.id,
                   EvenementAudit.nouveau_statut.in_(("valide", "approuve")))
           .order_by(EvenementAudit.horodatage.desc()).first())
    return evt.acteur if evt else None


def est_signee(dossier):
    """L'exemplaire signé du ministre a-t-il été déposé ?"""
    import amm_signee

    return amm_signee.est_disponible(dossier)


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------
def peut_consulter(dossier, utilisateur):
    """Consulter l'acte à l'écran.

    Ouvert à toute la chaîne, et au déposant pour son propre dossier : c'était
    la demande explicite — un acte que les échelons ayant instruit le dossier
    ne peuvent pas relire n'est pas traçable.
    """
    import permissions as perm

    if utilisateur is None:
        return False
    if utilisateur.est_externe:
        return dossier.demandeur_id == utilisateur.id or _meme_etablissement(
            dossier, utilisateur)
    return perm.a_permission(utilisateur, "voir_tous_dossiers_ma")


def peut_telecharger(dossier, utilisateur):
    """Emporter le PDF.

    Le déposant n'emporte que l'acte SIGNÉ. Tant que le ministre n'a pas
    signé, le document est un projet : le laisser circuler, c'est offrir de
    quoi se prévaloir d'une autorisation qui n'existe pas encore.
    """
    if not peut_consulter(dossier, utilisateur):
        return False
    if utilisateur.est_externe:
        return est_signee(dossier)
    return True


def motif_refus_telechargement(dossier, utilisateur):
    """Pourquoi le téléchargement est fermé — à afficher, pas à deviner."""
    if peut_telecharger(dossier, utilisateur):
        return None
    if utilisateur.est_externe and not est_signee(dossier):
        return ("Ce document est un projet d'acte, en attente de la signature "
                "du ministre. Il sera téléchargeable dès la mise en ligne de "
                "l'exemplaire signé.")
    return "Vous n'êtes pas autorisé à télécharger ce document."


def _meme_etablissement(dossier, utilisateur):
    return (utilisateur.etablissement_rattachement_id is not None
            and dossier.demandeur is not None
            and dossier.demandeur.etablissement_rattachement_id
            == utilisateur.etablissement_rattachement_id)


# ---------------------------------------------------------------------------
# Contexte du gabarit imprimable
# ---------------------------------------------------------------------------
# En-tête officiel bilingue, partagé par les gabarits HTML et les PDF : deux
# rédactions du même en-tête finiraient par différer, et c'est l'en-tête qui
# fait foi de l'émetteur.
ENTETE_FR = pdf_gen.ENTETE_FR
ENTETE_EN = pdf_gen.ENTETE_EN


def contexte(dossier, code_acte):
    """Tout ce dont le gabarit imprimable a besoin, calculé une fois."""
    acte = ACTES[code_acte]
    produit = dossier.produit
    titulaire = (produit.titulaire_amm.raison_sociale
                 if produit and produit.titulaire_amm else None)
    signee = est_signee(dossier)
    return {
        "acte": acte,
        "code_acte": code_acte,
        "dossier": dossier,
        "produit": produit,
        "numero_acte": numero(dossier, code_acte),
        "titulaire": titulaire or "—",
        "signataire": _signataire(dossier),
        "entete_fr": ENTETE_FR,
        "entete_en": ENTETE_EN,
        # Un projet se voit : le filigrane n'est pas décoratif.
        "projet": not acte["definitif"] and not signee,
        "signee": signee,
        "duree_annees": DUREE_VALIDITE_ANNEES,
        "mention_pied": (acte.get("mention_signee") if signee
                         and acte.get("mention_signee") else acte["mention"]),
    }


# ---------------------------------------------------------------------------
# Contrôle de cohérence — support des tests
# ---------------------------------------------------------------------------
def verifier_actes():
    anomalies = []
    for code in ORDRE:
        if code not in ACTES:
            anomalies.append(f"acte présenté mais non déclaré : {code}")
    for code, a in ACTES.items():
        if code not in ORDRE:
            anomalies.append(f"acte déclaré mais jamais présenté : {code}")
        for cle in ("libelle", "libelle_en", "signataire",
                    "signataire_en", "gabarit", "mention"):
            if not a.get(cle):
                anomalies.append(f"{code} : {cle} manquant")

    # L'effet nommé par la transition doit exister, sans quoi la validation du
    # directeur échouerait au moment le plus inopportun.
    valider = me.transition("valider")
    if valider.get("effet") not in me.EFFETS:
        anomalies.append(
            "la transition « valider » déclare un effet non enregistré")
    return anomalies
