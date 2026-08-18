"""
Espace super administrateur — gouvernance des accès (Lot A).

Quatre onglets : inscriptions à valider · rôles & fonctionnalités · utilisateurs
· journal d'audit. Chaque route est gardée par une FONCTIONNALITÉ sensible
(permission_requise → utilisateur_peut), pas par un rôle codé en dur : un super
admin les possède par défaut, mais elles restent délégables.

Le masquage d'un bouton n'est jamais l'unique protection : les actions
engageantes (accorder/retirer une fonctionnalité) passent par `gouvernance.py`,
qui revérifie côté serveur et journalise tout refus.
"""
from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import catalogue_fonctionnalites as cat
import gouvernance as gouv
from audit import enregistrer_audit
from auth import current_user, login_required, permission_requise
from models import (EvenementAudit, Fonctionnalite, Personne, Role,
                    SurchargeFonctionnalite, db)
from notifications import notifier
from permissions import ROLES_ACTIFS

bp = Blueprint("gouvernance", __name__, url_prefix="/gouvernance")


# ---------------------------------------------------------------------------
def _compteurs():
    """Badges partagés par les onglets (pastille des inscriptions en attente)."""
    return {"nb_inscriptions": Personne.query.filter_by(
        statut_compte="en_attente_validation").count()}


def _fonctionnalites_par_module():
    modules = {}
    for f in Fonctionnalite.query.order_by(Fonctionnalite.module,
                                           Fonctionnalite.code).all():
        modules.setdefault(f.module, []).append(f)
    return modules


def _audit_role(code, ajout, retrait):
    """Trace une modification de défauts de rôle. Role a une PK textuelle (pas
    d'`id` entier), donc on écrit l'EvenementAudit directement."""
    db.session.add(EvenementAudit(
        entite_type="Role", entite_id=0, acteur_id=current_user().id,
        action=f"role.gerer : {code}",
        commentaire=f"ajout {sorted(ajout)} / retrait {sorted(retrait)}"))


@bp.route("/")
@login_required
@permission_requise("utilisateur.lister")
def accueil():
    return redirect(url_for("gouvernance.inscriptions"))


# ---------------------------------------------------------------------------
# Onglet 1 — Inscriptions à valider
# ---------------------------------------------------------------------------
@bp.route("/inscriptions")
@login_required
@permission_requise("inscription.valider")
def inscriptions():
    en_attente = (Personne.query
                  .filter_by(statut_compte="en_attente_validation")
                  .order_by(Personne.date_creation.desc()).all())
    return render_template(
        "gouvernance/inscriptions.html", onglet="inscriptions",
        en_attente=en_attente, roles_actifs=ROLES_ACTIFS,
        modules=_fonctionnalites_par_module(), **_compteurs())


@bp.route("/inscriptions/<int:id>/valider", methods=["POST"])
@login_required
@permission_requise("inscription.valider")
def valider(id):
    p = Personne.query.get_or_404(id)
    if p.statut_compte != "en_attente_validation":
        flash("Ce compte n'est pas en attente de validation.", "danger")
        return redirect(url_for("gouvernance.inscriptions"))

    role = request.form.get("role_systeme") or p.role_systeme
    if role not in ROLES_ACTIFS:
        flash("Rôle invalide.", "danger")
        return redirect(url_for("gouvernance.inscriptions"))

    ancien_role = p.role_systeme
    p.role_systeme = role
    p.statut_compte = "actif"
    p.date_decision = datetime.utcnow()
    p.decide_par_id = current_user().id
    enregistrer_audit(
        p, "Inscription validée", current_user(),
        ancien_statut="en_attente_validation", nouveau_statut="actif",
        commentaire=(f"Rôle attribué : {role}" if role != ancien_role else None))
    notifier(p, "compte_valide",
             "Votre compte a été validé par la DPML. Vous pouvez désormais "
             "vous connecter.", lien="/login")
    db.session.commit()

    # Surcharges éventuelles accordées à la validation (chacune revérifiée et
    # journalisée par gouvernance.accorder).
    accordees = 0
    for code in request.form.getlist("surcharge"):
        try:
            gouv.accorder(current_user(), p, code,
                          motif="Accordée à la validation de l'inscription")
            accordees += 1
        except gouv.ErreurGouvernance as e:
            flash(f"Surcharge « {code} » non appliquée : {e}", "warning")

    flash(f"Compte de {p.nom_complet} validé"
          + (f" — {accordees} fonctionnalité(s) accordée(s)" if accordees else "")
          + ".", "success")
    return redirect(url_for("gouvernance.inscriptions"))


