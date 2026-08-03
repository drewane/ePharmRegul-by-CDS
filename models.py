"""
Modèle de données — SIREPH (socle commun + module MA)

Toutes les entités pivots du socle commun (01-modele-donnees.md) sont définies ici,
même celles peu exploitées par le module MA (Lot, géolocalisation d'Établissement),
pour que les futurs modules (VL, RI, LI, LT, MC, CT, LR) les réutilisent sans jamais
les dupliquer dans un stockage isolé — principe directeur explicite du cahier des
charges.
"""
import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Personne
# ---------------------------------------------------------------------------
class Personne(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom_complet = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)  # identifiant de connexion
    password_hash = db.Column(db.String(255), nullable=False)
    role_systeme = db.Column(db.String(50), nullable=False)
    etablissement_rattachement_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=True)
    contact = db.Column(db.String(200))
    statut_compte = db.Column(db.String(20), nullable=False, default="actif")
    # actif | en_attente_validation (auto-inscription, cf. app.py:inscription_labo) | suspendu
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    etablissement = db.relationship("Etablissement", foreign_keys=[etablissement_rattachement_id])

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

    @property
    def role_label(self):
        from permissions import ROLES
        return ROLES.get(self.role_systeme, self.role_systeme)

    @property
    def niveau(self):
        """Niveau de responsabilité (0 externe → 4 administration système)."""
        from permissions import niveau
        return niveau(self)

    @property
    def niveau_label(self):
        from permissions import LIBELLE_NIVEAU
        return LIBELLE_NIVEAU.get(self.niveau, "")

    @property
    def est_externe(self):
        from permissions import est_externe
        return est_externe(self.role_systeme)


# ---------------------------------------------------------------------------
# Établissement
# ---------------------------------------------------------------------------
class Etablissement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    raison_sociale = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(40), nullable=False)
    # fabricant | grossiste_repartiteur | officine | depot | importateur_exportateur | laboratoire_controle
    adresse = db.Column(db.String(500))
    latitude = db.Column(db.Float, nullable=True)   # géolocalisation — exploité par le futur module RI
    longitude = db.Column(db.Float, nullable=True)
    statut_licence = db.Column(db.String(20), nullable=False, default="en_instruction")
    # active | suspendue | expiree | en_instruction
    date_expiration_licence = db.Column(db.Date, nullable=True)
    pharmacien_responsable_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    # Pertinent pour les grossistes-répartiteurs uniquement : medicaments | dispositifs_medicaux | les_deux
    categorie_activite = db.Column(db.String(30), nullable=True)

    pharmacien_responsable = db.relationship("Personne", foreign_keys=[pharmacien_responsable_id])


# ---------------------------------------------------------------------------
# Produit
# ---------------------------------------------------------------------------
class Produit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    denomination_commune_internationale = db.Column(db.String(300), nullable=False, default="")
    nom_commercial = db.Column(db.String(300), nullable=False, default="")
    forme_pharmaceutique = db.Column(db.String(150), nullable=False, default="")
    dosage = db.Column(db.String(150))
    categorie = db.Column(db.String(30), nullable=False, default="medicament")
    # medicament | vaccin | produit_sanguin | dispositif_medical | autre
    # Nature du produit : pilote la profondeur du dossier technique exigé
    # (chimique | biologique | phytotherapie | dispositif_medical | autre).
    nature = db.Column(db.String(30), nullable=True)
    fabricant_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=True)
    titulaire_amm_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=True)
    pays_origine = db.Column(db.String(150))
    statut_amm_courant = db.Column(db.String(20), nullable=False, default="aucune")
    # aucune | en_cours | active | suspendue | retiree
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    # Marquage MITM (Médicament d'Intérêt Thérapeutique Majeur) — module MC §6,
    # configurable par administrateur_dpml, avec suivi de disponibilité déclarée.
    est_mitm = db.Column(db.Boolean, nullable=False, default=False)
    disponibilite_declaree = db.Column(db.String(20), nullable=True)  # disponible | rupture

    # Champs SECTION 2 du formulaire officiel DPML (Champs de formulaire — Template
    # DPLM Application Form) : identification complète du produit, au-delà du strict
    # nécessaire pour le circuit d'AMM déjà couvert par les champs ci-dessus.
    composition_integrale = db.Column(db.Text, nullable=True)
    classe_therapeutique = db.Column(db.String(300), nullable=True)
    indications_therapeutiques = db.Column(db.Text, nullable=True)
    voie_administration = db.Column(db.String(150), nullable=True)
    duree_stabilite = db.Column(db.String(100), nullable=True)
    prix_grossiste_ht = db.Column(db.Integer, nullable=True)  # XAF, hors taxe

    fabricant = db.relationship("Etablissement", foreign_keys=[fabricant_id])
    titulaire_amm = db.relationship("Etablissement", foreign_keys=[titulaire_amm_id])
    dossiers = db.relationship("DossierAMM", backref="produit", lazy="dynamic",
                                foreign_keys="DossierAMM.produit_id")

    @property
    def libelle(self):
        base = self.nom_commercial or self.denomination_commune_internationale or f"Produit #{self.id}"
        if self.dosage:
            return f"{base} ({self.dosage})"
        return base


