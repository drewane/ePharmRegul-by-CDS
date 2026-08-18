"""
Gabarits PDF des actes délivrés : certificat d'homologation et AMM.

Séparés de `pdf_gen`, qui reste tel quel : des dossiers antérieurs ont été
délivrés avec ses gabarits, et leur PDF doit rester reproductible à
l'identique. On n'y touche donc pas — on ajoute à côté.

L'en-tête bilingue, lui, est partagé : c'est lui qui fait foi de l'émetteur,
et deux rédactions du même en-tête finiraient par différer.
"""
import hashlib
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from pdf_gen import _qr_verification, dessiner_entete_bilingue


def _cartouche(c, y, lignes, hauteur_mm):
    """Encadré d'identification du produit."""
    largeur, _h = A4
    c.setFillColor(colors.HexColor("#f2f6fa"))
    c.rect(20 * mm, y - hauteur_mm * mm, largeur - 40 * mm,
           hauteur_mm * mm, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#c8d4e0"))
    c.rect(20 * mm, y - hauteur_mm * mm, largeur - 40 * mm,
           hauteur_mm * mm, fill=0, stroke=1)
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)

    yy = y - 7 * mm
    for label, valeur in lignes:
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(25 * mm, yy, f"{label} :")
        c.setFont("Helvetica", 8.5)
        c.drawString(88 * mm, yy, str(valeur or "—")[:62])
        yy -= 6 * mm
    return y - hauteur_mm * mm


def _lignes_produit(dossier):
    """Les mêmes rubriques sur les deux actes, dans le même ordre.

    Bilingues, parce que l'acte l'est : un titulaire étranger doit pouvoir
    lire ce qu'on lui délivre.
    """
    p = dossier.produit
    titulaire = (p.titulaire_amm.raison_sociale
                 if p and p.titulaire_amm else None)
    return [
        ("Nom commercial / Brand name", p.nom_commercial if p else None),
        ("Dénomination commune (DCI) / INN",
         p.denomination_commune_internationale if p else None),
        ("Forme pharmaceutique / Dosage form",
         p.forme_pharmaceutique if p else None),
        ("Dosage / Strength", p.dosage if p else None),
        ("Voie d'administration / Route",
         getattr(p, "voie_administration", None)),
        ("Classe thérapeutique / ATC class",
         getattr(p, "classe_therapeutique", None)),
        ("Titulaire / Authorization holder", titulaire),
        ("Pays d'origine / Country of origin",
         getattr(p, "pays_origine", None)),
    ]


def _filigrane(c, texte):
    """Marque un document comme non définitif, en travers de la page."""
    largeur, hauteur = A4
    c.saveState()
    c.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.13))
    c.setFont("Helvetica-Bold", 62)
    c.translate(largeur / 2, hauteur / 2)
    c.rotate(38)
    c.drawCentredString(0, 0, texte)
    c.restoreState()


def _pied(c, dossier, numero_acte, base_url, mention):
    """QR de vérification, empreinte d'intégrité et mention, en pied de page."""
    empreinte = hashlib.sha256(
        f"{numero_acte}|{dossier.numero}|"
        f"{(dossier.date_decision or datetime.utcnow()).isoformat()}"
        .encode("utf-8")).hexdigest()

    if base_url:
        url = f"{base_url.rstrip('/')}/verifier/{dossier.numero}"
        try:
            c.drawImage(ImageReader(_qr_verification(url)), 20 * mm, 18 * mm,
                        width=24 * mm, height=24 * mm)
            c.setFont("Helvetica", 6.5)
            c.drawString(20 * mm, 15 * mm, "Vérifier / Verify")
        except Exception:
            # Un QR absent ne doit pas empêcher la délivrance de l'acte.
            pass

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(50 * mm, 28 * mm, f"Empreinte SHA-256 : {empreinte[:48]}...")
    c.drawString(50 * mm, 24 * mm, mention[:110])
    c.setFillColor(colors.black)
    return empreinte


def _titre(c, y, titre_fr, titre_en, numero_acte):
    largeur, _h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(largeur / 2, y, titre_fr)
    y -= 6 * mm
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(largeur / 2, y, titre_en)
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(largeur / 2, y, f"N° {numero_acte}")
    return y - 12 * mm


def _bloc_signature(c, y, qualite, nom, mention_attente=None):
    largeur, _h = A4
    x = largeur - 95 * mm
    c.line(x, y + 4 * mm, largeur - 25 * mm, y + 4 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, nom)
    c.setFont("Helvetica", 7.5)
    ligne = y - 4.5 * mm
    for morceau in qualite:
        c.drawString(x, ligne, morceau)
        ligne -= 4 * mm
    if mention_attente:
        c.setFont("Helvetica-Oblique", 7.5)
        c.setFillColor(colors.HexColor("#b02a2a"))
        c.drawString(x, ligne - 1 * mm, mention_attente)
        c.setFillColor(colors.black)
    return ligne


