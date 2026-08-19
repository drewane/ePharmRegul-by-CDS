"""
Machine à états du dossier : statuts, transitions, acteurs, notifications.

UNE SEULE DÉCLARATION
---------------------
`TRANSITIONS` dit tout : d'où l'on part, où l'on va, qui a le droit, s'il faut
motiver, qui est prévenu. Les boutons d'action, le bandeau de statut et la
timeline se construisent en la LISANT. Rien ne se code en dur dans un gabarit :
c'est ainsi qu'un écran finit par offrir une action que le serveur refuse.

    brouillon
      └─ soumettre ──────────► en_attente_confirmation   (paiement à valider)
                                 └─ valider_paiement ───► en_attente_recevabilite
                                 └─ rejeter_paiement ───► brouillon
    en_attente_recevabilite
      ├─ declarer_recevable ─► recevable
      └─ demander_complement ► a_completer ──► (re-soumission) ► en_attente_recevabilite
    recevable ─ envoyer_commission ─► en_commission
    en_commission ─ retour_service ─► retour_homologation
    retour_homologation
      ├─ valider ────────────► valide ─► amm_a_signer ─► amm_signee
      ├─ demander_complement ► a_completer
      └─ rejeter ────────────► rejete

DEUX VOCABULAIRES, UNE SEULE VÉRITÉ
------------------------------------
Le dossier portait déjà des statuts (`soumis`, `evaluation_en_cours`,
`approuve`…). Le cahier des charges en nomme d'autres. Plutôt que de migrer
mille lignes et quinze suites de tests, `ALIAS` fait correspondre les anciens
aux nouveaux en LECTURE ; l'écriture, elle, se fait toujours dans le
vocabulaire canonique. Les dossiers antérieurs restent lisibles sans conversion.

CE QUE LE MOTEUR GARANTIT
-------------------------
  * une transition inconnue depuis l'état courant est refusée ;
  * un acteur sans le rôle requis est refusé, même s'il forge la requête ;
  * un motif obligatoire manquant est refusé ;
  * chaque passage est journalisé — qui, quand, d'où vers où, pourquoi ;
  * les notifications déclarées partent, et elles seules.
"""
from datetime import datetime

from audit import enregistrer_audit
from erreurs import ErreurWorkflow

# ---------------------------------------------------------------------------
# Statuts
# ---------------------------------------------------------------------------
# code → (libellé, couleur de pastille, terminal ?)
STATUTS = {
    "brouillon": ("Brouillon", "secondary", False),
    "en_attente_confirmation": ("En attente de confirmation du paiement",
                                "info", False),
    "en_attente_recevabilite": ("En attente de recevabilité", "info", False),
    "a_completer": ("À compléter", "warning", False),
    "recevable": ("Dossier recevable", "primary", False),
    "en_commission": ("En commission", "primary", False),
    "retour_homologation": ("Retour au service d'homologation", "primary",
                            False),
    "valide": ("Validé par la direction", "success", False),
    "amm_a_signer": ("AMM à signer par le ministre", "success", False),
    "amm_signee": ("AMM signée", "success", True),
    "rejete": ("Rejeté", "danger", True),
    "irrecevable": ("Irrecevable", "danger", True),
    "cloture_delai_depasse": ("Clôturé — délai dépassé", "dark", True),
}

# Ordre du parcours nominal, pour la timeline.
PARCOURS = ["brouillon", "en_attente_confirmation", "en_attente_recevabilite",
            "recevable", "en_commission", "retour_homologation", "valide",
            "amm_a_signer", "amm_signee"]

# Anciens statuts → statut canonique. Lecture seulement : rien n'est réécrit
# en base, et un dossier de 2025 reste affichable sans migration.
ALIAS = {
    "soumis": "en_attente_confirmation",
    "evaluation_en_cours": "en_commission",
    "complement_requis": "a_completer",
    "approuve": "valide",
}