# ---------------------------------------------------------------------------
# Lot — pivot pour les futurs modules VL / MC / LR. Non manipulé par MA.
# ---------------------------------------------------------------------------
class Lot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    numero_lot = db.Column(db.String(100), nullable=False)
    date_fabrication = db.Column(db.Date, nullable=True)
    date_peremption = db.Column(db.Date, nullable=True)
    fabricant_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=True)
    statut = db.Column(db.String(20), nullable=False, default="non_applicable")
    # en_circulation | rappele | quarantaine | libere | non_applicable

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    fabricant = db.relationship("Etablissement", foreign_keys=[fabricant_id])


# ---------------------------------------------------------------------------
# DossierAMM
# ---------------------------------------------------------------------------
class DossierAMM(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=True)  # AMM-{annee}-{seq4}, attribué au dépôt
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    type_procedure = db.Column(db.String(20), nullable=False, default="nouvelle_demande")
    # nouvelle_demande | renouvellement | variation | retrait
    demandeur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    statut = db.Column(db.String(30), nullable=False, default="brouillon")
    date_depot = db.Column(db.DateTime, nullable=True)
    date_decision = db.Column(db.DateTime, nullable=True)

    module_ctd_1_json = db.Column(db.Text, default="{}")
    module_ctd_2_json = db.Column(db.Text, default="{}")
    module_ctd_3_json = db.Column(db.Text, default="{}")
    module_ctd_4_json = db.Column(db.Text, default="{}")
    module_ctd_5_json = db.Column(db.Text, default="{}")

    motif_decision = db.Column(db.Text, nullable=True)
    date_validite_amm = db.Column(db.Date, nullable=True)
    date_limite_reponse_complement = db.Column(db.DateTime, nullable=True)
    date_limite_retrait_document = db.Column(db.Date, nullable=True)  # décision favorable uniquement

    # Liste de contrôle de recevabilité renseignée par le chef de service
    checklist_recevabilite = db.Column(db.JSON, default=dict)
    representant_local_nom = db.Column(db.String(200), nullable=True)
    representant_local_contact = db.Column(db.String(200), nullable=True)

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    demandeur = db.relationship("Personne", foreign_keys=[demandeur_id])
    avis = db.relationship("AvisEvaluationMA", backref="dossier", lazy="dynamic",
                            order_by="AvisEvaluationMA.date_creation",
                            cascade="all, delete-orphan")

    def _ctd_get(self, n):
        return json.loads(getattr(self, f"module_ctd_{n}_json") or "{}")

    def _ctd_set(self, n, valeur):
        setattr(self, f"module_ctd_{n}_json", json.dumps(valeur, ensure_ascii=False))

    module_ctd_1 = property(lambda self: self._ctd_get(1), lambda self, v: self._ctd_set(1, v))
    module_ctd_2 = property(lambda self: self._ctd_get(2), lambda self, v: self._ctd_set(2, v))
    module_ctd_3 = property(lambda self: self._ctd_get(3), lambda self, v: self._ctd_set(3, v))
    module_ctd_4 = property(lambda self: self._ctd_get(4), lambda self, v: self._ctd_set(4, v))
    module_ctd_5 = property(lambda self: self._ctd_get(5), lambda self, v: self._ctd_set(5, v))

    @property
    def est_editable_par_demandeur(self):
        return self.statut in ("brouillon", "complement_requis")


# ---------------------------------------------------------------------------
# AvisEvaluationMA — avis d'un evaluateur_amm sur un DossierAMM (0..n par dossier)
# ---------------------------------------------------------------------------
class AvisEvaluationMA(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), nullable=False)
    evaluateur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    module_concerne = db.Column(db.String(20))  # module1..5 | global
    valeur = db.Column(db.String(30), nullable=False)  # favorable | complement_requis | recommandation_rejet
    commentaire = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    evaluateur = db.relationship("Personne", foreign_keys=[evaluateur_id])


# ---------------------------------------------------------------------------
# NotificationVigilance (ICSR) — module VL, 12-VL-pharmacovigilance.md §5
# ---------------------------------------------------------------------------
class NotificationVigilance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # PV-{annee}-{seq4}, attribué à la réception
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=True)  # produit parfois inconnu
    lot_id = db.Column(db.Integer, db.ForeignKey("lot.id"), nullable=True)

    # Patient anonymisé dès la saisie : âge et sexe uniquement, jamais de donnée
    # directement identifiante (nom, n° de dossier médical, coordonnées du patient).
    patient_age = db.Column(db.Integer, nullable=True)
    patient_sexe = db.Column(db.String(10), nullable=True)  # M | F | inconnu

    description_effet = db.Column(db.Text, nullable=False)
    gravite = db.Column(db.String(20), nullable=False)  # non_grave | grave | fatal
    source = db.Column(db.String(30), nullable=False)  # professionnel_sante | patient | industriel | litterature

    # Coordonnées du NOTIFICATEUR (pas du patient) pour un éventuel suivi — optionnelles,
    # un notificateur externe peut rester anonyme (critère d'acceptation VL).
    notificateur_nom = db.Column(db.String(200), nullable=True)
    notificateur_contact = db.Column(db.String(200), nullable=True)

    statut = db.Column(db.String(20), nullable=False, default="recue")
    evaluation_causalite = db.Column(db.Text, nullable=True)
    type_mesure = db.Column(db.String(50), nullable=True)  # information|restriction|retrait, si mesure décidée
    motif_decision = db.Column(db.Text, nullable=True)  # motif de clôture sans mesure, ou de rejet de signal

    reference_e2b = db.Column(db.String(100), nullable=True)  # référence VigiFlow après transmission
    date_transmission_e2b = db.Column(db.DateTime, nullable=True)

    date_notification = db.Column(db.DateTime, default=datetime.utcnow)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    lot = db.relationship("Lot", foreign_keys=[lot_id])

    @property
    def gravite_label(self):
        return {"non_grave": "Non grave", "grave": "Grave", "fatal": "Fatal"}.get(self.gravite, self.gravite)


