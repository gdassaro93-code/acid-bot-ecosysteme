# -*- coding: utf-8 -*-
# =====================================================
#  💰 BUDGET DE RISQUE COMMUN — «…»
#  (demande patron 21/08, après le compte vidé)
#
#  LE PROBLÈME, mesuré sur 20 jours :
#    LE CERVEAU X € · MANUEL X € · EA ACID IA X €  →  compte à 0.
#  Chacun respectait SA limite. Personne ne voyait le TOTAL. Trois paris de
#  10% pris en même temps, ce n'est pas 10% de risque : c'est 30%.
#
#  LA SOLUTION : une enveloppe UNIQUE, lue et écrite par les trois bots.
#  Avant d'ouvrir, chacun demande «…». Quand l'enveloppe
#  est vide, tout le monde attend — même celui qui n'a rien perdu.
#
#  Le patron a choisi 10% par trade (21/08, en connaissance de cause) : c'est
#  l'enveloppe globale qui empêche ce 10% de devenir 30%.
# =====================================================
import json
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FICHIER = HERE / "budget_risque.json"

# ─── Les curseurs ────────────────────────────────────────────────────────
# 🪃 04/09 — LE FREIN LE PLUS BÊTE DE TOUS (patron : «…»).
# 10% par trade contre une enveloppe de 25% = 2 POSITIONS MAXIMUM sur tout
# l'écosystème. Or le patron ouvre 3 jambes (TP1/TP2/TP3) par idée : la 3e
# était refusée SYSTÉMATIQUEMENT depuis le 21/08. Son constat du 27/07 —
# «…» — avait la même cause, jamais vue.
# À 2% : 25/2 = 12 positions, soit 4 symboles x 3 jambes. Ça tombe juste.
# 🪃 04/09 — LE FREIN LE PLUS BÊTE DE TOUS.
# 10% par trade contre une enveloppe de 25% = 2 POSITIONS MAXIMUM sur tout
# l'écosystème. Or le patron ouvre 3 jambes (TP1/TP2/TP3) par idée : la 3e
# était refusée SYSTÉMATIQUEMENT. Son constat du 27/07 — «…
# …» — avait déjà cette cause, jamais vue.
#
# Décision patron du 04/09 : «…
# …
# …».
#
# ⚠️ CE QUE ÇA VEUT DIRE, ÉCRIT NOIR SUR BLANC : les 3 jambes partagent la
# MÊME entrée et le MÊME SL (seuls les TP diffèrent). Ce ne sont pas 3
# risques indépendants : si le SL saute, les 3 sautent ensemble.
#     10% par jambe x 3 jambes = 30% du capital sur UN SEUL mouvement.
# L'enveloppe est donc calée sur le kill-switch de l'EA (40%) : on ne peut
# pas s'autoriser à risquer plus que le seuil auquel on coupe tout. Ça fait
# 4 positions ouvertes au maximum — une idée complète en 3 jambes, plus une.
# Quand le patron passera à 5%, l'enveloppe rendra 8 positions sans rien
# toucher d'autre.
RISQUE_PAR_TRADE_PCT = 1.0    # version publique : réglage de base prudent (voir README.txt)
ENVELOPPE_TOTALE_PCT = 5.0    # version publique : enveloppe commune prudente (voir README.txt)
PERTE_JOUR_MAX_PCT   = 5.0    # au-delà, plus personne n'ouvre jusqu'à demain (version publique : 5 %)
# 💶 25/09 (patron : «…
# …», puis «…»). Mesuré sur ses 830 trades du 14 au 25/09 : un stop
# à X €/jour aurait laissé le compte à X € au lieu de X € (X €), en
# arrêtant 4 journées sur 7. Les -20 % ci-dessus n'ont JAMAIS été atteints (sa
# pire journée : X €, soit 9 %). Le compteur repart à zéro chaque matin :
# même avec X € sur le compte, les bots tradent — ils ont juste le droit de
# perdre X € dans la journée, pas plus.
PERTE_JOUR_MAX_EUR   = 0.0    # 0 = pas de plafond en euros : seul le plancher en % ci-dessus s'applique
OBJECTIF_JOUR_PCT    = 0.0    # >0 : on arrête d'ouvrir quand l'objectif du jour est pris
# 🎯 25/09 (patron : «…»).
# Ce que ses bots ont VRAIMENT fait du 14 au 25/09 : ils ont gagné, puis tout rendu.
#     14/09 : X € en main → X € à la fin      (rendu X €)
#     17/09 : X € en main → X € à la fin     (rendu X €)
#     16/09 : X € en main → X € à la fin     (rendu X €)
# Simulé sur ces mêmes trades, en bouclant la journée dès l'objectif atteint :
#     X € →X € de solde final · X € →X € · X € →X € · sans →X €
# (la réalité :X €). Donc X €, et il reprend le lendemain matin.
# ⚠️ mesuré sur 7 journées seulement : à revoir quand on en aura 30.
# 🔁 25/09, dans la foulée : «…
# …». Objectif JOURNALIER donc désactivé : la cible de
#X € se joue trade par trade (voir OBJECTIF_TRADE_EUR dans ia_watchdog).
OBJECTIF_JOUR_EUR    = 0.0    # 0 = désactivé (on retombe sur le pourcentage)

