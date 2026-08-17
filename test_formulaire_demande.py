"""
Tests du formulaire de demande enrichi.

Ce que le cahier des charges exige, et que ces tests éprouvent :
  * listes déroulantes pour forme, unités, classe, voie, durée ;
  * indications en choix multiple ;
  * dosage en nombre PUIS unité, dans deux champs distincts ;
  * composition ouvrant N groupes selon le nombre saisi ;
  * MTA basculant sur son propre variant ;
  * le type de produit pilotant le dossier technique attendu ;
  * téléphone et courriel séparés et validés ;
  * l'enregistrement BLOQUÉ — et non seulement signalé — si un obligatoire
    manque.

Le dernier point mérite son insistance : une validation qui ne vit que dans le
navigateur se contourne en désactivant JavaScript.

Exécution :  venv\\Scripts\\python test_formulaire_demande.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import formulaire_demande as fd
import referentiels_pharma as ref
import seed_comptes as sc
import workflow_formulaire as wff
from erreurs import ErreurWorkflow
from models import DossierAMM, EvenementAudit, Personne, Produit, db

_res = []
_MODELES = (EvenementAudit, DossierAMM, Produit)


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def _max_ids():
    return {M: (db.session.query(db.func.max(M.id)).scalar() or 0) for M in _MODELES}


def _nettoyer(reperes):
    for M in _MODELES:
        for obj in M.query.filter(M.id > reperes[M]).all():
            db.session.delete(obj)
    db.session.commit()


def _client():
    c = application.app.test_client()
    email = sc.COMPTES["demandeur_externe"][1]
    c.post("/login", data={"email": email,
                           "password": sc.mot_de_passe_courant(email)})
    return c


def _standard(**extra):
    donnees = {
        "nature_acte": "octroi", "type_produit": "medicament_chimique",
        "nom_commercial": f"Produit {uuid.uuid4().hex[:5]}",
        "dci": "Paracétamol", "forme_pharmaceutique": "Comprimé pelliculé",
        "dosage": "500", "dosage_unite": "mg",
        "nombre_principes_actifs": "1",
        "pa_1_dci": "Paracétamol", "pa_1_dosage": "500", "pa_1_unite": "mg",
        "classe_therapeutique": "N02", "voie_administration": "Orale",
        "indications": ["Douleur aiguë", "Fièvre"],
        "duree_stabilite": "36", "duree_stabilite_unite": "mois",
        "pharmacien_telephone": "+237 699 00 00 00",
        "pharmacien_email": "pharmacien@labo.cm",
    }
    donnees.update(extra)
    return donnees


def _mta(**extra):
    donnees = {
        "nature_acte": "octroi",
        "type_produit": "medicament_traditionnel_ameliore",
        "nom_commercial": f"Mangoro {uuid.uuid4().hex[:4]}",
        "dci": "Mangifera indica", "forme_pharmaceutique": "Sirop",
        "dosage": "250", "dosage_unite": "mg/mL",
        "conditionnement": "Flacon en verre", "quantite": "100 mL",
        "voie_administration": "Orale", "nombre_constituants": "1",
        "constituant_1_nom": "Mangifera indica",
        "constituant_1_partie": "Écorce de tige",
        "constituant_1_quantite": "150", "constituant_1_unite": "mg",
        "categorie_mta": ref.CATEGORIES_MTA[1],
        "classe_therapeutique": "P01", "indications": ["Paludisme"],
        "mecanisme_action": "Action antiparasitaire documentée.",
        "adresse_fabricant": "BP 1234, Douala",
        "adresse_site_fabrication": "Zone industrielle Bassa",
        "adresse_controle_qualite": "LANACOME, Yaoundé",
        "adresse_demandeur": "BP 4321, Yaoundé",
        "exploitant": "Phytocam SARL", "representant_cameroun": "Dr Ateba",
        "duree_stabilite": "24", "duree_stabilite_unite": "mois",
        "prix_grossiste": "2500", "prix_public": "4000",
        "pharmacien_telephone": "+237 677 11 22 33",
        "pharmacien_email": "pharma@phytocam.cm",
    }
    donnees.update(extra)
    return donnees


# ---------------------------------------------------------------------------
def test_referentiels():
    print("\n[1] Les référentiels remplacent la saisie libre")
    verifier("formes pharmaceutiques nombreuses et groupées",
             len(ref.FORMES_A_PLAT) >= 60 and len(ref.FORMES_PHARMACEUTIQUES) >= 6,
             f"{len(ref.FORMES_A_PLAT)} formes")
    verifier("aucune forme en double",
             len(ref.FORMES_A_PLAT) == len(set(ref.FORMES_A_PLAT)))
    verifier("unités groupées par grandeur",
             set(ref.UNITES_DOSAGE) >= {"Masse", "Volume", "Concentration"})
    verifier("les unités usuelles sont présentes",
             {"mg", "mL", "UI", "%", "mg/mL"} <= set(ref.UNITES_A_PLAT))
    verifier("voies d'administration EDQM",
             {"Orale", "Intraveineuse", "Cutanée", "Inhalée"}
             <= set(ref.VOIES_ADMINISTRATION))
    verifier("classes ATC groupées par groupe anatomique",
             len(ref.classes_par_groupe()) >= 10)
    verifier("les classes portent leur code",
             all(len(c) == 3 for c in ref.CLASSES_ATC))
    verifier("indications alimentées", len(ref.INDICATIONS) >= 30)
    verifier("les priorités nationales figurent en tête",
             {"Paludisme", "Tuberculose", "Infection à VIH"}
             <= set(ref.INDICATIONS[:5]))
    verifier("unités de durée distinctes des unités de dosage",
             set(ref.UNITES_DUREE).isdisjoint(ref.UNITES_A_PLAT))
    verifier("parties utilisées pour les MTA",
             {"Feuille", "Racine", "Écorce de tige"} <= set(ref.PARTIES_UTILISEES))
    verifier("une valeur hors référentiel est signalée",
             ref.valider_choix("Cachet", ref.FORMES_A_PLAT, "des formes")
             is not None)


def test_entete():
    print("\n[2] En-tête : nature de l'acte et type de produit")
    verifier("trois natures d'acte",
             set(fd.NATURES_ACTE) == {"octroi", "renouvellement", "variation"})
    verifier("le MTA figure parmi les types",
             "medicament_traditionnel_ameliore" in fd.TYPES_PRODUIT)
    verifier("chimique, biologique et vaccin aussi",
             {"medicament_chimique", "medicament_biologique", "vaccin"}
             <= set(fd.TYPES_PRODUIT))
    verifier("le MTA bascule sur son variant",
             fd.variant("medicament_traditionnel_ameliore") == "mta")
    verifier("les autres restent au variant standard",
             all(fd.variant(t) == "standard" for t in
                 ("medicament_chimique", "medicament_biologique", "vaccin")))


def test_type_pilote_le_dossier():
    print("\n[3] Le type de produit pilote le dossier technique attendu")
    verifier("un MTA appelle le dossier MTA",
             fd.dossier_attendu("medicament_traditionnel_ameliore") == "mta")
    for t in ("medicament_chimique", "medicament_biologique", "vaccin"):
        verifier(f"« {t} » appelle le CTD", fd.dossier_attendu(t) == "ctd")
    verifier("le MTA se rattache à la nature phytothérapie",
             fd.nature_correspondante("medicament_traditionnel_ameliore")
             == "phytotherapie")
    verifier("un type inconnu retombe sur le standard",
             fd.variant("inexistant") == "standard")


def test_champs_obligatoires():
    print("\n[4] Tous les champs requis bloquent l'enregistrement")
    obligatoires = fd.champs_obligatoires("medicament_chimique")
    verifier("le variant standard a ses obligatoires",
             len(obligatoires) >= 12, f"{len(obligatoires)}")
    verifier("le téléphone et le courriel sont deux champs distincts",
             "pharmacien_telephone" in obligatoires
             and "pharmacien_email" in obligatoires)

    for champ in ("nom_commercial", "forme_pharmaceutique",
                  "classe_therapeutique", "voie_administration",
                  "pharmacien_telephone", "pharmacien_email"):
        donnees = _standard()
        donnees[champ] = ""
        erreurs = fd.valider(donnees)
        verifier(f"sans « {champ} », la saisie est refusée", champ in erreurs)

    verifier("une saisie complète ne produit aucune erreur",
             not fd.valider(_standard()))


def test_dosage_nombre_et_unite():
    print("\n[5] Dosage : nombre et unité séparés")
    verifier("nombre sans unité refusé",
             "dosage" in fd.valider(_standard(dosage="500", dosage_unite="")))
    verifier("unité sans nombre refusée",
             "dosage" in fd.valider(_standard(dosage="", dosage_unite="mg")))
    verifier("unité hors référentiel refusée",
             "dosage" in fd.valider(_standard(dosage_unite="cuillères")))
    verifier("dosage non numérique refusé",
             "dosage" in fd.valider(_standard(dosage="cinq cents")))
    verifier("dosage négatif refusé",
             "dosage" in fd.valider(_standard(dosage="-5")))
    verifier("nombre et unité valides acceptés",
             "dosage" not in fd.valider(_standard()))
    verifier("la forme composée est reconstituée",
             fd.dosage_complet(_standard()) == "500 mg")
    verifier("la durée de stabilité a ses propres unités",
             "duree_stabilite" in fd.valider(
                 _standard(duree_stabilite_unite="mg")))


def test_composition_dynamique():
    print("\n[6] Composition : N groupes selon le nombre de principes actifs")
    trois = _standard(nombre_principes_actifs="3",
                      pa_2_dci="Caféine", pa_2_dosage="50", pa_2_unite="mg",
                      pa_3_dci="Codéine", pa_3_dosage="30", pa_3_unite="mg")
    verifier("trois groupes complets acceptés", not fd.valider(trois))
    verifier("la composition est mise en phrase",
             fd.composition_lisible("medicament_chimique", trois).count(";") == 2,
             fd.composition_lisible("medicament_chimique", trois))

    incomplet = _standard(nombre_principes_actifs="2")
    erreurs = fd.valider(incomplet)
    verifier("un groupe annoncé mais vide est refusé",
             "pa_2_dci" in erreurs, str(list(erreurs)[:3]))
    verifier("l'erreur nomme l'élément concerné",
             "Élément 2" in erreurs.get("pa_2_dci", ""))

    verifier("zéro principe actif refusé",
             "nombre_principes_actifs" in fd.valider(
                 _standard(nombre_principes_actifs="0")))
    verifier("un nombre déraisonnable est borné",
             "nombre_principes_actifs" in fd.valider(
                 _standard(nombre_principes_actifs="400")))
    verifier("la borne est explicite dans le message",
             str(fd.MAX_PRINCIPES_ACTIFS) in fd.valider(
                 _standard(nombre_principes_actifs="400"))
             ["nombre_principes_actifs"])


def test_indications_multiples():
    print("\n[7] Indications en choix multiple")
    verifier("plusieurs indications acceptées",
             not fd.valider(_standard(indications=["Paludisme", "Fièvre",
                                                   "Douleur aiguë"])))
    verifier("aucune indication refusée",
             "indications" in fd.valider(_standard(indications=[])))
    verifier("une indication hors référentiel refusée",
             "indications" in fd.valider(_standard(indications=["Fatigue"])))
    verifier("une chaîne unique est tolérée",
             not fd.valider(_standard(indications="Paludisme")))


def test_telephone_et_courriel():
    print("\n[8] Téléphone et courriel, validés séparément")
    for mauvais in ("abc", "12", "téléphone"):
        verifier(f"téléphone « {mauvais} » refusé",
                 "pharmacien_telephone" in fd.valider(
                     _standard(pharmacien_telephone=mauvais)))
    for bon in ("+237 699 00 00 00", "699000000", "+237-6-99-00-00-00"):
        verifier(f"téléphone « {bon} » accepté",
                 "pharmacien_telephone" not in fd.valider(
                     _standard(pharmacien_telephone=bon)))
    for mauvais in ("pharmacien", "a@b", "a b@c.cm"):
        verifier(f"courriel « {mauvais} » refusé",
                 "pharmacien_email" in fd.valider(
                     _standard(pharmacien_email=mauvais)))
    verifier("courriel valide accepté",
             "pharmacien_email" not in fd.valider(
                 _standard(pharmacien_email="p.mballa@labo-cameroun.cm")))


def test_variant_mta():
    print("\n[9] Variant MTA : ses champs propres")
    codes = {c for c, *_ in fd.CHAMPS["mta"]}
    for attendu in ("mecanisme_action", "categorie_mta", "adresse_fabricant",
                    "adresse_site_fabrication", "adresse_controle_qualite",
                    "adresse_demandeur", "exploitant", "representant_cameroun",
                    "prix_grossiste", "prix_public", "nombre_constituants"):
        verifier(f"le MTA réclame « {attendu} »", attendu in codes)
    verifier("le MTA ne parle pas de principes actifs",
             "nombre_principes_actifs" not in codes)
    verifier("le standard ne réclame pas le mécanisme d'action",
             "mecanisme_action" not in {c for c, *_ in fd.CHAMPS["standard"]})

    verifier("une saisie MTA complète est acceptée", not fd.valider(_mta()))
    verifier("sans mécanisme d'action, refusée",
             "mecanisme_action" in fd.valider(_mta(mecanisme_action="")))
    verifier("sans adresse du représentant, refusée",
             "representant_cameroun" in fd.valider(_mta(representant_cameroun="")))
    verifier("partie utilisée hors référentiel refusée",
             "constituant_1_partie" in fd.valider(
                 _mta(constituant_1_partie="le milieu")))
    verifier("la composition MTA porte la partie utilisée",
             "Écorce de tige" in fd.composition_lisible(
                 "medicament_traditionnel_ameliore", _mta()))
    verifier("les excipients sont repris",
             "Excipients" in fd.composition_lisible(
                 "medicament_traditionnel_ameliore",
                 _mta(excipients="Sirop de saccharose")))


def test_enregistrement():
    print("\n[10] Enregistrement en base")
    dep = Personne.query.filter_by(
        email=sc.COMPTES["demandeur_externe"][1]).first()

    verifier("une saisie invalide n'est jamais écrite",
             _leve(lambda: wff.enregistrer(dep, _standard(nom_commercial="")),
                   "invalides ou manquants"))

    donnees = _standard()
    dossier = wff.enregistrer(dep, donnees)
    db.session.flush()
    p = dossier.produit
    verifier("le dossier est numéroté par le système",
             dossier.numero.startswith("AMM-"), dossier.numero)
    verifier("la date de dépôt est horodatée", dossier.date_depot is not None)
    verifier("la nature de l'acte est conservée", dossier.nature_acte == "octroi")
    verifier("elle se rattache au type de procédure existant",
             dossier.type_procedure == "nouvelle_demande")
    verifier("le type de dossier attendu est CTD", dossier.type_dossier == "ctd")
    verifier("le dosage composé est reconstitué", p.dosage == "500 mg")
    verifier("valeur et unité restent distinctes",
             p.dosage_valeur == "500" and p.dosage_unite == "mg")
    verifier("la classe porte son intitulé",
             p.classe_therapeutique.startswith("N02 —"), p.classe_therapeutique)
    verifier("les indications sont jointes",
             "Douleur aiguë" in p.indications_therapeutiques)
    verifier("le dépôt est journalisé",
             EvenementAudit.query.filter_by(entite_type="DossierAMM",
                                            entite_id=dossier.id).count() >= 1)

    mta = wff.enregistrer(dep, _mta())
    db.session.flush()
    verifier("un MTA appelle le dossier MTA", mta.type_dossier == "mta")
    verifier("sa nature est la phytothérapie",
             mta.produit.nature == "phytotherapie")
    verifier("ses prix sont en FCFA entiers",
             mta.produit.prix_grossiste_ht == 2500
             and mta.produit.prix_public_cameroun == 4000)


def _leve(fn, motif=None):
    try:
        fn()
        return False
    except ErreurWorkflow as e:
        return motif is None or motif.lower() in str(e).lower()


def test_ecran():
    print("\n[11] Écran de saisie")
    c = _client()
    page = c.get("/demandes/formulaire").get_data(as_text=True)
    verifier("la page répond", "Nature de l'acte" in page)
    verifier("la forme est une liste déroulante",
             'id="forme_pharmaceutique"' in page and "<optgroup" in page)
    verifier("l'unité de dosage est une liste séparée",
             'name="dosage_unite"' in page)
    verifier("les indications sont un choix multiple",
             'name="indications"' in page and "multiple" in page)
    verifier("le numéro de dépôt n'est pas saisissable",
             "Attribué à la soumission" in page and "disabled" in page)
    verifier("la composition est dynamique",
             'id="groupes-composition"' in page)

    mta = c.get("/demandes/formulaire"
                "?type_produit=medicament_traditionnel_ameliore").get_data(
                    as_text=True)
    verifier("le MTA affiche la dénomination spéciale",
             "Dénomination spéciale" in mta)
    verifier("il affiche le mécanisme d'action", "Mécanisme d" in mta)
    verifier("il annonce le dossier MTA", "dossier MTA" in mta)
    verifier("il demande les prix en FCFA", "FCFA" in mta)
    verifier("le standard n'affiche pas le mécanisme d'action",
             "Mécanisme d" not in page)

    # L'enregistrement est bloqué côté serveur, pas seulement au navigateur.
    r = c.post("/demandes/formulaire",
               data={"action": "enregistrer", "nature_acte": "octroi",
                     "type_produit": "medicament_chimique"})
    verifier("une saisie incomplète ne crée rien",
             r.status_code == 200 and "à corriger" in r.get_data(as_text=True))

    avant = DossierAMM.query.count()
    donnees = _standard()
    donnees["action"] = "enregistrer"
    r = c.post("/demandes/formulaire", data=donnees)
    verifier("une saisie complète redirige vers le dossier technique",
             r.status_code == 302 and "technique" in (
                 r.headers.get("Location") or ""),
             r.headers.get("Location"))
    verifier("le dossier est bien créé", DossierAMM.query.count() == avant + 1)


def main():
    print("=" * 70)
    print("Formulaire de demande enrichi")
    print("=" * 70)
    with application.app.app_context():
        sc.creer_comptes()
        reperes = _max_ids()
        for t in (test_referentiels, test_entete, test_type_pilote_le_dossier,
                  test_champs_obligatoires, test_dosage_nombre_et_unite,
                  test_composition_dynamique, test_indications_multiples,
                  test_telephone_et_courriel, test_variant_mta,
                  test_enregistrement, test_ecran):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False,
                         f"{type(e).__name__}: {e}")
        db.session.rollback()
        _nettoyer(reperes)

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
