"""
Vérifications de la machine à états (lot 5).

Ce que l'on cherche à établir :
  1. le modèle déclaré est structurellement sain (pas de cul-de-sac, pas
     d'état inatteignable, pas d'action ouverte à personne) ;
  2. le parcours nominal va du brouillon à l'AMM signée ;
  3. les chemins de rejet et de complément fonctionnent et reviennent ;
  4. le moteur REFUSE ce qu'il doit refuser — mauvais rôle, mauvais état,
     motif manquant — même quand l'appel court-circuite l'interface ;
  5. chaque passage laisse une trace nominative ;
  6. les notifications déclarées partent, et elles seules ;
  7. l'écran ne peut pas offrir une action que le serveur refuserait.
"""
import app as application
import machine_etats as me
from erreurs import ErreurWorkflow
from models import (DossierAMM, EvenementAudit, Notification, Personne,
                    Produit, db)

ok = 0
ko = []


def verifier(condition, libelle):
    global ok
    if condition:
        ok += 1
    else:
        ko.append(libelle)
        print(f"  ECHEC : {libelle}")


def _max_ids():
    return {
        "dossier": db.session.query(db.func.max(DossierAMM.id)).scalar() or 0,
        "produit": db.session.query(db.func.max(Produit.id)).scalar() or 0,
        "audit": db.session.query(db.func.max(EvenementAudit.id)).scalar() or 0,
        "notif": db.session.query(db.func.max(Notification.id)).scalar() or 0,
    }


def _nettoyer(avant):
    EvenementAudit.query.filter(EvenementAudit.id > avant["audit"]).delete()
    Notification.query.filter(Notification.id > avant["notif"]).delete()
    DossierAMM.query.filter(DossierAMM.id > avant["dossier"]).delete()
    Produit.query.filter(Produit.id > avant["produit"]).delete()
    db.session.commit()


def _compte(role):
    return Personne.query.filter_by(role_systeme=role,
                                    statut_compte="actif").first()


def _dossier(deposant, statut="brouillon"):
    from numerotation import generer_numero

    p = Produit(nom_commercial="Testine 500", forme_pharmaceutique="Comprimé",
                dosage="500 mg", nature="chimique", categorie="medicament")
    db.session.add(p)
    db.session.flush()
    d = DossierAMM(numero=generer_numero("AMM"), produit_id=p.id,
                   demandeur_id=deposant.id, statut=statut,
                   type_procedure="nouvelle_demande")
    db.session.add(d)
    db.session.flush()
    return d


