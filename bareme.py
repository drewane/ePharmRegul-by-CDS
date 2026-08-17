"""
Barème des redevances — source unique des frais exigibles, tous modules confondus.

Chaque fait générateur est décrit ici : entité concernée, module de rattachement,
clé du paramètre configurable et montant par défaut. Les montants restent
modifiables sans redéploiement (ParametreModule, écran Administration).

Un montant à 0 signifie « acte gratuit » : aucun paiement n'est alors créé, ce
qui permet d'exonérer un acte par simple paramétrage (ex. certaines inspections
d'office, ou la déclaration d'un effet indésirable, qui doit rester gratuite).

Redevables : l'industriel/titulaire pour l'AMM, l'établissement (grossiste,
officine, laboratoire) pour les licences et les analyses, le promoteur pour les
essais cliniques, l'établissement inspecté pour les inspections soumises à frais.
"""
from delais import get_parametre

# code interne → (entité, module, clé de paramètre, montant par défaut, libellé)
BAREME = {
    "homologation": (
        "DossierAMM", "MA", "frais_dossier_xaf", 500000,
        "Homologation — demande d'AMM"),
    "licence": (
        "DemandeLicence", "LI", "frais_dossier_xaf", 150000,
        "Licence d'établissement"),
    "analyse_labo": (
        "Echantillon", "LT", "frais_analyse_xaf", 75000,
        "Analyse de laboratoire"),
    "essai_clinique": (
        "ProtocoleEssaiClinique", "CT", "frais_dossier_xaf", 300000,
        "Autorisation d'essai clinique"),
    "inspection": (
        "Inspection", "RI", "frais_inspection_xaf", 0,
        "Inspection réglementaire (descente)"),
    "liberation_lot": (
        "LiberationLot", "LR", "frais_liberation_xaf", 100000,
        "Libération de lot"),
    # ATU : GRATUITE, et déclarée telle plutôt que simplement absente du
    # barème. Un acte qui ne figure nulle part se lit comme un oubli ; inscrit
    # à 0, il affirme une décision — on ne fait pas payer l'accès d'un patient
    # à un traitement dont dépend sa survie, et le tarif ne peut pas remonter
    # par inadvertance sans qu'on le voie.
    "atu": (
        "AutorisationTemporaire", "MA", "frais_atu_xaf", 0,
        "Autorisation temporaire d'utilisation"),
}

# Défauts injectés dans ParametreModule par initialiser_parametres_bareme()
DESCRIPTIONS = {
    "frais_analyse_xaf": "Frais (XAF) exigés pour une analyse de laboratoire demandée "
                         "par un opérateur. 0 = gratuit.",
    "frais_inspection_xaf": "Frais (XAF) exigés pour une inspection soumise à redevance "
                            "(descente sur site). 0 = inspection non facturée.",
    "frais_liberation_xaf": "Frais (XAF) exigés pour une demande de libération de lot. "
                            "0 = gratuit.",
    "frais_atu_xaf": "Frais (XAF) exigés pour une autorisation temporaire "
                     "d'utilisation. Fixé à 0 : l'accès anticipé d'un patient "
                     "sans alternative thérapeutique n'est pas facturé.",
}


def par_entite(entite_type):
    """Retrouve l'entrée de barème correspondant à un type d'entité."""
    for code, (ent, *_reste) in BAREME.items():
        if ent == entite_type:
            return code, BAREME[code]
    return None, None


def montant(code):
    """Montant applicable, lu dans le paramétrage (repli sur le défaut du barème)."""
    if code not in BAREME:
        raise KeyError(f"Fait générateur inconnu : {code}")
    _entite, module, cle, defaut, _lib = BAREME[code]
    try:
        return int(get_parametre(module, cle, default=defaut))
    except (TypeError, ValueError):
        return defaut


def montant_pour(entite):
    """Montant applicable à une instance d'entité (0 si acte non facturé)."""
    code, _ = par_entite(entite.__class__.__name__)
    return montant(code) if code else 0


def libelle(code):
    return BAREME[code][4] if code in BAREME else code


def grille():
    """Barème complet et à jour, pour affichage (administration, page publique)."""
    return [
        {"code": code, "entite": ent, "module": mod, "cle": cle,
         "libelle": lib, "montant": montant(code)}
        for code, (ent, mod, cle, _def, lib) in BAREME.items()
    ]


def initialiser_parametres_bareme():
    """Crée les paramètres de frais absents. Idempotent — appelée au démarrage."""
    from models import ParametreModule, db
    cree = 0
    for code, (_ent, module, cle, defaut, _lib) in BAREME.items():
        if not ParametreModule.query.filter_by(module=module, cle=cle).first():
            db.session.add(ParametreModule(
                module=module, cle=cle, valeur=str(defaut),
                description=DESCRIPTIONS.get(cle, f"Frais (XAF) — {BAREME[code][4]}.")))
            cree += 1
    if cree:
        db.session.commit()
    return cree