def statut_canonique(dossier_ou_code):
    """Statut du dossier dans le vocabulaire de la machine à états."""
    code = getattr(dossier_ou_code, "statut", dossier_ou_code) or "brouillon"
    return ALIAS.get(code, code)


def libelle(code):
    return STATUTS.get(statut_canonique(code), (code, "secondary", False))[0]


def couleur(code):
    return STATUTS.get(statut_canonique(code), (code, "secondary", False))[1]


def est_terminal(dossier_ou_code):
    return STATUTS.get(statut_canonique(dossier_ou_code),
                       (None, None, False))[2]


# ---------------------------------------------------------------------------
# Rôles habilités
# ---------------------------------------------------------------------------
# Le vocabulaire du cahier des charges est traduit une fois, dans
# matrice_acces.CORRESPONDANCE_ROLES ; on emploie ici les rôles réels.
DEPOSANT = ("demandeur_externe",)
FINANCIER = ("responsable_financier",)
HOMOLOGATION = ("chef_service_amm", "chef_bureau")
COMMISSION = ("chef_service_amm", "membre_commission_specialisee")
DIRECTION = ("directeur_dpml",)
# La mise en ligne de l'acte signé relève du service, pas du cabinet.
SERVICE = ("chef_service_amm", "chef_bureau")
ADMIN = ("administrateur_dpml",)


# ---------------------------------------------------------------------------
# Effets
# ---------------------------------------------------------------------------
# Certaines transitions PRODUISENT quelque chose : la validation du directeur
# fait naître le certificat et l'AMM. Plutôt que d'importer ici le code
# documentaire — ce qui ferait dépendre le moteur de ce qu'il déclenche — les
# modules concernés s'inscrivent, et la transition ne nomme que l'effet.
EFFETS = {}


def enregistrer_effet(nom, fonction):
    """Rattache une fonction `(dossier, acteur, transition)` à un nom d'effet."""
    EFFETS[nom] = fonction


# ---------------------------------------------------------------------------
# Gardes
# ---------------------------------------------------------------------------
# Un rôle peut avoir le droit d'agir sans que le dossier soit en état de
# recevoir l'action. Le directeur a bien qualité pour valider — mais pas un
# dossier vide. La garde exprime cette seconde condition, qui porte sur la
# CHOSE et non sur la personne.
#
# Une garde reçoit le dossier et rend la liste des empêchements, en clair, ou
# rien. Le message est destiné à l'écran : il doit dire ce qui manque, pas
# qu'un contrôle a échoué.
GARDES = {}


def enregistrer_garde(nom, fonction):
    """Rattache une fonction `(dossier) -> [motifs]` à un nom de garde."""
    GARDES[nom] = fonction


