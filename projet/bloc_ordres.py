# -*- coding: utf-8 -*-
# =====================================================
#  🧱 BLOC D'ORDRES — la figure du patron, branchée EN RÉEL à sa demande
#
#  SA RÈGLE, mot pour mot (08/09) :
#    «…
#      …» · «…»
#    «…»
#
#  CE QUE MES MESURES DISENT, et il le sait :
#    864 configurations testées sur 8 mois de M5 → 0 retenue au protocole.
#    Le sens INVERSÉ gagnait plus (+4427 R contre +2445), et l'avantage
#    disparaissait en entrant une bougie plus tard (−754 R).
#  CE QUI RELATIVISE CE VERDICT : mes trois moteurs de la journée avaient chacun
#  un bug (miroir faux, spread compté deux fois, stops impossibles chez le broker).
#  Le patron a donc raison sur un point : un backtest qui s'est trompé trois fois
#  ne suffit pas à clore le débat. Le marché tranchera.
#
#  LE BLOC EST CELUI QUE SON EA DESSINE (ACID IA V1.mq5, DrawVision l.4200) :
#    baissier = une bougie HAUSSIÈRE dont le haut est suivi d'une chute d'au moins
#    1,2×ATR en 3 bougies, sommet jamais retouché depuis. On VEND le retour dedans.
#    haussier = le miroir exact. On ACHÈTE le retour dedans.
#
#  SÉCURITÉS : tout passe par execute(), donc le palier, le budget, la règle du
#  spread, le plafond de lot et l'interdiction d'empiler s'appliquent comme au
#  reste. Une position par marché. Aucune exception n'a été taillée pour lui.
# =====================================================
import json
import time
from pathlib import Path

ACTIF = True
MARCHES = ["BTCUSD", "NAS100", "SP500"]      # ses 3 meilleurs marchés mesurés
TIMEFRAME_NOM = "M5"
IB = 3                    # bougies de la chute qui crée le bloc
SEUIL_ATR = 1.2           # l'impulsion doit valoir au moins 1,2 ATR
AGE_MAX_BARRES = 60       # au-delà, le bloc est périmé
MARGE_SL_ATR = 0.3        # le stop se pose au-delà de la zone
TP_PIPS = 100             # «…» (sa règle)
DUREE_MAX_MIN = 2         # ⏱️ «…»
                          # (patron, 08/09). La cible de 100 pips reste la sortie haute,
                          # mais on ne DORT PAS dessus : au bout de 2 min on solde, gagnant
                          # ou perdant. C'est sa règle depuis le 04/09 : «…
                          # …».
CONFIANCE = 80
MIN_BARRES = 120

ETAT = Path(__file__).resolve().parent / "bloc_ordres_etat.json"
_SEC_TF = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}


def _lire():
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception:
        return {"dernier": {}, "en_position": {}, "signaux": 0, "ouverts": 0, "refuses": 0}


def _ecrire(d):
    try:
        tmp = ETAT.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(ETAT)
    except Exception:
        pass


def _atr(H, L, C, p=14):
    tr = [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
          for i in range(1, len(C))]
    return sum(tr[-p:]) / min(p, len(tr)) if tr else 0.0


def analyser(mt5, symbole, pip_fn=None):
    """Le bloc le plus récent NON touché, et le prix est-il en train d'y revenir ?
    Renvoie un dict prêt pour execute(), ou None."""
    tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME_NOM)
    r = mt5.copy_rates_from_pos(symbole, tf, 0, MIN_BARRES)
    if r is None or len(r) < 40:
        return None
    r = r[:-1]                                   # bougies CLÔTURÉES uniquement
    O = [float(x["open"]) for x in r]
    H = [float(x["high"]) for x in r]
    L = [float(x["low"]) for x in r]
    C = [float(x["close"]) for x in r]
    n = len(C)
    a = _atr(H, L, C)
    if a <= 0:
        return None
    tick = mt5.symbol_info_tick(symbole)
    info = mt5.symbol_info(symbole)
    if not tick or not info:
        return None
    pip = pip_fn(symbole) if pip_fn else info.point

    # on cherche le bloc le plus RÉCENT encore vierge, dans la fenêtre d'âge
    for i in range(n - IB - 2, max(0, n - AGE_MAX_BARRES) - 1, -1):
        conf = i + IB
        if conf >= n - 1:
            continue
        zh, zl = H[i], L[i]
        if zh <= zl:
            continue
        # baissier : bougie haussière puis chute d'au moins SEUIL_ATR en IB bougies
        baissier = C[i] > O[i] and (H[i] - C[conf]) >= SEUIL_ATR * a
        haussier = C[i] < O[i] and (C[conf] - L[i]) >= SEUIL_ATR * a
        if not (baissier or haussier):
            continue
        apres = range(conf + 1, n)
        if baissier:
            if any(H[j] >= zh for j in apres):    # sommet repris : bloc mort
                continue
            if tick.ask < zl:                     # le prix n'est pas encore revenu
                return None
            sens, entree = -1, tick.bid
            sl = zh + MARGE_SL_ATR * a
            tp = entree - TP_PIPS * pip
        else:
            if any(L[j] <= zl for j in apres):
                continue
            if tick.bid > zh:
                return None
            sens, entree = 1, tick.ask
            sl = zl - MARGE_SL_ATR * a
            tp = entree + TP_PIPS * pip
        risque = abs(entree - sl)
        if risque <= 0:
            return None
        return {"symbol": symbole, "sens": "SELL" if sens < 0 else "BUY",
                "prix": entree, "sl": round(sl, info.digits), "tp": round(tp, info.digits),
                "sl_pips": round(risque / pip, 1), "tp_pips": float(TP_PIPS),
                "zone": (round(zl, info.digits), round(zh, info.digits)),
                "bougie": int(r[i]["time"])}
    return None


