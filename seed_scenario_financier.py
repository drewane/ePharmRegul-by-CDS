"""
Scénario de démonstration : la séparation des tâches, bout en bout.

Prépare un dossier dans l'état exact où la règle se voit : soumis, complet sur
tous les points que le chef de service maîtrise, mais bloqué sur la preuve de
paiement — qu'il ne peut pas cocher. Seule l'approbation du responsable
financier lèvera le verrou, démarrera le délai légal et avertira le service.

    venv\\Scripts\\python seed_scenario_financier.py

Le script est idempotent : relancé, il remet le même dossier dans l'état de
départ plutôt que d'en accumuler.
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import suivi
import workflow_instruction as wfi
from models import DossierAMM, Paiement, Personne, Produit, db

REFERENCE = "AMM-DEMO-SEPARATION"


def _remettre_a_zero(dossier):
    """Ramène le dossier à l'état « en attente d'approbation financière »."""
    dossier.statut = "soumis"
    dossier.clock_debut = None
    dossier.clock_suspendu_depuis = None
    dossier.clock_total_suspendu_jours = 0
    dossier.date_decision = None
    dossier.motif_decision = None
    # Tout est vérifié sauf la recette, qui n'est pas du ressort de l'instructeur.
    dossier.checklist_recevabilite = {
        code: (code != "preuve_paiement")
        for code, _l, _b in wfi.CHECKLIST_RECEVABILITE}


def preparer():
    demandeur = Personne.query.filter_by(email="demandeur@pharmacam.demo").first()
    if demandeur is None:
        raise SystemExit("Compte demandeur@pharmacam.demo absent — lancer seed.py.")

    dossier = DossierAMM.query.filter_by(numero=REFERENCE).first()
    if dossier is None:
        produit = (Produit.query
                   .filter_by(titulaire_amm_id=demandeur.etablissement_rattachement_id)
                   .first())
        if produit is None:
            produit = Produit(nom_commercial="Paracétamol Démo 500",
                              denomination_commune_internationale="Paracétamol",
                              forme_pharmaceutique="Comprimé", nature="chimique",
                              titulaire_amm_id=demandeur.etablissement_rattachement_id)
            db.session.add(produit)
            db.session.flush()
        dossier = DossierAMM(numero=REFERENCE, produit_id=produit.id,
                             demandeur_id=demandeur.id, statut="soumis",
                             type_procedure="amm")
        db.session.add(dossier)
        db.session.flush()

    _remettre_a_zero(dossier)
    if not dossier.numero_suivi:
        dossier.numero_suivi = suivi.numero_suivi("amm")

    # Une seule créance en attente d'approbation à la fois.
    for ancien in Paiement.query.filter_by(entite_type="DossierAMM",
                                           entite_id=dossier.id).all():
        db.session.delete(ancien)
    db.session.flush()

    paiement = Paiement(numero=f"PAY-DEMO-{uuid.uuid4().hex[:4].upper()}",
                        entite_type="DossierAMM", entite_id=dossier.id,
                        montant=500000, devise="XAF", statut="preuve_deposee",
                        fournisseur="virement")
    db.session.add(paiement)
    db.session.commit()
    return dossier, paiement


def main():
    import app as application

    with application.app.app_context():
        dossier, paiement = preparer()
        manquants = wfi.points_manquants(dossier)

        print("=" * 74)
        print("SCÉNARIO — séparation des tâches finances / instruction")
        print("=" * 74)
        print(f"  Dossier   : {dossier.numero}  ({dossier.numero_suivi})")
        print(f"  Créance   : {paiement.numero} — "
              f"{paiement.montant:,} {paiement.devise}".replace(",", " "))
        print(f"  Statut    : preuve déposée, en attente d'approbation")
        print(f"  Bloquant  : "
              + (", ".join(libelle for _c, libelle in manquants) or "aucun"))
        print(f"  Délai     : {'démarré' if dossier.clock_debut else 'non démarré'}")
        print()
        print("  À FAIRE POUR ÉPROUVER LA RÈGLE")
        print("  1. chefservice@dpml.demo → /instruction/dossiers/"
              f"{dossier.id} : la recevabilité est refusée, "
              "la case « preuve de paiement » lui échappe.")
        print("  2. finances@dpml.demo    → /paiements/approbation : approuver.")
        print("  3. chefservice@dpml.demo → la recevabilité passe, "
              "le délai a démarré.")
        print("  Mot de passe : demo1234")
    return 0


if __name__ == "__main__":
    sys.exit(main())