def obstacles(dossier, t):
    """Ce qui empêche cette transition maintenant. Liste vide = rien.

    Fonction pure, comme `transitions_autorisees` : l'interface s'en sert pour
    griser un bouton et en donner la raison, sans rien modifier.
    """
    nom = t.get("garde")
    if not nom:
        return []
    garde = GARDES.get(nom)
    if garde is None:
        # Fail-closed : une garde déclarée mais absente bloque, elle n'ouvre
        # pas. Un contrôle qu'on a oublié de brancher ne doit pas se traduire
        # par une autorisation délivrée.
        return [f"Le contrôle « {nom} » n'est pas disponible."]
    return list(garde(dossier) or [])


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
# Chaque entrée : depuis · action · vers · libellé du bouton · rôles ·
# motif obligatoire · destinataires notifiés · ton du bouton · effet éventuel
TRANSITIONS = [
    {"depuis": "brouillon", "action": "soumettre",
     "vers": "en_attente_confirmation",
     "libelle": "Soumettre la demande", "roles": DEPOSANT + ADMIN,
     "motif_requis": False, "notifie": ("deposant", "responsable_financier"),
     "ton": "primary",
     "aide": "Ouvre la notification de paiement puis le choix du moyen."},

    {"depuis": "en_attente_confirmation", "action": "valider_paiement",
     "vers": "en_attente_recevabilite",
     "libelle": "Valider le paiement", "roles": FINANCIER,
     "motif_requis": False,
     "notifie": ("deposant", "chef_service_amm", "chef_bureau"),
     "ton": "success",
     "aide": "Constate l'encaissement et saisit le service instructeur."},

    {"depuis": "en_attente_confirmation", "action": "rejeter_paiement",
     "vers": "brouillon",
     "libelle": "Rejeter la preuve de paiement", "roles": FINANCIER,
     "motif_requis": True, "notifie": ("deposant",), "ton": "outline-danger",
     "aide": "Le dossier retourne au déposant pour un nouveau règlement."},

    {"depuis": "en_attente_recevabilite", "action": "declarer_recevable",
     "vers": "recevable",
     "libelle": "Déclarer recevable", "roles": HOMOLOGATION,
     "motif_requis": False, "notifie": ("deposant",), "ton": "success",
     "aide": "Après examen de la liste de contrôle."},

    {"depuis": "en_attente_recevabilite", "action": "demander_complement",
     "vers": "a_completer",
     "libelle": "Demander un complément", "roles": HOMOLOGATION,
     "motif_requis": True, "notifie": ("deposant",), "ton": "outline-warning",
     "aide": "Les éléments manquants sont précisés au déposant."},

    {"depuis": "en_attente_recevabilite", "action": "declarer_irrecevable",
     "vers": "irrecevable",
     "libelle": "Déclarer irrecevable", "roles": HOMOLOGATION,
     "motif_requis": True, "notifie": ("deposant",), "ton": "outline-danger",
     "aide": "Décision motivée, mettant fin à l'instruction."},

    {"depuis": "a_completer", "action": "repondre_complement",
     "vers": "en_attente_recevabilite",
     "libelle": "Transmettre les compléments", "roles": DEPOSANT + ADMIN,
     "motif_requis": False,
     "notifie": ("chef_service_amm", "chef_bureau"), "ton": "primary",
     "aide": "Le délai légal reprend à cette transmission."},

    {"depuis": "recevable", "action": "envoyer_commission",
     "vers": "en_commission",
     "libelle": "Inscrire en commission", "roles": HOMOLOGATION,
     "motif_requis": False, "notifie": ("deposant",), "ton": "primary",
     "aide": "Le dossier suit son cours dans les commissions successives."},

    {"depuis": "en_commission", "action": "retour_service",
     "vers": "retour_homologation",
     "libelle": "Retour au service d'homologation", "roles": COMMISSION,
     "motif_requis": False, "notifie": ("chef_service_amm",), "ton": "primary",
     "aide": "Les avis de commission sont consolidés."},

    {"depuis": "en_commission", "action": "demander_complement_commission",
     "vers": "a_completer",
     "libelle": "Demander un complément", "roles": COMMISSION + HOMOLOGATION,
     "motif_requis": True, "notifie": ("deposant",), "ton": "outline-warning",
     "aide": "Suspend le délai légal jusqu'à la réponse."},

    # C'est ici que les actes naissent. L'arbitrage retenu veut que la
    # validation du directeur close la procédure électronique et produise
    # d'un même geste le certificat et l'AMM : deux gestes séparés, c'est un
    # dossier validé dont l'acte n'est jamais édité.
    {"depuis": "retour_homologation", "action": "valider",
     "vers": "valide",
     "libelle": "Valider le dossier", "roles": DIRECTION,
     "motif_requis": False,
     "notifie": ("deposant", "chef_service_amm"), "ton": "success",
     "effet": "generer_actes",
     "garde": "dossier_instruit",
     "aide": "Génère le certificat d'homologation et l'AMM à signer."},

    {"depuis": "retour_homologation", "action": "renvoyer_complement",
     "vers": "a_completer",
     "libelle": "Renvoyer pour complément", "roles": DIRECTION,
     "motif_requis": True, "notifie": ("deposant", "chef_service_amm"),
     "ton": "outline-warning", "aide": ""},

    {"depuis": "retour_homologation", "action": "rejeter",
     "vers": "rejete",
     "libelle": "Rejeter le dossier", "roles": DIRECTION,
     "motif_requis": True, "notifie": ("deposant", "chef_service_amm"),
     "ton": "outline-danger", "aide": "Décision défavorable motivée."},

    # Les actes existent déjà à ce stade ; ce que le service constate ici,
    # c'est leur transmission au cabinet. Nommer cette action « éditer »
    # laisserait croire qu'elle les produit, et l'on chercherait longtemps
    # pourquoi ils sont datés de la veille.
    {"depuis": "valide", "action": "transmettre_signature",
     "vers": "amm_a_signer",
     "libelle": "Transmettre au cabinet pour signature", "roles": SERVICE,
     "motif_requis": False, "notifie": (), "ton": "primary",
     "aide": "Les actes édités sont portés à la signature du ministre."},

    {"depuis": "amm_a_signer", "action": "enregistrer_signature",
     "vers": "amm_signee",
     "libelle": "Enregistrer la signature du ministre", "roles": SERVICE,
     "motif_requis": False, "notifie": ("deposant",), "ton": "success",
     "aide": "Le ministre signe hors système ; on en prend acte ici."},
]


