"""
SIREPH — Socle commun + Module MA (Enregistrement/AMM) + Module VL (Pharmacovigilance)
Routes Flask : orchestration uniquement. Toute logique métier (transitions de
statut, contrôle de rôle, audit, notifications) vit dans workflow_ma.py /
workflow_vl.py / audit.py / notifications.py / delais.py — jamais ici. Le
module MA reste dans ce fichier ; le module VL est un blueprint (routes_vl.py)
— voir README.md pour la convention adoptée pour les modules suivants.

Lancement :
    pip install -r requirements.txt
    python seed.py
    python app.py
Puis ouvrir http://localhost:5000 (comptes de démonstration : voir seed.py / README.md)
"""
import os
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for, session,
                    flash, send_from_directory, abort)
from flask.sessions import SecureCookieSessionInterface

from models import (db, Personne, Etablissement, Produit, DossierAMM, AvisEvaluationMA,
                     EvenementAudit, Notification, ParametreModule, NotificationVigilance, Inspection,
                     DemandeLicence, Echantillon, SignalementQualite, ProtocoleEssaiClinique, LiberationLot,
                     Paiement, DemandeDerogation, VisaTechnique)
import workflow_ma as wf
import workflow_vl as wfvl
import workflow_ri as wfri
import workflow_li as wfli
import workflow_lt as wflt
import workflow_mc as wfmc
import workflow_ct as wfct
import workflow_lr as wflr
import workflow_derogation as wfd
import workflow_visas as wfv
from audit import enregistrer_audit, enregistrer_creation
from notifications import notifier
from delais import (executer_verifications_delais, executer_verifications_delais_vl, cas_vigilance_en_retard,
                     executer_verifications_delais_ri, plan_action_en_retard, executer_verifications_delais_li,
                     executer_verifications_delais_mc, executer_verifications_delais_ct)
import pdf_gen
from permissions import ROLES, ROLES_ACTIFS
from auth import (current_user, login_required, permission_requise,
                  roles_required)
from erreurs import ErreurWorkflow
from pieces import enregistrer_piece, lister_pieces
from paiements import (deposer_preuve, confirmer as confirmer_paiement, rejeter as rejeter_paiement,
                        lister_paiements)

# Nom commercial affiché. Distinct de l'en-tête officiel MINSANTE/DPML qui
# figure sur les actes : celui-ci identifie l'autorité, celui-là le logiciel.
NOM_APPLICATION = "ePharmRegul"
EDITEUR_APPLICATION = "by CDS"
SOUS_TITRE_APPLICATION = ("Gestion des demandes d'AMM et actes réglementaires "
                          "— DPML")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = os.path.join(BASE_DIR, "static", "certificats")
PAGE_SIZE = 50

app = Flask(__name__)
# Mode démonstration : publie l'annuaire des comptes d'essai et leur mot de
# passe commun. À METTRE À FAUX avant tout déploiement — la variable
# d'environnement SIREPH_PRODUCTION=1 suffit à le faire.
_PRODUCTION = os.environ.get("SIREPH_PRODUCTION") == "1"
app.config["MODE_DEMONSTRATION"] = not _PRODUCTION

# La clé de session signe les cookies d'authentification : connue, elle permet
# de forger la session de n'importe quel compte. Une valeur en dur convient à
# un poste de démonstration, jamais à une application exposée. En production,
# elle vient de l'environnement ou d'un fichier local hors dépôt.
_CLE_FICHIER = os.path.join(BASE_DIR, "instance", "cle_secrete.txt")


def _cle_secrete():
    depuis_env = os.environ.get("SIREPH_SECRET_KEY")
    if depuis_env:
        return depuis_env
    if os.path.exists(_CLE_FICHIER):
        with open(_CLE_FICHIER, encoding="utf-8") as f:
            valeur = f.read().strip()
        if valeur:
            return valeur
    if _PRODUCTION:
        import secrets
        valeur = secrets.token_urlsafe(48)
        os.makedirs(os.path.dirname(_CLE_FICHIER), exist_ok=True)
        with open(_CLE_FICHIER, "w", encoding="utf-8") as f:
            f.write(valeur)
        return valeur
    return "sireph-demo-secret-a-changer-en-production"


app.config["SECRET_KEY"] = _cle_secrete()
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'sireph.db')}"

# Durcissement des cookies. HttpOnly et SameSite ne coûtent rien et valent
# toujours.
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


class SessionSelonLeSchema(SecureCookieSessionInterface):
    """Marque le cookie de session « Secure » seulement si la requête est en HTTPS.

    Ce drapeau interdit au navigateur de renvoyer le cookie hors HTTPS. Piloté
    par une simple variable de configuration, il devient un piège : la même
    application, servie à la fois derrière le tunnel (HTTPS) et sur
    localhost (HTTP), refusait toute connexion locale. Le mot de passe était
    accepté, la session n'était jamais conservée, et aucun message n'apparaissait
    — le symptôme se lisait comme « mes identifiants ne marchent plus ».

    On décide donc par requête. Derrière le tunnel, Cloudflare annonce le
    schéma d'origine dans X-Forwarded-Proto ; en direct, le schéma de la
    requête suffit.
    """

    def get_cookie_secure(self, app):
        from flask import has_request_context
        if not has_request_context():
            return False
        annonce = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0]
        return annonce.strip().lower() == "https" or request.scheme == "https"


app.session_interface = SessionSelonLeSchema()
db.init_app(app)

# Après db.init_app, pour éviter tout import circulaire.
from routes_vl import vl_bp  # noqa: E402
from routes_ri import ri_bp  # noqa: E402
from routes_li import li_bp  # noqa: E402
from routes_lt import lt_bp  # noqa: E402
from routes_mc import mc_bp  # noqa: E402
from routes_ct import ct_bp  # noqa: E402
from routes_lr import lr_bp  # noqa: E402
from routes_pieces import pieces_bp  # noqa: E402
from routes_derogation import derogation_bp  # noqa: E402
from routes_visas import visas_bp  # noqa: E402
from routes_paiement import bp as paiement_bp  # noqa: E402
from routes_profils import bp as profils_bp  # noqa: E402
from routes_reliance import bp as reliance_bp  # noqa: E402
from routes_industriel import bp as industriel_bp  # noqa: E402
from routes_validation import bp as validation_bp  # noqa: E402
from routes_instruction import bp as instruction_bp  # noqa: E402
from routes_ctd import bp as ctd_bp  # noqa: E402
from routes_demandes import bp as demandes_bp  # noqa: E402
from routes_courriel import bp as courriel_bp  # noqa: E402
from routes_atu import bp as atu_bp  # noqa: E402
from routes_voies import bp as voies_bp  # noqa: E402
app.register_blueprint(vl_bp)
app.register_blueprint(ri_bp)
app.register_blueprint(li_bp)
app.register_blueprint(lt_bp)
app.register_blueprint(mc_bp)
app.register_blueprint(ct_bp)
app.register_blueprint(lr_bp)
app.register_blueprint(pieces_bp)
app.register_blueprint(derogation_bp)
app.register_blueprint(visas_bp)
app.register_blueprint(paiement_bp)
app.register_blueprint(profils_bp)
app.register_blueprint(reliance_bp)
app.register_blueprint(industriel_bp)
app.register_blueprint(validation_bp)
app.register_blueprint(instruction_bp)
app.register_blueprint(ctd_bp)
app.register_blueprint(demandes_bp)
app.register_blueprint(courriel_bp)
app.register_blueprint(atu_bp)
app.register_blueprint(voies_bp)

