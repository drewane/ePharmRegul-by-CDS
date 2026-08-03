"""
Ce que chaque échelon a besoin de voir pour signer.

Un ministre ne relit pas un rapport de stabilité : il vérifie que le dossier a
bien suivi son parcours et que les échelons compétents se sont prononcés. Un
chef de service, à l'inverse, a besoin du détail technique.

Cette différenciation n'est pas cosmétique : présenter au signataire final un
mur de données qu'il ne peut pas exploiter dilue sa responsabilité et allonge
inutilement le circuit.
"""
from permissions import ROLES

# Profondeur d'information par échelon
#   technique  — détail du dossier, avis individuels, pièces
#   synthese   — avis consolidés, points saillants, historique
#   parcours   — traçabilité, conformité de la procédure, décision attendue
PROFONDEUR = {
    "chef_service_amm": "technique",
    "chef_service_licences": "technique",
    "chef_service_inspection": "technique",
    "chef_service_labo": "technique",
    "sous_directeur_medicament": "synthese",
    "sous_directeur_etablissements": "synthese",
    "directeur_dpml": "synthese",
    "directeur_general_agence": "parcours",
    "secretaire_general_ms": "parcours",
    "ministre_sante": "parcours",
    "administrateur_dpml": "technique",
}

LIBELLE_PROFONDEUR = {
    "technique": "Vue technique complète",
    "synthese": "Vue de synthèse",
    "parcours": "Vue parcours et conformité",
}


def profondeur(user):
    if user is None:
        return "parcours"
    return PROFONDEUR.get(user.role_systeme, "parcours")


def _jalons(dossier):
    """Étapes franchies par le dossier, avec leurs dates — le fil du parcours."""
    from models import EvenementAudit

    evenements = (EvenementAudit.query
                  .filter_by(entite_type=dossier.__class__.__name__,
                             entite_id=dossier.id)
                  .order_by(EvenementAudit.horodatage).all())
    reperes = [
        ("Dépôt du dossier", dossier.date_depot),
        ("Décision", dossier.date_decision),
    ]
    jalons = [{"libelle": lib, "date": d} for lib, d in reperes if d]
    for mot, libelle in (("recevable", "Recevabilité prononcée"),
                         ("Rapport d'instruction", "Rapport transmis à la direction"),
                         ("Circuit de validation ouvert", "Circuit de signature ouvert")):
        e = next((x for x in evenements if mot.lower() in (x.action or "").lower()), None)
        if e:
            jalons.append({"libelle": libelle, "date": e.horodatage})
    return sorted(jalons, key=lambda j: j["date"])


def dossier_amm(dossier, user):
    """Ce qu'il faut montrer de ce dossier à cet utilisateur."""
    import validation_numerique as vn
    import workflow_instruction as wfi
    from models import Paiement

    niveau = profondeur(user)
    etat = wfi.etat_instruction(dossier)
    faits, total = vn.progression(dossier)
    paiements = (Paiement.query
                 .filter_by(entite_type="DossierAMM", entite_id=dossier.id).all())

    vue = {
        "profondeur": niveau,
        "libelle_profondeur": LIBELLE_PROFONDEUR[niveau],
        "role": ROLES.get(getattr(user, "role_systeme", ""), ""),
        # Socle commun à tous les échelons
        "reference": dossier.numero,
        "produit": dossier.produit.libelle if dossier.produit else "—",
        "demandeur": dossier.demandeur.nom_complet if dossier.demandeur else "—",
        "statut": dossier.statut,
        "signatures": f"{faits}/{total}" if total else "—",
        "jalons": _jalons(dossier),
        "frais_regles": any(p.statut == "confirme" for p in paiements),
    }

    if niveau == "parcours":
        # Le signataire final vérifie la régularité, pas la technique.
        vue["controles"] = [
            ("Dossier déposé et enregistré", bool(dossier.date_depot)),
            ("Frais de dossier réglés", vue["frais_regles"]),
            ("Recevabilité prononcée", dossier.statut != "soumis"),
            ("Évaluation interne réalisée", etat["evaluations_remises"] > 0),
            ("Avis de commission recueilli",
             any(i.avis_global for i in etat["inscriptions"])),
            ("Rapport de la direction transmis", etat["rapport"] is not None),
        ]
        if etat["rapport"]:
            vue["avis_direction"] = wfi.AVIS.get(etat["rapport"].avis_propose,
                                                 etat["rapport"].avis_propose)
            vue["motif_direction"] = etat["rapport"].motif
        vue["avis_commission"] = [
            wfi.AVIS.get(i.avis_global, i.avis_global)
            for i in etat["inscriptions"] if i.avis_global]
        return vue

    if niveau == "synthese":
        vue["avis_evaluateurs"] = [
            {"nom": a.evaluateur.nom_complet,
             "conclusion": wfi.AVIS.get(a.conclusion, a.conclusion or "en cours")}
            for a in etat["assignations"]]
        vue["syntheses_commission"] = [
            {"seance": i.session.numero,
             "avis": wfi.AVIS.get(i.avis_global, i.avis_global),
             "synthese": i.synthese}
            for i in etat["inscriptions"] if i.avis_global]
        vue["rapport"] = etat["rapport"]
        return vue

    # Vue technique : tout, y compris les rapports intégraux
    vue["assignations"] = etat["assignations"]
    vue["inscriptions"] = etat["inscriptions"]
    vue["rapport"] = etat["rapport"]
    vue["checklist"] = dossier.checklist_recevabilite or {}
    vue["points_manquants"] = etat["points_manquants"]
    return vue