# ---------------------------------------------------------------------------
# DemandeLicence — module LI, 14-LI-licences-etablissements.md §5
# ---------------------------------------------------------------------------
class DemandeLicence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # LIC-{annee}-{seq4}
    etablissement_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=False)
    type_demande = db.Column(db.String(20), nullable=False, default="nouvelle")  # nouvelle | renouvellement
    statut = db.Column(db.String(20), nullable=False, default="deposee")
    # deposee | en_instruction | approuvee | refusee
    pieces_justificatives = db.Column(db.Text, nullable=True)  # description libre, pas de pipeline de fichiers ici
    motif_decision = db.Column(db.Text, nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_decision = db.Column(db.DateTime, nullable=True)

    etablissement = db.relationship("Etablissement", foreign_keys=[etablissement_id])


# ---------------------------------------------------------------------------
# Échantillon — module LT, 15-LT-laboratoire.md §5
# ---------------------------------------------------------------------------
class Echantillon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # LAB-{annee}-{seq4}
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("lot.id"), nullable=True)
    origine = db.Column(db.String(30), nullable=False, default="demande_directe")
    # dossier_amm | inspection | signalement_marche | demande_directe | liberation_lot
    origine_reference_id = db.Column(db.Integer, nullable=True)
    date_reception = db.Column(db.DateTime, default=datetime.utcnow)
    # Redevable de l'analyse pour un échantillon reçu sur demande directe.
    # Nul pour un prélèvement d'office (inspection, signalement) : non facturé.
    demandeur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    analyste_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    validateur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    resultats_json = db.Column(db.Text, default="[]")  # liste de ResultatParametre
    statut = db.Column(db.String(20), nullable=False, default="recu")
    conclusion = db.Column(db.String(20), nullable=True)  # conforme | non_conforme, décision explicite RQ
    observation_rejet = db.Column(db.Text, nullable=True)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    lot = db.relationship("Lot", foreign_keys=[lot_id])
    demandeur = db.relationship("Personne", foreign_keys=[demandeur_id])
    analyste = db.relationship("Personne", foreign_keys=[analyste_id])
    validateur = db.relationship("Personne", foreign_keys=[validateur_id])

    @property
    def resultats(self):
        return json.loads(self.resultats_json or "[]")

    @resultats.setter
    def resultats(self, valeur):
        self.resultats_json = json.dumps(valeur, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SignalementQualite — module MC, 16-MC-surveillance-marche.md §5
# ---------------------------------------------------------------------------
class SignalementQualite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # SIG-{annee}-{seq4}
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    description = db.Column(db.Text, nullable=False)
    origine = db.Column(db.String(30), nullable=False)  # titulaire_amm | module_lt | module_ri | signalement_public
    niveau_risque = db.Column(db.String(5), nullable=True)  # I | II | III, fixé à l'évaluation
    statut = db.Column(db.String(20), nullable=False, default="signale")
    motif_decision = db.Column(db.Text, nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    lots_concernes = db.relationship("Lot", secondary="signalement_lot", lazy="subquery")

    @property
    def etablissements_notifies(self):
        """Dérivée automatiquement des lots concernés (fabricant) et du produit (titulaire
        AMM) — jamais saisie manuellement (règle de gestion MC)."""
        etabs = {}
        for lot in self.lots_concernes:
            if lot.fabricant_id:
                etabs[lot.fabricant_id] = lot.fabricant
        if self.produit.titulaire_amm_id:
            etabs[self.produit.titulaire_amm_id] = self.produit.titulaire_amm
        return list(etabs.values())


signalement_lot = db.Table(
    "signalement_lot",
    db.Column("signalement_id", db.Integer, db.ForeignKey("signalement_qualite.id"), primary_key=True),
    db.Column("lot_id", db.Integer, db.ForeignKey("lot.id"), primary_key=True),
)


class RappelStatutEtablissement(db.Model):
    """Sous-entité Rappel (§5) : statut individuel de confirmation de retrait par
    établissement notifié, une fois le signalement au statut `notifie`."""
    id = db.Column(db.Integer, primary_key=True)
    signalement_id = db.Column(db.Integer, db.ForeignKey("signalement_qualite.id"), nullable=False)
    etablissement_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=False)
    statut = db.Column(db.String(20), nullable=False, default="notifie")  # notifie | confirme_retrait
    date_confirmation = db.Column(db.DateTime, nullable=True)

    signalement = db.relationship("SignalementQualite", backref=db.backref("statuts_etablissements", lazy="dynamic"))
    etablissement = db.relationship("Etablissement", foreign_keys=[etablissement_id])


# ---------------------------------------------------------------------------
# ProtocoleEssaiClinique — module CT, 17-CT-essais-cliniques.md §5
# ---------------------------------------------------------------------------
class ProtocoleEssaiClinique(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # CT-{annee}-{seq4}
    titre = db.Column(db.String(300), nullable=False)
    promoteur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    produit_etudie_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=True)
    reference_comite_ethique = db.Column(db.String(150), nullable=True)
    statut_avis_ethique = db.Column(db.String(20), nullable=False, default="en_attente")
    # favorable | en_attente | defavorable
    statut = db.Column(db.String(30), nullable=False, default="depose")
    motif_decision = db.Column(db.Text, nullable=True)
    date_depot = db.Column(db.DateTime, nullable=True)
    date_decision = db.Column(db.DateTime, nullable=True)
    date_validite = db.Column(db.Date, nullable=True)
    date_limite_reponse_complement = db.Column(db.DateTime, nullable=True)
    amendements_json = db.Column(db.Text, default="[]")
    rapports_etape_json = db.Column(db.Text, default="[]")
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    promoteur = db.relationship("Personne", foreign_keys=[promoteur_id])
    produit_etudie = db.relationship("Produit", foreign_keys=[produit_etudie_id])
    sites_investigation = db.relationship("Etablissement", secondary="protocole_site", lazy="subquery")

    @property
    def amendements(self):
        return json.loads(self.amendements_json or "[]")

    @amendements.setter
    def amendements(self, valeur):
        self.amendements_json = json.dumps(valeur, ensure_ascii=False)

    @property
    def rapports_etape(self):
        return json.loads(self.rapports_etape_json or "[]")

    @rapports_etape.setter
    def rapports_etape(self, valeur):
        self.rapports_etape_json = json.dumps(valeur, ensure_ascii=False)


protocole_site = db.Table(
    "protocole_site",
    db.Column("protocole_id", db.Integer, db.ForeignKey("protocole_essai_clinique.id"), primary_key=True),
    db.Column("etablissement_id", db.Integer, db.ForeignKey("etablissement.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# LiberationLot — module LR, 18-LR-liberation-lots.md §5
# ---------------------------------------------------------------------------
class LiberationLot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # LR-{annee}-{seq4}
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("lot.id"), nullable=False)
    dossier_fabricant = db.Column(db.Text, nullable=True)  # description libre, pas de pipeline de fichiers
    echantillon_lt_id = db.Column(db.Integer, db.ForeignKey("echantillon.id"), nullable=True)
    statut = db.Column(db.String(30), nullable=False, default="recu")
    date_reception = db.Column(db.DateTime, default=datetime.utcnow)
    date_liberation = db.Column(db.DateTime, nullable=True)
    reference_pev = db.Column(db.String(150), nullable=True)
    motif_rejet = db.Column(db.Text, nullable=True)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    lot = db.relationship("Lot", foreign_keys=[lot_id])
    echantillon_lt = db.relationship("Echantillon", foreign_keys=[echantillon_lt_id])


# ---------------------------------------------------------------------------
# Inspection — module RI, 13-RI-inspection.md §5
# ---------------------------------------------------------------------------
class Inspection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # INS-{annee}-{seq4}
    etablissement_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=False)
    inspecteur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    type = db.Column(db.String(30), nullable=False, default="routine")
    # routine | suivi_plainte | suivi_non_conformite | declenchee_signalement
    date_planifiee = db.Column(db.Date, nullable=True)
    date_realisee = db.Column(db.DateTime, nullable=True)
    grille_json = db.Column(db.Text, default="[]")  # liste de GrilleItem, voir grille_ri.py
    score_conformite = db.Column(db.Integer, nullable=True)
    statut = db.Column(db.String(30), nullable=False, default="planifiee")
    plan_action = db.Column(db.Text, nullable=True)
    date_echeance_plan_action = db.Column(db.Date, nullable=True)
    non_conformite_grave = db.Column(db.Boolean, nullable=False, default=False)
    inspection_precedente_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=True)  # suivi_programme

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    etablissement = db.relationship("Etablissement", foreign_keys=[etablissement_id])
    inspecteur = db.relationship("Personne", foreign_keys=[inspecteur_id])
    inspection_precedente = db.relationship("Inspection", remote_side=[id])

    @property
    def grille(self):
        return json.loads(self.grille_json or "[]")

    @grille.setter
    def grille(self, valeur):
        self.grille_json = json.dumps(valeur, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ÉvènementAudit — journal universel (règle transversale n°2, non négociable)
# ---------------------------------------------------------------------------
class EvenementAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entite_type = db.Column(db.String(60), nullable=False, index=True)
    entite_id = db.Column(db.Integer, nullable=False, index=True)
    horodatage = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    acteur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)  # None = action système
    action = db.Column(db.String(255), nullable=False)
    ancien_statut = db.Column(db.String(50), nullable=True)
    nouveau_statut = db.Column(db.String(50), nullable=True)
    commentaire = db.Column(db.Text, nullable=True)

    acteur = db.relationship("Personne", foreign_keys=[acteur_id])


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    destinataire_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False, index=True)
    type = db.Column(db.String(60), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    statut_lecture = db.Column(db.String(10), nullable=False, default="non_lue")  # non_lue | lue
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    lien = db.Column(db.String(300), nullable=True)

    destinataire = db.relationship("Personne", foreign_keys=[destinataire_id])


# ---------------------------------------------------------------------------
# PieceJointe — document téléversé, générique (entite_type/entite_id, même
# pattern que ÉvènementAudit) : réutilisée par DossierAMM, DemandeLicence, et
# tout module futur, sans dupliquer un mécanisme de téléversement par module.
# ---------------------------------------------------------------------------
class PieceJointe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entite_type = db.Column(db.String(60), nullable=False, index=True)
    entite_id = db.Column(db.Integer, nullable=False, index=True)
    type_document = db.Column(db.String(150), nullable=True)  # ex. "Certificat de produit pharmaceutique"
    nom_fichier = db.Column(db.String(255), nullable=False)
    chemin_fichier = db.Column(db.String(500), nullable=False)
    taille_octets = db.Column(db.Integer, nullable=True)
    televerse_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    date_televersement = db.Column(db.DateTime, default=datetime.utcnow)

    televerse_par = db.relationship("Personne", foreign_keys=[televerse_par_id])


# ---------------------------------------------------------------------------
# Paiement — frais de dossier. NOTE IMPORTANTE : ceci n'est PAS une passerelle
# de paiement en ligne (aucune carte bancaire ni mobile money n'est traité par
# SIREPH). Conforme à la recommandation du cahier des charges d'origine
# (ARCHITECTURE.md du prototype voisin, §7) : le demandeur téléverse une preuve
# de paiement (virement, dépôt mobile money) et un agent DPML confirme la
# réception — l'intégration d'un vrai agrégateur de paiement est documentée
# comme une phase ultérieure distincte, nécessitant un prestataire agréé.
# ---------------------------------------------------------------------------
class Paiement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # PAY-{annee}-{seq4}
    # DossierAMM (homologation) | DemandeLicence | Echantillon (analyse de laboratoire)
    entite_type = db.Column(db.String(60), nullable=False, index=True)
    entite_id = db.Column(db.Integer, nullable=False, index=True)
    montant = db.Column(db.Integer, nullable=False)  # en XAF (entier, pas de sous-unité)
    devise = db.Column(db.String(5), nullable=False, default="XAF")
    statut = db.Column(db.String(20), nullable=False, default="en_attente")
    # en_attente | initie | preuve_deposee | confirme | rejete | echoue | expire
    piece_jointe_id = db.Column(db.Integer, db.ForeignKey("piece_jointe.id"), nullable=True)
    motif_rejet = db.Column(db.Text, nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_confirmation = db.Column(db.DateTime, nullable=True)
    confirme_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)

    # --- Paiement en ligne sécurisé (cf. paiement_gateway.py) ---------------
    # AUCUNE donnée de carte ni de compte mobile money n'est stockée ici : seules
    # des références opaques fournies par le prestataire agréé transitent.
    mode = db.Column(db.String(20), nullable=False, default="preuve_manuelle")
    # preuve_manuelle | en_ligne
    fournisseur = db.Column(db.String(30), nullable=True)   # mtn_momo | orange_money | carte
    reference_marchande = db.Column(db.String(64), unique=True, nullable=True)  # clé d'idempotence
    reference_transaction = db.Column(db.String(80), nullable=True)   # identifiant prestataire
    date_initiation = db.Column(db.DateTime, nullable=True)
    date_expiration = db.Column(db.DateTime, nullable=True)
    signature_notification = db.Column(db.String(120), nullable=True)  # HMAC vérifié du callback
    detail_echec = db.Column(db.Text, nullable=True)

    @property
    def est_regle(self):
        return self.statut == "confirme"

    piece_jointe = db.relationship("PieceJointe", foreign_keys=[piece_jointe_id])
    confirme_par = db.relationship("Personne", foreign_keys=[confirme_par_id])


# ---------------------------------------------------------------------------
# DemandeDerogation — demande d'exception motivée à une exigence réglementaire
# standard (délai, pièce justificative...), rattachée à un dossier d'AMM en cours.
# ---------------------------------------------------------------------------
class DemandeDerogation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # DER-{annee}-{seq4}
    dossier_amm_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), nullable=True)
    demandeur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    objet = db.Column(db.String(300), nullable=False)
    motif = db.Column(db.Text, nullable=False)
    statut = db.Column(db.String(20), nullable=False, default="deposee")
    # deposee | en_instruction | approuvee | refusee
    motif_decision = db.Column(db.Text, nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_decision = db.Column(db.DateTime, nullable=True)

    dossier_amm = db.relationship("DossierAMM", foreign_keys=[dossier_amm_id])
    demandeur = db.relationship("Personne", foreign_keys=[demandeur_id])


# ---------------------------------------------------------------------------
# VisaTechnique — autorisation technique d'importation délivrée pour un produit
# déjà titulaire d'une AMM active (distincte de l'AMM elle-même).
# ---------------------------------------------------------------------------
class VisaTechnique(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # VIS-{annee}-{seq4}
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    demandeur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    description = db.Column(db.Text, nullable=True)  # quantité, provenance, destination...
    statut = db.Column(db.String(20), nullable=False, default="demande")
    # demande | delivre | refuse
    motif_decision = db.Column(db.Text, nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_decision = db.Column(db.DateTime, nullable=True)

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    demandeur = db.relationship("Personne", foreign_keys=[demandeur_id])


# ---------------------------------------------------------------------------
# ParametreModule — délais et seuils configurables (règle transversale n°7)
# ---------------------------------------------------------------------------
class ParametreModule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(20), nullable=False)
    cle = db.Column(db.String(100), nullable=False)
    valeur = db.Column(db.String(300), nullable=False)
    description = db.Column(db.String(500))
    derniere_modif_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    derniere_modif_le = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    derniere_modif_par = db.relationship("Personne", foreign_keys=[derniere_modif_par_id])

    __table_args__ = (db.UniqueConstraint("module", "cle", name="uq_parametre_module_cle"),)


# ---------------------------------------------------------------------------
# SequenceNumerotation — compteur persistant par module+année (règle transversale n°3)
# ---------------------------------------------------------------------------
class SequenceNumerotation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(20), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    dernier_numero = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (db.UniqueConstraint("module", "annee", name="uq_sequence_module_annee"),)


# ===========================================================================
# VOLET RÉGIONAL — Reliance CEEAC
# ===========================================================================
# Principe non négociable : la souveraineté nationale. Aucune donnée de dossier
# ne quitte le pays sans un consentement explicite et tracé. Le Hub régional ne
# détient aucun dossier national : il n'assure qu'annuaire, routage et registre
# des décisions publiées.
class PaysCEEAC(db.Model):
    """Liste des États membres — DONNÉE DE CONFIGURATION, jamais codée en dur.

    Un pays peut être ajouté, retiré ou marqué « observateur » sans modifier le
    code (le statut du Rwanda, notamment, est rapporté de façon incohérente
    selon les sources).
    """
    __tablename__ = "pays_ceeac"
    id = db.Column(db.Integer, primary_key=True)
    code_iso = db.Column(db.String(2), unique=True, nullable=False)
    nom = db.Column(db.String(120), nullable=False)
    statut = db.Column(db.String(20), nullable=False, default="membre")
    # membre | observateur | retire
    autorite = db.Column(db.String(200))          # nom de l'ARN homologue
    url_instance = db.Column(db.String(300))      # instance SIREPH du pays, si déployée
    dans_reliance = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class AccordPartage(db.Model):
    """Consentement explicite et tracé — base légale de tout partage hors du pays.

    Sans accord actif, aucune donnée classée « partageable sous accord » ne peut
    être transmise. Révocable à tout moment.
    """
    __tablename__ = "accord_partage"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # ACC-{annee}-{seq4}
    objet = db.Column(db.String(300), nullable=False)
    dossier_amm_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), nullable=True)
    pays_destinataire = db.Column(db.String(2), nullable=False)
    portee = db.Column(db.String(50), nullable=False, default="rapport_evaluation")
    # rapport_evaluation | decision_seule | dossier_complet
    accorde_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    revoque = db.Column(db.Boolean, default=False)
    motif_revocation = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_revocation = db.Column(db.DateTime)

    dossier_amm = db.relationship("DossierAMM", foreign_keys=[dossier_amm_id])
    accorde_par = db.relationship("Personne", foreign_keys=[accorde_par_id])

    @property
    def actif(self):
        return not self.revoque