# 🎯 25/09 — LE PATRON : «…
# …». Ce n'est PAS un plafond de gain : c'est la distance
# minimale que doit viser un objectif. Un TP plus court que ça ne vaut pas le
# risque pris. MESURÉ le 25/09 au lot minimum réel,X € valent :
#     XAUUSD+ 11,37 $ = 0,7× ATR H1     NAS100  114 pts = 1,5×
#     CL-OIL   1,14 $ = 1,3×            BTCUSD  1 137 $ = 2,0×
# Donc sur 3 des 4 marchés,X € demandent de TENIR plus d'une heure de
# mouvement : c'est un objectif de position, pas de scalp. Au-delà de
# OBJECTIF_TRADE_MAX_ATR, on n'étire pas : on laisse l'objectif d'origine et on
# le dit, plutôt que de poser une cible que le marché n'atteint jamais.
OBJECTIF_TRADE_EUR     = 10.0
OBJECTIF_TRADE_MAX_ATR = 4.0

BOTS = ("oeil", "mammouth", "ea", "manuel")


def _lire() -> dict:
    # 🩹 08/09 — NE JAMAIS CONFONDRE «…» ET «…».
    # Avant : toute exception (JSON tronqué pendant l'écriture de l'autre processus,
    # disque occupé) donnait d = {}, donc «…», donc la journée était
    # reconstruite avec solde_debut = 0,0 — et un solde_debut nul DÉSACTIVE tous les
    # garde-fous du jour (peut_ouvrir et kill_switch_hit renvoient False sur 0).
    # Silencieusement, jusqu'au lendemain.
    d, lecture_ok = {}, False
    for _f in (FICHIER, FICHIER.with_suffix(FICHIER.suffix + ".bak")):
        try:
            d = json.loads(_f.read_text(encoding="utf-8"))
            lecture_ok = True
            break
        except FileNotFoundError:
            continue
        except Exception:
            continue
    if not lecture_ok and FICHIER.exists():
        # le fichier EXISTE mais ne se lit pas : on ne détruit pas la référence,
        # on rend une journée «…» que l'appelant ré-ancrera.
        try:
            import logging
            logging.getLogger(__name__).warning(
                "budget_risque : fichier illisible — référence du jour NON réinitialisée")
        except Exception:
            pass
    jour = time.strftime("%Y-%m-%d")
    if d.get("jour") != jour:                 # remise à zéro quotidienne
        # 🩹 28/08 — BUG QUI A COÛTÉ LE COMPTE. «…» n'était JAMAIS
        # écrit : au changement de jour, solde_debut retombait donc à 0, et la
        # vraie référence n'était prise qu'au PREMIER APPEL de peut_ouvrir —
        # c.-à-d. potentiellement après plusieurs pertes. Constat du 28/08 :
        # le fichier disait solde_debut =X € alors que la journée avait
        # commencé à ~X €. Le plancher -20% s'est donc calculé sur X € au
        # lieu de X € : il n'a mordu qu'à X €, bien trop tard.
        d = {"jour": jour, "solde_debut": d.get("solde_fin") or 0.0, "realise": 0.0,
             "gele": False, "raison": ""}
    return d


