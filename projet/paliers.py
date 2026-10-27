# -*- coding: utf-8 -*-
# =====================================================
#  🪜 PALIERS DE CAPITAL — la règle du patron (04/09/26)
#
#  SES PHRASES, mot pour mot :
#  «…
#    …
#    …»
#  «…
#    …»
#  «…»
#  «…»
#  «…
#    …»
#
#  L'IDÉE : plus le compte est petit, plus l'univers est étroit et plus on
#  tolère de drawdown (parce qu'un petit compte ne peut pas se diversifier
#  et doit accepter de respirer). Plus il grossit, plus on élargit et plus
#  on serre le risque. Les deux mouvements sont inverses, et c'est voulu.
#
#  ⚠️ CE MODULE NE SAIT PAS SI LE COMPTE EST RÉEL OU DÉMO, ET NE DOIT
#     JAMAIS L'APPRENDRE. Voir la règle gravée dans budget_risque.py :
#     «…».
#     Le CAPITAL est un fait objectif, identique en démo et en réel — il a
#     le droit de commander. Le STATUT du compte, non.
# =====================================================

# ── L'UNIVERS, par ordre de mérite MESURÉ (€/jour d'immobilisation, audit 30j)
#    NAS100 X € · BTCUSD X € · SP500 X € · EURUSD X €
#    XAUUSD+ et CL-OIL sont gardés par choix du patron (spécialité or) : ils
#    n'ont jamais pu s'exprimer sur un compte de X € (89% du capital/trade).
# ── L'UNIVERS N'EST PLUS UNE LISTE, C'EST UNE MESURE (08/09, décidé avec le patron)
# Avant : des paliers en dur (BTCUSD/NAS100 jusqu'à X €…) dont le coût était estimé
# avec un stop de 1,5×ATR H1 — alors que la stratégie qui tourne pose son stop à 5×ATR
# M15. Résultat mesuré ce matin à X € : le palier autorisait BTCUSD (X € la jambe,
# 14 % du capital) que le budget refusait à 9 %, et bloquait SP500 (X €, 3,9 %) qui
# rentrait largement. Le bot ne pouvait rien ouvrir du tout.
# Désormais : un marché entre dans l'univers QUAND SA JAMBE MINIMALE TIENT DANS LE
# BUDGET DE RISQUE, mesurée avec le vrai stop. Ça s'élargit tout seul quand le compte
# grossit, ça se resserre quand la volatilité monte, et ça ne bannit aucun marché par
# opinion — seulement par arithmétique. (Règle du patron : «…».)
UNIVERS = ["BTCUSD", "ETHUSD", "NAS100", "SP500", "XAUUSD+", "XAGUSD",
           "CL-OIL", "EURUSD+", "USDJPY+", "GBPUSD+"]
# USDX n'y figure pas : c'est le capteur du signal dollar, jamais un marché.

SL_ATR_REEL = 5.0             # le stop de la stratégie validée — la mesure honnête
TIMEFRAME_MESURE = "M15"

# ── Le risque dépend de la SOURCE du signal (point 3, retenu par le patron)
# 9 % : la stratégie validée sur 2 ans hors échantillon (retour à la moyenne) — elle
#       n'a jamais fait deux pertes d'affilée sur la période.
# 3 % : tout le reste (scalp IA de MAMMOUTH, idées du cerveau, reprises). Ces
#       sources n'ont AUCUNE validation hors échantillon : elles ne méritent pas le
#       même ticket. Avant, les deux tapaient à 9 %.
# 🔓 15/10 — LE PATRON OUVRE LES VANNES, compte RÉEL X €.
# Ses mots : «…
# …», «…», «…»,
# «…
# …». Mesuré sur SON compte le 15/10 : 0.01 sur l'or risque
#X € = 10,3 % — donc ses 3 lots font 31 %. Plafond posé à 35 % pour
# que sa règle des 3 lots puisse exister. Décision assumée : 3 pertes
# d'affilée à cette taille = -66 % du compte. Il le sait, il l'a dit.
RISQUE_VALIDE_PCT     = 1.0    # version publique : réglage de base prudent (voir README.txt)
RISQUE_PENDING_PCT     = 1.0   # les PIÈGES ont leur propre taux (version publique : 1 %).
                              # «…
                              # …» · «…
                              # …». Mesuré : l'or en 0.02 sur 30 pips coûte X € —
                              # une grosse part d'un petit compte. À 3 % tout était refusé sauf
                              # BTC et ETH. Un piège posé sur une zone travaillée n'est
                              # pas un scalp impulsif : il ne mérite pas le même plafond.