class RequeteReliance(db.Model):
    """Demande formelle adressée à une ARN homologue, ou reçue d'elle."""
    __tablename__ = "requete_reliance"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # REL-{annee}-{seq4}
    sens = db.Column(db.String(10), nullable=False, default="sortante")  # sortante | entrante
    pays_partenaire = db.Column(db.String(2), nullable=False)
    type_requete = db.Column(db.String(40), nullable=False, default="rapport_evaluation")
    # rapport_evaluation | clarification | statut_produit
    objet = db.Column(db.String(300), nullable=False)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=True)
    statut = db.Column(db.String(20), nullable=False, default="brouillon")
    # brouillon | transmise | recue | repondue | refusee | close
    reponse = db.Column(db.Text)
    motif_refus = db.Column(db.Text)
    accord_id = db.Column(db.Integer, db.ForeignKey("accord_partage.id"), nullable=True)
    demandeur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    delai_jours = db.Column(db.Integer, default=30)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_transmission = db.Column(db.DateTime)
    date_reponse = db.Column(db.DateTime)

    produit = db.relationship("Produit", foreign_keys=[produit_id])
    accord = db.relationship("AccordPartage", foreign_keys=[accord_id])
    demandeur = db.relationship("Personne", foreign_keys=[demandeur_id])


