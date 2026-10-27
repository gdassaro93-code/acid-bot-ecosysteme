# -*- coding: utf-8 -*-
# =====================================================
#  🧪 GÉNÉRATEUR DE DONNÉES ML DEPUIS LES PRIX (21/08/26)
#
#  POURQUOI CE FICHIER EXISTE
#  L'ancien jeu de données (ml_data/features_v2.csv) contenait 19 661 lignes
#  = les VRAIS trades du patron, de mars 2022 à juillet 2025. Deux défauts
#  mortels constatés le 21/08/26 :
#    1. il s'arrête il y a 13 mois (or à ~2000$ ; il vaut 4247$ aujourd'hui) ;
#    2. il apprend le COMPORTEMENT DU TRADER, pas le marché — et sur les
#       20 derniers jours ce comportement a produit X € sur 121 trades.
#       L'entraîner là-dessus, c'est lui apprendre à perdre.
#
#  CE QU'ON FAIT À LA PLACE
#  Le marché est le professeur, et il est gratuit : 199 400 bougies H1
#  disponibles chez Vantage, jusqu'à aujourd'hui. Pour chaque bougie on pose
#  la seule question qui compte :
#     «…»
#
#  ⚠️ LA LEÇON DU 07/08, ENCODÉE ICI : le SPREAD RÉEL est déduit à l'entrée et
#  à la sortie. Sans lui, un backtest affichait +101R… et -65R avec. Un modèle
#  entraîné sans le spread apprend un marché qui n'existe pas.
#
#  Utilisation :
#      python ml_dataset_prix.py                 # 10 symboles, 20 000 bougies
#      python ml_dataset_prix.py 5000            # plus rapide, pour tester
#  Sortie : ml_data/dataset_prix.csv
# =====================================================
import sys
import csv
import math
from pathlib import Path
from datetime import datetime

import MetaTrader5 as mt5

HERE = Path(__file__).resolve().parent
SORTIE = HERE / "ml_data" / "dataset_prix.csv"

SYMBOLES = ["XAUUSD+", "NAS100", "BTCUSD", "ETHUSD", "SP500",
            "CL-OIL", "XAGUSD", "EURUSD+", "USDJPY+", "GBPUSD+"]

SL_ATR = 1.0        # stop = 1×ATR H1 (la recette mesurée le 07/08)
TP_R = 2.0          # objectif = 2× le risque, sec (ni BE ni trailing : mesurés destructeurs)
HORIZON = 40        # on suit 40 bougies H1 max, sinon le trade est «…»
AMORCE = 60         # bougies nécessaires avant de pouvoir calculer les indicateurs


# ─── indicateurs (mêmes formules que le serveur ML, pour rester compatible) ──
def _ema(vals, n):
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    g = p = 0.0
    for i in range(-n, 0):
        d = closes[i] - closes[i - 1]
        g += max(d, 0)
        p += max(-d, 0)
    if p == 0:
        return 100.0
    rs = (g / n) / (p / n)
    return 100 - 100 / (1 + rs)


def _atr(h, l, c, n=14):
    if len(c) < n + 2:
        return 0.0
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
           for i in range(1, len(c))]
    return sum(trs[-n:]) / n


def _boll_w(closes, n=20):
    if len(closes) < n:
        return 0.0
    f = closes[-n:]
    m = sum(f) / n
    var = sum((x - m) ** 2 for x in f) / n
    return (2 * math.sqrt(var)) / m if m else 0.0


def _impulsion(o, h, l, c, atr):
    """Le détecteur mesuré rentable (07/08) donné au modèle comme indice :
    ampleur du mouvement récent en ATR, et sa propreté (0-1)."""
    best = (0.0, 0.0, 0)
    n = len(c)
    for taille in (3, 4, 5, 6, 7):
        deb = n - taille
        if deb < 1:
            continue
        net = c[-1] - o[deb]
        haut, bas = max(h[deb:]), min(l[deb:])
        etendue = max(haut - bas, 1e-12)
        amp = abs(net) / atr if atr else 0.0
        prop = abs(net) / etendue
        if amp > best[0]:
            best = (amp, prop, 1 if net > 0 else -1)
    return best


