"""
Inscription multi-profils et espaces dédiés aux acteurs externes.

Chaque profil dispose d'un parcours d'inscription adapté (un usager n'a pas
d'établissement à déclarer, un grossiste si) et d'un espace personnel listant
ses démarches et ses paiements.

Validation des comptes : seul le profil `usager` est actif immédiatement — il
ne donne accès qu'à la consultation publique, à la déclaration d'effet
indésirable et au signalement de produit. Tous les profils opérateurs
(laboratoire, grossiste, pharmacien, promoteur, industriel) sont créés en
`en_attente_validation` : un agent DPML doit les valider, car ils engagent des
démarches réglementaires.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

import paiements as svc_paiement
from auth import current_user, login_required
from models import Etablissement, Personne, db
from notifications import notifier_tous
from permissions import ROLES_EXTERNES

bp = Blueprint("profils", __name__)

# Profil → (libellé, type d'établissement, établissement requis ?, description)
PROFILS_INSCRIPTION = {
    "usager": (
        "Usager / professionnel de santé", None, False,
        "Consulter le registre public des produits homologués, déclarer un effet "
        "indésirable, signaler un produit suspect."),
    "demandeur_externe": (
        "Industriel / Titulaire d'AMM", "importateur_exportateur", True,
        "Déposer et suivre des demandes d'homologation (AMM), gérer vos produits "
        "et vos lots."),
    "laboratoire_prive": (
        "Laboratoire", "laboratoire_controle", True,
        "Demander des analyses au laboratoire national de contrôle et suivre vos "
        "certificats."),
    "grossiste": (
        "Grossiste-répartiteur", "grossiste_repartiteur", True,
        "Demander et renouveler votre licence d'établissement, suivre les rappels "
        "de lots qui vous concernent."),
    "pharmacien": (
        "Pharmacien d'officine", "officine", True,
        "Gérer la licence de votre officine, signaler un produit suspect, suivre "
        "les alertes de retrait."),
    "promoteur_essai": (
        "Promoteur d'essai clinique", "importateur_exportateur", True,
        "Déposer un protocole d'essai clinique, suivre son autorisation et ses "
        "amendements."),
}

# Profils actifs dès l'inscription (aucune démarche réglementaire engageante)
PROFILS_SANS_VALIDATION = ("usager",)


@bp.route("/inscription")
def inscription_choix():
    """Page d'entrée : l'usager choisit le profil qui le concerne."""
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("profils/choix.html", profils=PROFILS_INSCRIPTION)


@bp.route("/inscription/<profil>", methods=["GET", "POST"])
def inscription(profil):
    if current_user():
        return redirect(url_for("dashboard"))
    if profil not in PROFILS_INSCRIPTION:
        abort(404)
    libelle, type_etab, etab_requis, description = PROFILS_INSCRIPTION[profil]
    valeurs = {"nom_complet": "", "email": "", "raison_sociale": "", "contact": "",
               "adresse": ""}

    if request.method == "POST":
        valeurs = {c: request.form.get(c, "").strip() for c in valeurs}
        email = valeurs["email"].lower()
        mdp = request.form.get("password", "")
        mdp2 = request.form.get("password_confirm", "")

        erreurs = []
        if not valeurs["nom_complet"]:
            erreurs.append("Le nom complet est obligatoire.")
        if not email:
            erreurs.append("L'adresse e-mail est obligatoire.")
        elif Personne.query.filter_by(email=email).first():
            erreurs.append("Cette adresse est déjà utilisée — connectez-vous plutôt.")
        if etab_requis and not valeurs["raison_sociale"]:
            erreurs.append("Le nom de l'établissement est obligatoire pour ce profil.")
        if len(mdp) < 8:
            erreurs.append("Le mot de passe doit contenir au moins 8 caractères.")
        elif mdp != mdp2:
            erreurs.append("Les deux mots de passe ne correspondent pas.")

        if erreurs:
            for e in erreurs:
                flash(e, "danger")
            return render_template("profils/inscription.html", profil=profil,
                                   libelle=libelle, description=description,
                                   etab_requis=etab_requis, valeurs=valeurs)

        etab = None
        if etab_requis:
            etab = Etablissement.query.filter_by(
                raison_sociale=valeurs["raison_sociale"]).first()
            if not etab:
                etab = Etablissement(raison_sociale=valeurs["raison_sociale"],
                                     type=type_etab, adresse=valeurs["adresse"],
                                     statut_licence="en_instruction")
                db.session.add(etab)
                db.session.flush()

        actif = profil in PROFILS_SANS_VALIDATION
        personne = Personne(
            nom_complet=valeurs["nom_complet"], email=email, role_systeme=profil,
            contact=valeurs["contact"],
            etablissement_rattachement_id=etab.id if etab else None,
            statut_compte="actif" if actif else "en_attente_validation")
        personne.set_password(mdp)
        db.session.add(personne)
        db.session.commit()

        if actif:
            session["user_id"] = personne.id
            flash(f"Bienvenue {personne.nom_complet}. Votre compte est actif.", "success")
            return redirect(url_for("dashboard"))

        notifier_tous("administrateur_dpml", "compte_a_valider",
                      f"Nouvelle inscription à valider : {personne.nom_complet} "
                      f"({libelle}).", lien="/administration/utilisateurs")
        db.session.commit()
        flash("Votre demande d'inscription a été enregistrée. Elle doit être validée "
              "par la DPML ; vous serez notifié dès l'activation de votre compte.",
              "info")
        return redirect(url_for("login"))

    return render_template("profils/inscription.html", profil=profil, libelle=libelle,
                           description=description, etab_requis=etab_requis,
                           valeurs=valeurs)


@bp.route("/comptes-demonstration")
def comptes_demonstration():
    """Annuaire des comptes d'essai, groupés par niveau de responsabilité.

    Publier des identifiants n'a de sens que sur un poste de démonstration :
    la page n'existe que si MODE_DEMONSTRATION est vrai, et disparaît dès que
    SIREPH_PRODUCTION=1 est positionné.
    """
    from flask import current_app

    import seed_comptes

    if not current_app.config.get("MODE_DEMONSTRATION"):
        abort(404)
    return render_template(
        "profils/comptes_demonstration.html",
        groupes=seed_comptes.annuaire(),
        manquants=seed_comptes.roles_sans_compte(),
        mot_de_passe=seed_comptes.MOT_DE_PASSE)


@bp.route("/mon-espace")
@login_required
def mon_espace():
    """Espace personnel d'un acteur externe : démarches et paiements."""
    u = current_user()
    if not u.est_externe:
        return redirect(url_for("dashboard"))

    paiements = svc_paiement.paiements_du_redevable(u)
    a_regler = [p for p in paiements if p.statut in ("en_attente", "initie", "rejete",
                                                     "echoue", "expire")]
    total_du = sum(p.montant for p in a_regler)
    return render_template(
        "profils/mon_espace.html", u=u, paiements=paiements, a_regler=a_regler,
        total_du=total_du, libelle_objet=svc_paiement.LIBELLE_OBJET,
        profils=ROLES_EXTERNES)
