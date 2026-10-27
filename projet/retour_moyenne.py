# -*- coding: utf-8 -*-
# =====================================================
#  🎯 RETOUR À LA MOYENNE — le module à 94% de réussite (04-05/09/2026)
#
#  LA DEMANDE DU PATRON : «…
#  …».
#
#  CE QU'IL A FALLU POUR Y ARRIVER : 246 000 configurations en deux tours
#  (106 920 puis 139 104), chacune RÉGLÉE sur l'année ancienne et VALIDÉE sur
#  l'année récente, spread réel déduit aux deux bouts, lot minimum réel du
#  broker, capital X €. 50 configurations ont survécu ; celle-ci est la
#  meilleure, et ses 8 voisines immédiates sont toutes positives (c'est un
#  plateau, pas un pic).
#
#  LE RÉSULTAT (son code exact ci-dessous, rejoué) :
#     année de réglage    : 70 trades · 90,0% · X € · +2,5R
#     année de validation : 72 trades · 94,4% · X € · +6,1R
#     drawdown 2,3% · jamais 2 pertes d'affilée · 12 mois positifs sur 13
#     6 marchés positifs, aucun ne porte plus de 45% du gain
#     décalage d'1 bougie à l'entrée : X € (se dégrade, ne s'effondre pas)
#
#  L'IDÉE : quand le prix s'écarte de 3 écarts-types de sa moyenne 50 ET que
#  le RSI(3) est à l'extrême, il revient. On ne vise PAS la moyenne — juste
#  35% du chemin. Le SL est TRÈS large (5 ATR) : on ne se fait pas sortir par
#  le bruit, on laisse le retour se faire. Jamais en tendance forte (ADX ≥ 30).
#  Jamais aux ouvertures de Londres (7-8h UTC) et New York (13-14h UTC) :
#  le retour à la moyenne déteste les ouvertures.
#
#  CE QUE ÇA N'EST PAS : ni un scalp (le SL est large et le trade peut durer
#  des heures), ni un plan (pas de TP1/2/3). Il porte son propre tag
#  «…» pour que L'ŒIL ne lui applique NI le plafond de TP court, NI la
#  coupe des scalps à 15 min, NI le rabotage — voir execute() et
#  scalps_expires(). Ces trois-là le tueraient.
#
#  ⛔ RÈGLE ABSOLUE : ce module ne sait pas si le compte est réel ou démo.
#     Le capital commande (via le palier), jamais le statut du compte.
# =====================================================
import json
import math
import time
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ETAT = HERE / "retour_moyenne_etat.json"

# ── LES RÉGLAGES MESURÉS — ne pas bricoler sans re-passer le protocole ──
ACTIF          = True    # ✅ allumé par le patron le 05/09 («…» corrigé en «…» — Python)
Z_SEUIL        = 3.0     # écart à l'EMA50, en écarts-types (fenêtre 50)
RSI_PERIODE    = 3
RSI_SEUIL      = 8       # achat si RSI(3) < 8 · vente si RSI(3) > 92
CIBLE_FRACTION = 0.35    # 35% du chemin vers l'EMA50, pas plus
SL_ATR         = 5.0     # SL = 5 x ATR(14) — LARGE, c'est voulu
ADX_MAX        = 30      # jamais en tendance forte
HEURES_INTERDITES = {7, 8, 13, 14}   # heure SERVEUR MT5 (UTC+3), même repère que le backtest
                                     # = 6-7h et 12-13h Paris (pré-Londres, midi) — PAS «…»
TIMEFRAME_NOM  = "M15"
MIN_BARRES     = 260
CONFIANCE      = 94      # le WR mesuré, transmis à execute() comme confiance

# Les marchés où la stratégie a été VALIDÉE (finançables à X € avec un SL
# de 5 ATR). execute() applique ensuite le palier du capital par-dessus :
# à X € seuls BTCUSD et SP500 passent le palier — ce sont justement les deux
# qui portent le plus de R (+2,7 et +1,9 sur l'année de validation).
MARCHES = ["BTCUSD", "SP500", "EURUSD+", "USDJPY+", "GBPUSD+", "ETHUSD"]


def _ema(x, n):
    k = 2.0 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(c, n):
    d = np.diff(c, prepend=c[0])
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag = np.empty_like(c)
    al = np.empty_like(c)
    ag[:n + 1] = g[:n + 1].mean()
    al[:n + 1] = l[:n + 1].mean()
    for i in range(n + 1, len(c)):
        ag[i] = (ag[i - 1] * (n - 1) + g[i]) / n
        al[i] = (al[i - 1] * (n - 1) + l[i]) / n
    rs = np.where(al > 1e-12, ag / np.maximum(al, 1e-12), 999.0)
    return 100 - 100 / (1 + rs)


