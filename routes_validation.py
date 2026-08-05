"""
Validation numérique : parapheur des signataires et signature des documents.

Chaque échelon dispose d'un parapheur listant les documents qui attendent
précisément sa signature. Le document PDF n'est produit qu'à la signature du
dernier échelon.
"""
import os
import tempfile
from datetime import date, datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   send_file, url_for)

import pdf_gen
import validation_numerique as vn
from audit import enregistrer_audit
from auth import current_user, login_required, niveau_requis
from erreurs import ErreurWorkflow
from models import (DemandeDerogation, DossierAMM, EtapeValidation, VisaTechnique,
                    db)
from notifications import notifier

bp = Blueprint("validation", __name__, url_prefix="/validation")

# Type d'entité → (modèle, circuit, libellé, préfixe de fichier)
DOCUMENTS = {
    "DossierAMM": (DossierAMM, "amm", "Autorisation de mise sur le marché", "amm"),
    "DemandeDerogation": (DemandeDerogation, "derogation", "Dérogation spéciale",
                          "derogation"),
    "VisaTechnique": (VisaTechnique, "visa_technique", "Visa technique", "visa"),
}


def _entite(entite_type, entite_id):
    if entite_type not in DOCUMENTS:
        abort(404)
    obj = db.session.get(DOCUMENTS[entite_type][0], entite_id)
    if not obj:
        abort(404)
    return obj


def _entite_lisible(entite_type, entite_id):
    """Charge l'entité en vérifiant que l'utilisateur a le droit de la lire.

    Le circuit d'un dossier n'est pas une pièce publique : un agent y accède au
    titre de l'instruction, le déposant au titre du dossier qui est le sien. Un
    usager ou un concurrent n'y a rien à voir — sans ce contrôle, l'espace de
    validation contournerait le cloisonnement garanti par l'espace industriel.
    """
    from permissions import a_niveau

    obj = _entite(entite_type, entite_id)
    u = current_user()
    if a_niveau(u, 1):
        return obj

    import espace_industriel as esp
    demandeur = getattr(obj, "demandeur_id", None)
    if demandeur is not None and demandeur in esp.personnes_de_la_societe(u):
        return obj
    abort(404)      # 404 plutôt que 403 : ne révèle pas l'existence du dossier


# ---------------------------------------------------------------------------
# Parapheur : ce qui attend MA signature
# ---------------------------------------------------------------------------
@bp.route("/parapheur")
@login_required
@niveau_requis(1)
def parapheur():
    """Un parapheur n'a de sens que pour un agent : les externes n'en ont pas."""
    u = current_user()
    attente = (EtapeValidation.query
               .filter_by(role_requis=u.role_systeme, statut="en_attente")
               .order_by(EtapeValidation.date_creation).all())

    # Une étape n'est signable que si les précédentes le sont : on ne présente
    # que celles réellement ouvertes, pour ne pas promettre une action impossible.
    a_signer = []
    for e in attente:
        obj = db.session.get(DOCUMENTS[e.entite_type][0], e.entite_id) \
            if e.entite_type in DOCUMENTS else None
        if obj is None:
            continue
        courante = vn.etape_courante(obj)
        if courante is not None and courante.id == e.id:
            faits, total = vn.progression(obj)
            a_signer.append({"etape": e, "objet": obj,
                             "libelle": DOCUMENTS[e.entite_type][2],
                             "faits": faits, "total": total})

    # Historique de mes signatures
    signees = (EtapeValidation.query
               .filter_by(validateur_id=u.id)
               .order_by(EtapeValidation.date_validation.desc()).limit(20).all())
    return render_template("validation/parapheur.html", u=u, a_signer=a_signer,
                           signees=signees, documents=DOCUMENTS)