@bp.route("/inscriptions/<int:id>/rejeter", methods=["POST"])
@login_required
@permission_requise("inscription.rejeter")
def rejeter(id):
    p = Personne.query.get_or_404(id)
    if p.statut_compte != "en_attente_validation":
        flash("Ce compte n'est pas en attente de validation.", "danger")
        return redirect(url_for("gouvernance.inscriptions"))

    motif = (request.form.get("motif") or "").strip()
    if not motif:
        flash("Le motif de rejet est obligatoire.", "danger")
        return redirect(url_for("gouvernance.inscriptions"))

    p.statut_compte = "rejete"
    p.date_decision = datetime.utcnow()
    p.decide_par_id = current_user().id
    enregistrer_audit(p, "Inscription rejetée", current_user(),
                      ancien_statut="en_attente_validation",
                      nouveau_statut="rejete", commentaire=motif)
    notifier(p, "compte_rejete",
             f"Votre inscription a été rejetée par la DPML. Motif : {motif}",
             lien="/login")
    db.session.commit()
    flash(f"Inscription de {p.nom_complet} rejetée.", "info")
    return redirect(url_for("gouvernance.inscriptions"))


# ---------------------------------------------------------------------------
# Onglet 2 — Rôles & fonctionnalités
# ---------------------------------------------------------------------------
@bp.route("/roles")
@login_required
@permission_requise("role.gerer")
def roles():
    par_categorie = {}
    for r in Role.query.order_by(Role.categorie_code, Role.code).all():
        par_categorie.setdefault(r.categorie_code, []).append(r)
    return render_template("gouvernance/roles.html", onglet="roles",
                           par_categorie=par_categorie,
                           categories=cat.CATEGORIES, **_compteurs())


@bp.route("/roles/<code>", methods=["GET", "POST"])
@login_required
@permission_requise("role.gerer")
def role_edit(code):
    r = db.session.get(Role, code)
    if r is None:
        abort(404)

    if request.method == "POST":
        valides = {f.code for f in Fonctionnalite.query.all()}
        avant = set(r.fonctionnalites_par_defaut)
        apres = set(request.form.getlist("fonctionnalite")) & valides
        if avant != apres:
            r.fonctionnalites_par_defaut = sorted(apres)
            _audit_role(code, apres - avant, avant - apres)
            db.session.commit()
            flash(f"Défauts du rôle « {r.libelle} » mis à jour "
                  f"(+{len(apres - avant)} / −{len(avant - apres)}).", "success")
        else:
            flash("Aucun changement.", "secondary")
        return redirect(url_for("gouvernance.role_edit", code=code))

    return render_template(
        "gouvernance/role_edit.html", onglet="roles", role=r,
        actifs=set(r.fonctionnalites_par_defaut),
        modules=_fonctionnalites_par_module(),
        categorie=cat.CATEGORIES.get(r.categorie_code, r.categorie_code),
        **_compteurs())


# ---------------------------------------------------------------------------
# Onglet 3 — Utilisateurs
# ---------------------------------------------------------------------------
@bp.route("/utilisateurs")
@login_required
@permission_requise("utilisateur.lister")
def utilisateurs():
    q = request.args.get("q", "").strip()
    statut = request.args.get("statut", "")
    role = request.args.get("role", "")
    query = Personne.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Personne.nom_complet.ilike(like),
                                    Personne.email.ilike(like)))
    if statut:
        query = query.filter_by(statut_compte=statut)
    if role:
        query = query.filter_by(role_systeme=role)
    personnes = query.order_by(Personne.nom_complet).all()
    return render_template("gouvernance/utilisateurs.html", onglet="utilisateurs",
                           personnes=personnes, q=q, statut=statut, role=role,
                           roles_actifs=ROLES_ACTIFS, **_compteurs())


