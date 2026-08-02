"""
Pièces jointes — téléversement générique, réutilisé par les modules qui
acceptent des documents transmis par un demandeur (MA, LI...). Le type
d'entité concernée est dérivé de la classe de l'objet passé
(entite.__class__.__name__), même convention que audit.py, pour éviter des
chaînes "DossierAMM"/"DemandeLicence" recopiées à la main.

Pas de scan antivirus ni d'analyse de contenu : hors périmètre de ce
prototype, à ajouter avant un déploiement en production (cf. README, section
limitations assumées).
"""
import os
import uuid

from werkzeug.utils import secure_filename

from models import db, PieceJointe
from audit import enregistrer_audit
from erreurs import ErreurWorkflow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCUMENTS_DIR = os.path.join(BASE_DIR, "static", "documents")
EXTENSIONS_AUTORISEES = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx"}
TAILLE_MAX_OCTETS = 10 * 1024 * 1024  # 10 Mo


def _extension_autorisee(nom_fichier):
    return "." in nom_fichier and nom_fichier.rsplit(".", 1)[1].lower() in EXTENSIONS_AUTORISEES


def enregistrer_piece(entite, fichier_werkzeug, type_document, acteur):
    """
    Sauvegarde le fichier sur disque, crée la PieceJointe, journalise le dépôt
    dans la piste d'audit de l'entité parente (DossierAMM, DemandeLicence...).
    N'effectue pas le commit — à la charge de la route appelante.
    """
    if not fichier_werkzeug or not fichier_werkzeug.filename:
        raise ErreurWorkflow("Aucun fichier sélectionné.")
    nom_original = secure_filename(fichier_werkzeug.filename)
    if not nom_original or not _extension_autorisee(nom_original):
        raise ErreurWorkflow(
            "Type de fichier non autorisé (formats acceptés : PDF, images, Word, Excel).")

    entite_type = entite.__class__.__name__
    sous_dossier = os.path.join(DOCUMENTS_DIR, entite_type, str(entite.id))
    os.makedirs(sous_dossier, exist_ok=True)
    nom_stocke = f"{uuid.uuid4().hex}_{nom_original}"
    chemin_absolu = os.path.join(sous_dossier, nom_stocke)
    fichier_werkzeug.save(chemin_absolu)

    taille = os.path.getsize(chemin_absolu)
    if taille > TAILLE_MAX_OCTETS:
        os.remove(chemin_absolu)
        raise ErreurWorkflow("Fichier trop volumineux (10 Mo maximum).")

    piece = PieceJointe(
        entite_type=entite_type, entite_id=entite.id, type_document=type_document,
        nom_fichier=nom_original,
        # Toujours avec "/" (indépendant de l'OS) : send_from_directory (Werkzeug)
        # interprète ce chemin en le découpant sur "/", pas sur le séparateur natif.
        chemin_fichier="/".join([entite_type, str(entite.id), nom_stocke]),
        taille_octets=taille, televerse_par_id=acteur.id if acteur else None,
    )
    db.session.add(piece)
    enregistrer_audit(entite, "Téléversement de document", acteur,
                       commentaire=f"{type_document or 'Document'} — {nom_original}")
    return piece


def lister_pieces(entite):
    return (PieceJointe.query
            .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
            .order_by(PieceJointe.date_televersement.desc()).all())