# Fonctions réglementaires du cahier des charges (README §"Ordre de priorité") — MA et VL
# sont implémentés dans cette livraison ; les autres sont affichées grisées, jamais masquées.
FONCTIONS_REGLEMENTAIRES = [
    ("RS", "Système national"), ("MA", "Enregistrement / AMM"), ("VL", "Pharmacovigilance"),
    ("RI", "Inspection"), ("LI", "Licences établissements"), ("LT", "Laboratoire"),
    ("MC", "Surveillance du marché"), ("CT", "Essais cliniques"), ("LR", "Libération des lots"),
]
MODULES_IMPLEMENTES = {"MA", "VL", "RI", "LI", "LT", "MC", "CT", "LR"}


@app.context_processor
def inject_globals():
    u = current_user()
    # Filtrage de la bande latérale pour demandeur_externe : n'affiche une section
    # métier que si le demandeur a effectivement un dossier dans ce module, pour
    # respecter "ne montrer que ce qui concerne sa propre démarche".
    demandeur_a_amm = demandeur_a_licences = demandeur_a_ct = demandeur_a_derogations = demandeur_a_visas = False
    if u and u.role_systeme == "demandeur_externe":
        demandeur_a_amm = db.session.query(DossierAMM.id).filter_by(demandeur_id=u.id).first() is not None
        demandeur_a_ct = db.session.query(ProtocoleEssaiClinique.id).filter_by(promoteur_id=u.id).first() is not None
        demandeur_a_derogations = db.session.query(DemandeDerogation.id).filter_by(demandeur_id=u.id).first() is not None
        demandeur_a_visas = db.session.query(VisaTechnique.id).filter_by(demandeur_id=u.id).first() is not None
        if u.etablissement_rattachement_id:
            demandeur_a_licences = db.session.query(DemandeLicence.id).filter_by(
                etablissement_id=u.etablissement_rattachement_id).first() is not None
    # Compteur de paiements restant à régler, pour la pastille « Mon espace ».
    paiements_dus = 0
    if u is not None and u.est_externe:
        from paiements import paiements_du_redevable
        paiements_dus = sum(
            1 for p in paiements_du_redevable(u)
            if p.statut in ("en_attente", "initie", "rejete", "echoue", "expire"))
    # Reliance régionale : accès et alertes reçues restant à traiter.
    peut_reliance = alertes_reliance = 0
    if u is not None:
        from permissions import a_permission
        peut_reliance = a_permission(u, "consulter_reliance")
        if peut_reliance:
            from models import AlerteTransfrontaliere
            alertes_reliance = AlerteTransfrontaliere.query.filter_by(
                sens="recue", traitee=False).count()
    # Parapheur : documents attendant précisément la signature de cet échelon.
    signatures_attendues = 0
    if u is not None and u.niveau >= 2:
        from models import EtapeValidation
        signatures_attendues = EtapeValidation.query.filter_by(
            role_requis=u.role_systeme, statut="en_attente").count()
    # Recettes en attente d'approbation — visible du seul responsable financier.
    # `None` signifie « cet écran ne vous concerne pas », 0 « rien à traiter ».
    recettes_a_approuver = None
    if u is not None:
        from permissions import a_permission
        if a_permission(u, "confirmer_paiement"):
            recettes_a_approuver = Paiement.query.filter_by(
                statut="preuve_deposee").count()
    # Instruction : charge de travail du chef de service et des évaluateurs.
    dossiers_a_examiner = evaluations_a_rendre = 0
    if u is not None:
        if u.role_systeme in ("chef_service_amm", "administrateur_dpml"):
            dossiers_a_examiner = DossierAMM.query.filter_by(statut="soumis").count()
        elif u.role_systeme == "evaluateur_interne":
            from models import AssignationEvaluation
            evaluations_a_rendre = AssignationEvaluation.query.filter(
                AssignationEvaluation.evaluateur_id == u.id,
                AssignationEvaluation.statut != "terminee").count()
    # Menu latéral : résolu par la matrice d'accès, jamais par le gabarit.
    menu = []
    if u is not None:
        import matrice_acces
        menu = matrice_acces.entrees(u, {
            "paiements_dus": paiements_dus,
            "demandeur_a_amm": demandeur_a_amm,
            "demandeur_a_ct": demandeur_a_ct,
            "demandeur_a_licences": demandeur_a_licences,
            "demandeur_a_derogations": demandeur_a_derogations,
            "demandeur_a_visas": demandeur_a_visas,
        }, request.path)

    return dict(current_user=u, ROLES=ROLES, paiements_dus=paiements_dus,
                menu=menu, APPLICATION=NOM_APPLICATION,
                peut_reliance=peut_reliance, alertes_reliance=alertes_reliance,
                signatures_attendues=signatures_attendues,
                recettes_a_approuver=recettes_a_approuver,
                dossiers_a_examiner=dossiers_a_examiner,
                evaluations_a_rendre=evaluations_a_rendre,
                wf=wf, STATUTS=wf.STATUTS,
                TYPES_PROCEDURE=wf.TYPES_PROCEDURE, wfvl=wfvl, STATUTS_VL=wfvl.STATUTS,
                TYPES_MESURE=wfvl.TYPES_MESURE, wfri=wfri, STATUTS_RI=wfri.STATUTS,
                TYPES_RI=wfri.TYPES, wfli=wfli, STATUTS_LI=wfli.STATUTS_DEMANDE,
                STATUTS_LICENCE=wfli.STATUTS_LICENCE, TYPES_LI=wfli.TYPES_DEMANDE,
                wflt=wflt, STATUTS_LT=wflt.STATUTS, ORIGINES_LT=wflt.ORIGINES,
                wfmc=wfmc, STATUTS_MC=wfmc.STATUTS, ORIGINES_MC=wfmc.ORIGINES,
                wfct=wfct, STATUTS_CT=wfct.STATUTS, wflr=wflr, STATUTS_LR=wflr.STATUTS,
                wfd=wfd, STATUTS_DEROGATION=wfd.STATUTS, wfv=wfv, STATUTS_VISA=wfv.STATUTS,
                now=datetime.utcnow(),
                demandeur_a_amm=demandeur_a_amm, demandeur_a_licences=demandeur_a_licences,
                demandeur_a_ct=demandeur_a_ct, demandeur_a_derogations=demandeur_a_derogations,
                demandeur_a_visas=demandeur_a_visas)


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
# Tirets typographiques que le copier-coller substitue au trait d'union :
# aucun clavier ne les produit dans un champ de mot de passe, mais un texte
# copié depuis une page mise en forme ou un PDF en est plein.
_TIRETS = {"‐": "-", "‑": "-", "‒": "-", "–": "-",
           "—": "-", "−": "-", "­": ""}


def _nettoyer_saisie_mot_de_passe(saisie):
    """Corrige ce que le copier-coller abîme, sans jamais élargir la recherche.

    Un mot de passe recopié depuis un tableau emporte presque toujours une
    espace finale, et un texte mis en forme remplace les traits d'union par des
    tirets typographiques. Dans les deux cas la saisie est refusée avec
    « Identifiants incorrects » — message exact mais inexploitable, puisque
    l'utilisateur voit bien qu'il a saisi le bon mot de passe.

    On ne corrige que des variantes qu'AUCUN mot de passe légitime ne peut
    contenir : espaces de bordure et caractères invisibles. La casse, elle,
    n'est pas touchée — l'assouplir affaiblirait réellement le secret. Contre
    la majuscule automatique des claviers mobiles, la réponse est dans le
    formulaire (`autocapitalize="none"`), pas ici.
    """
    import unicodedata

    if not saisie:
        return ""
    texte = unicodedata.normalize("NFKC", saisie).strip()
    for source, cible in _TIRETS.items():
        texte = texte.replace(source, cible)
    return texte


