# -*- coding: utf-8 -*-
# =====================================================
#  🧠 AVIS DU ML — branchement direct dans L'ŒIL (29/08/26)
#
#  POURQUOI PAS LE SERVEUR (port 8001) :
#  Le serveur ML n'envoie que 6 chiffres (rsi, ema_ratio, atr, macd,
#  bollinger, news) et chargeait acidgpt_ml_model.pkl — archivé le 29/08
#  avec les autres modèles entraînés sur les vieux échecs. Le rebrancher
#  aurait ramené les fameux «…» : la valeur de repli, pas une
#  prédiction. Le nouveau modèle a besoin de 16 données, dont l'impulsion
#  et le coût du spread — que L'ŒIL calcule déjà pour lui-même.
#
#  On lit donc le modèle ICI, en direct, sans HTTP : plus rapide, un point
#  de panne en moins, et le serveur ML reste disponible pour qui le veut.
#
#  ⚠️ RÔLE : CONSULTATIF. Le patron, le 29/08 : «…
#  …». Il l'avait, il a bloqué des setups 4/4 parfaits avec,
#  il ne le récupère pas. Son avis se lit, il ne commande pas.
# =====================================================
import math
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELE = HERE / "ml_data" / "modele_prix.pkl"

_paquet = {"charge": False, "modele": None, "features": None, "seuil": 0.40}


def _charger():
    if _paquet["charge"]:
        return _paquet["modele"] is not None
    _paquet["charge"] = True
    try:
        import joblib
        d = joblib.load(MODELE)
        _paquet.update({"modele": d["modele"], "features": d["features"],
                        "seuil": float(d.get("seuil", 0.40))})
    except Exception:
        _paquet["modele"] = None
    return _paquet["modele"] is not None


def _ema(v, n):
    if len(v) < n:
        return None
    k = 2 / (n + 1)
    e = sum(v[:n]) / n
    for x in v[n:]:
        e = x * k + e * (1 - k)
    return e


def _rsi(c, n=14):
    if len(c) < n + 1:
        return 50.0
    g = p = 0.0
    for i in range(-n, 0):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        p += max(-d, 0)
    return 100.0 if p == 0 else 100 - 100 / (1 + (g / n) / (p / n))


