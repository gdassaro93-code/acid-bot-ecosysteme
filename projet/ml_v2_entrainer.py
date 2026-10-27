# -*- coding: utf-8 -*-
# =====================================================
#  🧠 ML V2 — LE SEUL MODÈLE DE L'ÉCOSYSTÈME, ENTRAÎNÉ SUR DU FRAIS (16/09/26)
#
#  LE PATRON :
#    «…
#      …»
#    «…
#      …»
#
#  CE QUI EXISTAIT, MESURÉ LE 16/09 SUR 2 546 BOUGIES JAMAIS VUES (bancs/banc_ml.py) :
#    server_ml_v2 + acidgpt_ml_model.pkl (trades VTMarkets 2022-2025)
#        AUC 0,507 — pile ou face ; suivre ses choix : 30,4 % contre 30,0 % au hasard
#    ml_avis + modele_prix.pkl (bougies Vantage)
#        AUC 0,560 ; suivre ses choix : 40,2 % de gagnants contre 30,0 % au hasard
#  Un seul portait un signal. Sa RECETTE devient celle de server_ml_v2, et on
#  la réentraîne sur les bougies Vantage jusqu'à aujourd'hui.
#
#  CE FICHIER REMPLACE : ml_dataset_prix.py + ml_entrainer.py (archivés).
#  Les formules des 16 données sont RECOPIÉES À L'IDENTIQUE — le modèle ne
#  vaut que si le service calcule exactement ce qu'on lui a appris.
#
#  ── POURQUOI UNE RÉÉCRITURE DU GÉNÉRATEUR ─────────────────────────────
#  L'original recalculait _atr et les quatre _ema DEPUIS LE DÉBUT de
#  l'historique à CHAQUE bougie : 20 000 bougies × 10 marchés, des milliards
#  d'opérations. Ici chaque série est calculée UNE fois, en avant.
#  `verifier_fidelite()` rejoue les fonctions ORIGINALES sur un échantillon et
#  compare : si un seul écart dépasse la tolérance, on s'arrête.
#
#  ── LE PROTOCOLE (celui du 29/08, plus un étage) ──────────────────────
#   1. découpage TEMPOREL strict, jamais aléatoire
#   2. FOSSÉ de 15 jours entre entraînement et test
#   3. TEST DE PARANOÏA : réentraîné sur étiquettes MÉLANGÉES, l'AUC doit
#      tomber à ~0,50 — c'est la preuve que le vrai modèle ne triche pas
#   4. ESPÉRANCE EN R au seuil, sur au moins 800 trades
#   5. NOUVEAU — une RÉSERVE FINALE : les 30 derniers jours ne servent NI à
#      entraîner NI à choisir le seuil. Le modèle et son seuil sont figés AVANT
#      d'y toucher. C'est le seul chiffre qui dise ce qu'il vaudra demain.
#  Refusé à la moindre étape ratée : on n'enregistre rien.
#
#      python ml_v2_entrainer.py            # tout : données, fidélité, entraînement
#      python ml_v2_entrainer.py 5000       # plus rapide, pour tester
# =====================================================
import io
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DOSSIER = HERE / "ml_data"
DATASET = DOSSIER / "dataset_v2.csv"
MODELE = DOSSIER / "modele_v2.pkl"
CARTE = DOSSIER / "modele_v2_carte.json"

SYMBOLES = ["XAUUSD+", "NAS100", "BTCUSD", "ETHUSD", "SP500",
            "CL-OIL", "XAGUSD", "EURUSD+", "USDJPY+", "GBPUSD+"]
SL_ATR = 1.0
TP_R = 2.0
HORIZON = 40
AMORCE = 60

FEATURES = ["sens", "rsi", "rsi_h4", "ema_ratio", "atr_pct", "macd",
            "bollinger_width", "heure", "jour_semaine", "pos_range20",
            "ret_1d", "ret_5d", "impulsion_atr", "impulsion_proprete",
            "impulsion_sens", "spread_pct_risque"]
FOSSE_JOURS = 15
RESERVE_JOURS = 30
MIN_TRADES = 800
# 🩹 16/09 — Le spread utilisé à l'entraînement, par marché. Le serveur s'en
# sert pour la donnée spread_pct_risque : en direct, le spread de l'or ou du
# forex est multiplié par 3 à 10 au rollover et pendant les news, une valeur
# jamais vue à l'entraînement, que le modèle lisait comme «…».
SPREADS_FICHIER = DOSSIER / "spreads_v2.json"
SPREADS = {}


# ══ LES FORMULES ORIGINALES (ml_dataset_prix.py), recopiées mot pour mot ══
# Elles servent de RÉFÉRENCE : la version rapide doit leur être identique.

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


# ══ LES SÉRIES RAPIDES — une passe en avant par marché ══════════════════