@bp.route("/utilisateurs/<int:id>")
@login_required
@permission_requise("utilisateur.lister")
def utilisateur_fiche(id):
    p = Personne.query.get_or_404(id)
    par_module = {}
    for ligne in gouv.fonctionnalites_effectives(p):
        par_module.setdefault(ligne["module"], []).append(ligne)
    return render_template(
        "gouvernance/utilisateur_fiche.html", onglet="utilisateurs", p=p,
        par_module=par_module, roles_actifs=ROLES_ACTIFS,
        dernier_admin=gouv.est_dernier_super_admin(p), **_compteurs())


@bp.route("/utilisateurs/<int:id>/fonctionnalite", methods=["POST"])
@login_required
@permission_requise("utilisateur.lister")
def utilisateur_fonctionnalite(id):
    p = Personne.query.get_or_404(id)
    code = request.form.get("code", "")
    sens = request.form.get("sens", "")
    motif = request.form.get("motif", "")
    try:
        if sens == "accorde":
            gouv.accorder(current_user(), p, code, motif)
        elif sens == "retire":
            gouv.retirer(current_user(), p, code, motif)
        elif sens == "annule":
            gouv.annuler_surcharge(current_user(), p, code, motif)
        else:
            flash("Action inconnue.", "danger")
            return redirect(url_for("gouvernance.utilisateur_fiche", id=id))
        flash("Fonctionnalité mise à jour.", "success")
    except gouv.ErreurGouvernance as e:
        flash(str(e), "danger")
    return redirect(url_for("gouvernance.utilisateur_fiche", id=id))


@bp.route("/utilisateurs/<int:id>/role", methods=["POST"])
@login_required
@permission_requise("role.gerer")
def utilisateur_role(id):
    p = Personne.query.get_or_404(id)
    nouveau = request.form.get("role_systeme", "")
    if nouveau not in ROLES_ACTIFS:
        flash("Rôle invalide.", "danger")
        return redirect(url_for("gouvernance.utilisateur_fiche", id=id))
    if gouv.est_dernier_super_admin(p) and nouveau != "administrateur_dpml":
        flash("Impossible : c'est le dernier super administrateur actif ; "
              "il ne peut être rétrogradé.", "danger")
        return redirect(url_for("gouvernance.utilisateur_fiche", id=id))
    ancien = p.role_systeme
    if ancien != nouveau:
        p.role_systeme = nouveau
        enregistrer_audit(p, "Rôle du compte modifié", current_user(),
                          ancien_statut=ancien, nouveau_statut=nouveau)
        db.session.commit()
        flash("Rôle mis à jour.", "success")
    return redirect(url_for("gouvernance.utilisateur_fiche", id=id))


@bp.route("/utilisateurs/<int:id>/suspendre", methods=["POST"])
@login_required
@permission_requise("utilisateur.suspendre")
def utilisateur_suspendre(id):
    p = Personne.query.get_or_404(id)
    ancien = p.statut_compte
    if ancien == "suspendu":
        p.statut_compte = "actif"
        action = "Compte réactivé"
    else:
        if gouv.est_dernier_super_admin(p):
            flash("Impossible de suspendre le dernier super administrateur "
                  "actif.", "danger")
            return redirect(url_for("gouvernance.utilisateur_fiche", id=id))
        p.statut_compte = "suspendu"
        action = "Compte suspendu"
    enregistrer_audit(p, action, current_user(), ancien_statut=ancien,
                      nouveau_statut=p.statut_compte)
    db.session.commit()
    flash(f"{action}.", "success")
    return redirect(url_for("gouvernance.utilisateur_fiche", id=id))


# ---------------------------------------------------------------------------
# Onglet 4 — Journal d'audit
# ---------------------------------------------------------------------------
@bp.route("/journal")
@login_required
@permission_requise("audit.consulter")
def journal():
    acteur = request.args.get("acteur", "").strip()
    action = request.args.get("action", "").strip()
    query = EvenementAudit.query
    if action:
        query = query.filter(EvenementAudit.action.ilike(f"%{action}%"))
    if acteur:
        like = f"%{acteur}%"
        ids = [x.id for x in Personne.query.filter(db.or_(
            Personne.nom_complet.ilike(like), Personne.email.ilike(like))).all()]
        query = query.filter(EvenementAudit.acteur_id.in_(ids or [-1]))
    evenements = (query.order_by(EvenementAudit.horodatage.desc())
                  .limit(200).all())
    return render_template("gouvernance/journal.html", onglet="journal",
                           evenements=evenements, acteur=acteur, action=action,
                           **_compteurs())
