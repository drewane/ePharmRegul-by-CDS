"""
Voie d'homologation d'un dossier d'AMM : nationale, reconnaissance, ou
préqualification OMS.

Le choix ne crée pas un dossier d'un autre genre : c'est le MÊME dossier
d'AMM, instruit sur des pièces différentes et dans un délai différent. Cette
route sert donc à qualifier un dossier, non à en ouvrir un type nouveau — ce
qui aurait dédoublé toute la chaîne d'instruction et de signature.
"""
from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import modules_ctd as ctd
import voies_homologation as vh
from auth import current_user, login_required
from models import DossierAMM, db

bp = Blueprint("voies", __name__, url_prefix="/homologation")


def _dossier_accessible(dossier_id):
    from permissions import a_niveau

    u = current_user()
    d = db.session.get(DossierAMM, dossier_id) or abort(404)
    if a_niveau(u, 1):
        return u, d
    import espace_industriel as esp
    if d.demandeur_id not in esp.personnes_de_la_societe(u):
        abort(404)
    return u, d


@bp.route("/voies")
@login_required
def presentation():
    """Les trois voies, ce qu'elles allègent et ce qu'elles n'allègent pas."""
    u = current_user()
    exemple_nature = "chimique"
    comparaison = []
    for code, voie in vh.VOIES.items():
        comparaison.append({
            "code": code, **voie,
            "modules": vh.modules_exiges(code, exemple_nature,
                                         "nouvelle_demande"),
            "pieces": vh.pieces_exigees(code),
        })
    return render_template("homologation/voies.html", u=u,
                           voies=comparaison,
                           autorites=vh.AUTORITES_REFERENCE,
                           programmes=vh.PROGRAMMES_OMS,
                           controles=vh.CONTROLES_NATIONAUX,
                           modules=ctd.MODULES)


@bp.route("/dossiers/<int:dossier_id>/voie", methods=["GET", "POST"])
@login_required
def choisir(dossier_id):
    """Qualifie un dossier existant : sur quelle évaluation s'appuie-t-il ?"""
    u, d = _dossier_accessible(dossier_id)

    if request.method == "POST":
        voie = (request.form.get("voie") or "").strip()
        autorite = (request.form.get("autorite_reference") or "").strip() or None
        programme = (request.form.get("programme_oms") or "").strip() or None
        if not vh.voie_valide(voie):
            flash("Voie d'homologation inconnue.", "danger")
            return redirect(url_for("voies.choisir", dossier_id=d.id))
        erreur = vh.verifier_reference(voie, autorite, programme)
        if erreur:
            flash(erreur, "danger")
            return redirect(url_for("voies.choisir", dossier_id=d.id))

        d.voie_homologation = voie
        d.autorite_reference = autorite if voie == "reconnaissance" else None
        d.programme_oms = programme if voie == "prequalification" else None
        d.reference_etrangere = (request.form.get("reference_etrangere")
                                 or "").strip() or None
        saisie = (request.form.get("date_reference") or "").strip()
        d.date_reference = None
        if saisie:
            try:
                d.date_reference = datetime.strptime(saisie, "%Y-%m-%d").date()
            except ValueError:
                flash("Date de la décision de référence illisible "
                      "(format AAAA-MM-JJ).", "warning")

        from audit import enregistrer_audit
        enregistrer_audit(
            d, f"Voie d'homologation : {vh.VOIES[voie]['libelle']}"
               + (f" — {vh.libelle_reference(voie, autorite, programme)}"
                  if vh.libelle_reference(voie, autorite, programme) else ""),
            u)
        db.session.commit()
        flash(f"Dossier qualifié en « {vh.VOIES[voie]['libelle']} ». "
              f"Délai d'instruction annoncé : {vh.delai_legal(voie)} jours.",
              "success")
        return redirect(url_for("voies.choisir", dossier_id=d.id))

    nature = ctd.nature_du_produit(d.produit)
    voie_actuelle = d.voie_homologation or vh.VOIE_PAR_DEFAUT
    return render_template(
        "homologation/choix_voie.html", u=u, d=d, VOIES=vh.VOIES,
        voie_actuelle=voie_actuelle,
        autorites=vh.AUTORITES_REFERENCE, programmes=vh.PROGRAMMES_OMS,
        modules_nationaux=ctd.modules_obligatoires(nature, d.type_procedure),
        modules_voie=vh.modules_exiges(voie_actuelle, nature, d.type_procedure),
        pieces=vh.pieces_exigees(voie_actuelle),
        controles=vh.CONTROLES_NATIONAUX,
        libelle_reference=vh.libelle_reference(
            voie_actuelle, d.autorite_reference, d.programme_oms),
        modules=ctd.MODULES,
        aujourdhui=__import__("datetime").date.today().isoformat())