class DecisionPubliee(db.Model):
    """Décision publiée au registre régional, ou reçue d'une ARN homologue.

    Ne contient QUE des données publiables : jamais de pièce de dossier.
    """
    __tablename__ = "decision_publiee"
    id = db.Column(db.Integer, primary_key=True)
    pays_origine = db.Column(db.String(2), nullable=False)
    produit_nom = db.Column(db.String(300), nullable=False)
    dci = db.Column(db.String(300))
    forme = db.Column(db.String(150))
    dosage = db.Column(db.String(150))
    titulaire = db.Column(db.String(300))
    # Clé pivot d'appariement « même produit » d'un pays à l'autre (esprit ISO IDMP)
    cle_pivot = db.Column(db.String(300), index=True)
    type_decision = db.Column(db.String(30), nullable=False, default="amm")
    # amm | variation | renouvellement | retrait | rejet_partage
    reference_nationale = db.Column(db.String(40))
    resume = db.Column(db.Text)
    rapport_partageable = db.Column(db.Boolean, default=False)
    dossier_amm_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), nullable=True)
    signature = db.Column(db.String(200))
    date_decision = db.Column(db.DateTime)
    date_publication = db.Column(db.DateTime, default=datetime.utcnow)

    dossier_amm = db.relationship("DossierAMM", foreign_keys=[dossier_amm_id])


