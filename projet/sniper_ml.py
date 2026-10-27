# -*- coding: utf-8 -*-
# =====================================================
#  🎯 SNIPER ML — le ML ne filtre plus : il CHASSE (16/09/26)
#
#  LE PATRON :
#    «…
#      …»
#    «…»
#    «…»
#
#  CE QUI A ÉTÉ MESURÉ LE 16/09 AVANT D'ÉCRIRE UNE LIGNE :
#   · Les entrées de l'EA se décident sur du RSI et des moyennes en M5, jamais
#     validés : 173 trades, 44,5 % gagnants, X €.
#   · Rejugées une par une par le ML v2, sur les trades qu'il n'avait JAMAIS vus :
#        le ML préférait l'INVERSE   27 trades · 30 % · X €/trade
#        le ML préférait CE sens     32 trades · 72 % · X €/trade
#   · Et surtout : l'EA n'est entré AUCUNE fois quand le ML voyait un vrai bon
#     setup (p ≥ 0,42). Il y en a pourtant des centaines par mois.
#   Le bon endroit où se renseigner, c'est celui qui a prouvé qu'il anticipe.
#
#  CE QUE FAIT CE CHASSEUR — exactement la recette qui a été validée :
#   · à chaque clôture de bougie H1, il interroge le ML sur les 10 marchés
#     (le serveur 8001 : un seul modèle, une seule voix)
#   · si un sens franchit SEUIL, il entre au marché dans ce sens
#   · stop = 1 × ATR H1, objectif = 2R, FIXES — ni BE ni trailing : c'est le
#     trade que le banc a mesuré, et les deux ont été mesurés destructeurs
#   · lot minimum, une seule position par marché, sortie forcée après 40 h
#     (l'horizon du label : au-delà, le banc écartait le trade comme indécis)
#
#  LE SEUIL — la «…» est un curseur, et ses deux crans sont mesurés
#  sur six mois glissants, chaque mois jugé par un modèle qui ne l'avait jamais vu :
#       p ≥ 0,42   +0,281 R/trade · 6 mois sur 6 · ~368 occasions/mois
#       p ≥ 0,38   +0,198 R/trade · 6 mois sur 6 · ~1 146 occasions/mois
#  Le patron veut plus de dalle : 0,38. Tripler les occasions pour un gain par
#  trade un peu plus faible, c'est ~2× plus de R par mois.
#
#  SON PROPRE NUMÉRO (MAGIC 424242) : aucun autre bot ne gère ses positions,
#  et on mesure ce qu'il rapporte sans le mélanger à personne. Le cerveau
#  l'exclut de son «…» (qui aurait remonté le stop au BE).
#  Il respecte l'enveloppe de risque commune (budget_risque) — c'est la
#  sécurité du compte, pas un filtre de trade.
# =====================================================
import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import MetaTrader5 as mt5

# 🛑 29/09 — NE JAMAIS FAIRE REVIVRE MT5 (même raison que dans ia_watchdog) :
# mt5.initialize() DÉMARRE le terminal quand il est fermé. Le patron ferme MT5,
# ce script le rouvre : «…». Ici on refuse d'initialiser tant que le
# terminal n'est pas déjà lancé par lui.
import subprocess as _sp_garde, time as _t_garde
_mt5_init_brut = mt5.initialize
_t64_garde = {"t": 0.0, "on": False}


def _terminal_tourne_garde(frais=False):
    # 02/10 : le cache laissait passer un initialize juste apres une fermeture
    # manuelle de MT5 — et MT5 ressuscitait. Avant chaque initialize on exige
    # une mesure de moins d'une seconde.
    if _t_garde.time() - _t64_garde["t"] < (1.0 if frais else 5.0):
        return _t64_garde["on"]
    try:
        r = _sp_garde.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                          capture_output=True, timeout=5, creationflags=0x08000000)
        _t64_garde["on"] = b"terminal64" in (r.stdout or b"")
    except Exception:
        _t64_garde["on"] = True
    _t64_garde["t"] = _t_garde.time()
    return _t64_garde["on"]


