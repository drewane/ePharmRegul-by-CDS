"""Routes du module LT (Analyses de laboratoire / LIMS), en Blueprint Flask."""
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_from_directory

from models import db, Echantillon, Produit, Lot
import workflow_lt as wflt
import pdf_gen
from auth import current_user, login_required, roles_required

lt_bp = Blueprint("lt", __name__)
ROLES_LT = ("administrateur_dpml", "agent_laboratoire", "responsable_qualite_labo")
CERT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "certificats")


@lt_bp.route("/echantillons")
@login_required
@roles_required(*ROLES_LT)
def registre():
    q = Echantillon.query
    statut = request.args.get("statut", "")
    origine = request.args.get("origine", "")
    if statut:
        q = q.filter_by(statut=statut)
    if origine:
        q = q.filter_by(origine=origine)
    echantillons = q.order_by(Echantillon.date_reception.desc()).all()
    return render_template("laboratoire/registre.html", echantillons=echantillons, statut=statut, origine=origine)


@lt_bp.route("/echantillons/nouveau", methods=["GET", "POST"])
@login_required
@roles_required("administrateur_dpml", "agent_laboratoire")
def nouveau():
    produits = Produit.query.order_by(Produit.nom_commercial).all()
    if request.method == "POST":
        produit = Produit.query.get(request.form.get("produit_id", type=int))
        if not produit:
            flash("Le produit est obligatoire.", "danger")
            return render_template("laboratoire/nouveau.html", produits=produits)
        numero_lot = request.form.get("numero_lot", "").strip()
        lot = None
        if numero_lot:
            lot = Lot.query.filter_by(produit_id=produit.id, numero_lot=numero_lot).first()
            if not lot:
                lot = Lot(produit_id=produit.id, numero_lot=numero_lot, statut="non_applicable")
                db.session.add(lot)
                db.session.flush()
        ech = wflt.creer_echantillon(produit, current_user(), origine="demande_directe", lot=lot)
        db.session.commit()
        flash(f"Échantillon {ech.numero} enregistré.", "success")
        return redirect(url_for("lt.fiche", id=ech.id))
    return render_template("laboratoire/nouveau.html", produits=produits)


@lt_bp.route("/echantillons/<int:id>")
@login_required
@roles_required(*ROLES_LT)
def fiche(id):
    ech = Echantillon.query.get_or_404(id)
    from models import EvenementAudit
    audit_events = EvenementAudit.query.filter_by(entite_type="Echantillon", entite_id=ech.id) \
        .order_by(EvenementAudit.horodatage.desc()).all()
    return render_template("laboratoire/fiche.html", ech=ech, audit_events=audit_events,
                            peut_agir=wflt.peut_agir(ech, current_user()))


@lt_bp.route("/echantillons/<int:id>/prendre-en-charge", methods=["POST"])
@login_required
@roles_required("agent_laboratoire")
def action_prendre_en_charge(id):
    ech = Echantillon.query.get_or_404(id)
    try:
        wflt.prendre_en_charge(ech, current_user())
        db.session.commit()
        flash("Échantillon pris en charge.", "success")
    except wflt.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lt.fiche", id=id))


@lt_bp.route("/echantillons/<int:id>/resultats", methods=["POST"])
@login_required
@roles_required("agent_laboratoire")
def action_resultats(id):
    ech = Echantillon.query.get_or_404(id)
    resultats = []
    for i in range(1, 8):
        parametre = request.form.get(f"parametre_{i}", "").strip()
        if not parametre:
            continue
        resultats.append({
            "parametre": parametre, "methode": request.form.get(f"methode_{i}", "").strip(),
            "resultat_mesure": request.form.get(f"resultat_{i}", "").strip(),
            "specification": request.form.get(f"specification_{i}", "").strip(),
        })
    try:
        wflt.saisir_resultats(ech, current_user(), resultats)
        db.session.commit()
        flash("Résultats saisis.", "success")
    except wflt.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lt.fiche", id=id))


@lt_bp.route("/echantillons/<int:id>/valider", methods=["POST"])
@login_required
@roles_required("responsable_qualite_labo")
def action_valider(id):
    ech = Echantillon.query.get_or_404(id)
    try:
        wflt.valider_resultats(ech, current_user(), request.form.get("decision"),
                                conclusion=request.form.get("conclusion"),
                                observation=request.form.get("observation", ""))
        db.session.commit()
        flash("Décision de validation enregistrée.", "success")
    except wflt.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lt.fiche", id=id))


@lt_bp.route("/echantillons/<int:id>/certificat", methods=["POST"])
@login_required
@roles_required("responsable_qualite_labo")
def action_certificat(id):
    ech = Echantillon.query.get_or_404(id)
    try:
        wflt.emettre_certificat(ech, current_user())
        db.session.commit()
        flash(f"Certificat émis pour {ech.numero}.", "success")
    except wflt.ErreurWorkflow as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("lt.fiche", id=id))


@lt_bp.route("/echantillons/<int:id>/certificat.pdf")
@login_required
def telecharger_certificat(id):
    ech = Echantillon.query.get_or_404(id)
    if ech.statut != "certificat_emis":
        abort(404)
    os.makedirs(CERT_DIR, exist_ok=True)
    chemin = os.path.join(CERT_DIR, f"{ech.numero}.pdf")
    if not os.path.exists(chemin):
        pdf_gen.generer_certificat_laboratoire(ech, chemin)
    return send_from_directory(CERT_DIR, f"{ech.numero}.pdf", as_attachment=False)