def ajuster_depots(mt5):
    """💰 04/09 — BUG DES «…».
    Constat du jour : le compte a fini hier a X €, le patron a recharge X €
    a 10h. Mais solde_debut avait ete fige a X € au changement de jour. Le
    plancher de -20% se calculait donc sur X € : le budget gelait TOUT des
    9 CENTIMES de perte. Le bot paraissait «…
    …» alors qu'il etait simplement a court de budget autorise.

    On lit les mouvements de CAISSE du jour (DEAL_TYPE_BALANCE : depots et
    retraits, jamais des trades) et on les repercute sur la reference. Un
    depot n'est pas un gain : il deplace le point de depart, il ne remplit
    pas l'objectif du jour.
    """
    try:
        from datetime import datetime, timedelta
        d = _lire()
        deja = float(d.get("caisse_vue") or 0.0)
        debut_jour = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        mouv = 0.0
        for x in (mt5.history_deals_get(debut_jour, datetime.now() + timedelta(hours=4)) or []):
            if getattr(x, "type", None) == mt5.DEAL_TYPE_BALANCE:
                mouv += float(x.profit or 0.0)
        if abs(mouv - deja) < 0.01:
            return 0.0
        delta = mouv - deja
        d["solde_debut"] = float(d.get("solde_debut") or 0.0) + delta
        d["caisse_vue"] = mouv
        # un depot annule un gel devenu absurde (le plancher etait calcule
        # sur l'ancienne reference, forcement trop basse)
        if delta > 0 and d.get("gele"):
            d["gele"] = False
            d["raison"] = ""
        _ecrire(d)
        return delta
    except Exception:
        return 0.0


def ancrer_reference(mt5):
    """📌 À appeler au DÉMARRAGE de chaque bot : fige le solde de référence du
    jour AVANT le premier trade. Sans ça, la référence est prise au premier
    ordre — donc après d'éventuelles pertes, et le plancher protège trop tard."""
    try:
        a = mt5.account_info()
        if not a or a.balance <= 0:
            return
        d = _lire()
        if not d.get("solde_debut"):
            d["solde_debut"] = a.balance
            d["solde_fin"] = a.balance
            _ecrire(d)
        ajuster_depots(mt5)      # 💰 un rechargement deplace la reference
    except Exception:
        pass


def _ecrire(d: dict):
    # 🩹 08/09 — ÉCRITURE ATOMIQUE : LE CERVEAU et MAMMOUTH lisent tous les deux ce
    # fichier ; un write_text direct laisse une fenêtre où le lecteur voit un JSON
    # tronqué. On écrit à côté puis on remplace d'un bloc, et on garde une copie.
    try:
        _tmp = FICHIER.with_suffix(FICHIER.suffix + ".tmp")
        _tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            if FICHIER.exists():
                shutil.copyfile(FICHIER, FICHIER.with_suffix(FICHIER.suffix + ".bak"))
        except Exception:
            pass
        os.replace(_tmp, FICHIER)
    except Exception:
        pass


def risque_ouvert(mt5) -> float:
    """Ce que TOUTES les positions ouvertes perdraient si tous les stops sautaient.
    C'est le seul chiffre honnête : la somme des risques réels, pas des intentions."""
    total = 0.0
    for p in (mt5.positions_get() or []):
        if not p.sl:
            # position nue : on compte son flottant négatif, faute de mieux
            total += abs(min(p.profit, 0.0))
            continue
        try:
            perte = mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY if p.type == 0 else mt5.ORDER_TYPE_SELL,
                p.symbol, p.volume, p.price_open, p.sl)
            total += abs(min(perte or 0.0, 0.0))
        except Exception:
            pass
    return total