RISQUE_NON_VALIDE_PCT     = 0.5    # version publique : réglage de base prudent
SOURCES_VALIDEES = ("retour",)
SOURCES_PENDING  = ("pending", "zone", "plan", "conv")   # les pièges et le plan du jour
RISQUE_BLOC_PCT     = 0.5   # la figure du patron, testée en réel (version publique : 0,5 %).
                         # Mon backtest la rejetait (le miroir gagnait plus, le décalage
                         # d'une bougie tuait l'avantage) — mais mes trois moteurs du jour
                         # avaient chacun un bug, donc le marché tranche. 5 % : assez pour
                         # que le test soit vrai, pas assez pour coûter cher s'il perd.
RISQUE_PAR_TRADE_PCT = RISQUE_VALIDE_PCT      # compat : l'ancien nom reste lisible

# ── Les seuils de capital (les seules valeurs en dur qui restent)
SEUIL_PETIT = 200.0           # «…» (patron, 08/09)
SEUIL_MOYEN = 400.0

# 🪜 LES PALIERS DE MARCHÉS (patron, 08/09 au soir) : «…
# …».
# Les trois sont MESURÉS sur son propre compte, pas choisis à l'intuition.
SEUIL_TROIS  = 100.0
SEUIL_CINQ   = 200.0
TROIS_MEILLEURS = ["BTCUSD", "NAS100", "SP500"]          # X € · X € · X €
DEUX_DE_PLUS    = ["EURUSD+", "USDJPY+"]                 # X € · X €


def univers_du_palier(capital: float) -> list:
    # 🔓 15/10 — LE PATRON OUVRE TOUT : «…
    # …». Son journal du 15/10
    # disait «…» et lui interdisait
    # l'or — le marché qu'il travaille le mieux — parce qu'il est sous X €.
    # Les seuils de capital ne ferment plus aucun marché. Ce qui décide
    # maintenant, c'est le coût réel d'une jambe face au budget, rien d'autre.
    # return list(UNIVERS)   # vanne du 15/10 désactivée dans la version publique : les paliers de capital ci-dessous s'appliquent

    """Les marchés que le CAPITAL ouvre (avant même la question du coût d'une jambe).
    Sous X € : les trois qui gagnent chez lui. Jusqu'à X € : cinq. Au-delà : tout.
    Rien n'est banni définitivement — tout se rouvre à X €."""
    if capital < SEUIL_TROIS:
        return list(TROIS_MEILLEURS)
    if capital < SEUIL_CINQ:
        return TROIS_MEILLEURS + DEUX_DE_PLUS
    return list(UNIVERS)


def risque_pct(source: str = None) -> float:
    """Le % du capital qu'une idée a le droit de risquer, selon d'où elle vient.
       9 % : la stratégie validée sur 2 ans hors échantillon (retour à la moyenne).
       8 % : les pièges posés d'avance et le plan du jour — travaillés, pas impulsifs.
       3 % : tout le reste (scalp IA, idées du cerveau, reprises)."""
    s = (source or "").lower()
    if s in SOURCES_VALIDEES:
        return RISQUE_VALIDE_PCT
    if s in SOURCES_PENDING:
        return RISQUE_PENDING_PCT
    if s == "bloc":
        return RISQUE_BLOC_PCT
    return RISQUE_NON_VALIDE_PCT