def _ema_serie(C, n):
    """Même arithmétique, même ordre que _ema : graine = moyenne des n
    premières valeurs, puis récurrence. Donc identique au bit près."""
    out = [None] * len(C)
    if len(C) < n:
        return out
    k = 2 / (n + 1)
    e = sum(C[:n]) / n
    out[n - 1] = e
    for i in range(n, len(C)):
        e = C[i] * k + e * (1 - k)
        out[i] = e
    return out


def _series(O, H, L, C):
    n = len(C)
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
    return {
        "tr": tr,
        "e12": _ema_serie(C, 12), "e20": _ema_serie(C, 20),
        "e26": _ema_serie(C, 26), "e50": _ema_serie(C, 50),
    }


def _features_k(k, O, H, L, C, T, S, T4, C4, spread):
    """Les 16 données à la bougie k, pour les deux sens. Retourne
    (atr, base) où base contient tout sauf 'sens' et 'spread_pct_risque'."""
    if k + 1 < 14 + 2:
        return 0.0, None
    atr = sum(S["tr"][k - 13:k + 1]) / 14
    if atr <= 0:
        return 0.0, None
    # RSI : les 14 derniers écarts, sommés dans le même ordre que _rsi
    g = p = 0.0
    for i in range(k - 13, k + 1):
        d = C[i] - C[i - 1]
        g += max(d, 0)
        p += max(-d, 0)
    rsi = 100.0 if p == 0 else 100 - 100 / (1 + (g / 14) / (p / 14))
    # RSI H4 : SEULEMENT les bougies H4 déjà CLÔTURÉES quand la décision tombe.
    # 🩹 16/09 — FUITE DU FUTUR trouvée à la relecture. T et T4 sont des heures
    # d'OUVERTURE. L'ancien test (T4 <= T[k]) gardait la H4 ouverte à 08:00 pour
    # une décision prise à 09:00 : sa clôture est celle de 12:00, trois heures
    # APRÈS l'entrée. Vrai pour 3 bougies H1 sur 4. Le modèle voyait donc une
    # partie de la réponse, et tous ses chiffres de validation étaient gonflés.
    # La décision tombe à la clôture de la H1 k (T[k] + 3600) ; une H4 ouverte à
    # t4 clôture à t4 + 14400 : elle est connue si t4 <= T[k] - 10800.
    j = int(np.searchsorted(T4, T[k] - 10800, side="right"))
    rsi_h4 = 50.0
    if j > 15:
        c4 = C4[max(0, j - 15):j]
        g4 = p4 = 0.0
        for i in range(-14, 0):
            d = c4[i] - c4[i - 1]
            g4 += max(d, 0)
            p4 += max(-d, 0)
        rsi_h4 = 100.0 if p4 == 0 else 100 - 100 / (1 + (g4 / 14) / (p4 / 14))
    e20, e50 = S["e20"][k], S["e50"][k]
    e12, e26 = S["e12"][k], S["e26"][k]
    f = C[k - 19:k + 1]
    m = sum(f) / 20
    boll = (2 * math.sqrt(sum((x - m) ** 2 for x in f) / 20)) / m if m else 0.0
    hi20, lo20 = max(H[k - 19:k + 1]), min(L[k - 19:k + 1])
    lo = max(0, k - 7)
    amp, prop, isens = _impulsion(O[lo:k + 1], H[lo:k + 1], L[lo:k + 1],
                                  C[lo:k + 1], atr)
    d = datetime.fromtimestamp(int(T[k]))
    base = {
        "rsi": round(rsi, 2), "rsi_h4": round(rsi_h4, 2),
        "ema_ratio": round((e20 / e50) if (e20 and e50) else 1.0, 5),
        "atr_pct": round(100 * atr / C[k], 4) if C[k] else 0,
        "macd": round((e12 or 0) - (e26 or 0), 6),
        "bollinger_width": round(boll, 6),
        "heure": d.hour, "jour_semaine": d.weekday(),
        "pos_range20": round((C[k] - lo20) / (hi20 - lo20), 4) if hi20 > lo20 else 0.5,
        "ret_1d": round(100 * (C[k] / C[k - 23] - 1), 4) if k + 1 > 24 else 0,
        "ret_5d": round(100 * (C[k] / C[k - 119] - 1), 4) if k + 1 > 120 else 0,
        "impulsion_atr": round(amp, 3), "impulsion_proprete": round(prop, 3),
        "impulsion_sens": isens,
    }
    return atr, base


