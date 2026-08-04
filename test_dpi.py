"""
Tests du moteur de déclarations d'intérêts et de déports.

L'enjeu : un lien d'intérêt doit BLOQUER effectivement, pas seulement être
signalé. Ces tests vérifient que le contrôle ne se contourne pas.

Exécution :  venv\\Scripts\\python test_dpi.py
"""
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import dpi
import workflow_instruction as wfi
from erreurs import ErreurWorkflow
from models import (AssignationEvaluation, AvisCommission, DeclarationInteret,
                    Deport, DossierAMM, DossierSession, Etablissement,
                    LienInteret, Notification, Personne, Produit,
                    SessionCommission, db)

_res = []
_MODELES = (Deport, LienInteret, DeclarationInteret, AvisCommission, DossierSession,
            SessionCommission, AssignationEvaluation, DossierAMM, Produit,
            Notification, Personne, Etablissement)


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


def _contexte(nom_labo="Pharma Alpha"):
    """Un dossier déposé par un laboratoire, et un évaluateur disponible."""
    s = uuid.uuid4().hex[:6]
    labo = Etablissement(raison_sociale=f"{nom_labo} {s}",
                         type="importateur_exportateur", statut_licence="active")
    db.session.add(labo); db.session.flush()
    dep = Personne(nom_complet=f"Dép {s}", email=f"dep{s}@t.demo",
                   role_systeme="demandeur_externe", statut_compte="actif",
                   etablissement_rattachement_id=labo.id)
    dep.set_password("pw"); db.session.add(dep); db.session.flush()
    p = Produit(nom_commercial=f"Prod {s}", forme_pharmaceutique="Comprimé",
                nature="chimique", titulaire_amm_id=labo.id)
    db.session.add(p); db.session.flush()
    d = DossierAMM(numero=f"AMM-DPI-{s}", produit_id=p.id, demandeur_id=dep.id,
                   statut="evaluation_en_cours")
    db.session.add(d); db.session.flush()

    ev = Personne(nom_complet=f"Éval {s}", email=f"ev{s}@t.demo",
                  role_systeme="evaluateur_interne", statut_compte="actif")
    ev.set_password("pw"); db.session.add(ev); db.session.flush()
    return labo, d, ev


def _chef():
    return (Personne.query.filter_by(role_systeme="chef_bureau").first()
            or Personne.query.filter_by(role_systeme="chef_service_amm").first())


def test_normalisation():
    print("\n[1] Rapprochement des noms d'organismes")
    verifier("insensible à la casse et aux accents",
             dpi.normaliser("Laboratoire Éclair SA") == dpi.normaliser("LABO ECLAIR"))
    verifier("insensible à l'ordre des mots",
             dpi.normaliser("Alpha Beta") == dpi.normaliser("Beta Alpha"))
    verifier("insensible aux mentions juridiques",
             dpi.normaliser("Sanofi SA") == dpi.normaliser("Sanofi"))
    verifier("deux organismes distincts ne se confondent pas",
             dpi.normaliser("Alpha") != dpi.normaliser("Omega"))
    verifier("chaîne vide gérée", dpi.normaliser(None) == "")


def test_declaration():
    print("\n[2] Déclaration d'intérêts")
    _labo, _d, ev = _contexte()
    verifier("aucune déclaration au départ", dpi.declaration_en_vigueur(ev) is None)
    verifier("situation « manquante »", dpi.situation(ev)["etat"] == "manquante")
    verifier("l'évaluateur est assujetti", dpi.est_assujetti(ev))

    verifier("déclaration vide refusée",
             leve(lambda: dpi.enregistrer_declaration(ev, []), "aucun lien"))

    d1 = dpi.enregistrer_declaration(ev, [], aucun_lien=True)
    db.session.flush()
    verifier("déclaration « néant » acceptée", d1.aucun_lien)
    verifier("situation « à jour »", dpi.situation(ev)["etat"] == "a_jour")
    verifier("version 1", d1.version == 1)

    d2 = dpi.enregistrer_declaration(ev, [
        {"organisme": "Pharma Alpha", "nature": "conseil",
         "description": "Mission d'expertise 2024"}])
    db.session.flush()
    verifier("nouvelle version créée", d2.version == 2)
    verifier("l'ancienne n'est plus en vigueur", not d1.en_vigueur)
    verifier("l'historique est conservé",
             DeclarationInteret.query.filter_by(personne_id=ev.id).count() == 2)
    verifier("gravité déduite de la nature", d2.liens[0].gravite == "majeur")
    verifier("nature inconnue refusée",
             leve(lambda: dpi.enregistrer_declaration(
                 ev, [{"organisme": "X", "nature": "inventée"}]), "nature"))


def test_croisement():
    print("\n[3] Croisement avec le dossier")
    labo, dossier, ev = _contexte("Pharma Beta")
    dpi.enregistrer_declaration(ev, [
        {"organisme": labo.raison_sociale, "nature": "remuneration"}])
    db.session.flush()

    verifier("organismes du dossier identifiés",
             labo.raison_sociale in dpi.organismes_du_dossier(dossier))
    trouves = dpi.conflits(ev, dossier)
    verifier("conflit détecté", len(trouves) == 1)
    verifier("conflit qualifié de majeur",
             len(dpi.conflits_majeurs(ev, dossier)) == 1)

    # Un évaluateur sans lien n'est pas inquiété
    _l2, _d2, ev2 = _contexte("Pharma Gamma")
    dpi.enregistrer_declaration(ev2, [], aucun_lien=True)
    db.session.flush()
    verifier("aucun conflit pour une déclaration néant",
             dpi.conflits(ev2, dossier) == [])

    # Un lien mineur ne déclenche pas de déport
    _l3, _d3, ev3 = _contexte()
    dpi.enregistrer_declaration(ev3, [
        {"organisme": labo.raison_sociale, "nature": "invitation"}])
    db.session.flush()
    verifier("un lien mineur est détecté", len(dpi.conflits(ev3, dossier)) == 1)
    verifier("un lien mineur n'est pas majeur",
             dpi.conflits_majeurs(ev3, dossier) == [])