@app.route("/login", methods=["GET", "POST"])
def login():
    import anti_force_brute as afb

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd = _nettoyer_saisie_mot_de_passe(request.form.get("password", ""))
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ip = ip.split(",")[0].strip()

        # Le blocage se vérifie AVANT de comparer le mot de passe : sinon la
        # durée de la réponse trahirait l'existence du compte.
        attente = afb.secondes_restantes(email, ip)
        if attente:
            flash(f"Trop de tentatives infructueuses. Réessayez dans "
                  f"{afb.duree_lisible(attente)}.", "danger")
            return render_template("login.html")

        u = Personne.query.filter_by(email=email).first()
        if u and u.check_password(pwd):
            if u.statut_compte == "actif":
                afb.enregistrer_succes(email, ip)
                session["user_id"] = u.id
                flash(f"Bienvenue, {u.nom_complet} ({u.role_label}).", "success")
                return redirect(request.args.get("next") or url_for("dashboard"))
            elif u.statut_compte == "en_attente_validation":
                flash("Votre compte est en attente de validation par la DPML. "
                      "Vous serez notifié dès qu'il sera activé.", "warning")
            else:
                flash("Ce compte est suspendu. Contactez la DPML.", "danger")
        else:
            bloque = afb.enregistrer_echec(email, ip)
            if bloque:
                flash(f"Trop de tentatives infructueuses. Réessayez dans "
                      f"{afb.duree_lisible(bloque)}.", "danger")
            else:
                restants = afb.essais_restants(email, ip)
                flash("Identifiants incorrects."
                      + (f" Il vous reste {restants} tentative"
                         + ("s" if restants > 1 else "") + "."
                         if restants <= 2 else ""), "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Tableau de bord (10-RS)
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    # Chaque opérateur externe dispose d'un tableau de bord cloisonné à sa
    # société ET composé selon son profil : il ne doit voir ni les dossiers
    # des autres, ni les indicateurs globaux de la DPML, ni des rubriques qui
    # ne le concernent pas.
    _u = current_user()
    if _u is not None and _u.est_externe:
        return redirect(url_for("industriel.tableau_bord"))
    executer_verifications_delais()
    executer_verifications_delais_vl()
    executer_verifications_delais_ri()
    executer_verifications_delais_li()
    executer_verifications_delais_mc()
    executer_verifications_delais_ct()
    u = current_user()

    dossiers_q = DossierAMM.query
    if u.role_systeme == "demandeur_externe":
        dossiers_q = dossiers_q.filter_by(demandeur_id=u.id)

    par_statut = {statut: dossiers_q.filter_by(statut=statut).count() for statut in wf.STATUTS}
    total_dossiers = sum(par_statut.values())
    total_actifs = sum(v for k, v in par_statut.items() if k not in wf.STATUTS_FINAUX)

    termines = dossiers_q.filter(DossierAMM.statut.in_(wf.STATUTS_FINAUX)) \
        .filter(DossierAMM.date_depot.isnot(None)).filter(DossierAMM.date_decision.isnot(None)).all()
    if termines:
        delai_moyen = round(sum((d.date_decision - d.date_depot).days for d in termines) / len(termines), 1)
    else:
        delai_moyen = None

    nb_finaux = dossiers_q.filter(DossierAMM.statut.in_(wf.STATUTS_FINAUX)).count()
    nb_delai_depasse = dossiers_q.filter_by(statut="cloture_delai_depasse").count()
    # Simplification assumée (README) : proportion de dossiers finalisés qui n'ont PAS été
    # clôturés pour dépassement de délai, faute d'un suivi "dans les délais réglementaires"
    # plus fin pour ce périmètre.
    pct_ma = round(100 * (nb_finaux - nb_delai_depasse) / nb_finaux) if nb_finaux else None

    cas_q = NotificationVigilance.query
    par_statut_vl = {statut: cas_q.filter_by(statut=statut).count() for statut in wfvl.STATUTS}
    total_cas_vl = sum(par_statut_vl.values())
    nb_cas_finaux = cas_q.filter(NotificationVigilance.statut.in_(wfvl.STATUTS_FINAUX)).count()
    nb_cas_en_retard = sum(1 for c in cas_q.filter_by(statut="recue").all() if cas_vigilance_en_retard(c))
    # Simplification assumée (README) : proportion de cas clôturés parmi le total, faute
    # d'un indicateur plus fin "traité dans les délais" pour ce périmètre.
    pct_vl = round(100 * nb_cas_finaux / total_cas_vl) if total_cas_vl else None

    insp_q = Inspection.query
    par_statut_ri = {statut: insp_q.filter_by(statut=statut).count() for statut in wfri.STATUTS}
    total_insp = sum(par_statut_ri.values())
    nb_insp_finales = insp_q.filter(Inspection.statut.in_(wfri.STATUTS_FINAUX)).count()
    nb_plans_en_retard = sum(1 for i in insp_q.filter_by(statut="plan_action_en_cours").all()
                              if plan_action_en_retard(i))
    # Simplification assumée (README) : proportion d'inspections finalisées parmi le total.
    pct_ri = round(100 * nb_insp_finales / total_insp) if total_insp else None

    licences_q = DemandeLicence.query
    par_statut_li = {statut: licences_q.filter_by(statut=statut).count() for statut in wfli.STATUTS_DEMANDE}
    total_licences = sum(par_statut_li.values())
    nb_licences_finales = licences_q.filter(DemandeLicence.statut.in_(wfli.STATUTS_DEMANDE_FINAUX)).count()
    nb_etablissements_suspendus = Etablissement.query.filter_by(statut_licence="suspendue").count()
    # Simplification assumée (README) : proportion de demandes finalisées parmi le total.
    pct_li = round(100 * nb_licences_finales / total_licences) if total_licences else None

    ech_q = Echantillon.query
    par_statut_lt = {statut: ech_q.filter_by(statut=statut).count() for statut in wflt.STATUTS}
    total_echantillons = sum(par_statut_lt.values())
    nb_ech_finaux = ech_q.filter(Echantillon.statut.in_(wflt.STATUTS_FINAUX)).count()
    pct_lt = round(100 * nb_ech_finaux / total_echantillons) if total_echantillons else None

    sig_q = SignalementQualite.query
    par_statut_mc = {statut: sig_q.filter_by(statut=statut).count() for statut in wfmc.STATUTS}
    total_signalements = sum(par_statut_mc.values())
    nb_sig_finaux = sig_q.filter(SignalementQualite.statut.in_(wfmc.STATUTS_FINAUX)).count()
    nb_niveau_i_attente = sig_q.filter_by(statut="evalue", niveau_risque="I").count()
    pct_mc = round(100 * nb_sig_finaux / total_signalements) if total_signalements else None

    ct_q = ProtocoleEssaiClinique.query
    par_statut_ct = {statut: ct_q.filter_by(statut=statut).count() for statut in wfct.STATUTS}
    total_protocoles = sum(par_statut_ct.values())
    nb_ct_finaux = ct_q.filter(ProtocoleEssaiClinique.statut.in_(wfct.STATUTS_FINAUX)).count()
    pct_ct = round(100 * nb_ct_finaux / total_protocoles) if total_protocoles else None

    lr_q = LiberationLot.query
    par_statut_lr = {statut: lr_q.filter_by(statut=statut).count() for statut in wflr.STATUTS}
    total_liberations = sum(par_statut_lr.values())
    nb_lr_finaux = lr_q.filter(LiberationLot.statut.in_(wflr.STATUTS_FINAUX)).count()
    pct_lr = round(100 * nb_lr_finaux / total_liberations) if total_liberations else None

    progression = []
    for code, nom in FONCTIONS_REGLEMENTAIRES:
        if code == "RS":
            # Pas de "dossiers" à faire progresser pour le socle de gouvernance lui-même
            # (tableau de bord, référentiels, utilisateurs) — implémenté à 100%, sans
            # métrique de complétion de cas comme les autres fonctions.
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": 100})
        elif code == "MA":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_ma})
        elif code == "VL":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_vl})
        elif code == "RI":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_ri})
        elif code == "LI":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_li})
        elif code == "LT":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_lt})
        elif code == "MC":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_mc})
        elif code == "CT":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_ct})
        elif code == "LR":
            progression.append({"code": code, "nom": nom, "implemente": True, "valeur": pct_lr})
        else:
            progression.append({"code": code, "nom": nom, "implemente": False, "valeur": None})

    notifications_non_lues = Notification.query.filter_by(destinataire_id=u.id, statut_lecture="non_lue") \
        .order_by(Notification.date_creation.desc()).limit(10).all()
    activite_recente = EvenementAudit.query.order_by(EvenementAudit.horodatage.desc()).limit(15).all()

    return render_template(
        "dashboard.html", par_statut=par_statut, total_dossiers=total_dossiers, total_actifs=total_actifs,
        delai_moyen=delai_moyen, progression=progression, notifications_non_lues=notifications_non_lues,
        activite_recente=activite_recente, par_statut_vl=par_statut_vl, total_cas_vl=total_cas_vl,
        nb_cas_en_retard=nb_cas_en_retard, par_statut_ri=par_statut_ri, total_insp=total_insp,
        nb_plans_en_retard=nb_plans_en_retard, par_statut_li=par_statut_li, total_licences=total_licences,
        nb_etablissements_suspendus=nb_etablissements_suspendus, par_statut_lt=par_statut_lt,
        total_echantillons=total_echantillons, par_statut_mc=par_statut_mc, total_signalements=total_signalements,
        nb_niveau_i_attente=nb_niveau_i_attente, par_statut_ct=par_statut_ct, total_protocoles=total_protocoles,
        par_statut_lr=par_statut_lr, total_liberations=total_liberations,
    )