def peut_ouvrir(mt5, qui: str, risque_eur: float, source: str = None) -> tuple:
    """LA question que chaque bot pose avant d'ouvrir.
    Retourne (autorisé: bool, raison: str).
    08/09 : `source` = d'où vient l'idée. La stratégie validée sur 2 ans a droit à
    9 % ; tout le reste (scalp IA, idées du cerveau, reprises) à 3 %. Avant, les
    deux tapaient au même plafond alors qu'une seule a fait ses preuves."""
    ajuster_depots(mt5)      # 💰 04/09 : un depot recale le plancher du jour
    a = mt5.account_info()
    if not a or a.balance <= 0:
        return False, "compte indisponible"
    d = _lire()
    if not d.get("solde_debut"):
        d["solde_debut"] = a.balance
        _ecrire(d)

    solde = a.balance
    debut = d.get("solde_debut") or solde
    if d.get("solde_fin") != solde:           # 28/08 : la clôture du jour, tenue à jour
        d["solde_fin"] = solde
        _ecrire(d)

    # 1) le trade lui-même respecte-t-il le curseur ?
    try:
        import paliers as _pal
        _pct = _pal.risque_pct(source)
    except Exception:
        _pct = RISQUE_PAR_TRADE_PCT
    plafond_trade = solde * _pct / 100.0
    if risque_eur > plafond_trade * 1.001:
        return False, (f"ce trade risque {risque_eur:.2f}€ > {_pct:g}% "
                       f"du solde ({plafond_trade:.2f}€) — source « {source or 'non validée'} »")

    # 2) l'enveloppe COMMUNE — le cœur du dispositif
    deja = risque_ouvert(mt5)
    enveloppe = solde * ENVELOPPE_TOTALE_PCT / 100.0
    if deja + risque_eur > enveloppe:
        return False, (f"enveloppe commune pleine : {deja:.2f}€ déjà en risque "
                       f"(tous bots) + {risque_eur:.2f}€ > {enveloppe:.2f}€ "
                       f"({ENVELOPPE_TOTALE_PCT:g}% du solde). "
                       f"Quelqu'un doit fermer avant que tu ouvres.")

    # 3) la journée est-elle déjà finie ?
    perte_jour = debut - solde
    _plafond_jour = debut * PERTE_JOUR_MAX_PCT / 100.0
    if PERTE_JOUR_MAX_EUR > 0:
        _plafond_jour = min(_plafond_jour, PERTE_JOUR_MAX_EUR)
    if perte_jour > 0 and perte_jour >= _plafond_jour:
        return False, (f"perte du jour {perte_jour:.2f}€ = "
                       f"{100 * perte_jour / debut:.1f}% — plancher atteint "
                       f"({_plafond_jour:.2f}€), on arrête TOUT jusqu'à demain")
    _objectif = debut * OBJECTIF_JOUR_PCT / 100.0 if OBJECTIF_JOUR_PCT > 0 else 0.0
    if OBJECTIF_JOUR_EUR > 0:
        _objectif = min(_objectif, OBJECTIF_JOUR_EUR) if _objectif > 0 else OBJECTIF_JOUR_EUR
    if _objectif > 0:
        gain_jour = solde - debut
        if gain_jour >= _objectif:
            return False, (f"🎯 objectif du jour atteint (+{gain_jour:.2f}€ ≥ "
                           f"{_objectif:.2f}€) — on garde les gains, on reprend demain")
    return True, ""


def etat(mt5) -> str:
    """Résumé lisible pour Telegram / terminal."""
    a = mt5.account_info()
    if not a:
        return "budget : compte indisponible"
    d = _lire()
    debut = d.get("solde_debut") or a.balance
    deja = risque_ouvert(mt5)
    env = a.balance * ENVELOPPE_TOTALE_PCT / 100.0
    jour = a.balance - debut
    pct = (100 * deja / env) if env else 0
    barre = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
    return (f"💰 BUDGET DE RISQUE COMMUN\n"
            f"  solde {a.balance:.2f}€ (début de journée {debut:.2f}€, "
            f"{jour:+.2f}€ aujourd'hui)\n"
            f"  risque ouvert : {deja:.2f}€ / {env:.2f}€  {barre} {pct:.0f}%\n"
            f"  par trade : {RISQUE_PAR_TRADE_PCT:g}% max "
            f"({a.balance * RISQUE_PAR_TRADE_PCT / 100:.2f}€)\n"
            f"  plancher du jour : -{min(debut * PERTE_JOUR_MAX_PCT / 100, PERTE_JOUR_MAX_EUR or 1e9):.2f}€ "
            f"(le plus serré entre -{PERTE_JOUR_MAX_PCT:g}% et -{PERTE_JOUR_MAX_EUR:g}€)")


# =====================================================
# 📏 CE QUE LE CAPITAL AUTORISE (27/08 — demande patron)
#
# Le bot a annoncé sur Telegram : «…
# …». Sur un compte de X € :
#     3 × 0.20 = 0.60 lot → si le SL saute : X € = 442% DU COMPTE.
#     (il n'aurait même pas eu la marge :X € requis pour X € disponibles)
# Le patron : «…
# …».
#
# Le défaut : le solde était donné au cerveau noyé dans un JSON
# («…»). Il le voyait sans jamais le traduire en lots.
#
# ⚠️ ON NE RABOTE RIEN APRÈS COUP (règle du patron : «…
# …»). On lui DONNE simplement le chiffre juste avant qu'il décide,
# pour qu'il raisonne correctement du premier coup.
# =====================================================