def test_blocage_attribution():
    print("\n[4] Attribution bloquée par le conflit")
    labo, dossier, ev = _contexte("Pharma Delta")
    chef = _chef()
    if chef is None:
        verifier("compte chef de bureau disponible", False)
        return
    dpi.enregistrer_declaration(ev, [
        {"organisme": labo.raison_sociale, "nature": "actions"}])
    db.session.flush()

    verifier("attribution refusée",
             leve(lambda: wfi.assigner(dossier, ev, chef), "lien d'intérêt"))
    db.session.flush()
    verifier("un déport a été prononcé automatiquement",
             dpi.deport_actif(ev, dossier) is not None)
    verifier("aucune assignation créée",
             AssignationEvaluation.query.filter_by(
                 dossier_id=dossier.id, evaluateur_id=ev.id).first() is None)

    autorise, motif = dpi.acces_autorise(ev, dossier)
    verifier("accès au dossier fermé", not autorise)
    verifier("motif communiqué à l'agent", "déporté" in (motif or "").lower())
    verifier("l'agent est prévenu",
             Notification.query.filter_by(destinataire_id=ev.id,
                                          type="deport_prononce").count() >= 1)


def test_declaration_obligatoire():
    print("\n[5] Pas de dossier sans déclaration")
    _labo, dossier, ev = _contexte()
    chef = _chef()
    verifier("attribution refusée sans DPI",
             leve(lambda: wfi.assigner(dossier, ev, chef), "déclaration"))
    dpi.enregistrer_declaration(ev, [], aucun_lien=True)
    db.session.flush()
    a = wfi.assigner(dossier, ev, chef)
    db.session.flush()
    verifier("attribution possible une fois la DPI déposée", a is not None)


def test_deport_en_seance():
    print("\n[6] Déport en séance de commission")
    labo, dossier, _ev = _contexte("Pharma Epsilon")
    chef = _chef()
    membres = Personne.query.filter_by(
        role_systeme="membre_commission_specialisee", statut_compte="actif").limit(2).all()
    if len(membres) < 2 or chef is None:
        verifier("membres de commission disponibles", False)
        return

    # Le premier membre a un lien avec le laboratoire, le second non.
    dpi.enregistrer_declaration(membres[0], [
        {"organisme": labo.raison_sociale, "nature": "conseil"}])
    dpi.enregistrer_declaration(membres[1], [], aucun_lien=True)
    db.session.flush()

    convocateur = Personne.query.filter_by(role_systeme="chef_service_amm").first()
    seance = wfi.convoquer_commission(convocateur, "Séance test DPI")
    ds = wfi.inscrire_dossier(seance, dossier, convocateur)
    db.session.flush()

    prononces = wfi.controler_deports_seance(seance, convocateur)
    db.session.flush()
    verifier("déport prononcé pour le membre en conflit", len(prononces) == 1,
             f"{len(prononces)} déport(s)")
    verifier("le membre en conflit ne peut pas délibérer",
             leve(lambda: wfi.saisir_avis(ds, membres[0], {}, "favorable"),
                  "déporté"))
    a = wfi.saisir_avis(ds, membres[1], {}, "favorable")
    db.session.flush()
    verifier("le membre sans lien délibère normalement", a is not None)

    wfi.clore_seance(seance, convocateur)
    db.session.flush()
    verifier("les déports sont portés au procès-verbal",
             membres[0].nom_complet in (seance.mention_deports or ""))


def test_levee_deport():
    print("\n[7] Levée d'un déport — réservée à la direction")
    labo, dossier, ev = _contexte("Pharma Zeta")
    dpi.enregistrer_declaration(ev, [
        {"organisme": labo.raison_sociale, "nature": "conseil"}])
    db.session.flush()
    dpi.controler_avant_attribution(ev, dossier)
    db.session.flush()
    d = dpi.deport_actif(ev, dossier)
    verifier("déport actif", d is not None)

    chef = _chef()
    verifier("un chef de bureau ne peut pas lever un déport",
             leve(lambda: dpi.lever_deport(d, chef, "motif"), "direction"))
    verifier("une levée sans motif est refusée",
             leve(lambda: dpi.lever_deport(
                 d, Personne.query.filter_by(role_systeme="directeur_dpml").first(), ""),
                  "motivée"))

    directeur = Personne.query.filter_by(role_systeme="directeur_dpml").first()
    dpi.lever_deport(d, directeur, "Lien échu depuis plus de cinq ans, vérifié.")
    db.session.flush()
    verifier("déport levé", d.leve)
    verifier("la levée est tracée", d.leve_par_id == directeur.id and d.motif_levee)
    autorise, _m = dpi.acces_autorise(ev, dossier)
    verifier("l'accès est rétabli", autorise)


def main():
    print("=" * 70)
    print("Déclarations d'intérêts et déports — tests")
    print("=" * 70)
    with application.app.app_context():
        reperes = _max_ids()
        for t in (test_normalisation, test_declaration, test_croisement,
                  test_blocage_attribution, test_declaration_obligatoire,
                  test_deport_en_seance, test_levee_deport):
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
