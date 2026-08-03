"""
Génération du certificat d'AMM (PDF avec sceau d'intégrité SHA-256 + QR code de
vérification publique). Pattern repris du prototype ehomologation-dplm.

NOTE (voir README.md) : la "signature électronique" ci-dessous est une
matérialisation graphique + un sceau d'intégrité à des fins de démonstration.
Elle ne constitue pas une signature électronique qualifiée au sens réglementaire.
"""
import hashlib
import io
from datetime import datetime

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _dessiner_entete(c, titre_organisme="RÉPUBLIQUE DU CAMEROUN — MINISTÈRE DE LA SANTÉ PUBLIQUE",
                      sous_titre="Direction de la Pharmacie, du Médicament et des Laboratoires (DPML)"):
    largeur, hauteur = A4
    c.setFillColor(colors.HexColor("#0b3d68"))
    c.rect(0, hauteur - 28 * mm, largeur, 28 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(largeur / 2, hauteur - 12 * mm, titre_organisme)
    c.setFont("Helvetica", 10)
    c.drawCentredString(largeur / 2, hauteur - 19 * mm, sous_titre)
    c.setFillColor(colors.black)


def _qr_verification(url_verification):
    img = qrcode.make(url_verification)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def calculer_hash(dossier, acteur_email, date_decision):
    base = f"{dossier.numero}|{date_decision.isoformat()}|{acteur_email}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def generer_certificat_amm(dossier, chemin_sortie, signataire, base_url=""):
    """Génère le PDF de l'AMM pour un DossierAMM au statut `approuve`.

    signataire : instance Personne (le directeur_dpml identifié dans la piste
    d'audit comme auteur de la décision d'approbation), utilisée pour le bloc
    de signature et le sceau d'intégrité.
    """
    c = canvas.Canvas(chemin_sortie, pagesize=A4)
    largeur, hauteur = A4
    _dessiner_entete(c)

    p = dossier.produit
    titulaire = p.titulaire_amm.raison_sociale if p.titulaire_amm else "-"
    fabricant = p.fabricant.raison_sociale if p.fabricant else "-"

    y = hauteur - 45 * mm
    c.setFont("Helvetica-Bold", 16)
    titre = "AUTORISATION DE MISE SUR LE MARCHÉ" if dossier.type_procedure != "retrait" else "DÉCISION DE RETRAIT D'AMM"
    c.drawCentredString(largeur / 2, y, titre)
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawCentredString(largeur / 2, y, f"N° {dossier.numero}")
    y -= 14 * mm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(25 * mm, y, "Produit :")
    c.setFont("Helvetica", 11)
    c.drawString(50 * mm, y, p.libelle)
    y -= 10 * mm

    champs = [
        ("Dénomination Commune Internationale (DCI)", p.denomination_commune_internationale),
        ("Forme pharmaceutique", p.forme_pharmaceutique or "-"),
        ("Dosage", p.dosage or "-"),
        ("Titulaire de l'AMM", titulaire),
        ("Fabricant", fabricant),
        ("Type de procédure", dossier.type_procedure.replace("_", " ").capitalize()),
    ]
    c.setFont("Helvetica", 10)
    for label, val in champs:
        val = (val or "-").replace("\n", " ")[:90]
        c.drawString(25 * mm, y, f"{label} : {val}")
        y -= 7 * mm

    y -= 6 * mm
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(25 * mm, y, "Le Directeur de la DPML, vu le dossier constitué conformément à la")
    y -= 5 * mm
    c.drawString(25 * mm, y, "réglementation en vigueur et l'avis de l'évaluation technique, délivre la")
    y -= 5 * mm
    if dossier.date_validite_amm:
        c.drawString(25 * mm, y, f"présente autorisation, valable jusqu'au {dossier.date_validite_amm.strftime('%d/%m/%Y')}.")
    else:
        c.drawString(25 * mm, y, "présente décision.")

    y -= 20 * mm
    c.setFont("Helvetica-Bold", 10)
    date_decision = dossier.date_decision
    c.drawString(25 * mm, y, f"Fait le {date_decision.strftime('%d/%m/%Y')}")
    y -= 14 * mm
    c.line(120 * mm, y + 4 * mm, 180 * mm, y + 4 * mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(120 * mm, y - 2 * mm, signataire.nom_complet if signataire else "Le Directeur DPML")
    c.setFont("Helvetica", 9)
    c.drawString(120 * mm, y - 7 * mm, "(signature électronique — voir cachet de vérification)")

    url_verif = f"{base_url}/verifier/{dossier.numero}"
    qr_buf = _qr_verification(url_verif)
    c.drawImage(ImageReader(qr_buf), 25 * mm, y - 25 * mm, width=28 * mm, height=28 * mm)
    c.setFont("Helvetica", 7)
    c.drawString(25 * mm, y - 27 * mm, f"Vérifier : {url_verif}")
    hash_verif = calculer_hash(dossier, signataire.email if signataire else "-", date_decision)
    c.drawString(25 * mm, y - 30 * mm, f"Sceau d'intégrité (SHA-256) : {hash_verif[:32]}...")

    c.showPage()
    c.save()
    return chemin_sortie


def generer_accuse_reception(dossier, chemin_sortie):
    """Accusé de Réception généré par le système/DPML lorsqu'un dossier est déclaré
    recevable — distinct de la preuve de paiement fournie par le demandeur (cf.
    formulaire officiel DPML, Section 3)."""
    c = canvas.Canvas(chemin_sortie, pagesize=A4)
    largeur, hauteur = A4
    _dessiner_entete(c)

    p = dossier.produit
    y = hauteur - 45 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(largeur / 2, y, "ACCUSÉ DE RÉCEPTION")
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawCentredString(largeur / 2, y, f"Dossier N° {dossier.numero}")
    y -= 14 * mm

    c.setFont("Helvetica", 10)
    champs = [
        ("Produit", p.libelle),
        ("Dénomination Commune Internationale (DCI)", p.denomination_commune_internationale),
        ("Type de procédure", dossier.type_procedure.replace("_", " ").capitalize()),
        ("Demandeur", dossier.demandeur.nom_complet if dossier.demandeur else "-"),
        ("Date de dépôt", dossier.date_depot.strftime("%d/%m/%Y") if dossier.date_depot else "-"),
    ]
    for label, val in champs:
        val = (val or "-").replace("\n", " ")[:90]
        c.drawString(25 * mm, y, f"{label} : {val}")
        y -= 7 * mm

    y -= 6 * mm
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(25 * mm, y, "La Direction de la Pharmacie, du Médicament et des Laboratoires (DPML) accuse")
    y -= 5 * mm
    c.drawString(25 * mm, y, "réception du dossier ci-dessus référencé, déclaré recevable à la présente date, et")
    y -= 5 * mm
    c.drawString(25 * mm, y, "confirme sa prise en charge pour instruction technique.")

    y -= 16 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25 * mm, y, f"Fait le {datetime.now().strftime('%d/%m/%Y')}")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(25 * mm, y, "Document généré automatiquement par le système SIREPH pour le compte de la DPML.")

    c.showPage()
    c.save()
    return chemin_sortie


def generer_certificat_laboratoire(echantillon, chemin_sortie):
    """Certificat d'analyse (conformité ou non-conformité) — module LT."""
    c = canvas.Canvas(chemin_sortie, pagesize=A4)
    largeur, hauteur = A4
    _dessiner_entete(c, sous_titre="Laboratoire National de Contrôle de Qualité des Médicaments (LANACOME)")

    y = hauteur - 45 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(largeur / 2, y, "CERTIFICAT D'ANALYSE")
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawCentredString(largeur / 2, y, f"N° {echantillon.numero}")
    y -= 14 * mm

    c.setFont("Helvetica", 10)
    for label, val in [
        ("Produit", echantillon.produit.libelle), ("Lot", echantillon.lot.numero_lot if echantillon.lot else "-"),
        ("Date de réception", echantillon.date_reception.strftime("%d/%m/%Y")),
        ("Analyste", echantillon.analyste.nom_complet if echantillon.analyste else "-"),
        ("Validé par", echantillon.validateur.nom_complet if echantillon.validateur else "-"),
    ]:
        c.drawString(25 * mm, y, f"{label} : {val}")
        y -= 7 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25 * mm, y, "Paramètre")
    c.drawString(85 * mm, y, "Résultat")
    c.drawString(120 * mm, y, "Spécification")
    c.drawString(160 * mm, y, "Conformité")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    for r in echantillon.resultats:
        c.drawString(25 * mm, y, str(r.get("parametre", ""))[:35])
        c.drawString(85 * mm, y, str(r.get("resultat_mesure", ""))[:20])
        c.drawString(120 * mm, y, str(r.get("specification", ""))[:20])
        c.drawString(160 * mm, y, "Conforme" if r.get("conformite") == "conforme" else "Non conforme")
        y -= 6 * mm

    y -= 10 * mm
    c.setFont("Helvetica-Bold", 12)
    conclusion = "CONFORME" if echantillon.conclusion == "conforme" else "NON CONFORME"
    c.drawString(25 * mm, y, f"Conclusion : {conclusion}")

    c.showPage()
    c.save()
    return chemin_sortie