mt5.initialize = (lambda *a, **k: _mt5_init_brut(*a, **k) if _terminal_tourne_garde(frais=True) else False)


import ml_v2_entrainer as V
import ml_client

MAGIC = 424242
SEUIL = 0.38
DELAI_APRES_OUVERTURE_S = 75     # le serveur ML garde ses calculs 60 s : on laisse passer
FENETRE_ENTREE_S = 10 * 60       # le banc entrait à l'ouverture de la bougie : pas 40 min après
# 🩹 16/09 (relecture) : la sortie se compte en BOUGIES H1 (V.HORIZON), comme au
# banc — plus en secondes. 40 h d'horloge coupaient au lundi matin tout trade
# ouvert à partir du jeudi, et chaque pause quotidienne volait ~2 bougies.
BOUCLE_S = 20
JOURNAL = HERE / "sniper_ml_journal.jsonl"
# ESSAI : ACID_SNIPER_DRY=1 → tout, sauf envoyer l'ordre ; un seul passage, sans
# attendre la clôture H1. Sert à vérifier le chasseur sans toucher au compte.
ESSAI = os.environ.get("ACID_SNIPER_DRY") == "1"
# 👁️ 16/09 — OBSERVATION par défaut. Le patron veut «…» ; ce chasseur
# vise 2R, donc ~40-48 % de gagnants par construction (rentable sur 6 mois, mais
# pas «…»). Il NOTE chaque setup qu'il aurait pris — entrée, stop,
# objectif — dans sniper_ml_journal.jsonl, sans envoyer d'ordre. Quelques jours de
# signaux réels, résolus contre les prix, diront ce qu'il aurait fait. Le patron
# décide ensuite. Passer à False pour qu'il trade.
OBSERVATION = True

log = logging.getLogger("sniper_ml")