@app.route("/notifications")
@login_required
def notifications_liste():
    notifs = Notification.query.filter_by(destinataire_id=current_user().id) \
        .order_by(Notification.date_creation.desc()).all()
    return render_template("notifications.html", notifications=notifs)


@app.route("/notifications/<int:id>/lire", methods=["POST"])
@login_required
def notification_lire(id):
    n = Notification.query.get_or_404(id)
    if n.destinataire_id != current_user().id:
        abort(403)
    n.statut_lecture = "lue"
    db.session.commit()
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------------------
# Registre des dossiers AMM (règle transversale n°5 : recherche/filtre/tri/pagination)
# ---------------------------------------------------------------------------
@app.route("/dossiers")
@login_required
def dossiers_registre():
    executer_verifications_delais()
    u = current_user()
    q = DossierAMM.query.join(Produit, DossierAMM.produit_id == Produit.id) \
        .join(Personne, DossierAMM.demandeur_id == Personne.id)
    if u.role_systeme == "demandeur_externe":
        q = q.filter(DossierAMM.demandeur_id == u.id)

    texte = request.args.get("q", "").strip()
    statut = request.args.get("statut", "")
    type_procedure = request.args.get("type_procedure", "")

    if texte:
        like = f"%{texte}%"
        q = q.filter(db.or_(
            Produit.nom_commercial.ilike(like), Produit.denomination_commune_internationale.ilike(like),
            Personne.nom_complet.ilike(like), DossierAMM.numero.ilike(like),
        ))
    if statut:
        q = q.filter(DossierAMM.statut == statut)
    if type_procedure:
        q = q.filter(DossierAMM.type_procedure == type_procedure)

    q = q.order_by(DossierAMM.date_maj.desc())
    page = max(1, request.args.get("page", 1, type=int))
    total = q.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    dossiers = q.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    return render_template("dossiers_registre.html", dossiers=dossiers, q=texte, statut=statut,
                            type_procedure=type_procedure, page=page, pages=pages, total=total)


# ---------------------------------------------------------------------------
# Nouvelle demande / renouvellement / variation / retrait
# ---------------------------------------------------------------------------
def _liste_demandeurs():
    return Personne.query.filter_by(role_systeme="demandeur_externe", statut_compte="actif") \
        .order_by(Personne.nom_complet).all()


def _produits_eligibles_procedure_liee(u):
    """Produits pour lesquels u peut initier un renouvellement/variation/retrait — même
    règle d'autorisation que dossier_procedure_liee (titulaire de l'AMM, ou administrateur_dpml)."""
    if u is None:
        return []
    q = Produit.query.filter_by(statut_amm_courant="active")
    if u.role_systeme == "demandeur_externe":
        if not u.etablissement_rattachement_id:
            return []
        q = q.filter_by(titulaire_amm_id=u.etablissement_rattachement_id)
    elif u.role_systeme != "administrateur_dpml":
        return []
    return q.order_by(Produit.nom_commercial).all()


CHAMPS_BROUILLON_AMM = ("nom_commercial", "dci", "forme_pharmaceutique", "dosage",
                        "fabricant_nom", "fabricant_site", "titulaire_nom", "pays_origine",
                        "composition_integrale", "classe_therapeutique", "indications_therapeutiques",
                        "voie_administration", "duree_stabilite", "prix_grossiste_ht",
                        "representant_local_nom", "representant_local_contact")


@app.route("/dossiers/nouveau", methods=["GET", "POST"])
def dossier_nouveau():
    """
    Accès libre (§ décision produit) : un laboratoire peut décrire son produit
    sans compte préalable. La création réelle du DossierAMM exige toujours un
    demandeur identifié (contrainte du modèle de données) — un visiteur anonyme
    est donc redirigé vers /inscription-labo à l'étape suivante, ses données de
    brouillon conservées en session le temps de créer son compte. Un compte
    existant (demandeur_externe ou administrateur_dpml) crée le dossier
    directement, comme avant.

    Le type de demande (nouvelle AMM / renouvellement / variation / retrait) est
    choisi dès cette première étape (Section 1 du formulaire officiel DPML) — un
    compte connecté ayant au moins un produit titulaire d'une AMM active peut
    choisir directement le produit concerné pour les 3 derniers types, au lieu de
    devoir naviguer jusqu'à la fiche du dossier approuvé correspondant.
    """
    u = current_user()
    if u and u.role_systeme not in ("demandeur_externe", "administrateur_dpml"):
        abort(403)
    produits_existants = _produits_eligibles_procedure_liee(u)

    if request.method == "POST":
        type_procedure = request.form.get("type_procedure", "nouvelle_demande")

        if type_procedure in ("renouvellement", "variation", "retrait"):
            if u is None:
                flash("Vous devez être connecté pour initier un renouvellement, une variation ou un retrait.",
                      "danger")
                return redirect(url_for("login", next=url_for("dossier_nouveau")))
            produit_id = request.form.get("produit_id", type=int)
            produit = db.session.get(Produit, produit_id) if produit_id else None
            autorise = produit and (
                u.role_systeme == "administrateur_dpml" or (
                    u.role_systeme == "demandeur_externe" and u.etablissement_rattachement_id
                    and u.etablissement_rattachement_id == produit.titulaire_amm_id
                )
            )
            if not produit:
                flash("Veuillez sélectionner le produit concerné.", "danger")
                return render_template("dossier_nouveau.html", demandeurs=_liste_demandeurs(),
                                        produits_existants=produits_existants)
            if not autorise:
                abort(403)
            demandeur = u
            if u.role_systeme != "demandeur_externe" and produit.titulaire_amm and produit.titulaire_amm.pharmacien_responsable:
                demandeur = produit.titulaire_amm.pharmacien_responsable
            try:
                d = wf.creer_dossier_procedure(produit, demandeur, type_procedure)
                db.session.commit()
            except wf.ErreurWorkflow as e:
                db.session.rollback()
                flash(str(e), "danger")
                return render_template("dossier_nouveau.html", demandeurs=_liste_demandeurs(),
                                        produits_existants=produits_existants)
            flash(f"Dossier de {wf.TYPES_PROCEDURE[type_procedure].lower()} créé en brouillon.", "success")
            return redirect(url_for("dossier_detail", id=d.id))

        donnees = {champ: request.form.get(champ, "") for champ in CHAMPS_BROUILLON_AMM}

        if u is None:
            if not donnees.get("nom_commercial", "").strip() or not donnees.get("dci", "").strip():
                flash("Le produit et la DCI doivent être renseignés avant de continuer.", "danger")
                return render_template("dossier_nouveau.html", demandeurs=[], produits_existants=[])
            session["brouillon_amm"] = donnees
            flash("Encore une étape : créez votre compte laboratoire pour finaliser cette demande.", "info")
            return redirect(url_for("inscription_labo"))

        demandeur = u
        if u.role_systeme == "administrateur_dpml":
            demandeur_id = request.form.get("demandeur_id", type=int)
            if demandeur_id:
                demandeur = db.session.get(Personne, demandeur_id)
        try:
            d = wf.creer_dossier_nouvelle_demande(demandeur, donnees)
            db.session.commit()
        except wf.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("dossier_nouveau.html", demandeurs=_liste_demandeurs(),
                                    produits_existants=produits_existants)
        flash("Dossier créé en brouillon. Complétez le dossier technique puis soumettez-le.", "success")
        return redirect(url_for("dossier_detail", id=d.id))
    return render_template("dossier_nouveau.html", demandeurs=_liste_demandeurs() if u else [],
                            produits_existants=produits_existants)