def genere(nb_bougies=20000):
    mt5.initialize()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    colonnes = ["symbole", "date", "sens", "rsi", "rsi_h4", "ema_ratio", "atr_pct",
                "macd", "bollinger_width", "heure", "jour_semaine",
                "pos_range20", "ret_1d", "ret_5d",
                "impulsion_atr", "impulsion_proprete", "impulsion_sens",
                "spread_pct_risque", "gagnant"]
    lignes = 0
    gagnants = 0
    with open(SORTIE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(colonnes)
        for sym in SYMBOLES:
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, nb_bougies)
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
            if r is None or info is None or len(r) < AMORCE + HORIZON + 10:
                print(f"  {sym:10} ignoré (données insuffisantes)")
                continue
            spread = (tick.ask - tick.bid) if tick else (info.spread * info.point)
            r4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, nb_bougies // 4)
            n_sym = 0
            O = [float(x["open"]) for x in r]
            H = [float(x["high"]) for x in r]
            L = [float(x["low"]) for x in r]
            C = [float(x["close"]) for x in r]
            T = [int(x["time"]) for x in r]

            for k in range(AMORCE, len(r) - HORIZON - 1):
                h, l, c, o = H[:k + 1], L[:k + 1], C[:k + 1], O[:k + 1]
                atr = _atr(h, l, c)
                if atr <= 0:
                    continue
                # les deux sens sont évalués : le modèle doit apprendre les deux
                for sens in (1, -1):
                    entree = O[k + 1] + sens * spread     # on paie le spread à l'entrée
                    sl = entree - sens * SL_ATR * atr
                    risque = abs(entree - sl)
                    if risque <= 0:
                        continue
                    tp = entree + sens * TP_R * risque
                    issue = None
                    for j in range(k + 1, k + 1 + HORIZON):
                        hi = H[j] + (spread if sens < 0 else 0)
                        lo = L[j] - (spread if sens > 0 else 0)
                        if sens > 0:
                            if lo <= sl:
                                issue = 0
                                break
                            if hi >= tp:
                                issue = 1
                                break
                        else:
                            if hi >= sl:
                                issue = 0
                                break
                            if lo <= tp:
                                issue = 1
                                break
                    if issue is None:
                        continue                  # ni l'un ni l'autre : exemple ambigu, écarté

                    d = datetime.fromtimestamp(T[k])
                    ema20, ema50 = _ema(c, 20), _ema(c, 50)
                    rsi_h4 = 50.0
                    if r4 is not None and len(r4) > 20:
                        c4 = [float(x["close"]) for x in r4 if int(x["time"]) <= T[k]]
                        if len(c4) > 15:
                            rsi_h4 = _rsi(c4)
                    hi20, lo20 = max(h[-20:]), min(l[-20:])
                    amp, prop, isens = _impulsion(o, h, l, c, atr)
                    w.writerow([
                        sym, d.strftime("%Y-%m-%d %H:%M"), sens,
                        round(_rsi(c), 2), round(rsi_h4, 2),
                        round((ema20 / ema50) if (ema20 and ema50) else 1.0, 5),
                        round(100 * atr / c[-1], 4) if c[-1] else 0,
                        round((_ema(c, 12) or 0) - (_ema(c, 26) or 0), 6),
                        round(_boll_w(c), 6),
                        d.hour, d.weekday(),
                        round((c[-1] - lo20) / (hi20 - lo20), 4) if hi20 > lo20 else 0.5,
                        round(100 * (c[-1] / c[-24] - 1), 4) if len(c) > 24 else 0,
                        round(100 * (c[-1] / c[-120] - 1), 4) if len(c) > 120 else 0,
                        round(amp, 3), round(prop, 3), isens,
                        round(100 * spread / risque, 3),      # ⚠️ le coût réel, jamais oublié
                        issue,
                    ])
                    lignes += 1
                    n_sym += 1
                    gagnants += issue
            print(f"  {sym:10} {n_sym:7d} exemples")
    mt5.shutdown()
    print(f"\n✅ {lignes} exemples écrits dans {SORTIE}")
    if lignes:
        print(f"   {100 * gagnants / lignes:.1f}% de gagnants "
              f"(un TP à 2R touche naturellement ~33% du temps : "
              f"c'est l'équilibre, tout ce que le modèle gagne au-dessus est de la valeur)")
    return lignes


if __name__ == "__main__":
    nb = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    print(f"🧪 Génération du jeu de données depuis les PRIX ({nb} bougies H1/symbole)\n")
    genere(nb)