class AlerteTransfrontaliere(db.Model):
    """Rappel de lot ou produit falsifié diffusé aux ARN de la sous-région."""
    __tablename__ = "alerte_transfrontaliere"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # ALR-{annee}-{seq4}
    sens = db.Column(db.String(10), nullable=False, default="emise")  # emise | recue
    pays_emetteur = db.Column(db.String(2), nullable=False)
    type_alerte = db.Column(db.String(30), nullable=False, default="rappel_lot")
    # rappel_lot | produit_falsifie | signal_vigilance | retrait_amm
    produit_nom = db.Column(db.String(300), nullable=False)
    numero_lot = db.Column(db.String(120))
    niveau_risque = db.Column(db.String(5))       # I | II | III
    message = db.Column(db.Text, nullable=False)
    signalement_id = db.Column(db.Integer, db.ForeignKey("signalement_qualite.id"), nullable=True)
    accuse_le = db.Column(db.DateTime)            # accusé de réception (alerte reçue)
    traitee = db.Column(db.Boolean, default=False)
    signature = db.Column(db.String(200))
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    signalement = db.relationship("SignalementQualite", foreign_keys=[signalement_id])


class MessageReliance(db.Model):
    """File d'échange avec le Hub — garantit la RÉSILIENCE.

    L'instance nationale reste pleinement opérationnelle si le Hub est
    injoignable : les messages sont mis en file, puis rejoués au rétablissement
    (idempotence par identifiant de message).
    """
    __tablename__ = "message_reliance"
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String(64), unique=True, nullable=False)
    sens = db.Column(db.String(10), nullable=False)       # sortant | entrant
    type_message = db.Column(db.String(40), nullable=False)
    destinataire = db.Column(db.String(12), nullable=False)   # code pays ou REGIONAL
    enveloppe = db.Column(db.JSON, nullable=False)
    statut = db.Column(db.String(20), nullable=False, default="en_file")
    # en_file | transmis | echec | recu
    tentatives = db.Column(db.Integer, default=0)
    derniere_erreur = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_transmission = db.Column(db.DateTime)