def lignes_par_symbole(capital: float) -> int:
    """Positions simultanées autorisées sur UN marché. Règle du patron : 2 sous X €."""
    if capital < SEUIL_PETIT:
        return 2
    return 3 if capital < SEUIL_MOYEN else 5


def jambes_par_idee(capital: float) -> int:
    """TP1/TP2/TP3 coûtent 3 fois le risque sur UNE idée : à X €, 27 % du compte.
    Sous X € on n'en pose qu'une ; les trois reviennent à X €."""
    if capital < SEUIL_PETIT:
        return 1
    return 2 if capital < SEUIL_MOYEN else 3


def lot_max(capital: float, defaut: float = 0.02) -> float:
    """Plafond de lot. Patron : «…» tant qu'on n'est pas à X €."""
    return 0.02 if capital < SEUIL_PETIT else defaut


def kill_switch_pct(capital: float) -> float:
    """«…
    …»."""
    if capital < 500:
        return 15.0   # version publique : 15 % quel que soit le capital
    return 15.0   # version publique : 15 % quel que soit le capital


def cout_mini_broker(mt5, symbole):
    """💶 08/09 — LE COÛT PLANCHER : lot minimum × le stop le plus SERRÉ que le broker
    accepte (stops_level + 2 spreads). C'est la bonne question pour l'univers :
    «…» — et non «…
    …».
    Mesure du 08/09 : à X €, l'or coûte X € avec un stop de 5×ATR (donc exclu)
    mais X € au stop minimum — et le patron venait justement de le trader avec un
    stop de 15 pips. On n'interdit plus un marché d'avance : c'est le contrôle par
    ORDRE (_risque_trade_ok, peut_ouvrir) qui refuse un stop trop large."""
    try:
        i = mt5.symbol_info(symbole)
        t = mt5.symbol_info_tick(symbole)
        if not i or not t or not t.ask:
            return None
        sp = i.spread * i.point
        d = (i.trade_stops_level or 0) * i.point + 2 * sp
        if d <= 0:
            d = max(4 * sp, i.point * 10)
        p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbole, i.volume_min, t.ask, t.ask - d)
        return abs(p or 0.0)
    except Exception:
        return None


def cout_reel(mt5, symbole, sl_atr: float = SL_ATR_REEL):
    """💶 Ce qu'UNE JAMBE coûte VRAIMENT, chez le broker, à l'instant : lot minimum
    × le stop RÉEL de la stratégie (5×ATR M15), converti en euros par MT5.
    Mesuré en direct et pas en dur : le 04/09 l'ATR du NAS100 est passé de 93 à 42
    pips en deux heures — un seuil figé aurait interdit à tort le meilleur marché.
    Renvoie (risque_eur, marge_eur), ou (None, None) si indisponible."""
    try:
        _i = mt5.symbol_info(symbole)
        _tk = mt5.symbol_info_tick(symbole)
        _tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME_MESURE)
        _r = mt5.copy_rates_from_pos(symbole, _tf, 1, 15)
        if not _i or not _tk or _r is None or len(_r) < 15:
            return None, None
        _H = [float(x["high"]) for x in _r]
        _L = [float(x["low"]) for x in _r]
        _C = [float(x["close"]) for x in _r]
        _tr = [max(_H[k] - _L[k], abs(_H[k] - _C[k - 1]), abs(_L[k] - _C[k - 1]))
               for k in range(1, len(_r))]
        _atr = sum(_tr) / len(_tr)
        if _atr <= 0:
            return None, None
        _p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbole, _i.volume_min,
                                   _tk.ask, _tk.ask - sl_atr * _atr)
        _m = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbole, _i.volume_min, _tk.ask)
        return abs(_p or 0.0), float(_m or 0.0)
    except Exception:
        return None, None


