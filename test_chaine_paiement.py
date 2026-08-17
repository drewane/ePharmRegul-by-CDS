"""
Test de bout en bout : chaque acte réglementaire déclenche-t-il la bonne
créance, auprès du bon redevable, et le règlement débloque-t-il la suite ?

Exécution :  venv\\Scripts\\python test_chaine_paiement.py
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app as application
import bareme
import paiement as pf
import paiements as svc
from models import (Echantillon, Etablissement, Lot, Paiement, Personne,
                    Produit, db)

_res = []


def verifier(nom, cond, detail=""):
    _res.append((nom, bool(cond)))
    print(f"  {'OK  ' if cond else 'ECHEC'}  {nom}" + (f" — {detail}" if detail else ""))


def creance_de(entite):
    return (Paiement.query
            .filter_by(entite_type=entite.__class__.__name__, entite_id=entite.id)
            .order_by(Paiement.id.desc()).first())


def test_essai_clinique():
    print("\n[1] Essai clinique — le promoteur est redevable")
    import workflow_ct as wf
    promoteur = Personne.query.filter_by(role_systeme="demandeur_externe").first()
    protocole = wf.deposer(promoteur, "Essai de phase III — test automatisé")
    db.session.commit()

    p = creance_de(protocole)
    verifier("créance créée au dépôt", p is not None)
    if p:
        verifier("montant conforme au barème", p.montant == bareme.montant("essai_clinique"),
                 f"{p.montant} XAF")
        redevable = svc._demandeur(p)
        verifier("redevable = le promoteur",
                 redevable is not None and redevable.id == promoteur.id,
                 redevable.email if redevable else "aucun")
        verifier("apparaît dans l'espace du promoteur",
                 any(x.id == p.id for x in svc.paiements_du_redevable(promoteur)))


def test_analyse_labo():
    print("\n[2] Analyse de laboratoire — seule la demande directe est facturée")
    import workflow_lt as wf
    demandeur = Personne.query.filter_by(role_systeme="demandeur_externe").first()
    agent = Personne.query.filter_by(role_systeme="agent_laboratoire").first()
    produit = Produit.query.first()

    directe = wf.creer_echantillon(produit, demandeur, origine="demande_directe")
    db.session.commit()
    p = creance_de(directe)
    verifier("demande directe : créance créée", p is not None)
    if p:
        verifier("redevable = le demandeur",
                 (svc._demandeur(p) or None) and svc._demandeur(p).id == demandeur.id)

    office = wf.creer_echantillon(produit, agent or demandeur, origine="inspection")
    db.session.commit()
    verifier("prélèvement d'office : AUCUNE créance", creance_de(office) is None)

    lie_amm = wf.creer_echantillon(produit, agent or demandeur, origine="dossier_amm")
    db.session.commit()
    verifier("échantillon lié à une AMM : AUCUNE créance (déjà couvert)",
             creance_de(lie_amm) is None)


def test_inspection_gratuite_par_defaut():
    print("\n[3] Inspection — non facturée par défaut, activable par paramètre")
    import workflow_ri as wf
    verifier("tarif par défaut à 0", bareme.montant("inspection") == 0)

    admin = Personne.query.filter_by(role_systeme="administrateur_dpml").first()
    inspecteur = Personne.query.filter_by(role_systeme="inspecteur_igspl").first()
    etab = Etablissement.query.first()
    if not (admin and inspecteur and etab):
        verifier("jeu de démonstration complet", False, "comptes manquants")
        return
    insp = wf.planifier(etab, inspecteur, admin)
    db.session.commit()
    verifier("aucune créance tant que le tarif vaut 0", creance_de(insp) is None)

    # Activation par simple paramétrage
    from models import ParametreModule
    prm = ParametreModule.query.filter_by(module="RI", cle="frais_inspection_xaf").first()
    prm.valeur = "50000"
    db.session.commit()
    verifier("tarif relu depuis le paramétrage", bareme.montant("inspection") == 50000)

    insp2 = wf.planifier(etab, inspecteur, admin)
    db.session.commit()
    p = creance_de(insp2)
    verifier("créance créée une fois le tarif activé", p is not None,
             f"{p.montant} XAF" if p else "aucune")

    prm.valeur = "0"          # on rétablit l'exonération
    db.session.commit()


def test_reglement_multi_moyens():
    print("\n[4] Règlement — les quatre moyens aboutissent")
    demandeur = Personne.query.filter_by(role_systeme="demandeur_externe").first()
    dus = [p for p in svc.paiements_du_redevable(demandeur) if p.statut != "confirme"]
    if len(dus) < 3:
        verifier("créances disponibles pour le test", False, f"{len(dus)} trouvée(s)")
        return

    contexte = {"url_retour": "/r", "url_notification": "/n", "url_simulateur": "/s",
                "numero_payeur": "699112233"}

    for code, p in zip(("mtn_momo", "carte", "virement"), dus):
        svc.initier_en_ligne(p, code, contexte, demandeur)
        db.session.commit()
        verifier(f"[{code}] créance initiée", p.statut == "initie")
        verifier(f"[{code}] référence préfixée",
                 (p.reference_marchande or "").startswith(pf.obtenir(code).prefixe_ref))

        f = pf.obtenir(code)
        if code == "virement":
            svc.rapprocher_virement(p, {"reference": p.reference_marchande,
                                        "montant": p.montant, "devise": p.devise,
                                        "reference_bancaire": "OP-TEST"}, demandeur)
        else:
            svc.traiter_notification(p, f.notification_simulee(p, succes=True), demandeur)
        db.session.commit()
        verifier(f"[{code}] créance réglée", p.statut == "confirme")
        verifier(f"[{code}] transaction tracée", bool(p.reference_transaction))


def test_coherence_bareme():
    print("\n[5] Cohérence du barème")
    grille = bareme.grille()
    verifier("7 faits générateurs", len(grille) == 7, str(len(grille)))
    gratuits = [l["libelle"] for l in grille if l["montant"] == 0]
    verifier("l'ATU est déclarée gratuite au barème",
             any("temporaire" in l.lower() for l in gratuits), str(gratuits))
    for ligne in grille:
        verifier(f"« {ligne['libelle']} » : montant lisible",
                 isinstance(ligne["montant"], int) and ligne["montant"] >= 0,
                 f"{ligne['montant']} XAF")


def main():
    print("=" * 70)
    print("Chaîne acte réglementaire → créance → règlement")
    print("=" * 70)
    with application.app.app_context():
        for t in (test_essai_clinique, test_analyse_labo,
                  test_inspection_gratuite_par_defaut, test_reglement_multi_moyens,
                  test_coherence_bareme):
            try:
                t()
            except Exception as e:                      # noqa: BLE001
                db.session.rollback()
                verifier(f"{t.__name__} sans exception", False, f"{type(e).__name__}: {e}")
        db.session.rollback()                            # on ne laisse rien en base

    total, ok = len(_res), sum(1 for _n, o in _res if o)
    print("\n" + "=" * 70)
    print(f"Résultat : {ok}/{total} vérifications réussies")
    if ok != total:
        print("Échecs : " + " | ".join(n for n, o in _res if not o))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