# ===========================================================================
# VALIDATION NUMÉRIQUE — circuit de signature hiérarchique
# ===========================================================================
class EtapeValidation(db.Model):
    """Une étape du circuit de signature d'un document.

    Le circuit est matérialisé par une suite ordonnée d'étapes, chacune
    attribuée à un rôle précis. Une étape ne peut être signée que si toutes
    celles qui la précèdent l'ont été : l'ordre hiérarchique est garanti par
    construction, pas seulement par l'interface.
    """
    __tablename__ = "etape_validation"
    id = db.Column(db.Integer, primary_key=True)
    # Document concerné (AMM, dérogation, visa technique…)
    entite_type = db.Column(db.String(50), nullable=False)
    entite_id = db.Column(db.Integer, nullable=False)
    circuit = db.Column(db.String(30), nullable=False)      # amm | derogation | visa_technique
    ordre = db.Column(db.Integer, nullable=False)           # 1, 2, 3…
    role_requis = db.Column(db.String(40), nullable=False)
    libelle_role = db.Column(db.String(120), nullable=False)
    statut = db.Column(db.String(20), nullable=False, default="en_attente")
    # en_attente | validee | refusee
    validateur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    commentaire = db.Column(db.Text)
    # Empreinte de la signature numérique : rend l'apposition vérifiable
    signature = db.Column(db.String(120))
    date_validation = db.Column(db.DateTime)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    validateur = db.relationship("Personne", foreign_keys=[validateur_id])

    __table_args__ = (
        db.UniqueConstraint("entite_type", "entite_id", "ordre",
                            name="uq_etape_entite_ordre"),
    )


class DemandeInspection(db.Model):
    """Demande d'inspection sollicitée par un industriel.

    Un titulaire d'AMM peut solliciter la venue de l'autorité sur son site de
    fabrication — y compris à l'étranger — pour faire constater sa conformité.
    Une fois recevable, la DPML planifie l'inspection via le module RI.
    """
    __tablename__ = "demande_inspection"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # DIN-{annee}-{seq4}
    demandeur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    etablissement_id = db.Column(db.Integer, db.ForeignKey("etablissement.id"), nullable=True)
    # Site à inspecter — souvent distinct du siège du demandeur
    site_nom = db.Column(db.String(300), nullable=False)
    site_pays = db.Column(db.String(120), nullable=False)
    site_adresse = db.Column(db.String(500))
    site_contact = db.Column(db.String(300))
    motif = db.Column(db.Text, nullable=False)
    produits_concernes = db.Column(db.Text)
    periode_souhaitee = db.Column(db.String(200))
    statut = db.Column(db.String(30), nullable=False, default="soumise")
    # soumise | recevable | irrecevable | planifiee | realisee | close
    motif_decision = db.Column(db.Text)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_decision = db.Column(db.DateTime)

    demandeur = db.relationship("Personne", foreign_keys=[demandeur_id])
    etablissement = db.relationship("Etablissement", foreign_keys=[etablissement_id])
    inspection = db.relationship("Inspection", foreign_keys=[inspection_id])

    @property
    def a_l_etranger(self):
        return (self.site_pays or "").strip().lower() not in ("cameroun", "cm")