def _issue(sens, k, O, H, L, C, atr, spread):
    """(gagnant, risque, j_sortie, r) du trade décidé à la clôture de k.

    🩹 16/09 — DEUX CHANGEMENTS, trouvés à la relecture :
    · Un trade qui ne touche NI le stop NI l'objectif en 40 bougies était
      JETÉ du jeu de données. Or le sniper, lui, le solde au marché à la 40e
      bougie. On ne mesurait donc que les trades «…», pas ceux qu'on
      joue. Ils comptent maintenant : gagnant = 0 (2R pas atteint), r = ce que
      la sortie au marché rapporte vraiment.
    · On garde la bougie de sortie (j_sortie) : sans elle, impossible de
      compter UNE position à la fois. Compter chaque bougie comme un trade
      séparé fait voter dix fois le même mouvement."""
    entree = O[k + 1] + sens * spread
    sl = entree - sens * SL_ATR * atr
    risque = abs(entree - sl)
    if risque <= 0 or k + HORIZON >= len(C):
        return None, risque, None, None
    tp = entree + sens * TP_R * risque
    for j in range(k + 1, k + 1 + HORIZON):
        hi = H[j] + (spread if sens < 0 else 0)
        lo = L[j] - (spread if sens > 0 else 0)
        if sens > 0:
            if lo <= sl:
                return 0, risque, j, -1.0
            if hi >= tp:
                return 1, risque, j, TP_R
        else:
            if hi >= sl:
                return 0, risque, j, -1.0
            if lo <= tp:
                return 1, risque, j, TP_R
    fin = k + HORIZON
    sortie = C[fin] - sens * spread
    return 0, risque, fin, round(sens * (sortie - entree) / risque, 4)


def _charge(mt5, sym, nb):
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, nb)
    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    if r is None or info is None or len(r) < AMORCE + HORIZON + 10:
        return None
    spread = (tick.ask - tick.bid) if tick else (info.spread * info.point)
    r4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, nb // 4)
    O = [float(x["open"]) for x in r]
    H = [float(x["high"]) for x in r]
    L = [float(x["low"]) for x in r]
    C = [float(x["close"]) for x in r]
    T = [int(x["time"]) for x in r]
    if r4 is not None and len(r4):
        T4 = np.array([int(x["time"]) for x in r4], dtype=np.int64)
        C4 = [float(x["close"]) for x in r4]
    else:
        T4, C4 = np.array([], dtype=np.int64), []
    return O, H, L, C, T, T4, C4, spread


# ══ LA PREUVE DE FIDÉLITÉ ════════════════════════════════════════════════

def verifier_fidelite(mt5, nb=3000, echantillon=250):
    """Rejoue les formules ORIGINALES (sur des tranches, comme genere() le
    faisait) et compare à la version rapide. Tolérance 1e-9 relative : les
    seuls écarts permis sont ceux d'un ordre d'addition différent."""
    print("🔬 FIDÉLITÉ — la version rapide contre les formules originales")
    rng = np.random.default_rng(3)
    pire = 0.0
    total = 0
    for sym in ("XAUUSD+", "BTCUSD", "EURUSD+"):
        d = _charge(mt5, sym, nb)
        if d is None:
            continue
        O, H, L, C, T, T4, C4, spread = d
        S = _series(O, H, L, C)
        ks = rng.choice(np.arange(AMORCE, len(C) - HORIZON - 1),
                        size=min(echantillon, len(C) - HORIZON - 1 - AMORCE),
                        replace=False)
        for k in ks:
            k = int(k)
            h, l, c, o = H[:k + 1], L[:k + 1], C[:k + 1], O[:k + 1]
            atr_ref = _atr(h, l, c)
            atr_rap, base = _features_k(k, O, H, L, C, T, S, T4, C4, spread)
            ref = {
                "rsi": round(_rsi(c), 2),
                "ema_ratio": round((_ema(c, 20) / _ema(c, 50))
                                   if (_ema(c, 20) and _ema(c, 50)) else 1.0, 5),
                "atr_pct": round(100 * atr_ref / c[-1], 4),
                "macd": round((_ema(c, 12) or 0) - (_ema(c, 26) or 0), 6),
                "bollinger_width": round(_boll_w(c), 6),
                "pos_range20": round((c[-1] - min(l[-20:])) /
                                     (max(h[-20:]) - min(l[-20:])), 4)
                               if max(h[-20:]) > min(l[-20:]) else 0.5,
                "ret_1d": round(100 * (c[-1] / c[-24] - 1), 4),
                "ret_5d": round(100 * (c[-1] / c[-120] - 1), 4) if len(c) > 120 else 0,
            }
            # 🩹 16/09 : la référence avait la même fuite — H4 CLÔTURÉE à la décision
            c4 = [C4[i] for i in range(len(C4)) if T4[i] + 14400 <= T[k] + 3600]
            ref["rsi_h4"] = round(_rsi(c4), 2) if len(c4) > 15 else 50.0
            amp, prop, isens = _impulsion(o, h, l, c, atr_ref)
            ref.update(impulsion_atr=round(amp, 3), impulsion_proprete=round(prop, 3),
                       impulsion_sens=isens)
            if base is None:
                raise SystemExit(f"❌ {sym} k={k} : la version rapide n'a rien produit")
            if abs(atr_ref - atr_rap) > 1e-9 * max(1.0, abs(atr_ref)):
                raise SystemExit(f"❌ {sym} k={k} ATR : {atr_ref} contre {atr_rap}")
            for cle, v in ref.items():
                w = base[cle]
                ecart = abs(float(v) - float(w)) / max(1e-12, abs(float(v)), 1.0)
                pire = max(pire, ecart)
                if ecart > 1e-6:
                    raise SystemExit(f"❌ {sym} k={k} {cle} : original {v} "
                                     f"contre rapide {w}")
            for sens in (1, -1):
                total += 1
        print(f"   {sym:9} {len(ks)} bougies comparées sur 16 données — identiques")
    print(f"   pire écart relatif : {pire:.2e}  (tolérance 1e-6)\n")
    return True


