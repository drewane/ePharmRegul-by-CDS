"""
Tests du lot D : généralisation aux licences et vue adaptée par profil.

Exécution :  venv\\Scripts\\python test_lot_d.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import validation_numerique as vn
import vue_par_profil as vpp
import workflow_instruction as wfi
from erreurs import ErreurWorkflow
from models import (DossierAMM, Etablissement, EtapeValidation, Notification,
                    Personne, Produit, RapportInstruction, db)

_res = []
from models import CourrielSortant  # noqa: E402

_MODELES = (EtapeValidation, RapportInstruction, CourrielSortant, DossierAMM,
            Produit, Notification, Personne, Etablissement)


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def leve(fn, motif=None):
    try:
        fn()
        return False
    except ErreurWorkflow as e:
        return motif is None or motif.lower() in str(e).lower()


def _max_ids():
    return {M: (db.session.query(db.func.max(M.id)).scalar() or 0) for M in _MODELES}


def _nettoyer(reperes):
    for M in _MODELES:
        for obj in M.query.filter(M.id > reperes[M]).all():
            db.session.delete(obj)
    db.session.commit()


def _r(role):
    return Personne.query.filter_by(role_systeme=role).first()


def _dossier():
    s = uuid.uuid4().hex[:6]
    etab = Etablissement(raison_sociale=f"L-{s}", type="importateur_exportateur",
                         statut_licence="active")
    db.session.add(etab); db.session.flush()
    dep = Personne(nom_complet=f"D{s}", email=f"{s}@t.demo",
                   role_systeme="demandeur_externe", statut_compte="actif",
                   etablissement_rattachement_id=etab.id)
    dep.set_password("pw"); db.session.add(dep); db.session.flush()
    p = Produit(nom_commercial=f"P{s}", forme_pharmaceutique="Comprimé",
                nature="chimique", titulaire_amm_id=etab.id)
    db.session.add(p); db.session.flush()
    d = DossierAMM(numero=f"AMM-D-{s}", produit_id=p.id, demandeur_id=dep.id,
                   statut="soumis")
    db.session.add(d); db.session.flush()
    return d


def test_circuit_licence():
    print("\n[1] Circuit licence — cinq échelons, sans commission")
    verifier("circuit licence déclaré", "licence" in vn.CIRCUITS)
    verifier("cinq échelons jusqu'au ministre", len(vn.CIRCUITS["licence"]) == 5,
             str(len(vn.CIRCUITS["licence"])))
    verifier("instruit par le service Licences",
             vn.CIRCUITS["licence"][0] == "chef_service_licences")
    verifier("passe par le sous-directeur des Établissements",
             vn.CIRCUITS["licence"][1] == "sous_directeur_etablissements")
    verifier("signée par le ministre",
             vn.CIRCUITS["licence"][-1] == "ministre_sante")
    verifier("pas de commission pour les licences",
             "licence" not in vn.CIRCUITS_AVEC_COMMISSION)
    verifier("l'AMM garde sa commission", "amm" in vn.CIRCUITS_AVEC_COMMISSION)
    verifier("l'AMM reste le circuit le plus long (audit IG)",
             len(vn.CIRCUITS["amm"]) > len(vn.CIRCUITS["licence"]))


def test_signature_licence():
    print("\n[2] Signature d'une licence de bout en bout")
    d = _dossier()
    cs = _r("chef_service_licences")
    sd = _r("sous_directeur_etablissements")
    dr = _r("directeur_dpml")
    sg = _r("secretaire_general_ms")
    mn = _r("ministre_sante")
    if not all((cs, sd, dr, sg, mn)):
        verifier("comptes des cinq échelons disponibles", False)
        return

    vn.ouvrir_circuit(d, "licence", cs)
    db.session.flush()
    verifier("premier échelon = chef de service Licences",
             vn.etape_courante(d).role_requis == "chef_service_licences")
    verifier("le chef Homologation ne signe pas une licence",
             leve(lambda: vn.signer(d, _r("chef_service_amm")), "revient au"))

    for acteur in (cs, sd, dr, sg):
        _e, acheve = vn.signer(d, acteur)
        db.session.flush()
        verifier(f"{acteur.role_systeme} a signé, circuit non achevé", not acheve)
    _e, acheve = vn.signer(d, mn)
    db.session.flush()
    verifier("signature du ministre = circuit achevé", acheve)
    verifier("cinq signatures apposées", vn.progression(d) == (5, 5))
    verifier("aucune commission pour la licence",
             "licence" not in vn.CIRCUITS_AVEC_COMMISSION)


def test_profondeur_par_profil():
    print("\n[3] Profondeur d'information par échelon")
    verifier("chef de service → vue technique",
             vpp.profondeur(_r("chef_service_amm")) == "technique")
    verifier("sous-directeur → vue de synthèse",
             vpp.profondeur(_r("sous_directeur_medicament")) == "synthese")
    verifier("directeur → vue de synthèse",
             vpp.profondeur(_r("directeur_dpml")) == "synthese")
    verifier("secrétaire général → vue parcours",
             vpp.profondeur(_r("secretaire_general_ms")) == "parcours")
    verifier("ministre → vue parcours",
             vpp.profondeur(_r("ministre_sante")) == "parcours")
    verifier("directeur général de l'agence → vue parcours",
             vpp.profondeur(_r("directeur_general_agence")) == "parcours")
    verifier("profil inconnu → vue parcours (le moins exposant)",
             vpp.profondeur(None) == "parcours")


def test_contenu_adapte():
    print("\n[4] Contenu réellement adapté au profil")
    d = _dossier()
    chef = _r("chef_service_amm")
    wfi.enregistrer_checklist(d, chef, {c: True for c in wfi.POINTS_BLOQUANTS})
    wfi.attester_paiement(d, _r("responsable_financier"))
    wfi.prononcer_recevabilite(d, chef, True)
    wfi.rediger_rapport(d, chef, "favorable", "Instruction complète.")
    db.session.flush()

    vue_ministre = vpp.dossier_amm(d, _r("ministre_sante"))
    vue_chef = vpp.dossier_amm(d, chef)

    verifier("le ministre reçoit une liste de contrôles de régularité",
             "controles" in vue_ministre and len(vue_ministre["controles"]) == 6)
    verifier("le ministre ne reçoit PAS le détail des assignations",
             "assignations" not in vue_ministre)
    verifier("le ministre ne reçoit PAS la checklist technique",
             "checklist" not in vue_ministre)
    verifier("le ministre voit l'avis de la direction",
             vue_ministre.get("avis_direction") is not None,
             str(vue_ministre.get("avis_direction")))

    verifier("le chef de service reçoit le détail technique",
             "assignations" in vue_chef and "checklist" in vue_chef)
    verifier("les deux voient la référence et le parcours",
             vue_ministre["reference"] == vue_chef["reference"]
             and "jalons" in vue_ministre and "jalons" in vue_chef)
    verifier("le parcours est horodaté", len(vue_ministre["jalons"]) >= 1,
             f"{len(vue_ministre['jalons'])} jalon(s)")

    vue_sd = vpp.dossier_amm(d, _r("sous_directeur_medicament"))
    verifier("le sous-directeur reçoit les avis consolidés",
             "avis_evaluateurs" in vue_sd and "syntheses_commission" in vue_sd)
    verifier("le sous-directeur ne reçoit pas la checklist brute",
             "checklist" not in vue_sd)


def test_generalisation_circuits():
    print("\n[5] Généralisation des circuits à tous les modules")
    attendus = {"amm", "licence", "derogation", "visa_technique", "essai_clinique",
                "controle_qualite", "inspection", "atu"}
    verifier("huit circuits déclarés", set(vn.CIRCUITS) == attendus,
             str(set(vn.CIRCUITS) ^ attendus) if set(vn.CIRCUITS) != attendus else "")
    verifier("chaque circuit a un libellé",
             all(c in vn.LIBELLE_CIRCUIT for c in vn.CIRCUITS))
    verifier("chaque circuit se termine par un signataire de niveau direction",
             all(e[-1] in ("directeur_dpml", "ministre_sante",
                           "directeur_general_agence") for e in vn.CIRCUITS.values()))
    verifier("commission pour l'AMM et l'essai clinique",
             vn.CIRCUITS_AVEC_COMMISSION == {"amm", "essai_clinique"})
    verifier("le contrôle qualité et l'inspection n'ont pas de commission",
             "controle_qualite" not in vn.CIRCUITS_AVEC_COMMISSION
             and "inspection" not in vn.CIRCUITS_AVEC_COMMISSION)
    verifier("chaque circuit démarre par un chef de service",
             all(e[0].startswith("chef_service") for e in vn.CIRCUITS.values()))
    verifier("le circuit ATU est le plus court — l'urgence en est la raison",
             len(vn.CIRCUITS["atu"]) == min(len(e) for e in vn.CIRCUITS.values()))
    # Chaque échelon d'un circuit doit exister comme rôle
    from permissions import ROLES
    inconnus = [r for e in vn.CIRCUITS.values() for r in e if r not in ROLES]
    verifier("tous les échelons correspondent à un rôle réel", not inconnus,
             str(inconnus))


def test_courriel():
    print("\n[6] Notification par courriel")
    import courriel
    from models import CourrielSortant
    verifier("service courriel disponible", hasattr(courriel, "envoyer"))
    verifier("types couverts déclarés", len(courriel.TYPES_A_ENVOYER) >= 10,
             f"{len(courriel.TYPES_A_ENVOYER)} types")
    verifier("sans SMTP, rien n'est prétendu envoyé",
             not courriel.etat()["configure"])

    d = _dossier()
    avant = CourrielSortant.query.count()
    chef = _r("chef_service_amm")
    wfi.enregistrer_checklist(d, chef, {c: True for c in wfi.POINTS_BLOQUANTS})
    wfi.attester_paiement(d, _r("responsable_financier"))
    wfi.prononcer_recevabilite(d, chef, True)
    db.session.flush()
    apres = CourrielSortant.query.count()
    verifier("un courriel est préparé à la recevabilité", apres > avant)
    c = CourrielSortant.query.order_by(CourrielSortant.id.desc()).first()
    verifier("adressé au déposant", c.adresse == d.demandeur.email, c.adresse)
    verifier("statut « journalisé » faute de SMTP", c.statut == "journalise",
             c.statut)
    verifier("le corps reprend le message", "évaluation" in c.corps)
    verifier("le corps porte un lien de consultation", "Consulter" in c.corps)

    # Un type non listé ne déclenche pas de courriel : on n'inonde pas.
    avant2 = CourrielSortant.query.count()
    from notifications import notifier
    notifier(d.demandeur, "type_sans_courriel", "Message interne.")
    db.session.flush()
    verifier("un type non listé ne part pas par courriel",
             CourrielSortant.query.count() == avant2)


def main():
    print("=" * 70)
    print("Lot D — licences, vue par profil, courriel")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_circuit_licence, test_signature_licence,
                  test_profondeur_par_profil, test_contenu_adapte,
                  test_generalisation_circuits, test_courriel):
            try:
                t()
            except Exception as e:                       # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False, f"{type(e).__name__}: {e}")
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