CHAMPS_BROUILLON_LICENCE = ("raison_sociale", "categorie_activite", "adresse")
CATEGORIES_ACTIVITE_LICENCE = {
    "medicaments": "Médicaments",
    "dispositifs_medicaux": "Dispositifs médicaux",
    "les_deux": "Médicaments et dispositifs médicaux",
}


def _etablissement_pour_licence(demandeur, donnees):
    """Réutilise l'établissement déjà rattaché au demandeur s'il en a un (évite de créer
    un doublon) ; sinon retrouve/crée par raison sociale, comme inscription_labo pour l'AMM."""
    if demandeur.role_systeme == "demandeur_externe" and demandeur.etablissement_rattachement_id:
        etab = db.session.get(Etablissement, demandeur.etablissement_rattachement_id)
        etab.categorie_activite = donnees["categorie_activite"]
        if donnees.get("adresse"):
            etab.adresse = donnees["adresse"]
        return etab
    etab = Etablissement.query.filter_by(raison_sociale=donnees["raison_sociale"]).first()
    if not etab:
        etab = Etablissement(raison_sociale=donnees["raison_sociale"], type="grossiste_repartiteur",
                              adresse=donnees.get("adresse", ""), categorie_activite=donnees["categorie_activite"],
                              statut_licence="en_instruction")
        db.session.add(etab)
        db.session.flush()
    if demandeur.role_systeme == "demandeur_externe" and not demandeur.etablissement_rattachement_id:
        demandeur.etablissement_rattachement_id = etab.id
    return etab


@app.route("/licences/nouvelle", methods=["GET", "POST"])
def licence_nouvelle():
    """
    Accès libre, miroir de dossier_nouveau (§ ci-dessus) pour les sociétés
    grossistes-répartiteurs demandant une licence d'établissement (médicaments
    et/ou dispositifs médicaux). Un visiteur anonyme est redirigé vers
    /inscription-labo, ses données conservées en session (brouillon_licence).
    """
    u = current_user()
    if u and u.role_systeme not in ("demandeur_externe", "administrateur_dpml"):
        abort(403)

    if request.method == "POST":
        donnees = {champ: request.form.get(champ, "").strip() for champ in CHAMPS_BROUILLON_LICENCE}
        if not donnees.get("raison_sociale") or donnees.get("categorie_activite") not in CATEGORIES_ACTIVITE_LICENCE:
            flash("Le nom de la société et la catégorie d'activité doivent être renseignés.", "danger")
            return render_template("licence_nouvelle.html", categories=CATEGORIES_ACTIVITE_LICENCE)

        if u is None:
            session["brouillon_licence"] = donnees
            flash("Encore une étape : créez votre compte pour finaliser cette demande.", "info")
            return redirect(url_for("inscription_labo"))

        try:
            etab = _etablissement_pour_licence(u, donnees)
            demande = wfli.deposer_demande(etab, u, type_demande="nouvelle")
            db.session.commit()
        except wfli.ErreurWorkflow as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("licence_nouvelle.html", categories=CATEGORIES_ACTIVITE_LICENCE)
        flash(f"Demande de licence {demande.numero} déposée.", "success")
        return redirect(url_for("li.fiche", id=demande.id))
    return render_template("licence_nouvelle.html", categories=CATEGORIES_ACTIVITE_LICENCE)


@app.route("/inscription-labo", methods=["GET", "POST"])
def inscription_labo():
    """Auto-inscription (rôle demandeur_externe) — seul point d'entrée où un compte
    est créé sans passer par administrateur_dpml. Rattachée au dépôt d'une demande
    d'AMM (dossier_nouveau) OU d'une demande de licence de grossiste (licence_nouvelle) —
    un seul brouillon est présent en session à la fois, selon le parcours emprunté."""
    if current_user():
        return redirect(url_for("dossier_nouveau"))

    draft_amm = session.get("brouillon_amm")
    draft_licence = session.get("brouillon_licence")
    draft = draft_amm or draft_licence
    if draft_amm:
        raison_sociale_defaut = draft_amm.get("titulaire_nom") or draft_amm.get("fabricant_nom", "")
    else:
        raison_sociale_defaut = (draft_licence or {}).get("raison_sociale", "")
    valeurs = {"nom_complet": "", "email": "", "raison_sociale": raison_sociale_defaut, "contact": ""}

    if request.method == "POST":
        valeurs = {champ: request.form.get(champ, "").strip() for champ in
                   ("nom_complet", "email", "raison_sociale", "contact")}
        email = valeurs["email"].lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        erreurs = []
        if not valeurs["nom_complet"]:
            erreurs.append("Le nom complet est obligatoire.")
        if not email:
            erreurs.append("L'e-mail est obligatoire.")
        elif Personne.query.filter_by(email=email).first():
            erreurs.append("Cet e-mail est déjà utilisé — connectez-vous plutôt.")
        if not valeurs["raison_sociale"]:
            erreurs.append("Le nom du laboratoire / établissement est obligatoire.")
        if len(password) < 8:
            erreurs.append("Le mot de passe doit contenir au moins 8 caractères.")
        elif password != password_confirm:
            erreurs.append("Les deux mots de passe ne correspondent pas.")

        if erreurs:
            for e in erreurs:
                flash(e, "danger")
            return render_template("inscription_labo.html", draft=draft, draft_licence=draft_licence,
                                    categories=CATEGORIES_ACTIVITE_LICENCE, valeurs=valeurs)

        etab = Etablissement.query.filter_by(raison_sociale=valeurs["raison_sociale"]).first()
        if not etab:
            if draft_licence:
                etab = Etablissement(raison_sociale=valeurs["raison_sociale"], type="grossiste_repartiteur",
                                      adresse=draft_licence.get("adresse", ""),
                                      categorie_activite=draft_licence.get("categorie_activite"),
                                      statut_licence="en_instruction")
            else:
                # Type par défaut assumé (voir README) : à ajuster par administrateur_dpml si besoin,
                # l'inscription ne demande pas le type précis d'établissement pour rester simple.
                etab = Etablissement(raison_sociale=valeurs["raison_sociale"], type="importateur_exportateur",
                                      statut_licence="en_instruction")
            db.session.add(etab)
            db.session.flush()

        # en_attente_validation : un agent DPML doit valider l'inscription avant que le
        # compte puisse être réutilisé pour une future connexion (voir /admin/utilisateurs).
        # La session de la démarche en cours reste toutefois active pour finaliser le dépôt.
        p = Personne(nom_complet=valeurs["nom_complet"], email=email, role_systeme="demandeur_externe",
                     etablissement_rattachement_id=etab.id, contact=valeurs["contact"],
                     statut_compte="en_attente_validation")
        p.set_password(password)
        db.session.add(p)
        db.session.flush()
        enregistrer_creation(p, p, "Auto-inscription en tant que laboratoire")
        session["user_id"] = p.id
        session.pop("brouillon_amm", None)
        session.pop("brouillon_licence", None)
        flash("Votre inscription est en attente de validation par la DPML avant toute reconnexion future.", "info")

        if draft_amm:
            try:
                d = wf.creer_dossier_nouvelle_demande(p, draft_amm)
                db.session.commit()
                flash(f"Compte créé, bienvenue {p.nom_complet}. Votre dossier a été déposé en brouillon.",
                      "success")
                return redirect(url_for("dossier_detail", id=d.id))
            except wf.ErreurWorkflow as e:
                db.session.commit()  # le compte existe malgré tout, seul le dossier a échoué
                flash(str(e), "danger")
                return redirect(url_for("dashboard"))

        if draft_licence:
            try:
                demande = wfli.deposer_demande(etab, p, type_demande="nouvelle")
                db.session.commit()
                flash(f"Compte créé, bienvenue {p.nom_complet}. Votre demande de licence a été déposée.",
                      "success")
                return redirect(url_for("li.fiche", id=demande.id))
            except wfli.ErreurWorkflow as e:
                db.session.commit()  # le compte existe malgré tout, seule la demande a échoué
                flash(str(e), "danger")
                return redirect(url_for("dashboard"))

        db.session.commit()
        flash(f"Compte créé, bienvenue {p.nom_complet}.", "success")
        return redirect(url_for("dashboard"))

    return render_template("inscription_labo.html", draft=draft, draft_licence=draft_licence,
                            categories=CATEGORIES_ACTIVITE_LICENCE, valeurs=valeurs)