# ══ LE JEU DE DONNÉES ════════════════════════════════════════════════════

def generer(mt5, nb=20000):
    import csv
    DOSSIER.mkdir(parents=True, exist_ok=True)
    tmp = DATASET.with_suffix(".tmp")
    lignes = gagnants = 0
    t0 = time.time()
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbole", "date"] + FEATURES + ["gagnant", "r", "idx", "idx_sortie"])
        for sym in SYMBOLES:
            d = _charge(mt5, sym, nb)
            if d is None:
                print(f"   {sym:9} ignoré (données insuffisantes)")
                continue
            O, H, L, C, T, T4, C4, spread = d
            SPREADS[sym] = spread
            S = _series(O, H, L, C)
            n_sym = 0
            for k in range(AMORCE, len(C) - HORIZON - 1):
                atr, base = _features_k(k, O, H, L, C, T, S, T4, C4, spread)
                if base is None:
                    continue
                date = datetime.fromtimestamp(T[k]).strftime("%Y-%m-%d %H:%M")
                for sens in (1, -1):
                    issue, risque, j_sortie, r_issue = _issue(sens, k, O, H, L, C, atr, spread)
                    if issue is None:
                        continue
                    row = dict(base, sens=sens,
                               spread_pct_risque=round(100 * spread / risque, 3))
                    w.writerow([sym, date] + [row[x] for x in FEATURES]
                               + [issue, r_issue, k, j_sortie])
                    lignes += 1
                    n_sym += 1
                    gagnants += issue
            print(f"   {sym:9} {n_sym:7d} exemples · "
                  f"{datetime.fromtimestamp(T[AMORCE]):%d/%m/%Y} → "
                  f"{datetime.fromtimestamp(T[len(C) - HORIZON - 2]):%d/%m/%Y} · "
                  f"{time.time() - t0:.0f}s")
    tmp.replace(DATASET)
    SPREADS_FICHIER.write_text(json.dumps(SPREADS, indent=1), encoding="utf-8")
    print(f"\n   {lignes} exemples · {100 * gagnants / max(1, lignes):.1f} % de gagnants "
          f"(équilibre d'un {TP_R:g}R : {100 / (1 + TP_R):.1f} %)\n")
    return lignes


# ══ L'ENTRAÎNEMENT ═══════════════════════════════════════════════════════