# ---------------------------------------------------------------------------
# Circuit d'un document
# ---------------------------------------------------------------------------
@bp.route("/<entite_type>/<int:entite_id>")
@login_required
def circuit(entite_type, entite_id):
    obj = _entite_lisible(entite_type, entite_id)
    u = current_user()
    # Chaque échelon voit ce qui lui est utile pour décider : le ministre
    # vérifie le parcours, le chef de service relit la technique.
    vue = None
    if entite_type == "DossierAMM":
        import vue_par_profil
        vue = vue_par_profil.dossier_amm(obj, u)

    # Les pièces du dossier accompagnent le circuit d'un bout à l'autre : on
    # ne signe pas sur la foi d'un résumé. Le demandeur, lui, ne voit ici que
    # l'acte signé — le reste de l'instruction ne le regarde pas.
    from permissions import a_niveau
    import amm_signee
    from pieces import lister_pieces

    signee = amm_signee.piece_signee(obj) if entite_type == "DossierAMM" else None
    pieces = lister_pieces(obj) if a_niveau(u, 1) else (
        [signee] if signee is not None else [])

    return render_template(
        "validation/circuit.html", objet=obj, entite_type=entite_type,
        libelle=DOCUMENTS[entite_type][2], etapes=vn.etapes(obj), vue=vue,
        courante=vn.etape_courante(obj), acheve=vn.circuit_acheve(obj),
        refuse=vn.circuit_refuse(obj), peut_signer=vn.peut_signer(obj, u),
        pieces=pieces, signee=signee, agent=a_niveau(u, 1),
        peut_deposer_signee=(entite_type == "DossierAMM"
                             and amm_signee.peut_deposer(obj, u)),
        duree_defaut=amm_signee.duree_par_defaut(),
        duree_max=amm_signee.DUREE_MAX_ANNEES,
        aujourdhui=date.today().isoformat())


@bp.route("/DossierAMM/<int:entite_id>/amm-signee", methods=["POST"])
@login_required
def deposer_amm_signee(entite_id):
    """Le chef de service dépose l'acte signé du ministre et fixe sa validité."""
    import amm_signee

    obj = _entite("DossierAMM", entite_id)
    lien = url_for("validation.circuit", entite_type="DossierAMM",
                   entite_id=entite_id)
    date_signature = None
    saisie = (request.form.get("date_signature") or "").strip()
    if saisie:
        try:
            date_signature = datetime.strptime(saisie, "%Y-%m-%d").date()
        except ValueError:
            flash("Date de signature illisible (format attendu : AAAA-MM-JJ).",
                  "danger")
            return redirect(lien)
    try:
        amm_signee.deposer(obj, request.files.get("fichier"), current_user(),
                           request.form.get("duree_annees"), date_signature)
        db.session.commit()
        flash(f"AMM signée déposée. Le titulaire peut la télécharger ; elle est "
              f"valable jusqu'au {obj.date_validite_amm.strftime('%d/%m/%Y')}, "
              "avec rappel de renouvellement six mois avant l'échéance.",
              "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(lien)


@bp.route("/<entite_type>/<int:entite_id>/ouvrir", methods=["POST"])
@login_required
def ouvrir(entite_type, entite_id):
    """Ouvre le circuit de signature — après instruction technique."""
    from permissions import a_niveau
    u = current_user()
    if not a_niveau(u, 2):
        abort(403)
    obj = _entite(entite_type, entite_id)
    circuit_code = DOCUMENTS[entite_type][1]
    try:
        vn.ouvrir_circuit(obj, circuit_code, u,
                          lien=url_for("validation.circuit", entite_type=entite_type,
                                       entite_id=entite_id))
        db.session.commit()
        flash("Circuit de validation ouvert. Le premier échelon a été alerté.", "success")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("validation.circuit", entite_type=entite_type,
                            entite_id=entite_id))


@bp.route("/<entite_type>/<int:entite_id>/signer", methods=["POST"])
@login_required
def signer(entite_type, entite_id):
    u = current_user()
    obj = _entite(entite_type, entite_id)
    lien = url_for("validation.circuit", entite_type=entite_type, entite_id=entite_id)
    try:
        _etape, acheve = vn.signer(obj, u, request.form.get("commentaire"), lien=lien)
        if acheve:
            _finaliser(obj, entite_type, u)
            flash("Signature finale apposée — le document officiel a été produit.",
                  "success")
        else:
            suivante = vn.etape_courante(obj)
            flash(f"Votre validation est enregistrée. Le dossier passe au "
                  f"« {suivante.libelle_role} ».", "success")
        db.session.commit()
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(lien)


@bp.route("/<entite_type>/<int:entite_id>/refuser", methods=["POST"])
@login_required
def refuser(entite_type, entite_id):
    u = current_user()
    obj = _entite(entite_type, entite_id)
    try:
        vn.refuser(obj, u, request.form.get("motif", ""))
        db.session.commit()
        flash("Refus enregistré : le circuit est interrompu.", "info")
    except ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("validation.circuit", entite_type=entite_type,
                            entite_id=entite_id))


