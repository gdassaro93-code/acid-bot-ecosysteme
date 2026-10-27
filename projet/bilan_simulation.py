# -*- coding: utf-8 -*-
# =====================================================
#  🧪 BILAN DE SIMULATION — «…»
#  (demande patron 22/08, avant de remettre X € sur le compte)
#
#  L'ŒIL tourne en mode SIMULATION : il décide pour de vrai mais n'envoie
#  aucun ordre — il les écrit dans simulation_trades.jsonl. Ce script les
#  rejoue sur les prix RÉELS et répond aux seules questions qui comptent :
#     • combien le compte vaudrait-il aujourd'hui ?
#     • quelle est la pire perte qu'il aurait fait subir (drawdown) ?
#     • est-ce qu'il saigne lentement, ou est-ce qu'il gagne ?
#
#  Utilisation :
#      python bilan_simulation.py            # capital de départ X €
#      python bilan_simulation.py 250        # autre capital
# =====================================================
import json
import sys
from datetime import datetime
from pathlib import Path

import MetaTrader5 as mt5

HERE = Path(__file__).resolve().parent
FICHIER = HERE / "simulation_trades.jsonl"


def charger():
    if not FICHIER.exists():
        return []
    out = []
    for ligne in FICHIER.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ligne))
        except Exception:
            pass
    return out


def rejouer(capital=100.0):
    mt5.initialize()
    trades = [t for t in charger() if t.get("action") in ("MARCHE", "PENDING")
              and t.get("sl") and t.get("volume")]
    if not trades:
        print("🧪 Aucun trade simulé pour l'instant.")
        print("   Lance L'ŒIL (SIMULATION = True) et laisse-le tourner quelques heures.")
        mt5.shutdown()
        return

    debut = datetime.fromtimestamp(min(t["ts"] for t in trades))
    print(f"🧪 BILAN DE SIMULATION — {len(trades)} ordres depuis le "
          f"{debut:%d/%m %H:%M}\n")

    solde = capital
    pic = capital
    creux_max = 0.0
    gagnants = perdants = encours = 0
    detail = {}

    for t in trades:
        sym, vol = t["symbol"], float(t["volume"])
        entree, sl, tp = float(t["prix"] or 0), float(t["sl"]), float(t.get("tp") or 0)
        if entree <= 0:
            continue
        # BUY = types 0,2,4 chez MT5 ; SELL = 1,3,5
        est_achat = t.get("type") in (0, 2, 4)
        # on rejoue les bougies M5 depuis l'ordre
        r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M5,
                                 datetime.fromtimestamp(t["ts"]), datetime.now())
        if r is None or len(r) == 0:
            continue
        issue = None
        for b in r:
            hi, lo = float(b["high"]), float(b["low"])
            if est_achat:
                if lo <= sl:
                    issue = "perte"
                    break
                if tp and hi >= tp:
                    issue = "gain"
                    break
            else:
                if hi >= sl:
                    issue = "perte"
                    break
                if tp and lo <= tp:
                    issue = "gain"
                    break
        prix_sortie = sl if issue == "perte" else (tp if issue == "gain" else float(r[-1]["close"]))
        try:
            pnl = mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY if est_achat else mt5.ORDER_TYPE_SELL,
                sym, vol, entree, prix_sortie) or 0.0
        except Exception:
            pnl = 0.0

        solde += pnl
        pic = max(pic, solde)
        creux_max = max(creux_max, pic - solde)
        if issue == "gain":
            gagnants += 1
        elif issue == "perte":
            perdants += 1
        else:
            encours += 1
        d = detail.setdefault(sym, [0, 0.0])
        d[0] += 1
        d[1] += pnl

    clos = gagnants + perdants
    print(f"{'SYMBOLE':10} {'ordres':>7} {'RESULTAT':>10}")
    for s, (n, p) in sorted(detail.items(), key=lambda x: x[1][1]):
        print(f"  {s:10} {n:7d} {p:+9.2f}€")
    print("-" * 32)
    print(f"\n💰 Capital de départ : {capital:.2f}€")
    print(f"💰 Capital simulé    : {solde:.2f}€   ({solde - capital:+.2f}€, "
          f"{100 * (solde - capital) / capital:+.1f}%)")
    print(f"📉 Pire creux subi   : -{creux_max:.2f}€ "
          f"({100 * creux_max / capital:.1f}% du capital)")
    if clos:
        print(f"🎯 Trades clos       : {clos}  →  {gagnants} gagnants / {perdants} perdants "
              f"({100 * gagnants / clos:.0f}%)")
    print(f"⏳ Encore ouverts    : {encours}")

    print("\n" + "=" * 58)
    if solde > capital and creux_max < capital * 0.3:
        print("✅ VERDICT : il gagne, et sans creux dangereux.")
        print("   Tu peux envisager de le passer en réel (SIMULATION = False).")
    elif solde > capital:
        print("⚠️ VERDICT : il gagne, MAIS le creux traversé est important.")
        print(f"   Avec {capital:.0f}€ tu aurais vu ton compte descendre à "
              f"{capital - creux_max:.2f}€ avant de remonter. Baisse le risque avant le réel.")
    elif clos < 20:
        print("⏳ VERDICT : trop tôt pour juger — moins de 20 trades clos.")
        print("   Laisse tourner encore. Un verdict sur 5 trades ne vaut rien.")
    else:
        print("❌ VERDICT : il perd. NE PAS passer en réel.")
        print("   C'est exactement le « petit feu » que tu craignais — et il a coûté")
        print("   0€ à découvrir. C'est à ça que sert la simulation.")
    print("=" * 58)
    mt5.shutdown()


if __name__ == "__main__":
    cap = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
    rejouer(cap)