# ===========================================================================
# INSTRUCTION DES DOSSIERS — évaluation interne puis commission
# ===========================================================================
class AssignationEvaluation(db.Model):
    """Dossier confié à un évaluateur interne par le chef de service.

    L'évaluation interne prépare les travaux de commission : elle ne décide de
    rien, elle instruit.
    """
    __tablename__ = "assignation_evaluation"
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), nullable=False)
    evaluateur_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    assigne_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    consigne = db.Column(db.Text)
    statut = db.Column(db.String(20), nullable=False, default="assignee")
    # assignee | en_cours | terminee
    rapport = db.Column(db.Text)
    conclusion = db.Column(db.String(30))
    # favorable | defavorable | complement_requis
    date_assignation = db.Column(db.DateTime, default=datetime.utcnow)
    date_echeance = db.Column(db.DateTime)
    date_remise = db.Column(db.DateTime)

    dossier = db.relationship("DossierAMM", foreign_keys=[dossier_id])
    evaluateur = db.relationship("Personne", foreign_keys=[evaluateur_id])
    assigne_par = db.relationship("Personne", foreign_keys=[assigne_par_id])

    __table_args__ = (
        db.UniqueConstraint("dossier_id", "evaluateur_id",
                            name="uq_assignation_dossier_evaluateur"),
    )


class SessionCommission(db.Model):
    """Séance de commission convoquée par le chef de service."""
    __tablename__ = "session_commission"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)  # COM-{annee}-{seq4}
    type_commission = db.Column(db.String(30), nullable=False, default="specialisee")
    # specialisee | nationale
    intitule = db.Column(db.String(300), nullable=False)
    date_seance = db.Column(db.DateTime)
    lieu = db.Column(db.String(300))
    convoquee_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    statut = db.Column(db.String(20), nullable=False, default="convoquee")
    # convoquee | en_cours | close
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_cloture = db.Column(db.DateTime)

    convoquee_par = db.relationship("Personne", foreign_keys=[convoquee_par_id])
    inscriptions = db.relationship("DossierSession", back_populates="session",
                                    cascade="all, delete-orphan")

    @property
    def role_membre(self):
        return ("membre_commission_nationale" if self.type_commission == "nationale"
                else "membre_commission_specialisee")


class DossierSession(db.Model):
    """Inscription d'un dossier à l'ordre du jour d'une séance."""
    __tablename__ = "dossier_session"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("session_commission.id"),
                           nullable=False)
    dossier_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), nullable=False)
    # Synthèse automatique des avis des membres, produite à la clôture
    synthese = db.Column(db.Text)
    avis_global = db.Column(db.String(30))
    # favorable | defavorable | complement_requis
    recommandations = db.Column(db.Text)

    session = db.relationship("SessionCommission", back_populates="inscriptions")
    dossier = db.relationship("DossierAMM", foreign_keys=[dossier_id])

    __table_args__ = (
        db.UniqueConstraint("session_id", "dossier_id", name="uq_session_dossier"),
    )


class AvisCommission(db.Model):
    """Avis individuel d'un membre, saisi en séance depuis sa tablette."""
    __tablename__ = "avis_commission"
    id = db.Column(db.Integer, primary_key=True)
    dossier_session_id = db.Column(db.Integer, db.ForeignKey("dossier_session.id"),
                                   nullable=False)
    membre_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    # Réponses à la grille d'évaluation : {code_question: oui|non|sans_objet}
    reponses = db.Column(db.JSON, default=dict)
    avis = db.Column(db.String(30), nullable=False)
    # favorable | defavorable | complement_requis
    motif = db.Column(db.Text)
    date_saisie = db.Column(db.DateTime, default=datetime.utcnow)

    dossier_session = db.relationship("DossierSession", foreign_keys=[dossier_session_id])
    membre = db.relationship("Personne", foreign_keys=[membre_id])

    __table_args__ = (
        db.UniqueConstraint("dossier_session_id", "membre_id",
                            name="uq_avis_membre_dossier"),
    )


class RapportInstruction(db.Model):
    """Rapport du chef de service transmis à la direction.

    Consolide l'évaluation interne et l'avis de commission ; c'est lui qui
    déclenche le circuit de signature.
    """
    __tablename__ = "rapport_instruction"
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey("dossier_amm.id"), unique=True,
                           nullable=False)
    redige_par_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    avis_propose = db.Column(db.String(30), nullable=False)
    # favorable | defavorable | complement_requis
    motif = db.Column(db.Text)
    synthese = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    dossier = db.relationship("DossierAMM", foreign_keys=[dossier_id])
    redige_par = db.relationship("Personne", foreign_keys=[redige_par_id])


class CourrielSortant(db.Model):
    """Trace de chaque courriel préparé par l'application.

    En l'absence de configuration SMTP, les messages sont journalisés au lieu
    d'être envoyés : la démonstration reste utilisable et l'administration
    peut vérifier ce qui aurait été adressé, sans qu'on prétende avoir envoyé
    quoi que ce soit.
    """
    __tablename__ = "courriel_sortant"
    id = db.Column(db.Integer, primary_key=True)
    destinataire_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=True)
    adresse = db.Column(db.String(200), nullable=False)
    sujet = db.Column(db.String(300), nullable=False)
    corps = db.Column(db.Text, nullable=False)
    type_notification = db.Column(db.String(60))
    statut = db.Column(db.String(20), nullable=False, default="en_attente")
    # en_attente | envoye | echec | journalise | rejoue
    erreur = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_envoi = db.Column(db.DateTime)

    destinataire = db.relationship("Personne", foreign_keys=[destinataire_id])