# ---------------------------------------------------------------------------
# Production du document final
# ---------------------------------------------------------------------------
def _finaliser(obj, entite_type, acteur):
    """Applique la décision et produit le document officiel signé."""
    if entite_type == "DossierAMM":
        ancien = obj.statut
        obj.statut = "approuve"
        obj.date_decision = obj.date_decision or datetime.utcnow()
        # La durée de validité n'est PAS déduite ici : elle est celle que porte
        # l'acte signé, saisie par le chef de service à son dépôt. La présumer
        # à cinq ans reviendrait à armer les rappels de renouvellement sur une
        # échéance que le ministre n'a pas fixée.
        enregistrer_audit(
            obj, "AMM signée par le Ministre de la Santé — décision favorable",
            acteur, ancien, obj.statut)
        notifier_tous_roles = ("chef_service_amm", "chef_bureau")
        for role in notifier_tous_roles:
            from notifications import notifier_tous
            notifier_tous(role, "amm_a_publier",
                          f"Le circuit du dossier {obj.numero} est achevé. "
                          "Déposez l'AMM signée du ministre pour la mettre à "
                          "disposition du titulaire.",
                          lien=f"/validation/DossierAMM/{obj.id}")
        if obj.demandeur:
            notifier(obj.demandeur, "amm_octroyee",
                     f"Votre demande {obj.numero} a reçu une décision favorable, "
                     "signée par le ministre. L'autorisation vous sera "
                     "communiquée dès sa mise en ligne par le service.",
                     lien=f"/industriel/suivi/{obj.id}")
    else:
        enregistrer_audit(obj, f"{DOCUMENTS[entite_type][2]} signé — document produit",
                          acteur)
        destinataire = getattr(obj, "demandeur", None)
        if destinataire:
            notifier(destinataire, "document_signe",
                     f"Votre {DOCUMENTS[entite_type][2].lower()} "
                     f"{getattr(obj, 'numero', '')} a été signé.",
                     lien=f"/validation/{entite_type}/{obj.id}")


@bp.route("/<entite_type>/<int:entite_id>/document")
@login_required
@niveau_requis(1)
def document(entite_type, entite_id):
    """Certificat d'homologation — support interne, réservé à l'administration.

    Tout agent y accède, à tout échelon : la signature s'appuie sur ce que les
    services ont pu lire. Le demandeur, lui, n'y a pas accès — un certificat
    généré, sans signature manuscrite ni sceau, se présenterait trop aisément
    comme l'autorisation elle-même. Ce que le demandeur télécharge, c'est
    l'acte signé déposé par le chef de service (cf. amm_signee.py).
    """
    obj = _entite(entite_type, entite_id)
    if not vn.circuit_acheve(obj):
        flash("Le document officiel n'est produit qu'au terme du circuit de "
              "validation.", "warning")
        return redirect(url_for("validation.circuit", entite_type=entite_type,
                                entite_id=entite_id))

    prefixe = DOCUMENTS[entite_type][3]
    numero = getattr(obj, "numero", obj.id)
    chemin = os.path.join(tempfile.gettempdir(), f"{prefixe}-{numero}.pdf")
    etapes = vn.etapes(obj)

    if entite_type == "DossierAMM":
        pdf_gen.generer_amm(obj, chemin, etapes_validation=etapes,
                            base_url=request.url_root)
    else:
        lignes = [("Référence", numero),
                  ("Demandeur", obj.demandeur.nom_complet
                   if getattr(obj, "demandeur", None) else "—"),
                  ("Objet", getattr(obj, "objet", None)
                   or getattr(obj, "motif", None) or "—"),
                  ("Date", datetime.utcnow().strftime("%d/%m/%Y"))]
        pdf_gen.generer_decision_signee(
            obj, chemin, DOCUMENTS[entite_type][2], lignes,
            etapes_validation=etapes,
            mention="Le présent document est délivré au terme du circuit de "
                    "validation numérique de la Direction de la Pharmacie, du "
                    "Médicament et des Laboratoires.")

    return send_file(chemin, as_attachment=True,
                     download_name=f"{prefixe}-{numero}.pdf",
                     mimetype="application/pdf")
