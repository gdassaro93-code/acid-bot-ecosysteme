# -*- coding: utf-8 -*-
# =====================================================
#  💵 SIGNAL DOLLAR — la méthode du patron, mesurée et codée (21/08/26)
#
#  SA PHRASE : «…».
#  C'est du fondamental, et il avait raison sur le principe : la corrélation
#  dollar/or mesurée sur 2000 heures est de -0,578. Très forte.
#
#  MAIS la mesure a corrigé DEUX choses :
#
#  1. Le dollar ne PRÉDIT pas : il accompagne. Corrélation à l'heure suivante
#     = -0,008, soit zéro. Quand on voit le dollar bouger, l'or a déjà bougé.
#     Ce qui marche, c'est la DIVERGENCE : le dollar a bougé fort, la cible
#     n'a pas encore réagi → elle rattrape.
#
#  2. La cible n'est pas celle qu'il croyait. Backtest avec SL/TP et spread
#     réel, ~250 cas par marché, testé sur les deux moitiés de l'historique :
#         NAS100  +31,6R  (+7,0 puis +24,6)   ← robuste, le seul
#         XAGUSD  +30,3R  (-2,9 puis +33,2)   ← tout vient de la fin : fragile
#         BTCUSD   -3,8R                       ← son spread de 17$ mange le gain
#         XAUUSD  -22,8R                       ← perdant net
#     Le dollar prédit le NASDAQ, pas l'or.
#
#  Convergence notable : le NAS100 est AUSSI le meilleur marché du détecteur
#  d'impulsion (+30R). Deux signaux indépendants qui désignent le même marché,
#  ça mérite qu'on les écoute tous les deux.
# =====================================================
import time

import MetaTrader5 as mt5

FENETRE_H = 8          # on regarde la variation du dollar sur 8 heures
SEUIL_PCT = 0.30       # en dessous, c'est du bruit
PART_SUIVIE = 0.15     # la cible a «…» si elle a fait 15% du mouvement attendu
SL_ATR = 1.5
TP_R = 2.0
SPREAD_MAX_PCT_R = 15.0

# Ce que le dollar pilote vraiment, par ordre de solidité mesurée.
CIBLES = {
    "NAS100": {"poids": 1.0, "note": "robuste : +31,6R, positif sur les deux moitiés"},
    "XAGUSD": {"poids": 0.5, "note": "prometteur mais instable : tout le gain vient de la 2e moitié"},
}

_cache = {"t": 0.0, "res": []}


def _dollar_var(fenetre=FENETRE_H):
    """Variation du dollar (USDX) en % sur la fenêtre. None si indisponible."""
    r = mt5.copy_rates_from_pos("USDX", mt5.TIMEFRAME_H1, 0, fenetre + 2)
    if r is None or len(r) < fenetre + 1:
        # 21/08 : au tout premier appel après initialize(), MT5 renvoie parfois
        # du vide tant que le symbole n'est pas monté dans le Market Watch.
        # On le sélectionne et on retente UNE fois avant d'abandonner.
        try:
            mt5.symbol_select("USDX", True)
            r = mt5.copy_rates_from_pos("USDX", mt5.TIMEFRAME_H1, 0, fenetre + 2)
        except Exception:
            return None
        if r is None or len(r) < fenetre + 1:
            return None
    debut, fin = float(r[-fenetre - 1]["close"]), float(r[-1]["close"])
    return 100 * (fin / debut - 1) if debut else None


def lire(force=False):
    """Retourne la liste des opportunités de divergence dollar en cours.
    Chaque entrée est un plan prêt à exécuter (entrée/SL/TP), ou [] si rien."""
    if not force and time.time() - _cache["t"] < 300:
        return _cache["res"]
    _cache["t"] = time.time()
    out = []
    var_d = _dollar_var()
    if var_d is None or abs(var_d) < SEUIL_PCT:
        _cache["res"] = out
        return out

    attendu = -var_d          # la cible devrait aller à l'inverse du dollar
    for sym, meta in CIBLES.items():
        try:
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, FENETRE_H + 20)
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
            if r is None or len(r) < FENETRE_H + 16 or not info or not tick:
                continue
            C = [float(x["close"]) for x in r]
            H = [float(x["high"]) for x in r]
            L = [float(x["low"]) for x in r]
            var_c = 100 * (C[-1] / C[-FENETRE_H - 1] - 1)

            # a-t-elle déjà suivi ? alors il n'y a plus rien à prendre
            if attendu > 0 and var_c > PART_SUIVIE * attendu:
                continue
            if attendu < 0 and var_c < PART_SUIVIE * attendu:
                continue

            trs = [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
                   for i in range(1, len(C))]
            atr = sum(trs[-14:]) / 14
            if atr <= 0:
                continue
            s = 1 if attendu > 0 else -1
            spread = max(tick.ask - tick.bid, info.point or 0.0)
            prix = tick.ask if s > 0 else tick.bid
            sl = prix - s * SL_ATR * atr
            risque = abs(prix - sl)
            if risque <= 0 or spread > SPREAD_MAX_PCT_R / 100.0 * risque:
                continue
            out.append({
                "symbol": sym,
                "sens": "BUY" if s > 0 else "SELL",
                "entree": prix,
                "sl": round(sl, info.digits),
                "tp": round(prix + s * TP_R * risque, info.digits),
                "dollar_pct": round(var_d, 3),
                "cible_pct": round(var_c, 3),
                "retard_pct": round(attendu - var_c, 3),
                "poids": meta["poids"],
                "note": meta["note"],
            })
        except Exception:
            pass
    _cache["res"] = out
    return out


def contexte() -> str:
    """Bloc injecté dans le cerveau — le volet FONDAMENTAL demandé par le patron."""
    var_d = _dollar_var()
    if var_d is None:
        return "💵 DOLLAR : indice USDX indisponible."
    tete = (f"💵 DOLLAR (USDX) : {var_d:+.2f}% sur {FENETRE_H} h — "
            f"{'il MONTE, donc pression BAISSIÈRE sur les actifs en dollar' if var_d > 0 else 'il BAISSE, donc pression HAUSSIÈRE sur les actifs en dollar' if var_d < 0 else 'stable'}.")
    ops = lire()
    if not ops:
        return (tete + "\nAucune divergence exploitable : soit le dollar est calme, "
                "soit les cibles ont déjà suivi le mouvement (dans ce cas il est "
                "TROP TARD, on ne court pas après).")
    lignes = [tete,
              "⚠️ Mesuré : le dollar n'ANTICIPE pas (corrélation à H+1 ≈ 0). Ce qui "
              "paie, c'est le RETARD d'une cible sur un mouvement du dollar déjà "
              "acquis. Le dollar pilote le NASDAQ ; sur l'or et le BTC ce même "
              "signal a été mesuré PERDANT (-22,8R et -3,8R) — ne pas le jouer là.",
              "OPPORTUNITÉS DE RATTRAPAGE :"]
    for o in ops:
        lignes.append(f"  {o['symbol']} → {o['sens']} | dollar {o['dollar_pct']:+.2f}%, "
                      f"cible {o['cible_pct']:+.2f}%, retard {o['retard_pct']:+.2f}% | "
                      f"entrée {o['entree']}, SL {o['sl']}, TP {o['tp']} | {o['note']}")
    return "\n".join(lignes)


if __name__ == "__main__":
    mt5.initialize()
    print(contexte())
    mt5.shutdown()