def avis(mt5, chart_patterns, symbole, sens_voulu):
    """Probabilité que CE trade atteigne 2R avant de toucher son stop.

    sens_voulu : "BUY" ou "SELL".
    Retourne {proba, seuil, favorable, texte} — ou None si indisponible.
    Les features sont calculées EXACTEMENT comme dans ml_dataset_prix.py :
    tout écart ici rendrait la prédiction fausse sans prévenir."""
    if not _charger():
        return None
    try:
        r = mt5.copy_rates_from_pos(symbole, mt5.TIMEFRAME_H1, 0, 140)
        info = mt5.symbol_info(symbole)
        tick = mt5.symbol_info_tick(symbole)
        if r is None or len(r) < 130 or not info or not tick:
            return None
        O = [float(x["open"]) for x in r]
        H = [float(x["high"]) for x in r]
        L = [float(x["low"]) for x in r]
        C = [float(x["close"]) for x in r]

        atr = chart_patterns._atr(H, L, C)
        if atr <= 0 or C[-1] <= 0:
            return None
        spread = max(tick.ask - tick.bid, info.point or 0.0)
        risque = 1.0 * atr                     # le dataset a été bâti sur un stop 1×ATR

        r4 = mt5.copy_rates_from_pos(symbole, mt5.TIMEFRAME_H4, 0, 40)
        rsi_h4 = 50.0
        if r4 is not None and len(r4) > 20:
            rsi_h4 = _rsi([float(x["close"]) for x in r4])

        e20, e50 = _ema(C, 20), _ema(C, 50)
        f = C[-20:]
        moy = sum(f) / 20
        var = sum((x - moy) ** 2 for x in f) / 20
        boll = (2 * math.sqrt(var)) / moy if moy else 0.0
        hi20, lo20 = max(H[-20:]), min(L[-20:])
        amp, prop, isens = chart_patterns._impulsion(O, H, L, C, atr) \
            if hasattr(chart_patterns, "_impulsion") else (0.0, 0.0, 0)
        d = datetime.fromtimestamp(int(r[-1]["time"]))
        s = 1 if str(sens_voulu).upper().startswith("B") else -1

        valeurs = {
            "sens": s, "rsi": _rsi(C), "rsi_h4": rsi_h4,
            "ema_ratio": (e20 / e50) if (e20 and e50) else 1.0,
            "atr_pct": 100 * atr / C[-1],
            "macd": (_ema(C, 12) or 0) - (_ema(C, 26) or 0),
            "bollinger_width": boll, "heure": d.hour, "jour_semaine": d.weekday(),
            "pos_range20": (C[-1] - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5,
            "ret_1d": 100 * (C[-1] / C[-24] - 1) if len(C) > 24 else 0.0,
            "ret_5d": 100 * (C[-1] / C[-120] - 1) if len(C) > 120 else 0.0,
            "impulsion_atr": amp, "impulsion_proprete": prop, "impulsion_sens": isens,
            "spread_pct_risque": 100 * spread / risque if risque else 0.0,
        }
        X = [[valeurs[k] for k in _paquet["features"]]]
        p = float(_paquet["modele"].predict_proba(X)[0][1])
        seuil = _paquet["seuil"]
        return {
            "proba": round(p, 3), "seuil": seuil, "favorable": p >= seuil,
            "texte": (f"{symbole} {sens_voulu} : le ML donne {100 * p:.0f}% de chances "
                      f"d'atteindre 2R (seuil retenu {100 * seuil:.0f}%) — "
                      f"{'FAVORABLE' if p >= seuil else 'défavorable'}"),
        }
    except Exception:
        return None


def contexte(mt5, chart_patterns, symboles, sens_par_symbole=None):
    """Bloc pour le cerveau. CONSULTATIF : il informe, il n'interdit rien."""
    if not _charger():
        return ""
    lignes = []
    for sym in list(symboles)[:8]:
        sens = (sens_par_symbole or {}).get(sym)
        # 29/08 : on n'affiche QU'UN sens par symbole — le plus probable.
        # Sans ça il annonçait «…» ET «…» :
        # haussier et baissier en même temps, donc aucune information.
        # Quand les deux sens se valent, c'est qu'il n'a pas d'avis : on
        # exige un écart net (3 points) pour qu'il ait le droit de parler.
        candidats = []
        for essai in ([sens] if sens else ["BUY", "SELL"]):
            a = avis(mt5, chart_patterns, sym, essai)
            if a:
                candidats.append((a["proba"], essai, a))
        if not candidats:
            continue
        candidats.sort(reverse=True)
        p, essai, a = candidats[0]
        if len(candidats) > 1 and (p - candidats[1][0]) < 0.03:
            continue                       # les deux sens se valent : il se tait
        if a["favorable"]:
            lignes.append(f"  {sym} {essai} → {100 * p:.0f}% (seuil "
                          f"{100 * a['seuil']:.0f}%)")
    if not lignes:
        return ("🧠 ML : aucun setup au-dessus de son seuil en ce moment. "
                "C'est un AVIS, pas un veto — si tes autres juges sont alignés, "
                "tu peux tirer sans lui.")
    return ("🧠 ML (réentraîné le 29/08 sur 157 176 exemples de PRIX, pas sur nos "
            "anciens trades ; AUC 0,58 contre 0,49 en test de paranoïa ; "
            "+0,139R par trade au seuil retenu).\n"
            "⚠️ CONSULTATIF — aucun droit de veto : son silence n'interdit RIEN, "
            "son accord ne dispense pas des autres juges.\n"
            "Setups qu'il juge favorables :\n" + "\n".join(lignes))
