# -*- coding: utf-8 -*-
# =====================================================
#  🏟️ ARÈNE DES MODÈLES — la compétition demandée le 09/07
#  5 champions (GPT / Claude / Gemini / Mistral / Grok) — Opus et Sonnet 5
#  virés le 14/07 (7411 décisions : les gros raisonneurs perdent au scalp)
#  reçoivent EXACTEMENT les mêmes données de marché en direct, décident,
#  et le MARCHÉ les note (barrière ±1 ATR, comme le ML V1/V2).
#  100 % observation (shadow) : aucun ordre, aucune interférence.
#  Coût : 0 de plus (forfait mammouth, ~7 requêtes/min max).
#  12/07 : Fable 5 demandé aussi mais indisponible chez mammouth (HTTP 400
#  "Invalid model name") — seuls opus-4.8 et sonnet-5 répondent (testé).
#  Usage :
#     python model_arena.py           -> boucle (1 round / 5 min)
#     python model_arena.py once      -> un seul round (test)
#     python model_arena.py stats     -> le classement
# =====================================================
import io
import re
import sys
import json
import time
import csv
from datetime import datetime
from pathlib import Path

import requests
import MetaTrader5 as mt5

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
from secrets_acid import MAMMOUTH_API_KEY
from token_meter import compte as compte_tokens   # 🧮 compteur journalier (14/07)

CHAMPIONS = {
    "gpt":     "gpt-5.4-mini",
    "claude":  "claude-sonnet-4-6",
    "gemini":  "gemini-3.5-flash",
    "mistral": "mistral-large-3",
    # 🥊 28/08 (patron : «…») :
    # medium entre en lice contre large. Contexte : medium était le cerveau
    # de L'ŒIL (514 réponses) parce qu'il répond en 1,20 s contre 5,01 s.
    # Mais sur un cas réel il raisonnait FAUX (il comparait X € de risque à
    # un ATR de 17,8$ pour refuser un trade), pendant que large — déjà
    # champion ici avec 68% de réussite et +665R sur 1873 trades — décidait.
    # Que le marché tranche : c'est lui le seul juge.
    "mistralmed": "mistral-medium-3-5",
    "grok":    "grok-4.3",
    # 🧪 29/07 (patron) : Kimi K3 ajoute au championnat. Nom d'API confirme
    # par sonde directe mammouth.ai = "kimi-k3" (les autres formes -> 400).
    "kimi":    "kimi-k3",
    # ⚰️ 14/07, verdict du patron sur 7411 décisions : opus (-0.25 R/trade,
    # WR 37%) et sonnet5 (-0.27, WR 36%) VIRÉS du championnat — «…
    # …» : les gros raisonneurs sur-analysent
    # le scalp pendant que la fenêtre se referme (latence 3-5s vs 1.4-2.5s
    # pour les légers). Leurs 1446 avis restent dans le CSV (l'histoire ne
    # s'efface pas), ils ne sont juste plus interrogés ni classés.
}
SYMBOLS   = ["XAUUSD+", "BTCUSD", "EURUSD+"]   # 06/08 : noms Vantage   # 13/07 : 5→3 (les 3 actifs cœur) — anti-saturation mammouth
# 17/07 : même chemin explicite que MAMMOUTH — un initialize() nu peut viser
# le mauvais terminal depuis la réinstall (XM Global MT5 → XM MT5)
MT5_PATH  = r"C:\Program Files\Vantage Markets MT5 Terminal\terminal64.exe"
INTERVAL  = 1200         # 13/07 : 5→20 min — l'Arène c'est de l'observation, sa rafale n'a pas à saturer la clé mammouth
HORIZON   = 2 * 3600     # verdict au plus tard après 2 h
CSV_FILE  = HERE / "ml_data" / "arena_decisions.csv"
PAUSE_FLAG = HERE / "arena_pause.flag"   # posé/levé par L'ŒIL (3e porte Mistral)
COLS = ["ts", "date", "symbol", "model", "action", "signal", "conf",
        "price", "atr", "latence_s", "json_ok", "outcome", "r"]


