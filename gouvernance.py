"""
Services de gouvernance des accès (Lot A) : surcharges de fonctionnalités par
utilisateur.

DEUX RÈGLES NON NÉGOCIABLES
---------------------------
1. AUCUNE AUTO-ÉLÉVATION. Attribuer ou retirer une fonctionnalité exige soi-même
   la fonctionnalité `fonctionnalite.attribuer` / `fonctionnalite.retirer`
   (sensibles, donc réservées au super admin), ET nul ne modifie ses propres
   droits — même le super admin. Toute tentative est refusée ET journalisée.
2. JOURNAL APPEND-ONLY. Chaque action et chaque refus laissent une trace
   nominative et horodatée dans la piste d'audit universelle (`EvenementAudit`),
   conformément à la décision d'Étape 1 (pas de table dédiée).

L'écran super admin (Étape 4) appellera ces fonctions ; elles portent le
contrôle serveur, indépendamment de tout masquage de bouton.
"""
from datetime import datetime

from audit import enregistrer_audit
from models import Fonctionnalite, SurchargeFonctionnalite, db
from permissions import utilisateur_peut

SENS_VALIDES = ("accorde", "retire")


class ErreurGouvernance(Exception):
    """Refus d'une action de gouvernance (droit absent, auto-élévation, motif…)."""


def _journaliser(acteur, action, cible, commentaire):
    """Trace append-only dans EvenementAudit, puis commit (atomique côté appelant
    pour les succès ; isolé pour les refus qui ne modifient rien d'autre)."""
    enregistrer_audit(cible, action, acteur, commentaire=commentaire)
    db.session.commit()


def _appliquer(acteur, cible, code, sens, permission, motif):
    # 1. L'acteur a-t-il le droit de gérer les fonctionnalités ?
    if not utilisateur_peut(acteur, permission):
        _journaliser(acteur, f"REFUS {permission}", cible if cible is not None else acteur,
                     f"{code} : droit « {permission} » absent — tentative refusée")
        raise ErreurGouvernance(
            "Vous n'avez pas le droit de gérer les fonctionnalités.")

    # 2. Anti-auto-élévation : jamais sur soi-même.
    if cible is None or getattr(cible, "id", None) == getattr(acteur, "id", None):
        _journaliser(acteur, f"REFUS {permission}", acteur,
                     f"{code} : auto-attribution refusée")
        raise ErreurGouvernance(
            "Auto-attribution refusée : nul ne modifie ses propres droits.")

    # 3. Motif obligatoire.
    motif = (motif or "").strip()
    if not motif:
        raise ErreurGouvernance("Un motif est obligatoire.")

    # 4. La fonctionnalité doit exister au catalogue.
    if db.session.get(Fonctionnalite, code) is None:
        raise ErreurGouvernance(f"Fonctionnalité inconnue : {code}.")

    # 5. Une seule surcharge active par (utilisateur, code) : on remplace.
    SurchargeFonctionnalite.query.filter_by(
        utilisateur_id=cible.id, fonctionnalite_code=code).delete()
    surcharge = SurchargeFonctionnalite(
        utilisateur_id=cible.id, fonctionnalite_code=code, sens=sens,
        motif=motif, par_id=acteur.id, date=datetime.utcnow())
    db.session.add(surcharge)
    enregistrer_audit(cible, f"{permission} : {code} ({sens})", acteur,
                      commentaire=motif)
    db.session.commit()
    return surcharge


def accorder(acteur, cible, code, motif):
    """Accorde `code` à `cible`. Refuse et journalise toute auto-élévation."""
    return _appliquer(acteur, cible, code, "accorde",
                      "fonctionnalite.attribuer", motif)


def retirer(acteur, cible, code, motif):
    """Retire `code` à `cible`. Refuse et journalise toute auto-élévation."""
    return _appliquer(acteur, cible, code, "retire",
                      "fonctionnalite.retirer", motif)


def annuler_surcharge(acteur, cible, code, motif):
    """Supprime la surcharge (retour au défaut du rôle). Mêmes gardes."""
    if not utilisateur_peut(acteur, "fonctionnalite.attribuer"):
        _journaliser(acteur, "REFUS fonctionnalite.attribuer",
                     cible if cible is not None else acteur,
                     f"{code} : droit absent — annulation refusée")
        raise ErreurGouvernance(
            "Vous n'avez pas le droit de gérer les fonctionnalités.")
    if cible is None or cible.id == acteur.id:
        _journaliser(acteur, "REFUS fonctionnalite.attribuer", acteur,
                     f"{code} : auto-modification refusée")
        raise ErreurGouvernance(
            "Auto-modification refusée : nul ne modifie ses propres droits.")
    n = SurchargeFonctionnalite.query.filter_by(
        utilisateur_id=cible.id, fonctionnalite_code=code).delete()
    enregistrer_audit(cible, f"annulation surcharge : {code}", acteur,
                      commentaire=(motif or "").strip() or None)
    db.session.commit()
    return n


def fonctionnalites_effectives(user):
    """Vue « fiche utilisateur » : défaut hérité vs surcharge, distinction visible.

    Retourne une liste triée de dicts {code, module, sensible, defaut, surcharge,
    effective}. `surcharge` ∈ {None, 'accorde', 'retire'}. Alimente l'écran
    super admin ; ne décide de rien (l'autorité reste utilisateur_peut).
    """
    from models import Role
    role = db.session.get(Role, user.role_systeme) if user else None
    defauts = set(role.fonctionnalites_par_defaut) if role else set()
    surcharges = {s.fonctionnalite_code: s.sens
                  for s in SurchargeFonctionnalite.query.filter_by(
                      utilisateur_id=user.id).all()} if user else {}

    lignes = []
    for f in Fonctionnalite.query.order_by(Fonctionnalite.module,
                                           Fonctionnalite.code).all():
        surch = surcharges.get(f.code)
        defaut = f.code in defauts
        effective = (surch == "accorde") or (defaut and surch != "retire")
        lignes.append({
            "code": f.code, "libelle": f.libelle, "module": f.module,
            "sensible": f.sensible, "defaut": defaut, "surcharge": surch,
            "effective": bool(effective),
        })
    return lignes


def compter_super_admins_actifs():
    """Nombre de super administrateurs (administrateur_dpml) actifs."""
    from models import Personne
    return Personne.query.filter_by(role_systeme="administrateur_dpml",
                                    statut_compte="actif").count()


def est_dernier_super_admin(personne):
    """Vrai si `personne` est le SEUL super admin actif restant.

    Sert de garde : le dernier super administrateur ne peut être ni suspendu,
    ni rétrogradé — sans quoi plus personne ne pourrait gérer les accès.
    """
    if personne is None or personne.role_systeme != "administrateur_dpml" \
            or personne.statut_compte != "actif":
        return False
    return compter_super_admins_actifs() <= 1
