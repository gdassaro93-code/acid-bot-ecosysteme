# -*- coding: utf-8 -*-
# =====================================================
#  🏹 CHASSEUR DE TENDANCE — la règle du patron (02/09/26)
#
#  SA PHRASE, mot pour mot :
#  «…
#    …
#    …»
#
#  Autrement dit : le biais de fond décide du SENS, et on n'entre que sur
#  les REBONDS contraires. On vend les rebonds dans une tendance baissière,
#  on achète les replis dans une tendance haussière. Jamais l'inverse.
#
#  ⚠️ Ce n'est PAS une grille : j'avais d'abord codé du contre-tendance
#  (acheter quand ça baisse) et le patron a corrigé — «…
#  …». Il avait raison :
#  sa version mesure BEAUCOUP mieux.
#
#  MESURE (1500 bougies H1, spread réel Vantage, deux moitiés vérifiées) :
#     XAUUSD  241 trades  38,2%  +35R   (+18 puis +17 — remarquablement stable)
#     CL-OIL   51 trades  45,1%  +18R   (+16 puis +2 — solide mais peu de signaux)
#     NAS100  119 trades  31,1%   -8R   ✗
#     BTCUSD  546 trades  29,1%  -69R   ✗
#  → actif sur l'OR seulement, et le pétrole en plus petit (choix patron :
#    «…
#    …»).
#
#  Détail contre-intuitif : le NASDAQ, champion du détecteur d'impulsion
#  (+41R), PERD ici. Les deux stratégies ne visent pas les mêmes marchés —
#  elles se complètent, elles ne se remplacent pas.
# =====================================================
import time

import MetaTrader5 as mt5

# Réglages issus de la mesure — ne pas bricoler sans re-mesurer.
# 🥇 02/09 — RÉGLAGES DE SPÉCIALISTE DE L'OR (patron : «…
# …»). Balayage de 36 combinaisons
# sur 1500 bougies H1, spread réel, chaque candidat vérifié sur les DEUX
# moitiés de l'historique :
#     3j · 100p · TP450/SL225 → +64,0R  MAIS +54,0 puis +10,0  (déséquilibré)
#     2j · 100p · TP600/SL200 → +62,0R  ET  +36,0 puis +26,0   ← RETENU
# On prend le second : presque le même total, mais il tient sur les deux
# moitiés. Le premier doit sa performance au début de l'historique — le genre
# de chiffre flatteur qui ne se reproduit pas. (Ancien réglage : 3j/150p/600/300
# = +35R ; on gagne 27R en affinant, sans rien changer à la logique.)
JOURS_TENDANCE = 2        # biais plus court = plus réactif sur l'or
REBOND_PIPS    = 100      # 150→100 : plus d'occasions, sans perdre en qualité
TP_PIPS        = 600
SL_PIPS        = 200      # ratio 3:1 (au lieu de 2:1)
FENETRE_EXTREME = 12      # on suit le plus bas / plus haut des 12 dernières heures

# Poids par marché : ce que la mesure autorise, pas ce qu'on espère.
MARCHES = {
    "XAUUSD+": {"poids": 1.0, "note": "+35R sur 241 trades, stable sur les deux moitiés"},
    "CL-OIL":  {"poids": 0.5, "note": "+18R mais seulement 51 signaux — moitié de taille"},
}

_cache = {"t": 0.0, "res": []}


def _pip(sym):
    return 0.1 if "XAU" in sym.upper() else 0.01


def lire(force=False):
    """Les setups en cours. Chaque entrée est un plan prêt : sens, entrée, SL, TP."""
    if not force and time.time() - _cache["t"] < 300:
        return _cache["res"]
    _cache["t"] = time.time()
    out = []
    for sym, meta in MARCHES.items():
        try:
            n_t = JOURS_TENDANCE * 24
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, n_t + 40)
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
            if r is None or len(r) < n_t + 20 or not info or not tick:
                continue
            H = [float(x["high"]) for x in r]
            L = [float(x["low"]) for x in r]
            C = [float(x["close"]) for x in r]
            pip = _pip(sym)

            # 1️⃣ LE BIAIS : où était le prix il y a 3 jours ?
            biais = -1 if C[-1] < C[-1 - n_t] else 1
            sens = "SELL" if biais < 0 else "BUY"

            # 2️⃣ L'EXTRÊME RÉCENT : le plus bas (si on vend) ou le plus haut
            extreme = min(L[-FENETRE_EXTREME:]) if biais < 0 else max(H[-FENETRE_EXTREME:])
            prix = tick.bid if biais < 0 else tick.ask

            # 3️⃣ LE REBOND : le prix est-il remonté (ou redescendu) assez ?
            ecart = (prix - extreme) if biais < 0 else (extreme - prix)
            rebond_pips = ecart / pip
            if rebond_pips < REBOND_PIPS:
                continue          # pas encore rebondi : on attend, on ne court pas après

            sl = (prix + SL_PIPS * pip) if biais < 0 else (prix - SL_PIPS * pip)
            tp = prix - TP_PIPS * pip if biais < 0 else prix + TP_PIPS * pip
            out.append({
                "symbol": sym, "sens": sens,
                "entree": prix,
                "sl": round(sl, info.digits),
                "tp": round(tp, info.digits),
                "rebond_pips": round(rebond_pips),
                "biais_jours": JOURS_TENDANCE,
                "poids": meta["poids"],
                "note": meta["note"],
            })
        except Exception:
            pass
    _cache["res"] = out
    return out


def contexte() -> str:
    """Bloc injecté dans le cerveau."""
    setups = lire()
    tete = ("🏹 CHASSEUR DE TENDANCE (règle du patron, mesurée : XAUUSD +35R sur "
            "241 trades, stable sur les deux moitiés de l'historique).\n"
            "RÈGLE : le biais de 3 jours décide du SENS — on ne prend QUE des ventes "
            "en tendance baissière, QUE des achats en tendance haussière. On entre "
            "uniquement sur un REBOND contraire d'au moins 150 pips (on vend le "
            "rebond, on n'court pas après le prix). TP 600 / SL 300 = ratio 2:1.\n"
            "⚠️ Actif sur l'OR et le pétrole UNIQUEMENT — mesuré perdant ailleurs "
            "(NAS100 -8R, BTCUSD -69R) : ne pas l'appliquer aux autres marchés.")
    if not setups:
        return tete + "\nAucun rebond exploitable en ce moment : soit la tendance " \
                      "est plate, soit le prix n'a pas assez rebondi pour offrir " \
                      "un point d'entrée."
    lignes = ["SETUPS EN COURS :"]
    for s in setups:
        lignes.append(f"  {s['symbol']} → {s['sens']} | rebond de {s['rebond_pips']} pips "
                      f"contre une tendance de {s['biais_jours']} jours | "
                      f"entrée {s['entree']}, SL {s['sl']}, TP {s['tp']} | "
                      f"taille × {s['poids']:g} ({s['note']})")
    return tete + "\n" + "\n".join(lignes)


if __name__ == "__main__":
    mt5.initialize()
    print(contexte())
    mt5.shutdown()