# ---------------------------------------------------------------------------
# Interrogation
# ---------------------------------------------------------------------------
def transitions_autorisees(dossier, role_utilisateur):
    """Transitions ouvertes depuis l'état courant, pour ce rôle.

    Fonction PURE : elle ne lit que le statut du dossier et le rôle, n'écrit
    rien, ne notifie rien. C'est ce qui la rend testable exhaustivement et
    utilisable pour construire l'interface sans effet de bord.
    """
    courant = statut_canonique(dossier)
    return [t for t in TRANSITIONS
            if t["depuis"] == courant and role_utilisateur in t["roles"]]


def transition(action, depuis=None):
    """La transition nommée, éventuellement contrainte à un état de départ."""
    for t in TRANSITIONS:
        if t["action"] == action and (depuis is None or t["depuis"] == depuis):
            return t
    return None


def actions_possibles(statut):
    """Toutes les actions déclarées depuis un statut, tous rôles confondus."""
    courant = statut_canonique(statut)
    return [t["action"] for t in TRANSITIONS if t["depuis"] == courant]


def acteurs_attendus(dossier):
    """Codes des rôles capables de faire avancer le dossier maintenant."""
    courant = statut_canonique(dossier)
    roles = set()
    for t in TRANSITIONS:
        if t["depuis"] == courant:
            roles.update(t["roles"])
    return sorted(roles)


def acteurs_attendus_lisibles(dossier):
    """Les mêmes, en clair, pour l'affichage.

    Deux fonctions plutôt qu'une : « responsable_financier » affiché tel quel
    à un déposant ne lui apprend rien, mais une comparaison de rôle faite sur
    un libellé traduit échoue en silence.
    """
    from permissions import ROLES

    return [ROLES.get(r, r) for r in acteurs_attendus(dossier)]