def _protocole(d, etiquette):
    """Le protocole du 29/08 sur le jeu `d`. Retourne (modele, seuil, bilan)
    ou (None, None, raison)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    coupe = d["date"].quantile(0.70)
    fosse = coupe + np.timedelta64(FOSSE_JOURS, "D")
    tr, te = d[d["date"] <= coupe], d[d["date"] >= fosse]
    print(f"   [{etiquette}] entraînement {len(tr)} jusqu'au {coupe:%d/%m/%Y} · "
          f"fossé {FOSSE_JOURS} j · test {len(te)} dès le {fosse:%d/%m/%Y}")
    Xtr, ytr = tr[FEATURES].values, tr["gagnant"].values
    Xte, yte = te[FEATURES].values, te["gagnant"].values

    def neuf():
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                              max_depth=5, random_state=42)
    m = neuf().fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(yte, p)
    faux = neuf().fit(Xtr, np.random.default_rng(0).permutation(ytr))
    auc_faux = roc_auc_score(yte, faux.predict_proba(Xte)[:, 1])
    signal = auc - auc_faux
    print(f"   [{etiquette}] AUC {auc:.4f} · paranoïa (étiquettes mélangées) "
          f"{auc_faux:.4f} · signal net {signal:+.4f}")
    meilleur = None
    rte = te["r"].values
    for seuil in np.arange(0.26, 0.60, 0.02):
        sel = p >= seuil
        if sel.sum() < 150:
            break
        tx = yte[sel].mean()
        esp = float(rte[sel].mean())     # 🩹 16/09 : le R réel, sorties à 40 bougies comprises
        if esp > 0 and sel.sum() >= MIN_TRADES and (meilleur is None or esp > meilleur[1]):
            meilleur = (float(seuil), float(esp), int(sel.sum()), float(tx))
    bilan = dict(auc=round(float(auc), 4), auc_paranoia=round(float(auc_faux), 4),
                 signal_net=round(float(signal), 4))
    if signal < 0.03:
        return None, None, f"signal net {signal:+.4f} < 0,03"
    if meilleur is None:
        return None, None, "aucun seuil rentable sur au moins 800 trades"
    seuil, esp, n, tx = meilleur
    bilan.update(seuil=round(seuil, 2), esperance_R=round(esp, 3),
                 reussite_au_seuil=round(100 * tx, 1), trades_au_seuil=n)
    print(f"   [{etiquette}] seuil {seuil:.2f} : {100 * tx:.1f} % de gagnants, "
          f"{esp:+.3f} R par trade sur {n} trades")
    return m, seuil, bilan


REGLES_FIXES = [round(x, 2) for x in np.arange(0.30, 0.47, 0.02)]
REGLES_QUANTILE = [0.80, 0.90, 0.95, 0.98]
FENETRE_QUANTILE = "7D"
N_PLIS = 6
MIN_TRADES_PAR_PLI = 300
PLIS_POSITIFS_MIN = 5
# 🩹 16/09 — le critère qui compte : UNE position à la fois par marché.
# Fixé ici AVANT de lancer quoi que ce soit sur les données corrigées.
MIN_TRADES_REELS_PAR_PLI = 30
MIN_TRADES_REELS_RESERVE = 20


def _une_a_la_fois(zone, sel, scores):
    """Ce que la règle rapporte quand on la JOUE : une position à la fois par
    marché, comme le sniper.

    Le problème (GPT, 16/09, à propos de l'Arène : +4 804 R en comptant les
    signaux qui se chevauchent, -1 667 R une fois corrigé) : chaque bougie du
    jeu de données est un trade. Pendant qu'un trade de 20 bougies court, les
    19 bougies suivantes «…» presque le même trade, et un seul bon
    mouvement est compté vingt fois.
    Ici on parcourt le temps : un trade n'est pris que si le précédent sur ce
    marché est déjà sorti. Si l'ACHAT et la VENTE d'une même bougie passent
    tous les deux, on garde le plus probable. Retourne (n, R total, gagnants)."""
    if not sel.any():
        return 0, 0.0, 0
    z = zone.loc[sel, ["symbole", "idx", "idx_sortie", "r", "gagnant"]].copy()
    z["score"] = scores[sel]
    z = z.sort_values(["symbole", "idx", "score"], ascending=[True, True, False])
    n, total, gagnes, occupe = 0, 0.0, 0, {}
    for sym, idx, sortie, r, g in z[["symbole", "idx", "idx_sortie", "r", "gagnant"]] \
            .itertuples(index=False):
        if idx < occupe.get(sym, -1):
            continue                     # le trade précédent court encore
        occupe[sym] = sortie             # prochaine décision possible à la clôture de la sortie
        n += 1
        total += float(r)
        gagnes += int(g)
    return n, total, gagnes


def _neuf():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                          max_depth=5, random_state=42)


def _appliquer_regles(scores, dates, masque_eval):
    """Pour chaque règle candidate, le masque des trades qu'elle retient.

    La règle QUANTILE est CAUSALE : un trade est retenu si son score dépasse
    le quantile q des scores produits pendant les 7 jours STRICTEMENT avant
    lui (closed='left'). Aucune étiquette n'y entre, rien du futur non plus —
    c'est exactement ce que le service pourra calculer en direct.
    Pourquoi elle existe : le 16/09, le seuil fixe 0,46 retenait 1 % des
    trades au développement et 0,3 % sur le dernier mois. Un seuil en
    PROBABILITÉ ne suit pas un changement de régime ; un seuil en RANG, si."""
    import pandas as pd
    ordre = np.argsort(dates.values, kind="stable")
    s_ord = pd.Series(scores[ordre], index=pd.DatetimeIndex(dates.values[ordre]))
    out = {}
    for t in REGLES_FIXES:
        out[("fixe", t)] = (scores >= t) & masque_eval
    for q in REGLES_QUANTILE:
        cut_ord = s_ord.rolling(FENETRE_QUANTILE, closed="left").quantile(q).values
        cut = np.empty(len(scores))
        cut[ordre] = cut_ord
        out[("quantile", q)] = (scores >= np.nan_to_num(cut, nan=np.inf)) & masque_eval
    return out


def _nom(regle):
    typ, v = regle
    return f"p ≥ {v:.2f}" if typ == "fixe" else f"top {100 * (1 - v):.0f} % sur 7 j"


def choisir_regle(dev):
    """Six fenêtres mensuelles successives. Pour chacune : un modèle entraîné
    jusqu'à 15 jours AVANT, qui juge un mois qu'il n'a jamais vu. Une règle
    n'est éligible que si elle garde au moins 300 trades par mois en moyenne
    et gagne de l'argent sur au moins 5 mois sur 6.
    Ce critère est fixé ICI, avant toute ouverture de la réserve finale."""
    import pandas as pd
    limite = dev["date"].max()
    print(f"🔁 CHOIX DE LA RÈGLE — {N_PLIS} mois glissants, chacun jamais vu par son modèle")
    stats = {}
    for i in range(N_PLIS - 1, -1, -1):
        w1 = limite - pd.Timedelta(days=30 * i)
        w0 = w1 - pd.Timedelta(days=30)
        tr = dev[dev["date"] <= w0 - pd.Timedelta(days=FOSSE_JOURS)]
        zone = dev[(dev["date"] >= w0 - pd.Timedelta(days=7)) & (dev["date"] < w1)]
        if len(tr) < 50000 or len(zone) < 1000:
            continue
        m = _neuf().fit(tr[FEATURES].values, tr["gagnant"].values)
        sc = m.predict_proba(zone[FEATURES].values)[:, 1]
        y = zone["gagnant"].values
        rz = zone["r"].values
        evalm = (zone["date"] >= w0).values
        base_tx = y[evalm].mean()
        n_b, r_b, _g = _une_a_la_fois(zone, evalm, sc)
        print(f"   mois {w0:%d/%m/%y}→{w1:%d/%m/%y} · appris sur {len(tr)} · "
              f"base {100 * base_tx:.1f} % ({rz[evalm].mean():+.3f} R) · "
              f"une à la fois sans filtre : {n_b} trades {r_b / max(1, n_b):+.3f} R")
        for regle, sel in _appliquer_regles(sc, zone["date"], evalm).items():
            n = int(sel.sum())
            r_total = float(rz[sel].sum()) if n else 0.0
            n1, r1, _g1 = _une_a_la_fois(zone, sel, sc)
            st = stats.setdefault(regle, {"n": 0, "R": 0.0, "plis": [],
                                          "n1": 0, "R1": 0.0, "plis1": []})
            st["n"] += n
            st["R"] += r_total
            st["plis"].append((n, (r_total / n) if n else 0.0))
            st["n1"] += n1
            st["R1"] += r1
            st["plis1"].append((n1, (r1 / n1) if n1 else 0.0))
    if not stats:
        return None, "pas assez d'historique pour les plis"
    print()
    print(f"   {'règle':<20}{'bougies':>8}{'R/b':>8}{'| JOUÉ 1 à la fois':>19}"
          f"{'/mois':>7}{'R/trade':>9}{'mois +':>8}   par mois (joué)")
    eligibles = []
    for regle, st in sorted(stats.items(), key=lambda kv: -(kv[1]['R1'] / max(1, kv[1]['n1']))):
        nplis = len(st["plis"])
        moy = st["n"] / max(1, nplis)
        esp = st["R"] / max(1, st["n"])
        positifs = sum(1 for n, e in st["plis"] if n > 0 and e > 0)
        moy1 = st["n1"] / max(1, nplis)
        esp1 = st["R1"] / max(1, st["n1"])
        positifs1 = sum(1 for n, e in st["plis1"] if n > 0 and e > 0)
        # 🩹 16/09 — éligible seulement si la règle tient AUSSI jouée une
        # position à la fois : c'est ce que le sniper fera réellement.
        ok = (moy >= MIN_TRADES_PAR_PLI and positifs >= min(PLIS_POSITIFS_MIN, nplis)
              and moy1 >= MIN_TRADES_REELS_PAR_PLI
              and positifs1 >= min(PLIS_POSITIFS_MIN, nplis))
        detail = " ".join(f"{e:+.2f}" for n, e in st["plis1"])
        print(f"   {_nom(regle):<20}{st['n']:>8}{esp:>+8.3f}{st['n1']:>19}{moy1:>7.0f}"
              f"{esp1:>+9.3f}{positifs1:>5}/{nplis:<2} {detail}{'   ← éligible' if ok else ''}")
        if ok:
            eligibles.append((esp1, regle, st))
    if not eligibles:
        return None, (f"aucune règle ne tient {PLIS_POSITIFS_MIN} mois sur {N_PLIS} en la jouant "
                      f"une position à la fois (≥ {MIN_TRADES_REELS_PAR_PLI} trades/mois)")
    eligibles.sort(key=lambda x: -x[0])
    esp1, regle, st = eligibles[0]
    print(f"\n   ➜ RETENUE : {_nom(regle)} · jouée une à la fois : {esp1:+.3f} R/trade "
          f"sur {st['n1']} trades")
    return regle, st


def entrainer():
    import joblib
    import pandas as pd
    from sklearn.metrics import roc_auc_score

    d = pd.read_csv(DATASET)
    if not {"r", "idx", "idx_sortie"} <= set(d.columns):
        raise SystemExit("❌ jeu de données d'avant le 16/09 (fuite H4, sans sorties) — "
                         "relancer SANS --sans-donnees pour le régénérer")
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    print(f"📊 {len(d)} exemples, du {d['date'].min():%d/%m/%Y} au {d['date'].max():%d/%m/%Y}\n")

    fin = d["date"].max()
    debut_reserve = fin - pd.Timedelta(days=RESERVE_JOURS)
    limite_dev = debut_reserve - pd.Timedelta(days=FOSSE_JOURS)
    dev = d[d["date"] <= limite_dev]
    print(f"🔒 RÉSERVE FINALE : du {debut_reserve:%d/%m/%Y} au {fin:%d/%m/%Y}")
    print(f"   ⚠️ DÉJÀ OUVERTE DEUX FOIS le 16/09 (seuil fixe 0,46 refusé, puis le modèle")
    print(f"   à fuite H4). C'est la 3e ouverture : elle ne vaut plus une donnée jamais")
    print(f"   vue. La seule mesure vierge sera le sniper en OBSERVATION, en direct.\n")

    # étage 1-3 : le modèle apprend-il quelque chose de réel ?
    print("🧪 SIGNAL — découpage 70/30, fossé, paranoïa")
    m, _seuil_ignore, bilan_dev = _protocole(dev, "dev")
    if m is None:
        print(f"\n❌ REFUSÉ au développement : {bilan_dev}")
        return False
    print()

    # étage 4 : quelle règle de filtre tient dans la durée ?
    regle, st = choisir_regle(dev)
    if regle is None:
        print(f"\n❌ REFUSÉ : {st}")
        return False

    # étage 5 : la réserve, une fois, règle figée
    m_dev = _neuf().fit(dev[FEATURES].values, dev["gagnant"].values)
    zone = d[d["date"] >= debut_reserve - pd.Timedelta(days=7)]
    sc = m_dev.predict_proba(zone[FEATURES].values)[:, 1]
    y = zone["gagnant"].values
    evalm = (zone["date"] >= debut_reserve).values
    sel = _appliquer_regles(sc, zone["date"], evalm)[regle]
    yr = y[evalm]
    rz = zone["r"].values
    auc_r = roc_auc_score(yr, sc[evalm])
    n_r = int(sel.sum())
    tx_r = float(y[sel].mean()) if n_r else 0.0
    esp_r = float(rz[sel].mean()) if n_r else 0.0
    tx_base = float(yr.mean())
    esp_base = float(rz[evalm].mean())
    se = 100 * math.sqrt(tx_r * (1 - tx_r) / n_r) if n_r else 0.0
    n1, r1, g1 = _une_a_la_fois(zone, sel, sc)
    nb1, rb1, gb1 = _une_a_la_fois(zone, evalm, sc)
    esp1 = r1 / n1 if n1 else 0.0
    esp_b1 = rb1 / nb1 if nb1 else 0.0
    print(f"\n🔓 RÉSERVE — règle figée : {_nom(regle)}")
    print(f"   AUC {auc_r:.4f}")
    print(f"   sans filtre : {len(yr)} bougies · {100 * tx_base:.1f} % · {esp_base:+.3f} R")
    print(f"   avec filtre : {n_r} bougies · {100 * tx_r:.1f} % (± {se:.1f}) · {esp_r:+.3f} R")
    print(f"   JOUÉ une position à la fois : sans filtre {nb1} trades "
          f"{100 * gb1 / max(1, nb1):.1f} % {esp_b1:+.3f} R · avec filtre {n1} trades "
          f"{100 * g1 / max(1, n1):.1f} % {esp1:+.3f} R")

    raisons = []
    if auc_r < 0.52:
        raisons.append(f"AUC {auc_r:.4f} < 0,52 — il ne classe plus")
    if n_r < 100:
        raisons.append(f"seulement {n_r} trades filtrés < 100 — trop peu pour conclure")
    if esp_r <= esp_base:
        raisons.append(f"espérance filtrée {esp_r:+.3f} R <= {esp_base:+.3f} R sans filtre")
    if n1 < MIN_TRADES_REELS_RESERVE:
        raisons.append(f"joué une position à la fois : {n1} trades < {MIN_TRADES_REELS_RESERVE}")
    elif esp1 <= 0:
        raisons.append(f"joué une position à la fois : {esp1:+.3f} R/trade — il perd")
    if raisons:
        print("\n❌ REFUSÉ sur la réserve :")
        for r_ in raisons:
            print(f"   · {r_}")
        print("   Rien n'est enregistré.")
        return False

    m_final = _neuf().fit(d[FEATURES].values, d["gagnant"].values)
    typ, val = regle
    if typ == "fixe":
        regle_json = {"type": "fixe", "seuil": float(val)}
    else:
        # 🩹 16/09 — le serveur ne garde pas 7 jours de scores en mémoire : il
        # recevait une règle quantile SANS seuil et retombait en silence sur 0,42,
        # une valeur jamais validée. On lui donne le seuil équivalent, mesuré sur
        # les 7 derniers jours avec le modèle final.
        recents = d[d["date"] >= fin - pd.Timedelta(FENETRE_QUANTILE)]
        equiv = float(np.quantile(m_final.predict_proba(recents[FEATURES].values)[:, 1], val))
        regle_json = {"type": "quantile", "q": float(val), "fenetre": FENETRE_QUANTILE,
                      "seuil_equivalent": round(equiv, 4)}
    try:
        spreads = json.loads(SPREADS_FICHIER.read_text(encoding="utf-8"))
    except Exception:
        spreads = {}
    # écriture ATOMIQUE : le serveur ML peut recharger à cet instant précis
    # (/force_retrain, rechargement du dimanche) — il ne doit jamais lire un
    # fichier à moitié écrit
    import os as _os
    _tmp = MODELE.with_suffix(".pkl.tmp")
    joblib.dump({"modele": m_final, "features": FEATURES, "regle": regle_json,
                 "seuil": float(val) if typ == "fixe" else regle_json["seuil_equivalent"],
                 "spreads": spreads, "h4": "clôturées seulement (16/09)",
                 "version": "v2", "revision": "2.2", "cree_le": time.strftime("%Y-%m-%d %H:%M")}, _tmp)
    _os.replace(_tmp, MODELE)
    CARTE.write_text(json.dumps({
        "cree_le": time.strftime("%Y-%m-%d %H:%M"),
        "source": "bougies H1/H4 Vantage — marché pur, spread réel",
        "exemples": int(len(d)),
        "periode": f"{d['date'].min():%Y-%m-%d} → {d['date'].max():%Y-%m-%d}",
        "question": f"stop {SL_ATR:g}×ATR H1, objectif {TP_R:g}R : passe ou casse ?",
        "signal_developpement": bilan_dev,
        "regle": regle_json,
        "regle_sur_6_mois": {"trades": st["n1"],
                             "esperance_R": round(st["R1"] / max(1, st["n1"]), 3),
                             "par_mois": [round(e, 3) for n, e in st["plis1"]],
                             "compte": "une position à la fois par marché",
                             "bougies_chevauchantes": {"trades": st["n"],
                                                       "esperance_R": round(st["R"] / max(1, st["n"]), 3)}},
        "reserve_finale": {
            "periode": f"{debut_reserve:%Y-%m-%d} → {fin:%Y-%m-%d}",
            "deja_ouverte_avant": 2,
            "auc": round(float(auc_r), 4),
            "trades_filtres": n1,
            "reussite_filtre": round(100 * g1 / max(1, n1), 1),
            "esperance_filtre_R": round(esp1, 3),
            "reussite_sans_filtre": round(100 * gb1 / max(1, nb1), 1),
            "esperance_sans_filtre_R": round(esp_b1, 3),
            "compte": "une position à la fois par marché",
            "bougies_chevauchantes": {"trades": n_r, "reussite": round(100 * tx_r, 1),
                                      "esperance_R": round(esp_r, 3)},
        },
        "corrections_16_09": ["RSI H4 : bougies clôturées seulement (fuite du futur)",
                              "trades à 40 bougies sans issue comptés (sortie au marché)",
                              "règle jugée une position à la fois par marché",
                              "spread d'entraînement transmis au serveur"],
        "features": FEATURES,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ VALIDÉ ET ENREGISTRÉ → {MODELE.name}  (fiche {CARTE.name})")
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    import MetaTrader5 as mt5
    _chiffres = [a for a in sys.argv[1:] if a.isdigit()]
    nb = int(_chiffres[0]) if _chiffres else 20000
    if not mt5.initialize():
        raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
    print("=" * 66)
    print("🧠 ML V2 — un seul modèle, entraîné sur les bougies Vantage d'aujourd'hui")
    print("=" * 66 + "\n")
    if "--sans-donnees" not in sys.argv:
        verifier_fidelite(mt5)
        print("📥 GÉNÉRATION DU JEU DE DONNÉES")
        generer(mt5, nb)
    mt5.shutdown()
    entrainer()
