"""
Dossier d'AMM complet, prêt pour la décision du directeur.

POURQUOI CE SCRIPT
------------------
Depuis l'ajout de la garde `dossier_instruit`, on ne valide plus un dossier
vide — et c'est tant mieux. Mais la base de démonstration n'en contenait aucun
qui fût réellement instruit : la chaîne s'arrêtait donc à un bouton grisé.

Ce script fabrique un dossier qui a traversé tout le circuit : redevance
encaissée, recevabilité prononcée, passage en commission, avis rendus, pièces
déposées. Il s'arrête à `retour_homologation` — l'état où le directeur décide.
La dernière étape n'est pas jouée, c'est justement celle qu'on veut montrer.

    venv\\Scripts\\python seed_demonstration_amm.py

IDEMPOTENT
----------
Rejouable sans risque : le dossier est reconnu à sa référence. Relancer ne
crée pas de doublon, cela remet le dossier existant à l'état de décision — ce
qui permet de rejouer la démonstration autant de fois qu'on veut.

    venv\\Scripts\\python seed_demonstration_amm.py --supprimer

le retire entièrement, pièces et fichiers compris.
"""
import io
import os
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Repère de reconnaissance : ce nom identifie le dossier de démonstration.
NOM_PRODUIT = "Palurex 20 mg / 120 mg"

# Les pièces qu'un dossier d'AMM porte réellement. Le contenu est symbolique —
# ce sont de vrais PDF, pour que le téléchargement fonctionne d'un bout à
# l'autre, mais leur texte ne fait qu'énoncer ce qu'ils représentent.
PIECES = [
    ("Certificat de produit pharmaceutique (CPP)",
     "Certificat de produit pharmaceutique",
     "Modèle OMS. Atteste l'autorisation du produit dans le pays d'origine "
     "et la conformité du site de fabrication."),
    ("Certificat de bonnes pratiques de fabrication (BPF)",
     "Certificat BPF",
     "Délivré par l'autorité du pays de fabrication à l'issue d'une "
     "inspection du site."),
    ("Dossier technique — module 3 (Qualité)",
     "module_ctd_3",
     "Composition qualitative et quantitative, procédé de fabrication, "
     "contrôles de la substance active et du produit fini, stabilité."),
    ("Étude de bioéquivalence",
     "Étude de bioéquivalence",
     "Comparaison au produit de référence. Rapports de concentration "
     "plasmatique dans les intervalles d'acceptation."),
    ("Projet de notice et d'étiquetage",
     "Notice et étiquetage",
     "Mentions obligatoires en français et en anglais, conformément à la "
     "réglementation nationale."),
]

# Les avis d'évaluation. Deux modules et un avis global : c'est le global qui
# lève la garde, les avis de module documentent l'instruction.
AVIS = [
    ("module3", "favorable",
     "Qualité pharmaceutique conforme. Spécifications et méthodes de contrôle "
     "validées ; stabilité démontrée sur 24 mois en zone climatique IVb."),
    ("module5", "favorable",
     "Bioéquivalence démontrée par rapport au produit de référence. "
     "Intervalles de confiance dans les bornes d'acceptation."),
    ("global", "favorable",
     "Rapport bénéfice/risque favorable dans l'indication revendiquée. "
     "La commission recommande l'octroi de l'autorisation."),
]


def _pdf(titre, corps):
    """Un vrai PDF d'une page, pour que le téléchargement soit réel."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    tampon = io.BytesIO()
    c = canvas.Canvas(tampon, pagesize=A4)
    largeur, hauteur = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(25 * mm, hauteur - 35 * mm, titre)
    c.setFont("Helvetica", 10)
    y = hauteur - 48 * mm
    mots, ligne = corps.split(), ""
    for mot in mots:
        if len(ligne) + len(mot) > 88:
            c.drawString(25 * mm, y, ligne)
            y -= 6 * mm
            ligne = mot
        else:
            ligne = f"{ligne} {mot}".strip()
    if ligne:
        c.drawString(25 * mm, y, ligne)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(25 * mm, 25 * mm,
                 "Pièce de démonstration — ePharmRegul by CDS. "
                 "Sans valeur réglementaire.")
    c.showPage()
    c.save()
    tampon.seek(0)
    return tampon


def _compte(db, email, role=None):
    from models import Personne

    if email:
        p = Personne.query.filter_by(email=email).first()
        if p:
            return p
    return Personne.query.filter_by(role_systeme=role,
                                    statut_compte="actif").first()


def _dossier_existant():
    from models import DossierAMM, Produit

    produit = Produit.query.filter_by(nom_commercial=NOM_PRODUIT).first()
    if produit is None:
        return None, None
    return produit, DossierAMM.query.filter_by(produit_id=produit.id).first()


def supprimer():
    """Retire le dossier de démonstration et ce qui s'y rattache."""
    from models import (AvisEvaluationMA, DossierAMM, EvenementAudit, Paiement,
                        PieceJointe, db)
    from pieces import DOCUMENTS_DIR

    produit, dossier = _dossier_existant()
    if dossier is None:
        print("Aucun dossier de démonstration à retirer.")
        return 0

    for p in PieceJointe.query.filter_by(entite_type="DossierAMM",
                                         entite_id=dossier.id).all():
        chemin = os.path.join(DOCUMENTS_DIR, *p.chemin_fichier.split("/"))
        if os.path.exists(chemin):
            os.remove(chemin)
        db.session.delete(p)
    AvisEvaluationMA.query.filter_by(dossier_id=dossier.id).delete()
    EvenementAudit.query.filter_by(entite_type="DossierAMM",
                                   entite_id=dossier.id).delete()
    Paiement.query.filter_by(entite_type="DossierAMM",
                             entite_id=dossier.id).delete()
    reference = dossier.numero
    db.session.delete(dossier)
    db.session.flush()
    if produit:
        db.session.delete(produit)
    db.session.commit()
    print(f"Dossier {reference} et ses pièces retirés.")
    return 0