def attend_le_deposant(dossier):
    """Le dossier est-il dans le camp du déposant ?"""
    return any(r in DEPOSANT for r in acteurs_attendus(dossier))


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def appliquer_transition(dossier, action, acteur, commentaire=None):
    """Fait passer le dossier d'un état à l'autre, en journalisant.

    Refuse — et ne journalise rien — si la transition n'est pas ouverte, si
    l'acteur n'a pas le rôle, ou si un motif obligatoire manque. Le contrôle
    est ici, dans le moteur, et non dans la route : une règle qui ne tient
    qu'à un décorateur de vue tombe au premier script d'import.
    """
    courant = statut_canonique(dossier)
    role = getattr(acteur, "role_systeme", None)

    t = transition(action, depuis=courant)
    if t is None:
        connues = actions_possibles(courant)
        raise ErreurWorkflow(
            f"L'action « {action} » n'est pas ouverte depuis l'état "
            f"« {libelle(courant)} ». "
            + (f"Actions possibles : {', '.join(connues)}." if connues
               else "Ce dossier est clos."))

    if role not in t["roles"]:
        raise ErreurWorkflow(
            f"« {t['libelle']} » relève de : "
            f"{', '.join(t['roles'])}. Votre profil ne le permet pas.")

    motif = (commentaire or "").strip()
    if t["motif_requis"] and not motif:
        raise ErreurWorkflow(
            f"« {t['libelle']} » doit être motivé : le déposant doit savoir "
            "ce qui lui est reproché ou demandé.")

    # L'acteur a qualité, mais le dossier est-il en état ? Le contrôle est ici
    # et non dans le gabarit : un garde-fou qui ne tient qu'à un écran ne tient
    # pas — il tombe au premier appel direct.
    empechements = obstacles(dossier, t)
    if empechements:
        raise ErreurWorkflow(
            f"« {t['libelle']} » est impossible en l'état : "
            + " ".join(empechements))

    ancien = dossier.statut
    dossier.statut = t["vers"]
    if hasattr(dossier, "date_maj"):
        dossier.date_maj = datetime.utcnow()
    if t["vers"] in ("valide", "rejete", "irrecevable") \
            and hasattr(dossier, "date_decision") and not dossier.date_decision:
        dossier.date_decision = datetime.utcnow()
    if motif and hasattr(dossier, "motif_decision"):
        dossier.motif_decision = motif

    enregistrer_audit(
        dossier,
        f"{t['libelle']} — {libelle(ancien)} → {libelle(t['vers'])}",
        acteur, ancien_statut=ancien, nouveau_statut=t["vers"],
        commentaire=motif or None)

    # L'effet s'exécute AVANT la notification, et ses erreurs remontent : on
    # ne veut pas prévenir un déposant que son AMM est prête si sa génération
    # a échoué. L'appelant valide la transaction, donc un échec ici annule
    # aussi le changement d'état.
    nom_effet = t.get("effet")
    if nom_effet:
        effet = EFFETS.get(nom_effet)
        if effet is None:
            raise ErreurWorkflow(
                f"La transition « {t['libelle']} » déclare l'effet "
                f"« {nom_effet} », qu'aucun module n'a enregistré.")
        effet(dossier, acteur, t)

    _notifier(dossier, t, acteur, motif)
    return t


def _notifier(dossier, t, acteur, motif):
    """Prévient les destinataires déclarés — eux, et personne d'autre."""
    from notifications import notifier, notifier_tous

    if not t["notifie"]:
        return
    reference = getattr(dossier, "numero_suivi", None) or dossier.numero
    lien = f"/dossiers/{dossier.id}"
    texte = f"Dossier {reference} : {libelle(t['vers'])}."
    if motif:
        texte += f" Motif : {motif}"

    for destinataire in t["notifie"]:
        if destinataire == "deposant":
            if getattr(dossier, "demandeur", None):
                notifier(dossier.demandeur, f"dossier_{t['vers']}", texte,
                         lien=lien)
        else:
            notifier_tous(destinataire, f"dossier_{t['vers']}", texte, lien=lien)


# ---------------------------------------------------------------------------
# Historique et timeline
# ---------------------------------------------------------------------------
def historique(dossier):
    """Changements d'état du dossier, du plus ancien au plus récent."""
    from models import EvenementAudit

    return (EvenementAudit.query
            .filter(EvenementAudit.entite_type == dossier.__class__.__name__,
                    EvenementAudit.entite_id == dossier.id,
                    EvenementAudit.nouveau_statut.isnot(None))
            .order_by(EvenementAudit.horodatage.asc()).all())