# ---------- indicateurs (mêmes recettes que le bot : RSI Cutler, EMA, ATR) ----
def _indics(sym):
    r5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 120)
    r15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 120)
    if r5 is None or r15 is None or len(r5) < 60 or len(r15) < 60:
        return None
    c = [float(x["close"]) for x in r5][:-1]
    h = [float(x["high"]) for x in r5][:-1]
    l = [float(x["low"]) for x in r5][:-1]
    d = [c[i] - c[i - 1] for i in range(1, len(c))]
    up = sum(x for x in d[-14:] if x > 0) / 14
    dn = sum(-x for x in d[-14:] if x < 0) / 14
    rsi = 100 - 100 / (1 + up / (dn + 1e-9))
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = sum(tr[-14:]) / 14
    def ema(serie, n):
        k, e = 2 / (n + 1), serie[0]
        for v in serie[1:]:
            e = v * k + e * (1 - k)
        return e
    c15 = [float(x["close"]) for x in r15][:-1]
    trend15 = "BULLISH" if ema(c15, 20) > ema(c15, 50) else "BEARISH"
    return {"price": c[-1], "rsi": rsi, "atr": atr, "trend15": trend15}


def _cot(sym):
    try:
        d = json.loads((HERE / "oeil_context.json").read_text(encoding="utf-8"))["cot"].get(sym)
        return f"{d['bias']} ({d['pct']:+}% OI)" if d else "indisponible"
    except Exception:
        return "indisponible"