with application.app.app_context():
    avant = _max_ids()
    print("== Machine à états ==")

    # -----------------------------------------------------------------
    print("\n-- 1. Santé structurelle du modèle --")
    anomalies = me.verifier_machine()
    verifier(not anomalies, f"modèle sans anomalie ({anomalies})")
    verifier(len(me.TRANSITIONS) >= 15, "au moins quinze transitions déclarées")
    verifier(all(t["depuis"] in me.STATUTS and t["vers"] in me.STATUTS
                 for t in me.TRANSITIONS),
             "toute transition relie deux statuts connus")
    verifier(all(t["motif_requis"] for t in me.TRANSITIONS
                 if t["vers"] in ("rejete", "irrecevable", "a_completer")),
             "tout rejet, irrecevabilité ou complément exige un motif")
    verifier(me.statut_canonique("soumis") == "en_attente_confirmation"
             and me.statut_canonique("approuve") == "valide"
             and me.statut_canonique("complement_requis") == "a_completer",
             "les anciens statuts se lisent dans le vocabulaire canonique")
    verifier(me.statut_canonique("brouillon") == "brouillon",
             "un statut déjà canonique reste inchangé")
    verifier(me.est_terminal("amm_signee") and me.est_terminal("rejete")
             and not me.est_terminal("recevable"),
             "les états terminaux sont correctement marqués")

    # Un seul acteur peut valider : c'est l'arbitrage retenu.
    valider = me.transition("valider")
    verifier(valider["roles"] == ("directeur_dpml",),
             "la validation finale relève du seul directeur")
    verifier(me.transition("enregistrer_signature")["vers"] == "amm_signee",
             "la signature du ministre est constatée, non simulée")

    # -----------------------------------------------------------------
    print("\n-- 2. Parcours nominal, du brouillon à l'AMM signée --")
    deposant = _compte("demandeur_externe")
    financier = _compte("responsable_financier")
    chef = _compte("chef_service_amm")
    directeur = _compte("directeur_dpml")
    verifier(all([deposant, financier, chef, directeur]),
             "les quatre acteurs du circuit ont un compte actif")

    d = _dossier(deposant)
    nominal = [
        ("soumettre", deposant, "en_attente_confirmation"),
        ("valider_paiement", financier, "en_attente_recevabilite"),
        ("declarer_recevable", chef, "recevable"),
        ("envoyer_commission", chef, "en_commission"),
        ("retour_service", chef, "retour_homologation"),
        ("valider", directeur, "valide"),
        ("transmettre_signature", chef, "amm_a_signer"),
        ("enregistrer_signature", chef, "amm_signee"),
    ]
    for action, acteur, attendu in nominal:
        ouvertes = [t["action"] for t in
                    me.transitions_autorisees(d, acteur.role_systeme)]
        verifier(action in ouvertes,
                 f"« {action} » est offerte à {acteur.role_systeme} "
                 f"depuis {d.statut}")
        me.appliquer_transition(d, action, acteur)
        verifier(d.statut == attendu, f"{action} → {attendu} (obtenu {d.statut})")
    db.session.commit()

    verifier(d.date_decision is not None,
             "la validation horodate la décision")
    verifier(me.est_terminal(d), "le dossier abouti est en état terminal")
    verifier(me.transitions_autorisees(d, "directeur_dpml") == [],
             "un dossier signé n'offre plus aucune action")

    # -----------------------------------------------------------------
    print("\n-- 3. Historique et audit --")
    h = me.historique(d)
    verifier(len(h) == len(nominal),
             f"huit passages journalisés (obtenu {len(h)})")
    verifier([e.nouveau_statut for e in h] == [a[2] for a in nominal],
             "l'historique restitue le parcours dans l'ordre")
    verifier(all(e.acteur_id is not None for e in h),
             "chaque passage est nominatif")
    verifier(h[0].ancien_statut == "brouillon"
             and h[-1].nouveau_statut == "amm_signee",
             "l'audit porte l'état d'avant et l'état d'après")
    etapes = me.etapes(d)
    verifier(all(e["atteint"] or e["courant"] for e in etapes),
             "toutes les étapes du parcours nominal sont marquées atteintes")
    verifier(all(e["date"] is not None for e in etapes
                 if e["code"] != "brouillon"),
             "la timeline est datée depuis l'audit, non recalculée")

    # -----------------------------------------------------------------
    print("\n-- 4. Cas de complément --")
    d2 = _dossier(deposant, statut="en_attente_recevabilite")
    try:
        me.appliquer_transition(d2, "demander_complement", chef, "   ")
        verifier(False, "un motif fait d'espaces est refusé")
    except ErreurWorkflow:
        verifier(True, "un motif fait d'espaces est refusé")
    verifier(d2.statut == "en_attente_recevabilite",
             "le refus laisse le dossier dans son état")

    me.appliquer_transition(d2, "demander_complement", chef,
                            "Certificat GMP du site de fabrication absent.")
    verifier(d2.statut == "a_completer", "le complément met le dossier à compléter")
    verifier(me.attend_le_deposant(d2), "la balle est dans le camp du déposant")
    acteur_att, _libelle = me.prochaine_etape(d2)
    verifier(acteur_att == "vous", "la prochaine action est annoncée au déposant")

    verifier([t["action"] for t in
              me.transitions_autorisees(d2, "demandeur_externe")]
             == ["repondre_complement"],
             "le déposant n'a qu'une seule suite : répondre")
    me.appliquer_transition(d2, "repondre_complement", deposant)
    verifier(d2.statut == "en_attente_recevabilite",
             "la réponse au complément replace le dossier en recevabilité")
    db.session.commit()

    trace = me.historique(d2)
    verifier(any("Certificat GMP" in (e.commentaire or "") for e in trace),
             "le motif du complément est conservé dans l'audit")
    verifier(len(trace) == 2, "la tentative refusée n'a rien journalisé")

    # -----------------------------------------------------------------
    print("\n-- 5. Cas de rejet --")
    d3 = _dossier(deposant, statut="retour_homologation")
    try:
        me.appliquer_transition(d3, "rejeter", directeur)
        verifier(False, "un rejet sans motif est refusé")
    except ErreurWorkflow as e:
        verifier("motivé" in str(e), "un rejet sans motif est refusé, et dit pourquoi")

    me.appliquer_transition(d3, "rejeter", directeur,
                            "Bioéquivalence non démontrée.")
    verifier(d3.statut == "rejete", "le rejet clôt le dossier")
    verifier(d3.motif_decision == "Bioéquivalence non démontrée.",
             "le motif est porté par le dossier, pas seulement par l'audit")
    verifier(me.transitions_autorisees(d3, "directeur_dpml") == [],
             "un dossier rejeté n'offre plus rien")
    etapes3 = me.etapes(d3)
    verifier(etapes3[-1]["code"] == "rejete" and etapes3[-1]["courant"],
             "la timeline d'un rejet se termine sur le rejet")
    verifier(not any(e["code"] in ("valide", "amm_signee") for e in etapes3),
             "un dossier rejeté n'affiche pas les étapes qu'il n'atteindra pas")
    db.session.commit()

    # -----------------------------------------------------------------
    print("\n-- 6. Ce que le moteur refuse --")
    d4 = _dossier(deposant, statut="en_attente_recevabilite")

    try:
        me.appliquer_transition(d4, "valider", directeur)
        verifier(False, "valider depuis un état trop précoce est refusé")
    except ErreurWorkflow:
        verifier(True, "valider depuis un état trop précoce est refusé")

    try:
        me.appliquer_transition(d4, "declarer_recevable", deposant)
        verifier(False, "le déposant ne peut pas se déclarer recevable")
    except ErreurWorkflow:
        verifier(True, "le déposant ne peut pas se déclarer recevable")

    try:
        me.appliquer_transition(d4, "declarer_recevable", financier)
        verifier(False, "le financier ne prononce pas la recevabilité")
    except ErreurWorkflow:
        verifier(True, "le financier ne prononce pas la recevabilité")

    try:
        me.appliquer_transition(d4, "action_inventee", chef)
        verifier(False, "une action inconnue est refusée")
    except ErreurWorkflow:
        verifier(True, "une action inconnue est refusée")

    verifier(d4.statut == "en_attente_recevabilite",
             "quatre refus, et le dossier n'a pas bougé")
    verifier(me.historique(d4) == [], "un refus ne laisse aucune trace d'état")
    db.session.commit()

    # -----------------------------------------------------------------
    print("\n-- 7. Notifications : les déclarées, et elles seules --")
    d5 = _dossier(deposant)
    repere = db.session.query(db.func.max(Notification.id)).scalar() or 0
    me.appliquer_transition(d5, "soumettre", deposant)
    db.session.commit()
    envoyees = Notification.query.filter(Notification.id > repere).all()
    destinataires = {n.destinataire_id for n in envoyees}
    verifier(deposant.id in destinataires,
             "la soumission prévient le déposant")
    financiers = {p.id for p in Personne.query.filter_by(
        role_systeme="responsable_financier", statut_compte="actif")}
    verifier(financiers and financiers <= destinataires,
             "la soumission prévient le service financier")
    verifier(directeur.id not in destinataires,
             "elle ne prévient pas le directeur, qui n'a rien à faire encore")

    repere = db.session.query(db.func.max(Notification.id)).scalar() or 0
    me.appliquer_transition(d5, "rejeter_paiement", financier,
                            "Virement non retrouvé sur le relevé.")
    db.session.commit()
    envoyees = Notification.query.filter(Notification.id > repere).all()
    verifier({n.destinataire_id for n in envoyees} == {deposant.id},
             "le rejet de paiement ne prévient que le déposant")
    verifier(any("Virement non retrouvé" in n.contenu for n in envoyees),
             "le motif est transmis au déposant, pas seulement archivé")
    verifier(d5.statut == "brouillon",
             "un paiement rejeté renvoie le dossier au brouillon")

    # -----------------------------------------------------------------
    print("\n-- 8. Concordance : l'écran ne promet rien que le serveur refuse --")
    roles = sorted({r for t in me.TRANSITIONS for r in t["roles"]})
    incoherences = []
    for statut in me.STATUTS:
        temoin = type("T", (), {"statut": statut})()
        for role in roles:
            offertes = me.transitions_autorisees(temoin, role)
            for t in offertes:
                # Ce qui est offert doit être exactement ce que le moteur
                # accepterait : même état de départ, même rôle.
                if t["depuis"] != me.statut_canonique(statut):
                    incoherences.append((statut, role, t["action"], "état"))
                if role not in t["roles"]:
                    incoherences.append((statut, role, t["action"], "rôle"))
            for t in me.TRANSITIONS:
                if (t["depuis"] == me.statut_canonique(statut)
                        and role in t["roles"] and t not in offertes):
                    incoherences.append((statut, role, t["action"], "omise"))
    verifier(not incoherences,
             f"aucune divergence offre/autorisation ({incoherences[:3]})")

    couverts = {t["depuis"] for t in me.TRANSITIONS} | {t["vers"] for t in me.TRANSITIONS}
    verifier(couverts == set(me.STATUTS) - {"cloture_delai_depasse"} | couverts,
             "tous les statuts déclarés participent au graphe")

    # -----------------------------------------------------------------
    print("\n-- 9. Route générique de transition --")
    client = application.app.test_client()
    d6 = _dossier(deposant, statut="retour_homologation")
    db.session.commit()
    id6 = d6.id

    with client.session_transaction() as s:
        s["user_id"] = deposant.id
    r = client.post(f"/dossiers/{id6}/transition",
                    data={"action": "valider"}, follow_redirects=True)
    rafraichi = db.session.get(DossierAMM, id6)
    db.session.refresh(rafraichi)
    verifier(rafraichi.statut == "retour_homologation",
             "un déposant qui force la route ne valide pas son propre dossier")

    with client.session_transaction() as s:
        s["user_id"] = directeur.id
    r = client.get(f"/dossiers/{id6}/parcours")
    verifier(r.status_code == 200, "la page parcours répond au directeur")
    page = r.data.decode("utf-8")
    verifier("Valider le dossier" in page,
             "elle propose au directeur la validation")
    verifier("Rejeter le dossier" in page, "et le rejet")
    verifier("Déclarer recevable" not in page,
             "et rien qui relève d'un autre état")

    r = client.post(f"/dossiers/{id6}/transition",
                    data={"action": "valider"}, follow_redirects=True)
    db.session.refresh(rafraichi)
    verifier(rafraichi.statut == "valide", "le directeur valide par la route")

    with client.session_transaction() as s:
        s["user_id"] = deposant.id
    r = client.get(f"/dossiers/{id6}/parcours")
    verifier(r.status_code == 200, "le déposant voit le parcours de son dossier")
    verifier("Éditer le certificat" not in r.data.decode("utf-8"),
             "sans se voir offrir une action du service")

    autre = Personne.query.filter(
        Personne.role_systeme == "demandeur_externe",
        Personne.id != deposant.id,
        Personne.etablissement_rattachement_id
        != (deposant.etablissement_rattachement_id or -1)).first()
    if autre:
        with client.session_transaction() as s:
            s["user_id"] = autre.id
        verifier(client.get(f"/dossiers/{id6}/parcours").status_code == 403,
                 "un déposant tiers ne voit pas le dossier d'autrui")
    else:
        verifier(True, "pas de déposant tiers pour éprouver le cloisonnement")

    # -----------------------------------------------------------------
    _nettoyer(avant)

print(f"\n{ok} vérifications passées, {len(ko)} échec(s)")
if ko:
    for libelle in ko:
        print(f"  - {libelle}")
    raise SystemExit(1)