@app.route("/produits/<int:produit_id>/procedures/<string:type_procedure>", methods=["POST"])
@login_required
def dossier_procedure_liee(produit_id, type_procedure):
    if type_procedure not in ("renouvellement", "variation", "retrait"):
        abort(404)
    u = current_user()
    produit = Produit.query.get_or_404(produit_id)
    autorise = (u.role_systeme == "administrateur_dpml") or (
        u.role_systeme == "demandeur_externe" and u.etablissement_rattachement_id
        and u.etablissement_rattachement_id == produit.titulaire_amm_id
    )
    if not autorise:
        abort(403)
    # Le demandeur du nouveau dossier est la personne connectée si c'est le titulaire lui-même ;
    # si c'est administrateur_dpml qui initie (ex. retrait décidé par la DPML, §3.4), on rattache
    # le dossier au pharmacien responsable de l'établissement titulaire s'il est identifié, sinon
    # à l'administrateur lui-même à défaut d'un tiers plus pertinent.
    demandeur = u
    if u.role_systeme != "demandeur_externe" and produit.titulaire_amm and produit.titulaire_amm.pharmacien_responsable:
        demandeur = produit.titulaire_amm.pharmacien_responsable
    try:
        d = wf.creer_dossier_procedure(produit, demandeur, type_procedure)
        db.session.commit()
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("dossiers_registre"))
    flash(f"Dossier de {wf.TYPES_PROCEDURE[type_procedure].lower()} créé en brouillon.", "success")
    return redirect(url_for("dossier_detail", id=d.id))


# ---------------------------------------------------------------------------
# Fiche dossier + actions du circuit
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Cloisonnement d'un dossier vu par un opérateur externe
# ---------------------------------------------------------------------------
def _verifier_acces_dossier(dossier, u, actions_reservees=()):
    """Refuse l'accès à un dossier qui n'est pas de la société du demandeur.

    Le périmètre est l'ÉTABLISSEMENT, pas la personne. Exiger que ce soit le
    compte déposant lui-même interdisait à un collègue de téléverser une pièce
    ou de déposer la preuve de paiement — or c'est rarement celui qui monte le
    dossier qui règle la facture. Le reste de l'application cloisonne déjà par
    société (espace_industriel, suivi, validation) ; ces quatre routes étaient
    les dernières à s'en écarter.

    `actions_reservees` liste les rôles internes admis lorsque la route modifie
    quelque chose ; vide, la route est en lecture pour tout agent.
    """
    if u is not None and u.role_systeme == "demandeur_externe":
        import espace_industriel as esp
        if dossier.demandeur_id not in esp.personnes_de_la_societe(u):
            abort(404)   # ne révèle pas l'existence du dossier d'un concurrent
        return
    if actions_reservees and (u is None or u.role_systeme not in actions_reservees):
        abort(403)