def lots_autorises(mt5, risque_pct=None, symboles=None):
    """Pour chaque symbole : le lot que le capital autorise vraiment.
    Retourne (texte prêt à injecter dans un prompt, {symbole: lot_max})."""
    risque_pct = risque_pct if risque_pct is not None else RISQUE_PAR_TRADE_PCT
    a = mt5.account_info()
    if not a or a.balance <= 0:
        return "💰 CAPITAL : compte indisponible.", {}
    cap = a.balance
    budget = cap * risque_pct / 100.0
    # 25/09 (patron : «…») : plus de lots affichés pour
    # des marchés où X € par trade est hors de portée.
    symboles = symboles or ["XAUUSD+", "NAS100", "CL-OIL", "BTCUSD"]
    lignes, table, chers = [], {}, []
    for s in symboles:
        try:
            i = mt5.symbol_info(s)
            r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 20)
            if not i or r is None or len(r) < 15:
                continue
            atr = sum(float(x["high"]) - float(x["low"]) for x in r[-14:]) / 14
            val_pt = i.trade_tick_value / i.trade_tick_size    # € par unité de prix, 1 lot
            if atr <= 0 or val_pt <= 0:
                continue
            vmin = i.volume_min or 0.01
            pas = i.volume_step or 0.01
            lot_max = int((budget / (atr * val_pt)) / pas) * pas
            cout_mini = atr * val_pt * vmin
            table[s] = round(max(lot_max, 0.0), 2)
            if lot_max < vmin:
                chers.append(f"{s} ({vmin:g} lot = {cout_mini:.2f}€ de risque, "
                             f"soit {100 * cout_mini / cap:.0f}% du compte)")
            else:
                lignes.append(f"  {s:9} jusqu'à {lot_max:.2f} lot   "
                              f"(stop 1×ATR = {atr:.2f} pts = "
                              f"{atr * val_pt * lot_max:.2f}€ en jeu)")
        except Exception:
            pass
    txt = [f"💰 TON CAPITAL RÉEL : {cap:.2f}€. Un trade engage au maximum "
           f"{risque_pct:g}% = {budget:.2f}€.",
           "📏 CE QUE ÇA REPRÉSENTE EN LOTS (déjà calculé sur TON solde — sers-t'en "
           "au lieu d'estimer, et n'annonce jamais un lot que le compte ne peut pas "
           "porter) :"]
    txt += lignes or ["  (aucun symbole calculable)"]
    if chers:
        txt.append("⚠️ TRÈS LOURDS pour ce capital — le lot minimum du broker y engage "
                   "déjà une grosse part du compte : " + " · ".join(chers))
    txt.append(f"📌 Un petit capital n'est PAS une raison de grossir les positions pour "
               f"« rattraper ». Avec {cap:.2f}€ on joue {budget:.2f}€ par trade. "
               f"Et on ne dit pas « je pose du lourd » avec ce solde.")
    return "\n".join(txt), table


# =====================================================
# 🏦 RÉEL OU DÉMO ? (02/09 — question du patron : «…
# …»)
#
# Réponse d'alors : NON. Le code ne lisait jamais account_info().trade_mode —
# les deux seules occurrences de «…» concernaient les SYMBOLES.
# Démo et réel étaient traités à l'identique.
#
# Le danger n'est pas de croire réel un compte démo (on serait juste trop
# prudent). C'est l'inverse : tester en démo, rebasculer en réel, et que
# personne dans la chaîne ne s'en aperçoive. MT5 le dit — il suffisait de
# le demander.
# =====================================================
TYPE_COMPTE = {0: "DÉMO", 1: "CONCOURS", 2: "RÉEL"}


def type_compte(mt5) -> tuple:
    """Retourne (libellé, est_reel). Prudent par défaut : si on ne sait pas,
    on considère que c'est RÉEL — mieux vaut trop de précautions."""
    try:
        a = mt5.account_info()
        if not a:
            return "INCONNU", True
        m = getattr(a, "trade_mode", 2)
        return TYPE_COMPTE.get(m, "INCONNU"), (m != 0)
    except Exception:
        return "INCONNU", True


# ⛔⛔ RÈGLE ABSOLUE, POSÉE PAR LE PATRON LE 02/09 :
#     «…
#       …»
#     «…»
#
# Il a raison, et j'allais faire l'erreur. J'étais sur le point d'injecter
# «…» dans le prompt du cerveau.
# Un bot plus prudent en réel qu'en démo rend TOUS les tests en démo
# inutilisables : on mesurerait un comportement qu'on n'aura jamais en vrai.
#
# DONC : ces fonctions servent UNIQUEMENT à AFFICHER (contrôle avant vol,
# terminal, Telegram). Elles ne doivent JAMAIS entrer dans le prompt du
# cerveau, ni moduler un seuil, un lot, une confiance ou un garde-fou.
# Le bot décide pareil partout. C'est ce qui rend le démo utile.

# 🧹 04/09 — bandeau_compte() retirée : jamais appelée nulle part, et faisait
# doublon avec _capital_context() d'ia_watchdog (l.6264) qui, lui, est bien
# injecté dans le prompt du cerveau — c'est celui-là qui répond à la demande
# du patron «…».
# type_compte() est conservée : elle sert à l'affichage du contrôle avant vol.