def _json_soft(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    for cand in (m.group(0), re.sub(r",\s*([}\]])", r"\1", m.group(0))):
        try:
            return json.loads(cand)
        except Exception:
            continue
    return {}


def _ask(model, prompt):
    t0 = time.time()
    for tentative in (1, 2):   # 🚦 429 : on laisse passer la rafale et on retente UNE fois
        try:
            r = requests.post("https://api.mammouth.ai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {MAMMOUTH_API_KEY}"},
                              json={"model": model, "max_tokens": 900,
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=45)
            r.raise_for_status()
            data = r.json()
            compte_tokens(model, data.get("usage") or {}, "arene", duree_s=time.time() - t0)   # ⏱️ 16/09
            d = _json_soft(data["choices"][0]["message"]["content"])
            ok = d.get("action") in ("TRADE", "SKIP")
            return d if ok else {}, time.time() - t0, ok
        except Exception as e:
            if "429" in str(e) and tentative == 1:
                time.sleep(3)   # sinon le classement compte de FAUX échecs pendant les tempêtes
                continue
            return {}, time.time() - t0, False
    return {}, time.time() - t0, False


# ---------- un round : mêmes données pour tous, décisions consignées ---------
def round_once():
    if not mt5.initialize(path=MT5_PATH):
        print("⚠️ MT5 injoignable — round sauté")
        return
    CSV_FILE.parent.mkdir(exist_ok=True)
    nouveau = not CSV_FILE.exists()
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if nouveau:
            w.writerow(COLS)
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            ind = _indics(sym)
            if ind is None:
                continue
            prompt = (f'Tu es un bot de scalping. Réponds UNIQUEMENT ce JSON, rien d\'autre: '
                      f'{{"action":"TRADE" ou "SKIP","signal":"BUY" ou "SELL","confidence":0-100,"reason":"..."}}\n'
                      f'Contexte: {sym} prix {ind["price"]:.5f}. RSI M5={ind["rsi"]:.1f}. '
                      f'ATR M5={ind["atr"]:.5f}. Tendance M15={ind["trend15"]}. '
                      f'COT institutionnel: {_cot(sym)}.')
            now = time.time()
            for nom, model in CHAMPIONS.items():
                # 🚦 politesse (13/07) : 35 appels/round sans pause saturaient le
                # compte mammouth → 429 pour TOUT l'écosystème (L'ŒIL, EA, bot).
                time.sleep(1.5)
                d, lat, ok = _ask(model, prompt)
                w.writerow([f"{now:.0f}", datetime.now().strftime("%Y-%m-%d %H:%M"),
                            sym, nom, d.get("action", "ERREUR"), d.get("signal", ""),
                            d.get("confidence", ""), f"{ind['price']:.5f}",
                            f"{ind['atr']:.6f}", f"{lat:.1f}", int(ok), "", ""])
            print(f"  {sym} : {len(CHAMPIONS)} avis recueillis")


# ---------- le marché rend son verdict (barrière ±1 ATR, max 2 h) ------------
def label_pass():
    if not CSV_FILE.exists() or not mt5.initialize(path=MT5_PATH):
        return
    rows = list(csv.DictReader(open(CSV_FILE, encoding="utf-8")))
    changed = 0
    for row in rows:
        if row["outcome"] or row["action"] != "TRADE" or row["signal"] not in ("BUY", "SELL"):
            continue
        ts, entry, atr = float(row["ts"]), float(row["price"]), float(row["atr"])
        if atr <= 0:
            row["outcome"], row["r"] = "invalide", "0"
            continue
        r1 = mt5.copy_rates_range(row["symbol"], mt5.TIMEFRAME_M1,
                                  datetime.fromtimestamp(ts), datetime.now())
        if r1 is None or len(r1) < 2:
            continue
        haussier = row["signal"] == "BUY"
        tp = entry + atr if haussier else entry - atr
        sl = entry - atr if haussier else entry + atr
        verdict = None
        for b in r1[1:]:
            hit_tp = b["high"] >= tp if haussier else b["low"] <= tp
            hit_sl = b["low"] <= sl if haussier else b["high"] >= sl
            if hit_tp and hit_sl:
                verdict = ("perte", -1.0)      # les 2 dans la même bougie : conservateur
            elif hit_tp:
                verdict = ("gain", 1.0)
            elif hit_sl:
                verdict = ("perte", -1.0)
            if verdict:
                break
        if verdict is None and time.time() - ts >= HORIZON:
            dern = float(r1[-1]["close"])
            r_val = (dern - entry) / atr * (1 if haussier else -1)
            verdict = ("timeout", max(-1.0, min(1.0, r_val)))
        if verdict:
            row["outcome"], row["r"] = verdict[0], f"{verdict[1]:.2f}"
            changed += 1
    if changed:
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
        print(f"  ⚖️ {changed} décision(s) notée(s) par le marché")


# ---------- le classement ----------------------------------------------------
def stats():
    if not CSV_FILE.exists():
        print("🏟️ Aucune donnée — lance d'abord l'arène.")
        return
    rows = list(csv.DictReader(open(CSV_FILE, encoding="utf-8")))
    print(f"🏟️ ARÈNE DES MODÈLES — {len(rows)} décisions consignées\n")
    print(f"{'modèle':9s} {'avis':>5s} {'trades':>7s} {'notés':>6s} {'gains':>6s} "
          f"{'WR':>5s} {'R total':>8s} {'R/trade':>8s} {'lat.':>6s} {'JSON⚠':>6s}")
    for nom in CHAMPIONS:
        sub = [r for r in rows if r["model"] == nom]
        trades = [r for r in sub if r["action"] == "TRADE"]
        notes = [r for r in trades if r["outcome"] and r["outcome"] != "invalide"]
        gains = [r for r in notes if r["outcome"] == "gain"]
        rtot = sum(float(r["r"] or 0) for r in notes)
        lat = sum(float(r["latence_s"] or 0) for r in sub) / max(1, len(sub))
        ko = sum(1 for r in sub if r["json_ok"] == "0")
        wr = 100 * len(gains) / len(notes) if notes else 0
        rpt = rtot / len(notes) if notes else 0
        print(f"{nom:9s} {len(sub):5d} {len(trades):7d} {len(notes):6d} {len(gains):6d} "
              f"{wr:4.0f}% {rtot:+8.2f} {rpt:+8.2f} {lat:5.1f}s {ko:6d}")
    print("\nR = résultat en unités d'ATR (±1 max). Le marché est le seul juge. 🦅")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"
    if mode == "stats":
        stats()
    elif mode == "once":
        print("🏟️ Round unique…")
        round_once()
        label_pass()
        stats()
    else:
        print(f"🏟️ Arène ouverte : {', '.join(CHAMPIONS.values())}")
        print(f"   1 round / {INTERVAL // 60} min · verdicts ±1 ATR (max {HORIZON // 3600} h) · shadow pur")
        while True:
            try:
                # 🛑 drapeau posé par L'ŒIL quand il tourne sur la 3e porte
                # (Mistral direct, quota compté) : round sauté, mais les
                # verdicts du marché continuent (0 token, MT5 seulement).
                if PAUSE_FLAG.exists():
                    print(f"— {datetime.now().strftime('%H:%M')} : 🛑 pause (L'ŒIL sur la 3e porte) — verdicts seulement —")
                else:
                    print(f"— round {datetime.now().strftime('%H:%M')} —")
                    round_once()
                label_pass()
            except Exception as e:
                print(f"⚠️ {e}")
            time.sleep(INTERVAL)