def generer_certificat(dossier, chemin_sortie, signataire, base_url=""):
    """Certificat d'homologation — acte de la DPML, signé par son directeur.

    Définitif dès sa génération : le directeur qui valide est celui qui signe,
    et sa décision est déjà prise quand ce document existe.
    """
    c = canvas.Canvas(chemin_sortie, pagesize=A4)
    largeur, _h = A4
    y = dessiner_entete_bilingue(c) - 12 * mm
    y = _titre(c, y, "CERTIFICAT D'HOMOLOGATION",
               "CERTIFICATE OF MARKETING AUTHORIZATION",
               dossier.numero_certificat)

    c.setFont("Helvetica", 9)
    for ligne in ("Le Directeur de la Pharmacie, du Médicament et des "
                  "Laboratoires certifie que le produit désigné",
                  "ci-après a satisfait à l'évaluation technique et "
                  "réglementaire prévue par la réglementation",
                  "pharmaceutique en vigueur en République du Cameroun."):
        c.drawString(20 * mm, y, ligne)
        y -= 5 * mm
    y -= 6 * mm

    y = _cartouche(c, y, _lignes_produit(dossier), 55) - 10 * mm

    c.setFont("Helvetica", 9)
    reference = f"Dossier de référence : {dossier.numero}"
    if dossier.numero_suivi:
        reference += f" · Suivi : {dossier.numero_suivi}"
    c.drawString(20 * mm, y, reference)
    y -= 5.5 * mm
    if dossier.date_validite_amm:
        c.drawString(20 * mm, y, "Validité / Validity : jusqu'au "
                     f"{dossier.date_validite_amm.strftime('%d/%m/%Y')}")
        y -= 5.5 * mm

    date_decision = dossier.date_decision or datetime.utcnow()
    y -= 14 * mm
    c.setFont("Helvetica", 9)
    c.drawString(largeur - 95 * mm, y,
                 f"Yaoundé, le {date_decision.strftime('%d/%m/%Y')}")
    y -= 20 * mm
    _bloc_signature(
        c, y,
        ("Directeur de la Pharmacie, du Médicament", "et des Laboratoires"),
        signataire.nom_complet if signataire else "Le Directeur DPML")

    _pied(c, dossier, dossier.numero_certificat, base_url,
          "Certificat délivré par voie électronique — ePharmRegul by CDS.")
    c.showPage()
    c.save()
    return chemin_sortie


def generer_amm(dossier, chemin_sortie, base_url="", signee=False):
    """Autorisation de mise sur le marché — acte du ministre.

    Tant que l'exemplaire signé n'est pas déposé, le document porte la mention
    PROJET en filigrane. Un projet d'AMM qui ne se distinguerait pas d'une AMM
    signée est une invitation à s'en prévaloir à tort.
    """
    c = canvas.Canvas(chemin_sortie, pagesize=A4)
    largeur, _h = A4
    if not signee:
        _filigrane(c, "PROJET")
    y = dessiner_entete_bilingue(c) - 12 * mm
    y = _titre(c, y, "AUTORISATION DE MISE SUR LE MARCHÉ",
               "MARKETING AUTHORIZATION", dossier.numero_amm)

    c.setFont("Helvetica", 9)
    visas = [
        "Le Ministre de la Santé publique,",
        "Vu la réglementation pharmaceutique en vigueur en République du "
        "Cameroun ;",
        "Vu le rapport d'évaluation et le certificat d'homologation "
        f"n° {dossier.numero_certificat} de la",
        "Direction de la Pharmacie, du Médicament et des Laboratoires ;",
    ]
    for ligne in visas:
        c.drawString(20 * mm, y, ligne)
        y -= 5 * mm
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 10.5)
    c.drawCentredString(largeur / 2, y,
                        "AUTORISE LA MISE SUR LE MARCHÉ DU PRODUIT DÉSIGNÉ "
                        "CI-APRÈS")
    y -= 12 * mm

    y = _cartouche(c, y, _lignes_produit(dossier), 55) - 10 * mm

    c.setFont("Helvetica", 9)
    if dossier.date_validite_amm:
        c.drawString(20 * mm, y, "La présente autorisation est valable "
                     f"jusqu'au {dossier.date_validite_amm.strftime('%d/%m/%Y')}, "
                     "sauf suspension ou retrait.")
        y -= 5.5 * mm
    c.drawString(20 * mm, y, "Elle est délivrée sous réserve du respect, par "
                             "le titulaire, de ses obligations réglementaires,")
    y -= 5 * mm
    c.drawString(20 * mm, y, "notamment en matière de pharmacovigilance et de "
                             "qualité des lots mis sur le marché.")

    date_decision = dossier.date_decision or datetime.utcnow()
    y -= 18 * mm
    c.setFont("Helvetica", 9)
    c.drawString(largeur - 95 * mm, y,
                 f"Yaoundé, le {date_decision.strftime('%d/%m/%Y')}")
    y -= 22 * mm
    _bloc_signature(
        c, y, ("Ministre de la Santé publique",),
        "Le Ministre de la Santé publique",
        None if signee else "Signature manuscrite en attente")

    mention = ("Exemplaire signé déposé au dossier." if signee else
               "PROJET — sans valeur tant que la signature du ministre n'est "
               "pas déposée.")
    _pied(c, dossier, dossier.numero_amm, base_url, mention)
    c.showPage()
    c.save()
    return chemin_sortie