@app.route("/dossiers/<int:id>")
@login_required
def dossier_detail(id):
    d = DossierAMM.query.get_or_404(id)
    u = current_user()
    _verifier_acces_dossier(d, u)
    audit_events = EvenementAudit.query.filter_by(entite_type="DossierAMM", entite_id=d.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    avis = d.avis.order_by(AvisEvaluationMA.date_creation.desc()).all()
    dossiers_lies = DossierAMM.query.filter_by(produit_id=d.produit_id) \
        .filter(DossierAMM.id != d.id).order_by(DossierAMM.date_creation.desc()).all()
    echantillons_lies = Echantillon.query.filter_by(origine="dossier_amm", origine_reference_id=d.id) \
        .order_by(Echantillon.date_reception.desc()).all()
    return render_template("dossier_detail.html", d=d, audit_events=audit_events, echantillons_lies=echantillons_lies,
                            peut_agir=wf.peut_agir(d, u), avis=avis, dossiers_lies=dossiers_lies,
                            pieces=lister_pieces(d), paiements=lister_paiements(d),
                            montant_frais_soumission=wf.montant_frais(d.type_procedure),
                            etapes_suivi=wf.etapes_suivi(d))


@app.route("/dossiers/<int:id>/documents", methods=["POST"])
@login_required
def dossier_televerser_document(id):
    d = DossierAMM.query.get_or_404(id)
    u = current_user()
    _verifier_acces_dossier(d, u, ("administrateur_dpml",))
    try:
        enregistrer_piece(d, request.files.get("fichier"), request.form.get("type_document", "").strip(), u)
        db.session.commit()
        flash("Document téléversé avec succès.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/paiements/<int:paiement_id>/preuve", methods=["POST"])
@login_required
def dossier_paiement_preuve(id, paiement_id):
    d = DossierAMM.query.get_or_404(id)
    paiement = Paiement.query.get_or_404(paiement_id)
    u = current_user()
    if paiement.entite_type != "DossierAMM" or paiement.entite_id != d.id:
        abort(404)
    _verifier_acces_dossier(d, u, ("administrateur_dpml",))
    try:
        deposer_preuve(paiement, request.files.get("fichier"), u)
        db.session.commit()
        flash("Preuve de paiement déposée. Elle sera vérifiée par la DPML.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/paiements/<int:paiement_id>/confirmer", methods=["POST"])
@login_required
@permission_requise("confirmer_paiement")
def dossier_paiement_confirmer(id, paiement_id):
    paiement = Paiement.query.get_or_404(paiement_id)
    try:
        confirmer_paiement(paiement, current_user())
        db.session.commit()
        flash("Paiement confirmé.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/paiements/<int:paiement_id>/rejeter", methods=["POST"])
@login_required
@permission_requise("confirmer_paiement")
def dossier_paiement_rejeter(id, paiement_id):
    paiement = Paiement.query.get_or_404(paiement_id)
    try:
        rejeter_paiement(paiement, current_user(), request.form.get("motif", ""))
        db.session.commit()
        flash("Preuve de paiement rejetée.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/produit", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def dossier_modifier_produit(id):
    d = DossierAMM.query.get_or_404(id)
    try:
        wf.modifier_produit_brouillon(d, current_user(), {
            "denomination_commune_internationale": request.form.get("dci", ""),
            "nom_commercial": request.form.get("nom_commercial", ""),
            "forme_pharmaceutique": request.form.get("forme_pharmaceutique", ""),
            "dosage": request.form.get("dosage", ""),
            "pays_origine": request.form.get("pays_origine", ""),
            "composition_integrale": request.form.get("composition_integrale", ""),
            "classe_therapeutique": request.form.get("classe_therapeutique", ""),
            "indications_therapeutiques": request.form.get("indications_therapeutiques", ""),
            "voie_administration": request.form.get("voie_administration", ""),
            "duree_stabilite": request.form.get("duree_stabilite", ""),
            "prix_grossiste_ht": request.form.get("prix_grossiste_ht", ""),
            "representant_local_nom": request.form.get("representant_local_nom", ""),
            "representant_local_contact": request.form.get("representant_local_contact", ""),
        })
        db.session.commit()
        flash("Informations produit mises à jour.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/ctd", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def dossier_modifier_ctd(id):
    d = DossierAMM.query.get_or_404(id)
    donnees = {f"module_ctd_{n}": request.form.get(f"module_ctd_{n}", "") for n in range(1, 6)}
    try:
        wf.modifier_ctd(d, current_user(), donnees)
        db.session.commit()
        flash("Dossier technique mis à jour.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/soumettre", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def dossier_soumettre(id):
    d = DossierAMM.query.get_or_404(id)
    try:
        wf.soumettre(d, current_user())
        db.session.commit()
        flash(f"Dossier soumis avec succès. Numéro attribué : {d.numero}.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/recevabilite", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def dossier_recevabilite(id):
    d = DossierAMM.query.get_or_404(id)
    try:
        wf.marquer_recevabilite(d, current_user(), request.form.get("decision"), request.form.get("motif", ""))
        db.session.commit()
        flash("Décision de recevabilité enregistrée.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/avis", methods=["POST"])
@login_required
@roles_required("evaluateur_amm")
def dossier_avis(id):
    d = DossierAMM.query.get_or_404(id)
    try:
        wf.deposer_avis_evaluation(d, current_user(), request.form.get("module_concerne", "global"),
                                    request.form.get("valeur"), request.form.get("commentaire", ""))
        db.session.commit()
        flash("Avis d'évaluation enregistré.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/decision", methods=["POST"])
@login_required
@roles_required("directeur_dpml")
def dossier_decision(id):
    d = DossierAMM.query.get_or_404(id)
    decision = request.form.get("decision")
    try:
        wf.decider(d, current_user(), decision, request.form.get("motif", ""))
        db.session.commit()
        if decision == "approuve":
            flash(f"Dossier approuvé ({d.numero}). Le certificat est disponible au téléchargement.", "success")
        else:
            flash("Décision enregistrée.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/repondre-complement", methods=["POST"])
@login_required
@roles_required("demandeur_externe")
def dossier_repondre_complement(id):
    d = DossierAMM.query.get_or_404(id)
    donnees = {f"module_ctd_{n}": request.form.get(f"module_ctd_{n}", "") for n in range(1, 6)}
    try:
        wf.deposer_reponse_complement(d, current_user(), donnees)
        db.session.commit()
        flash("Réponse au complément déposée. Le dossier retourne en évaluation technique.", "success")
    except wf.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("dossier_detail", id=id))


@app.route("/dossiers/<int:id>/certificat")
@login_required
def dossier_certificat(id):
    d = DossierAMM.query.get_or_404(id)
    u = current_user()
    _verifier_acces_dossier(d, u)
    if d.statut != "approuve":
        abort(404)
    os.makedirs(CERT_DIR, exist_ok=True)
    chemin = os.path.join(CERT_DIR, f"{d.numero}.pdf")
    if not os.path.exists(chemin):
        evt = EvenementAudit.query.filter_by(entite_type="DossierAMM", entite_id=d.id, nouveau_statut="approuve") \
            .order_by(EvenementAudit.horodatage.desc()).first()
        signataire = evt.acteur if evt else None
        pdf_gen.generer_certificat_amm(d, chemin, signataire, base_url=request.url_root.rstrip("/"))
    return send_from_directory(CERT_DIR, f"{d.numero}.pdf", as_attachment=False)


# ---------------------------------------------------------------------------
# Registre public / vérification (accès sans authentification)
# ---------------------------------------------------------------------------
@app.route("/verifier/<numero>")
def verifier(numero):
    d = DossierAMM.query.filter_by(numero=numero).first()
    return render_template("verifier.html", d=d)


@app.route("/acces")
def acces():
    """Adresses d'accès et QR code — à ouvrir sur le poste, à scanner au téléphone."""
    import acces as svc_acces
    u = svc_acces.urls(request.host.split(":")[-1].isdigit()
                       and int(request.host.split(":")[-1]) or svc_acces.PORT_DEFAUT)
    profil = (svc_acces.profil_reseau() or "").strip()
    reseau = svc_acces.nom_reseau() or ""
    return render_template(
        "acces.html", u=u,
        qr=svc_acces.qr_data_uri(u["reseau"]) if u["reseau"] else None,
        pare_feu=svc_acces.regle_pare_feu_presente(u["port"]),
        profil=profil, reseau=reseau,
        profil_public=profil.lower() not in ("private", ""),
        commande_reseau=svc_acces.COMMANDE_RESEAU_PRIVE.format(reseau=reseau),
        commande_pare_feu=svc_acces.COMMANDE_PARE_FEU.format(port=u["port"]))


@app.route("/registre-public")
def registre_public():
    texte = request.args.get("q", "").strip()
    q = Produit.query.filter_by(statut_amm_courant="active")
    if texte:
        like = f"%{texte}%"
        q = q.filter(db.or_(Produit.nom_commercial.ilike(like),
                             Produit.denomination_commune_internationale.ilike(like)))
    produits = q.order_by(Produit.nom_commercial).all()
    infos = []
    for p in produits:
        dossier = DossierAMM.query.filter_by(produit_id=p.id, statut="approuve") \
            .order_by(DossierAMM.date_decision.desc()).first()
        infos.append((p, dossier))
    return render_template("registre_public.html", infos=infos, q=texte)


# ---------------------------------------------------------------------------
# Administration — référentiels (paramètres configurables)
# ---------------------------------------------------------------------------
@app.route("/admin/referentiels")
@login_required
@roles_required("administrateur_dpml")
def admin_referentiels():
    parametres_par_module = {}
    for p in ParametreModule.query.order_by(ParametreModule.module, ParametreModule.cle).all():
        parametres_par_module.setdefault(p.module, []).append(p)
    return render_template("admin/referentiels.html", parametres_par_module=parametres_par_module)


@app.route("/admin/referentiels/<int:id>/modifier", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def admin_referentiel_modifier(id):
    p = ParametreModule.query.get_or_404(id)
    nouvelle_valeur = request.form.get("valeur", "").strip()
    if not nouvelle_valeur:
        flash("La valeur ne peut pas être vide.", "danger")
        return redirect(url_for("admin_referentiels"))
    ancienne = p.valeur
    p.valeur = nouvelle_valeur
    p.derniere_modif_par_id = current_user().id
    enregistrer_audit(p, f"Paramètre {p.module}.{p.cle} modifié", current_user(),
                       ancien_statut=ancienne, nouveau_statut=nouvelle_valeur)
    db.session.commit()
    flash(f"Paramètre « {p.cle} » mis à jour ({ancienne} → {nouvelle_valeur}). "
          "Cette modification s'applique aux nouveaux calculs uniquement — les délais déjà "
          "engagés sur des dossiers en cours ne sont pas recalculés rétroactivement.", "success")
    return redirect(url_for("admin_referentiels"))


# ---------------------------------------------------------------------------
# Administration — utilisateurs et rôles
# ---------------------------------------------------------------------------
@app.route("/admin/utilisateurs")
@login_required
@roles_required("administrateur_dpml")
def admin_utilisateurs():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    statut = request.args.get("statut", "")
    query = Personne.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Personne.nom_complet.ilike(like), Personne.email.ilike(like)))
    if role:
        query = query.filter_by(role_systeme=role)
    if statut:
        query = query.filter_by(statut_compte=statut)
    personnes = query.order_by(Personne.nom_complet).all()
    nb_en_attente_validation = Personne.query.filter_by(statut_compte="en_attente_validation").count()
    return render_template("admin/utilisateurs.html", personnes=personnes, q=q, role=role, statut=statut,
                            roles_actifs=ROLES_ACTIFS, nb_en_attente_validation=nb_en_attente_validation)


@app.route("/admin/utilisateurs/nouveau", methods=["GET", "POST"])
@login_required
@roles_required("administrateur_dpml")
def admin_utilisateur_nouveau():
    etablissements = Etablissement.query.order_by(Etablissement.raison_sociale).all()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or not request.form.get("nom_complet", "").strip():
            flash("Le nom et l'e-mail sont obligatoires.", "danger")
            return render_template("admin/utilisateur_form.html", personne=None, etablissements=etablissements,
                                    roles_actifs=ROLES_ACTIFS)
        if Personne.query.filter_by(email=email).first():
            flash("Cet e-mail existe déjà.", "danger")
            return render_template("admin/utilisateur_form.html", personne=None, etablissements=etablissements,
                                    roles_actifs=ROLES_ACTIFS)
        p = Personne(
            nom_complet=request.form.get("nom_complet", "").strip(), email=email,
            role_systeme=request.form.get("role_systeme"),
            etablissement_rattachement_id=request.form.get("etablissement_id", type=int) or None,
            contact=request.form.get("contact", ""),
        )
        p.set_password("demo1234")
        db.session.add(p)
        db.session.flush()
        enregistrer_creation(p, current_user(), "Création du compte utilisateur")
        db.session.commit()
        flash("Compte créé (mot de passe par défaut : demo1234).", "success")
        return redirect(url_for("admin_utilisateurs"))
    return render_template("admin/utilisateur_form.html", personne=None, etablissements=etablissements,
                            roles_actifs=ROLES_ACTIFS)


@app.route("/admin/utilisateurs/<int:id>/modifier", methods=["GET", "POST"])
@login_required
@roles_required("administrateur_dpml")
def admin_utilisateur_modifier(id):
    p = Personne.query.get_or_404(id)
    etablissements = Etablissement.query.order_by(Etablissement.raison_sociale).all()
    if request.method == "POST":
        ancien_role = p.role_systeme
        p.nom_complet = request.form.get("nom_complet", "").strip()
        p.role_systeme = request.form.get("role_systeme")
        p.etablissement_rattachement_id = request.form.get("etablissement_id", type=int) or None
        p.contact = request.form.get("contact", "")
        if ancien_role != p.role_systeme:
            enregistrer_audit(p, "Rôle du compte modifié", current_user(),
                               ancien_statut=ancien_role, nouveau_statut=p.role_systeme)
        db.session.commit()
        flash("Compte mis à jour.", "success")
        return redirect(url_for("admin_utilisateurs"))
    return render_template("admin/utilisateur_form.html", personne=p, etablissements=etablissements,
                            roles_actifs=ROLES_ACTIFS)


@app.route("/admin/utilisateurs/<int:id>/suspendre", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def admin_utilisateur_suspendre(id):
    # Jamais de suppression physique d'un compte ayant produit de l'activité — seule la
    # bascule de statut_compte est possible (règle transversale, 10-RS §6).
    p = Personne.query.get_or_404(id)
    ancien = p.statut_compte
    p.statut_compte = "actif" if ancien == "suspendu" else "suspendu"
    enregistrer_audit(p, "Statut de compte modifié", current_user(), ancien_statut=ancien, nouveau_statut=p.statut_compte)
    db.session.commit()
    flash("Statut du compte mis à jour.", "success")
    return redirect(url_for("admin_utilisateurs"))


@app.route("/admin/utilisateurs/<int:id>/valider", methods=["POST"])
@login_required
@roles_required("administrateur_dpml")
def admin_utilisateur_valider(id):
    p = Personne.query.get_or_404(id)
    if p.statut_compte != "en_attente_validation":
        flash("Ce compte n'est pas en attente de validation.", "danger")
        return redirect(url_for("admin_utilisateurs"))
    ancien = p.statut_compte
    p.statut_compte = "actif"
    enregistrer_audit(p, "Inscription validée", current_user(), ancien_statut=ancien, nouveau_statut=p.statut_compte)
    notifier(p, "compte_valide",
             "Votre compte a été validé par la DPML. Vous pouvez désormais vous connecter.", lien="/login")
    db.session.commit()
    flash(f"Compte de {p.nom_complet} validé.", "success")
    return redirect(url_for("admin_utilisateurs"))


# ---------------------------------------------------------------------------
# Explorateur de base de données (lecture seule) — réponse directe à "où vont
# les données ?" : montre le fichier SQLite exact et le contenu réel de
# chaque table, sans dépendre d'un outil externe (DB Browser, etc.).
# ---------------------------------------------------------------------------
@app.route("/admin/base-donnees")
@login_required
@roles_required("administrateur_dpml")
def admin_base_donnees():
    tables = []
    for nom, table in sorted(db.metadata.tables.items()):
        nb = db.session.execute(db.text(f'SELECT COUNT(*) FROM "{nom}"')).scalar()
        tables.append({"nom": nom, "nb_colonnes": len(table.columns), "nb_lignes": nb})
    return render_template("admin/base_donnees.html", tables=tables,
                            chemin_fichier=app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))


@app.route("/admin/base-donnees/<nom_table>")
@login_required
@roles_required("administrateur_dpml")
def admin_base_donnees_table(nom_table):
    if nom_table not in db.metadata.tables:
        abort(404)
    table = db.metadata.tables[nom_table]
    colonnes = [c.name for c in table.columns]
    cle_tri = "rowid"
    if "id" in colonnes:
        cle_tri = "id"
    lignes = db.session.execute(
        db.text(f'SELECT * FROM "{nom_table}" ORDER BY {cle_tri} DESC LIMIT 50')
    ).mappings().all()
    # Masqué même pour l'administrateur : le hachage n'apporte aucune information utile
    # ici et ne doit pas être exposé au-delà de ce qui est strictement nécessaire.
    if "password_hash" in colonnes:
        lignes = [{**l, "password_hash": "••••••••"} for l in lignes]
    nb_total = db.session.execute(db.text(f'SELECT COUNT(*) FROM "{nom_table}"')).scalar()
    return render_template("admin/base_donnees_table.html", nom_table=nom_table, colonnes=colonnes,
                            lignes=lignes, nb_total=nb_total)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