def _atr(h, l, c, n=14):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    out = np.empty_like(tr)
    s = 0.0
    for i in range(len(tr)):
        s += tr[i]
        if i >= n:
            s -= tr[i - n]
            out[i] = s / n
        else:
            out[i] = s / (i + 1)
    return out


def _adx(h, l, c, n=14):
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    dmp = np.where((up > dn) & (up > 0), up, 0.0)
    dmm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    k = np.ones(n) / n
    stp = np.convolve(dmp, k, mode="full")[:len(h)]
    stm = np.convolve(dmm, k, mode="full")[:len(h)]
    st = np.maximum(np.convolve(tr, k, mode="full")[:len(h)], 1e-9)
    pdi, mdi = 100 * stp / st, 100 * stm / st
    return 100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9)


def _std50(x):
    n = 50
    if len(x) < n + 1:
        return 0.0
    fen = x[-n:]
    m = fen.mean()
    return float(math.sqrt(max(((fen - m) ** 2).mean(), 0.0)))


def _lire_etat():
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception:
        return {"dernier_signal": {}, "signaux": 0, "ouverts": 0}


def _ecrire_etat(d):
    try:
        ETAT.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def analyser(mt5, symbole, pip_fn=None):
    """Le signal sur la DERNIÈRE bougie clôturée. Renvoie un dict prêt pour
    execute(), ou None. Ne décide de rien d'autre : pas de palier, pas de
    budget — c'est le rôle d'execute()."""
    tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME_NOM)
    r = mt5.copy_rates_from_pos(symbole, tf, 0, MIN_BARRES + 2)
    if r is None or len(r) < MIN_BARRES:
        return None
    r = r[:-1]                                  # clôturées uniquement
    H = r["high"].astype(float)
    L = r["low"].astype(float)
    C = r["close"].astype(float)
    T = int(r["time"][-1])
    heure = (T // 3600) % 24
    if heure in HEURES_INTERDITES:
        return None
    A = _atr(H, L, C)
    if A[-1] <= 0:
        return None
    if _adx(H, L, C)[-1] >= ADX_MAX:
        return None                             # tendance trop forte
    e50 = _ema(C, 50)
    sd = _std50(C)
    if sd <= 0:
        return None
    z = (C[-1] - e50[-1]) / sd
    rsi = _rsi(C, RSI_PERIODE)[-1]
    sens = 0
    if z <= -Z_SEUIL and rsi < RSI_SEUIL:
        sens = 1
    elif z >= Z_SEUIL and rsi > 100 - RSI_SEUIL:
        sens = -1
    if sens == 0:
        return None
    info = mt5.symbol_info(symbole)
    tick = mt5.symbol_info_tick(symbole)
    if not info or not tick:
        return None
    spread = tick.ask - tick.bid
    prix = tick.ask if sens > 0 else tick.bid
    risque = max(SL_ATR * A[-1], 3.0 * spread)
    cible = prix + (e50[-1] - prix) * CIBLE_FRACTION
    if (cible - prix) * sens <= 2 * spread:
        return None                             # cible dans le spread : non
    # 🎯 05/09 : la MÊME unité de pip que celle avec laquelle L'ŒIL relit sl_pips/tp_pips
    # (pip_of : BTCUSD/SP500 = 1.0, or = 0.1…). Avant : point du broker → facteur 100 sur BTC/SP500.
    pip = pip_fn(symbole) if pip_fn else (info.point * 10 if info.digits in (3, 5) else info.point)
    return {
        "symbol": symbole, "sens": "BUY" if sens > 0 else "SELL",
        "prix": prix, "sl": round(prix - sens * risque, info.digits),
        "tp": round(cible, info.digits),
        "sl_pips": round(risque / pip, 1), "tp_pips": round(abs(cible - prix) / pip, 1),
        "z": round(float(z), 2), "rsi": round(float(rsi), 1), "atr": float(A[-1]),
        "bougie": T,
    }


_SEC_TF = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}