def _journal(**d):
    try:
        d["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _atr_h1(sym):
    """L'ATR EXACT de l'entraînement : moyenne simple des 14 derniers True
    Range sur les bougies H1 CLÔTURÉES (ml_v2_entrainer._series)."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 60)
    if r is None or len(r) < 30:
        return 0.0
    r = r[:-1]
    O = [float(x["open"]) for x in r]; H = [float(x["high"]) for x in r]
    L = [float(x["low"]) for x in r]; C = [float(x["close"]) for x in r]
    S = V._series(O, H, L, C)
    k = len(C) - 1
    return sum(S["tr"][k - 13:k + 1]) / 14


def tenter(sym, sens, p, av):
    if not OBSERVATION and any(q.magic == MAGIC for q in (mt5.positions_get(symbol=sym) or [])):
        log.info(f"🎯 {sym} {sens} p={p:.3f} : déjà une position du sniper sur ce marché")
        return
    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    atr = _atr_h1(sym)
    if not info or not tick or atr <= 0:
        return
    achat = sens == "BUY"
    s = 1 if achat else -1
    prix = tick.ask if achat else tick.bid
    sl = round(prix - s * V.SL_ATR * atr, info.digits)
    tp = round(prix + s * V.TP_R * V.SL_ATR * atr, info.digits)
    mini = (info.trade_stops_level or 0) * info.point
    if mini and abs(prix - sl) < mini * 1.2:
        log.info(f"🎯 {sym} : stop trop proche pour le broker ({abs(prix - sl):.5f} < {mini:.5f})")
        return
    lot = info.volume_min
    typ = mt5.ORDER_TYPE_BUY if achat else mt5.ORDER_TYPE_SELL
    _v = mt5.order_calc_profit(typ, sym, lot, prix, sl)
    risque = abs(float(_v)) if _v is not None else 0.0
    # 🩹 16/09 (relecture) — FAIL-CLOSED. Un risque illisible valait X € et passait
    # tous les plafonds ; un budget illisible laissait passer l'ordre sans trace.
    if risque <= 0:
        ok, raison = False, "risque en euros incalculable (conversion MT5 indisponible)"
    else:
        try:
            import budget_risque
            ok, raison = budget_risque.peut_ouvrir(mt5, "sniper_ml", risque)
        except Exception as e:
            ok, raison = False, f"budget illisible ({e})"
    if OBSERVATION and not ESSAI:
        # 🩹 16/09 : le signal est noté MÊME si le budget refuse — on mesure la
        # qualité du modèle, pas l'occupation du compte à cet instant.
        log.info(f"👁️ SIGNAL {sym} {sens} @ {prix} · SL {sl} · TP {tp} · p={p:.3f} · "
                 f"risque {risque:.2f} € · budget {'OK' if ok else 'REFUS'} (observation : aucun ordre)")
        _journal(evt="signal", sym=sym, sens=sens, p=round(p, 4), prix=prix, sl=sl, tp=tp,
                 lot=lot, risque=round(risque, 2), t_serveur=int(tick.time),
                 bougie=av.get("bougie"), budget_ok=bool(ok), budget_raison=raison or None,
                 p_buy=av.get("p_buy"), p_sell=av.get("p_sell"))
        return
    if not ok:
        log.info(f"🎯 {sym} {sens} p={p:.3f} refusé par l'enveloppe de risque : {raison}")
        if ESSAI:
            return
        _journal(evt="refus_budget", sym=sym, sens=sens, p=round(p, 4), risque=round(risque, 2),
                 raison=raison)
        return
    if ESSAI:
        log.info(f"🧪 (essai) AURAIT OUVERT {sym} {sens} {lot} @ {prix} · SL {sl} · TP {tp} · "
                 f"p={p:.3f} · risque {risque:.2f} € · budget : {raison or 'OK'}")
        return
    res = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot, "type": typ,
        "price": prix, "sl": sl, "tp": tp, "deviation": 20, "magic": MAGIC,
        "comment": f"ML_SNIPER|p={p:.2f}", "type_filling": mt5.ORDER_FILLING_IOC,
    })
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"🎯 ENTRÉE {sym} {sens} {lot} @ {prix} · SL {sl} · TP {tp} · p={p:.3f} "
                 f"· risque {risque:.2f} €")
        _journal(evt="entree", sym=sym, sens=sens, p=round(p, 4), prix=prix, sl=sl, tp=tp,
                 lot=lot, risque=round(risque, 2), p_buy=av.get("p_buy"), p_sell=av.get("p_sell"),
                 ticket=getattr(res, "order", None))
    else:
        log.warning(f"🎯 {sym} {sens} : ordre refusé ({getattr(res, 'retcode', '?')} "
                    f"{getattr(res, 'comment', '')})")
        _journal(evt="ordre_refuse", sym=sym, sens=sens, p=round(p, 4),
                 code=getattr(res, "retcode", None), comment=getattr(res, "comment", ""))


def fermer_les_vieux():
    """Au-delà de 40 bougies H1, le banc solde le trade au marché (ml_v2_entrainer
    ._issue). En direct, pareil — et les 40 bougies sont des BOUGIES, pas 40 h :
    le week-end et les pauses du marché ne comptent pas."""
    for q in (mt5.positions_get() or []):
        if q.magic != MAGIC:
            continue
        tick = mt5.symbol_info_tick(q.symbol)
        if not tick:
            continue
        r = mt5.copy_rates_from_pos(q.symbol, mt5.TIMEFRAME_H1, 0, V.HORIZON + 10)
        if r is None or len(r) < 2:
            continue
        ouverture_entree = int(q.time) // 3600 * 3600      # la bougie H1 où il est entré
        jouees = sum(1 for x in r[:-1] if int(x["time"]) >= ouverture_entree)   # bougies CLÔTURÉES
        if jouees < V.HORIZON:
            continue
        achat = q.type == mt5.POSITION_TYPE_BUY
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": q.symbol, "volume": q.volume,
            "type": mt5.ORDER_TYPE_SELL if achat else mt5.ORDER_TYPE_BUY,
            "position": q.ticket, "price": tick.bid if achat else tick.ask,
            "deviation": 20, "magic": MAGIC, "comment": "ML_SNIPER|40h",
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        ok = res and res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"⏳ {q.symbol} #{q.ticket} : {V.HORIZON} bougies H1 sans stop ni objectif → soldé "
                 f"{'OK' if ok else 'REFUSÉ'} (P/L {q.profit:+.2f} €)")
        _journal(evt="sortie_40h", sym=q.symbol, ticket=q.ticket, pl=round(q.profit, 2), ok=bool(ok))


def fiche():
    try:
        import tableau
        mes = [q for q in (mt5.positions_get() or []) if q.magic == MAGIC]
        tableau.ecrire("sniper", seuil=SEUIL, positions=len(mes),
                       flottant_eur=round(sum(q.profit for q in mes), 2),
                       marches=",".join(sorted({q.symbol for q in mes})) or None)
    except Exception:
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),   # stdout reconfiguré en UTF-8 (stderr ne l'est pas)
                  RotatingFileHandler(HERE / "sniper_ml.log", maxBytes=2 * 1024 * 1024,
                                      backupCount=2, encoding="utf-8")])
    log.info(f"🎯 SNIPER ML démarré · seuil p ≥ {SEUIL} · stop 1×ATR H1 · objectif 2R · "
             f"magic {MAGIC} · {len(V.SYMBOLES)} marchés"
             f"{' · 👁️ OBSERVATION (aucune nouvelle entrée)' if OBSERVATION else ' · ⚔️ TRADE'}")
    deja_vu = {}
    while True:
        try:
            if not mt5.initialize():
                time.sleep(BOUCLE_S)
                continue
            if not ESSAI:                           # 🩹 16/09 : l'essai ne touche JAMAIS au compte
                fermer_les_vieux()
            a_juger = []
            attendue = {}
            for sym in V.SYMBOLES:
                mt5.symbol_select(sym, True)
                r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2)
                tick = mt5.symbol_info_tick(sym)
                if r is None or len(r) < 2 or not tick:
                    continue
                ouverture = int(r[-1]["time"])      # la bougie qui vient de s'ouvrir
                attendue[sym] = int(r[-2]["time"])  # celle que le ML doit avoir jugée
                if deja_vu.get(sym) == ouverture:
                    continue
                age = int(tick.time) - ouverture
                if ESSAI:
                    a_juger.append(sym); continue
                if age < DELAI_APRES_OUVERTURE_S:
                    continue
                deja_vu[sym] = ouverture            # jugée une seule fois par bougie
                if age > FENETRE_ENTREE_S:
                    continue                        # trop tard : le prix a déjà bougé
                a_juger.append(sym)
            if a_juger:
                ml_client._cache.clear()
                avis = ml_client.avis_lot(a_juger)
                if not avis:
                    log.warning(f"🎯 le serveur ML ne répond pas — {len(a_juger)} marché(s) non jugé(s)")
                for sym in a_juger:
                    a = avis.get(sym)
                    if not a or a.get("p") is None:
                        continue
                    # 🩹 16/09 (relecture) : le serveur garde ses calculs 60 s. Si le
                    # premier tick de l'heure arrive en retard, il a pu juger la
                    # bougie D'AVANT. On ne tire pas sur un avis périmé : on rejuge
                    # au tour suivant (la fenêtre d'entrée est de 10 min).
                    if (not ESSAI and a.get("bougie") is not None
                            and int(a["bougie"]) != attendue.get(sym)):
                        deja_vu.pop(sym, None)
                        log.info(f"   {sym:<9} avis ML sur une bougie périmée — on rejuge au tour suivant")
                        continue
                    if a["p"] >= SEUIL:
                        tenter(sym, a["sens"], a["p"], a)
                    else:
                        log.info(f"   {sym:<9} {a['sens']:<4} p={a['p']:.3f} (< {SEUIL}) — rien")
            if ESSAI:
                log.info("🧪 essai terminé — aucun ordre envoyé")
                break
            fiche()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"boucle : {e}")
        time.sleep(BOUCLE_S)


if __name__ == "__main__":
    main()