def palier(capital: float, mt5=None, source: str = None) -> dict:
    """L'état du capital. Ne renvoie QUE des faits, jamais une décision."""
    pct = risque_pct(source)
    budget = capital * pct / 100.0
    financables, bloques, couts = [], {}, {}
    for _s in univers_du_palier(capital):
        if mt5 is None:
            financables.append(_s)
            continue
        _risque, _marge = cout_reel(mt5, _s)      # coût avec le stop de la stratégie
        _plancher = cout_mini_broker(mt5, _s)     # coût au stop le plus serré possible
        if _risque:
            couts[_s] = _risque
        # 08/09 : c'est le PLANCHER qui décide de l'univers. Un marché reste
        # atteignable tant qu'un stop serré y tient dans le budget.
        _ref = _plancher if _plancher else _risque
        if _ref is None:
            continue                      # marché muet (fermé, illisible) : on n'invente pas
        if _ref <= budget:
            financables.append(_s)
        else:
            bloques[_s] = round(_ref * 100.0 / pct)   # capital qu'il faudrait
    lignes = lignes_par_symbole(capital)
    kill = kill_switch_pct(capital)
    return {
        "capital": capital,
        "seuil": SEUIL_PETIT if capital < SEUIL_PETIT else (SEUIL_MOYEN if capital < SEUIL_MOYEN else 0),
        "note": ("petit capital : 1 jambe par idée, 2 lignes par marché, lot 0.02"
                 if capital < SEUIL_PETIT else "capital moyen" if capital < SEUIL_MOYEN
                 else "capital confortable : les 3 jambes reviennent"),
        "symboles": financables,          # ce qu'il PEUT vraiment trader, mesuré
        "autorisés": univers_du_palier(capital),
        "bloqués_faute_de_capital": bloques,
        "kill_switch_pct": kill,
        "risque_trade_pct": pct,
        "perte_jour_max_eur": round(capital * kill / 100.0, 2),
        "lignes_par_symbole": lignes,
        "jambes_par_idee": jambes_par_idee(capital),
        "lot_max": lot_max(capital),
        "meme_sens_interdit": capital < SEUIL_PETIT,
        "positions_max": len(financables) * lignes,
        "cout_par_jambe": couts,
    }


def contexte(capital: float, mt5=None) -> str:
    """Bloc lisible — pour Telegram et pour le cerveau."""
    p = palier(capital, mt5)
    t = (f"🪜 CAPITAL {p['capital']:.2f}€ — {p['note']}\n"
         f"   risque {p['risque_trade_pct']:g}%/trade · {p['jambes_par_idee']} jambe(s) par idée · "
         f"{p['lignes_par_symbole']} ligne(s) max par marché · lot max {p['lot_max']:g}\n"
         + ("   ⛔ pas de 2e entrée dans le MÊME SENS sur un marché déjà occupé "
            "(le sens inverse reste permis)\n" if p['meme_sens_interdit'] else ""))
    if p["symboles"]:
        t += f"   ✅ tradables : {', '.join(p['symboles'])} "
        t += f"({p['positions_max']} positions max au total)\n"
        for _s in p["symboles"]:
            _c = p["cout_par_jambe"].get(_s)
            if _c:
                t += ("      " + _s + " : " + format(_c, ".2f") + "EUR la jambe ("
                      + format(_c / capital * 100, ".1f") + "% du capital)" + chr(10))
    else:
        t += "   ⛔ AUCUN marché finançable à ce capital — ne rien ouvrir.\n"
    if p["bloqués_faute_de_capital"]:
        t += "   ⏳ ouverts par le palier mais PAS finançables : " + ", ".join(
            f"{s} (il faut {c}€)" for s, c in p["bloqués_faute_de_capital"].items()) + "\n"
    t += (f"   🛑 kill-switch à -{p['kill_switch_pct']:g}% "
          f"= -{p['perte_jour_max_eur']:.2f}€ sur ce capital\n")
    return t


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        import MetaTrader5 as _mt
        _mt.initialize()
        _a = _mt.account_info()
        print("=== TON COMPTE MAINTENANT ===")
        print(contexte(float(_a.balance), _mt))
        print("=== LA PROGRESSION PAR PALIER ===")
        for _c in (200, 400, 500, 2000):
            print(contexte(float(_c), _mt))
        _mt.shutdown()
    except Exception as _e:
        print("MT5 indisponible :", _e)