def calculer_hash_recu(paiement):
    """Empreinte du reçu : rend toute altération détectable a posteriori."""
    base = (f"{paiement.numero}|{paiement.montant}|{paiement.devise}|"
            f"{paiement.reference_transaction or ''}|"
            f"{paiement.date_confirmation.isoformat() if paiement.date_confirmation else ''}")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def generer_recu_paiement(paiement, chemin_sortie, objet="", redevable=None,
                           moyen="", base_url=""):
    """Reçu de paiement — délivré uniquement pour une créance confirmée.

    Porte une empreinte SHA-256 et un QR de vérification : un reçu présenté sur
    papier peut être recoupé avec la base.
    """
    c = canvas.Canvas(chemin_sortie, pagesize=A4)
    largeur, hauteur = A4
    _dessiner_entete(c, sous_titre="Direction de la Pharmacie, du Médicament et des "
                                    "Laboratoires (DPML) — Recettes réglementaires")

    y = hauteur - 45 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(largeur / 2, y, "REÇU DE PAIEMENT")
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawCentredString(largeur / 2, y, f"N° {paiement.numero}")
    y -= 16 * mm

    # Montant encaissé, mis en évidence
    c.setFillColor(colors.HexColor("#eaf3ea"))
    c.rect(25 * mm, y - 4 * mm, largeur - 50 * mm, 16 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#14532d"))
    c.setFont("Helvetica-Bold", 18)
    montant = f"{paiement.montant:,}".replace(",", " ")
    c.drawCentredString(largeur / 2, y + 1 * mm, f"{montant} {paiement.devise}")
    c.setFillColor(colors.black)
    y -= 20 * mm

    c.setFont("Helvetica", 10)
    lignes = [
        ("Objet", objet or paiement.entite_type),
        ("Redevable", redevable.nom_complet if redevable else "-"),
        ("Établissement", redevable.etablissement.raison_sociale
         if redevable is not None and redevable.etablissement else "-"),
        ("Moyen de paiement", moyen or paiement.fournisseur or "-"),
        ("Référence de transaction", paiement.reference_transaction or "-"),
        ("Référence marchande", paiement.reference_marchande or "-"),
        ("Date d'encaissement",
         paiement.date_confirmation.strftime("%d/%m/%Y à %H:%M")
         if paiement.date_confirmation else "-"),
    ]
    for label, val in lignes:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(25 * mm, y, f"{label} :")
        c.setFont("Helvetica", 10)
        c.drawString(72 * mm, y, str(val)[:70])
        y -= 7 * mm

    y -= 6 * mm
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(25 * mm, y, "Ce reçu atteste du règlement de la redevance ci-dessus. "
                             "Il ne préjuge pas de la décision réglementaire.")
    c.setFillColor(colors.black)

    # Empreinte + QR de vérification
    empreinte = calculer_hash_recu(paiement)
    y -= 14 * mm
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, y, f"Empreinte SHA-256 : {empreinte}")

    if base_url:
        url = f"{base_url.rstrip('/')}/paiements/verifier/{paiement.numero}"
        try:
            c.drawImage(ImageReader(_qr_verification(url)), largeur - 55 * mm,
                        y - 30 * mm, width=30 * mm, height=30 * mm)
            c.setFont("Helvetica", 7)
            c.drawCentredString(largeur - 40 * mm, y - 34 * mm, "Vérifier ce reçu")
        except Exception:
            pass          # un QR indisponible ne doit pas empêcher la délivrance

    c.setFont("Helvetica", 8)
    c.drawCentredString(largeur / 2, 15 * mm,
                        f"Document généré par SIREPH le "
                        f"{datetime.utcnow().strftime('%d/%m/%Y à %H:%M')} UTC")

    c.showPage()
    c.save()
    return chemin_sortie