def etapes(dossier):
    """Parcours affichable : étapes traversées, étape courante, à venir.

    Les dates viennent de l'historique : la timeline n'est pas une seconde
    source de vérité, c'est une lecture de l'audit.
    """
    courant = statut_canonique(dossier)
    dates = {}
    for evenement in historique(dossier):
        # L'audit peut porter un ancien statut : un dossier ouvert avant la
        # machine à états a été journalisé « soumis », pas
        # « en_attente_confirmation ». On le canonise à la lecture, faute de
        # quoi l'étape atteinte s'afficherait sans date.
        dates.setdefault(statut_canonique(evenement.nouveau_statut),
                         evenement.horodatage)

    # Un dossier rejeté ou irrecevable n'a pas « sauté » les étapes suivantes :
    # il s'est arrêté. On tronque le parcours plutôt que de les afficher
    # comme à venir.
    interrompu = courant in ("rejete", "irrecevable", "cloture_delai_depasse")
    rang = PARCOURS.index(courant) if courant in PARCOURS else -1

    resultat = []
    for i, code in enumerate(PARCOURS):
        if interrompu and code not in dates:
            continue
        resultat.append({
            "code": code, "libelle": STATUTS[code][0],
            "couleur": STATUTS[code][1],
            "atteint": code in dates or (rang >= 0 and i < rang),
            "courant": code == courant,
            "date": dates.get(code),
        })
    if interrompu:
        resultat.append({
            "code": courant, "libelle": STATUTS[courant][0],
            "couleur": STATUTS[courant][1], "atteint": True, "courant": True,
            "date": dates.get(courant),
        })
    return resultat


def prochaine_etape(dossier):
    """Libellé de ce qui est attendu, et de qui — pour le portefeuille."""
    if est_terminal(dossier):
        return None, f"Dossier clos : {libelle(dossier)}"
    ouvertes = [t for t in TRANSITIONS
                if t["depuis"] == statut_canonique(dossier)]
    if not ouvertes:
        return None, "Aucune suite déclarée pour cet état"
    principale = ouvertes[0]
    if attend_le_deposant(dossier):
        return "vous", principale["libelle"]
    return "l'administration", principale["libelle"]


# ---------------------------------------------------------------------------
# Contrôle de cohérence — support des tests
# ---------------------------------------------------------------------------
def verifier_machine():
    """Anomalies structurelles : états inatteignables, culs-de-sac, doublons."""
    anomalies = []
    codes = set(STATUTS)

    for t in TRANSITIONS:
        if t["depuis"] not in codes:
            anomalies.append(f"état de départ inconnu : {t['depuis']}")
        if t["vers"] not in codes:
            anomalies.append(f"état d'arrivée inconnu : {t['vers']}")
        if not t["roles"]:
            anomalies.append(f"{t['action']} n'est ouverte à aucun rôle")
        if not t["libelle"]:
            anomalies.append(f"{t['action']} sans libellé")

    for t in TRANSITIONS:
        nom = t.get("garde")
        if nom and nom not in GARDES:
            anomalies.append(
                f"{t['action']} déclare la garde « {nom} », qu'aucun module "
                "n'a enregistrée")
        nom = t.get("effet")
        if nom and nom not in EFFETS:
            anomalies.append(
                f"{t['action']} déclare l'effet « {nom} », qu'aucun module "
                "n'a enregistré")

    # Une même action ne doit pas partir deux fois du même état.
    vus = set()
    for t in TRANSITIONS:
        cle = (t["depuis"], t["action"])
        if cle in vus:
            anomalies.append(f"transition en double : {cle}")
        vus.add(cle)

    # Tout état non terminal doit avoir une suite, sinon le dossier s'y échoue.
    for code, (_l, _c, terminal) in STATUTS.items():
        if terminal:
            continue
        if not any(t["depuis"] == code for t in TRANSITIONS):
            anomalies.append(f"cul-de-sac : aucune sortie de « {code} »")

    # Tout état doit être atteignable, sauf le point de départ.
    atteignables = {t["vers"] for t in TRANSITIONS} | {"brouillon"}
    for code in codes:
        if code not in atteignables and code != "cloture_delai_depasse":
            anomalies.append(f"état inatteignable : {code}")

    return anomalies