def main():
    import app as application
    import machine_etats as me
    from models import AvisEvaluationMA, DossierAMM, Produit, db

    with application.app.app_context():
        if "--supprimer" in sys.argv:
            return supprimer()

        import gardes_dossier  # noqa: F401 — enregistre la garde
        from numerotation import generer_numero
        from pieces import enregistrer_piece
        from suivi import numero_suivi
        from werkzeug.datastructures import FileStorage

        deposant = _compte(db, "demandeur@pharmacam.demo", "demandeur_externe")
        financier = _compte(db, "finances@dpml.demo", "responsable_financier")
        chef = _compte(db, "chefservice@dpml.demo", "chef_service_amm")
        evaluateur = _compte(db, "evaluateur@dpml.demo", "evaluateur_amm") or chef
        if not all([deposant, financier, chef]):
            print("Comptes de démonstration absents : lancez seed_comptes.py.")
            return 1

        produit, dossier = _dossier_existant()

        # --- Remise en état d'un dossier déjà présent --------------------
        if dossier is not None:
            dossier.statut = "retour_homologation"
            dossier.numero_certificat = None
            dossier.numero_amm = None
            dossier.date_decision = None
            dossier.date_validite_amm = None
            dossier.motif_decision = None
            db.session.commit()
            reste = me.obstacles(dossier, me.transition("valider"))
            print(f"Dossier {dossier.numero} remis à l'état de décision.")
            print("  empêchements :", reste or "aucun — le directeur peut valider")
            return 0

        # --- Création ----------------------------------------------------
        produit = Produit(
            nom_commercial=NOM_PRODUIT,
            denomination_commune_internationale="artéméther + luméfantrine",
            forme_pharmaceutique="Comprimé pelliculé",
            dosage="20 mg / 120 mg",
            dosage_valeur="20", dosage_unite="mg",
            nature="chimique", categorie="medicament",
            voie_administration="Voie orale",
            classe_therapeutique="P01 — Antiprotozoaires",
            code_atc="P01",
            indications_therapeutiques="Traitement du paludisme simple à "
                                       "Plasmodium falciparum",
            conditionnement="Boîte de 24 comprimés sous plaquettes",
            quantite_conditionnement="24",
            composition_integrale="Artéméther 20 mg ; luméfantrine 120 mg ; "
                                  "excipients q.s.p. un comprimé pelliculé.",
            pays_origine="Cameroun",
            duree_stabilite="24 mois",
            titulaire_amm_id=deposant.etablissement_rattachement_id,
        )
        db.session.add(produit)
        db.session.flush()

        dossier = DossierAMM(
            numero=generer_numero("AMM"), produit_id=produit.id,
            demandeur_id=deposant.id, statut="brouillon",
            type_procedure="nouvelle_demande",
            nature_acte="octroi", type_produit="medicament_chimique",
            type_dossier="ctd",
            date_depot=datetime.utcnow() - timedelta(days=38),
        )
        db.session.add(dossier)
        db.session.flush()
        dossier.numero_suivi = numero_suivi("amm")
        db.session.commit()
        print(f"Dossier créé : {dossier.numero} · {dossier.numero_suivi}")

        # --- Pièces ------------------------------------------------------
        for titre, type_doc, corps in PIECES:
            fichier = FileStorage(
                stream=_pdf(titre, corps),
                filename=f"{titre.split('(')[0].strip().lower()
                             .replace(' ', '-').replace('—', '')}.pdf",
                content_type="application/pdf")
            enregistrer_piece(dossier, fichier, type_doc, deposant)
        db.session.commit()
        print(f"  {len(PIECES)} pièces déposées")

        # --- Parcours ----------------------------------------------------
        me.appliquer_transition(dossier, "soumettre", deposant)
        db.session.commit()

        # La redevance passe par le vrai circuit financier : c'est lui qui
        # démarre le délai légal et fait avancer la machine.
        import paiements
        paiement = paiements.creer_paiement(dossier, 250000)
        paiement.statut = "preuve_deposee"
        db.session.commit()
        paiements.confirmer(paiement, financier)
        db.session.commit()
        print(f"  redevance {paiement.numero} encaissée — "
              f"statut : {me.libelle(dossier)}")

        for action, acteur in (("declarer_recevable", chef),
                               ("envoyer_commission", chef),
                               ("retour_service", chef)):
            me.appliquer_transition(dossier, action, acteur)
            db.session.commit()

        # --- Avis d'évaluation -------------------------------------------
        for module, valeur, commentaire in AVIS:
            db.session.add(AvisEvaluationMA(
                dossier_id=dossier.id, evaluateur_id=evaluateur.id,
                module_concerne=module, valeur=valeur,
                commentaire=commentaire))
        db.session.commit()
        print(f"  {len(AVIS)} avis d'évaluation rendus")

        # --- Contrôle ----------------------------------------------------
        reste = me.obstacles(dossier, me.transition("valider"))
        print()
        print("=" * 70)
        print(f"  {dossier.numero} — {NOM_PRODUIT}")
        print(f"  État : {me.libelle(dossier)}")
        print(f"  Empêchements : {reste or 'aucun'}")
        print()
        print("  Le directeur (directeur@dpml.demo) le trouve dans")
        print("  « Ma file d'attente » et peut le valider.")
        print("=" * 70)
        return 0 if not reste else 1


if __name__ == "__main__":
    sys.exit(main())