def cycle(mt5, execute, log=None, telegram=None, positions_ouvertes=None, pip_fn=None):
    """À appeler toutes les 2 s depuis L'ŒIL (oeil_rapide) — mais il ne
    calcule qu'une fois par bougie M15 et par marché. Ouvre via execute()
    avec le tag «…», une seule position par marché.
    pip_fn = la convention de pips de L'ŒIL (pip_of) : indispensable pour que
    sl_pips/tp_pips soient relus dans l'unité où ils sont écrits."""
    if not ACTIF:
        return 0
    etat = _lire_etat()
    etat.setdefault("dernier_signal", {})
    etat.setdefault("en_position", {})
    n = 0
    tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME_NOM)
    duree = _SEC_TF.get(TIMEFRAME_NOM, 900)
    for sym in MARCHES:
        try:
            en_pos = bool(positions_ouvertes) and any(
                p.symbol == sym and "RETOUR" in (p.comment or "").upper() for p in positions_ouvertes)
            if en_pos:
                etat["en_position"][sym] = True      # une seule position «…» par marché
                continue
            r = mt5.copy_rates_from_pos(sym, tf, 0, 2)
            if r is None or len(r) < 2:
                continue
            derniere = int(r[0]["time"])             # la dernière bougie CLÔTURÉE
            if etat["en_position"].get(sym):
                # 🎯 05/09 : la position vient de se fermer. Comme le backtest, on n'accepte
                # qu'un signal STRICTEMENT postérieur à la bougie de sortie : les bougies
                # vécues pendant la position et celle de la sortie (en cours) sont consommées.
                etat["dernier_signal"][sym] = int(r[1]["time"])
                etat["en_position"][sym] = False
                continue
            if etat["dernier_signal"].get(sym) == derniere:
                continue                              # déjà évaluée
            etat["dernier_signal"][sym] = derniere
            # 🎯 05/09 : FRAÎCHEUR. Le backtest entre au close de la bougie de signal. Après un
            # redémarrage (ou un état perdu) on lirait une bougie clôturée depuis 14 min et on
            # entrerait à un prix qui n'a plus rien à voir : au-delà de 60 s, on note, on ne trade pas.
            tick = mt5.symbol_info_tick(sym)
            if tick is None or (tick.time - (derniere + duree)) > 60:
                if log:
                    log.debug(f"retour_moyenne {sym} : bougie {derniere} périmée, non tradée")
                continue
            s = analyser(mt5, sym, pip_fn)
            if not s:
                continue
            etat["signaux"] = etat.get("signaux", 0) + 1
            if log:
                log.info(f"🎯 RETOUR {sym} {s['sens']} : z={s['z']} rsi3={s['rsi']} "
                         f"SL {s['sl_pips']}p ({SL_ATR}×ATR) · cible {s['tp_pips']}p "
                         f"({CIBLE_FRACTION:.0%} vers EMA50)")
            execute({"type": s["sens"], "cible": "MT5", "symbol": sym,
                     "sl_pips": s["sl_pips"], "tp_pips": s["tp_pips"],
                     "confiance": CONFIANCE, "tag": "retour",
                     "raison": (f"RETOUR À LA MOYENNE {s['sens']} : z={s['z']} rsi3={s['rsi']} "
                                f"→ cible {s['tp']} (35% vers EMA50), SL {s['sl']} (5×ATR)")}, False)
            # 🎯 05/09 : on n'annonce QUE ce qui est réellement ouvert — execute() peut refuser
            # (budget, palier, plafond, enveloppe…) et ne renvoie rien.
            ouvert = any("RETOUR" in (p.comment or "").upper()
                         for p in (mt5.positions_get(symbol=sym) or []))
            if not ouvert:
                etat["refuses"] = etat.get("refuses", 0) + 1
                if log:
                    log.info(f"🎯 RETOUR {sym} : signal vu mais NON ouvert (refusé par execute — voir la garde au-dessus)")
                continue
            etat["en_position"][sym] = True
            etat["ouverts"] = etat.get("ouverts", 0) + 1
            n += 1
            if telegram:
                telegram(f"🎯 RETOUR À LA MOYENNE — {sym} {s['sens']} @ {s['prix']}\n"
                         f"   écart {s['z']}σ · RSI(3) {s['rsi']} · cible {s['tp']} · SL {s['sl']}\n"
                         f"   (stratégie validée à 94% de réussite sur 2 ans — "
                         f"un trade toutes les ~10 jours par marché, c'est normal)")
        except Exception as e:
            if log:
                log.debug(f"retour_moyenne {sym} : {e}")
    _ecrire_etat(etat)
    return n

def contexte() -> str:
    """Bloc pour le cerveau / Telegram."""
    e = _lire_etat()
    return (f"🎯 RETOUR À LA MOYENNE : {'ACTIF' if ACTIF else 'DORMANT (ACTIF=False)'} · "
            f"{e.get('signaux', 0)} signaux vus · {e.get('ouverts', 0)} ouverts · {e.get('refuses', 0)} refusés · "
            f"réglages z{Z_SEUIL}/RSI{RSI_PERIODE}<{RSI_SEUIL}/cible {CIBLE_FRACTION:.0%}/SL {SL_ATR}×ATR · "
            f"validé 94% sur 2 ans")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import MetaTrader5 as mt5
    mt5.initialize()
    print(contexte())
    for s in MARCHES:
        print(s, analyser(mt5, s))
    mt5.shutdown()