def cycle(mt5, execute, log=None, telegram=None, positions_ouvertes=None, pip_fn=None):
    """Appelé depuis la boucle rapide de L'ŒIL. Une évaluation par bougie clôturée
    et par marché, une position «…» à la fois par marché."""
    if not ACTIF:
        return 0
    e = _lire()
    e.setdefault("dernier", {})
    e.setdefault("en_position", {})
    n = 0
    # ⏱️ D'ABORD : on solde ce qui a dépassé son temps. Une capture de bougie qui
    # dure dix minutes n'est plus une capture, c'est une position oubliée.
    try:
        for p in (positions_ouvertes or []):
            if "BLOC" not in (p.comment or "").upper():
                continue
            age = (time.time() - p.time) / 60.0
            if age < DUREE_MAX_MIN:
                continue
            t = mt5.symbol_info_tick(p.symbol)
            if not t:
                continue
            r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                                "position": p.ticket, "volume": p.volume,
                                "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                                "price": t.bid if p.type == 0 else t.ask,
                                "deviation": 20, "magic": p.magic,
                                "comment": "BLOC_temps",
                                "type_filling": mt5.ORDER_FILLING_IOC})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                e["en_position"][p.symbol] = False
                if log:
                    log.info("BLOC %s solde a %.1f min (%+.2f EUR) - la bougie est "
                             "capturee, on ne dort pas dessus", p.symbol, age, p.profit)
                if telegram:
                    telegram("BLOC " + p.symbol + " ferme a " + format(age, ".0f")
                             + " min -> " + format(p.profit, "+.2f") + " EUR"
                             + chr(10) + "   (ta regle : on capture la bougie et on sort)")
    except Exception as ex:
        if log:
            log.debug("bloc_ordres expiration : %s", ex)

    tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME_NOM)
    duree = _SEC_TF.get(TIMEFRAME_NOM, 300)
    for sym in MARCHES:
        try:
            if positions_ouvertes and any(p.symbol == sym and "BLOC" in (p.comment or "").upper()
                                          for p in positions_ouvertes):
                e["en_position"][sym] = True
                continue
            r = mt5.copy_rates_from_pos(sym, tf, 0, 2)
            if r is None or len(r) < 2:
                continue
            derniere = int(r[0]["time"])
            if e["en_position"].get(sym):        # on sort de position : on consomme la bougie
                e["dernier"][sym] = derniere
                e["en_position"][sym] = False
                continue
            if e["dernier"].get(sym) == derniere:
                continue
            e["dernier"][sym] = derniere
            tick = mt5.symbol_info_tick(sym)
            if tick is None or (tick.time - (derniere + duree)) > 60:
                continue                          # bougie périmée : on ne rejoue pas le passé
            s = analyser(mt5, sym, pip_fn)
            if not s:
                continue
            e["signaux"] = e.get("signaux", 0) + 1
            if log:
                log.info(f"🧱 BLOC {sym} {s['sens']} : zone {s['zone']} · "
                         f"SL {s['sl_pips']}p · TP {TP_PIPS}p")
            execute({"type": s["sens"], "cible": "MT5", "symbol": sym,
                     "sl_pips": s["sl_pips"], "tp_pips": s["tp_pips"],
                     "confiance": CONFIANCE, "tag": "bloc",
                     "raison": (f"BLOC D'ORDRES {s['sens']} : retour dans la zone "
                                f"{s['zone'][0]}-{s['zone'][1]}, TP {TP_PIPS} pips")}, False)
            ouvert = any("BLOC" in (p.comment or "").upper()
                         for p in (mt5.positions_get(symbol=sym) or []))
            if not ouvert:
                e["refuses"] = e.get("refuses", 0) + 1
                if log:
                    log.info(f"🧱 BLOC {sym} : signal vu mais refusé par les garde-fous")
                continue
            e["en_position"][sym] = True
            e["ouverts"] = e.get("ouverts", 0) + 1
            n += 1
            if telegram:
                telegram(f"🧱 BLOC D'ORDRES — {sym} {s['sens']} @ {s['prix']}\n"
                         f"   zone {s['zone'][0]} → {s['zone'][1]} · SL {s['sl']} · TP {s['tp']}\n"
                         f"   (test EN RÉEL demandé par le patron — mon backtest disait non,\n"
                         f"    on tranche sur 20-30 signaux réels)")
        except Exception as ex:
            if log:
                log.debug(f"bloc_ordres {sym} : {ex}")
    _ecrire(e)
    return n


def contexte() -> str:
    e = _lire()
    return (f"🧱 BLOC D'ORDRES : {'ACTIF' if ACTIF else 'DORMANT'} · "
            f"{e.get('signaux', 0)} signaux · {e.get('ouverts', 0)} ouverts · "
            f"{e.get('refuses', 0)} refusés · TP {TP_PIPS} pips · marchés {', '.join(MARCHES)}\n"
            f"   (test EN RÉEL : le backtest le rejetait, le patron a demandé l'épreuve du marché)")
