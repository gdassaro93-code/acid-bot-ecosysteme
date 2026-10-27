# -*- coding: utf-8 -*-
# =====================================================
#  🏦 COT — Commitment of Traders (CFTC)
#  «…» : position nette des grands
#  spéculateurs (non-commercials) sur TES instruments.
#  Donnée publique CFTC, hebdomadaire (vendredi ~21h30 Paris).
#  Cache local (cot_cache.json) — rafraîchi au plus 1×/12h.
# =====================================================
import json
import time
from pathlib import Path

import requests

HERE       = Path(__file__).resolve().parent
CACHE_FILE = HERE / "cot_cache.json"
API        = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
CACHE_TTL  = 12 * 3600   # 12 h (la donnée ne bouge qu'une fois/semaine)

# symbole XM -> (nom exact du contrat CFTC, signe)
# signe = -1 quand le contrat est inversé par rapport au symbole XM
# (ex: futures YEN = JPY/USD -> long yen = BAISSIER pour USDJPY)
MARKET_MAP = {
    "GOLD#":      ("GOLD - COMMODITY EXCHANGE INC.",              1),
    "SILVER#":    ("SILVER - COMMODITY EXCHANGE INC.",            1),
    "OILCash#":   ("CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE", 1),
    "EURUSD#":    ("EURO FX - CHICAGO MERCANTILE EXCHANGE",       1),
    "USDJPY#":    ("JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE", -1),
    "US500Cash#": ("E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", 1),
    "BTCUSD#":    ("BITCOIN - CHICAGO MERCANTILE EXCHANGE",       1),
    "ETHUSD#":    ("ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE", 1),
}


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _fetch_from_cftc() -> dict:
    """Récupère le dernier rapport COT pour chaque marché mappé."""
    names = list({m for m, _ in MARKET_MAP.values()})
    quoted = ",".join("'" + n.replace("'", "''") + "'" for n in names)
    where = f"market_and_exchange_names in({quoted}) AND report_date_as_yyyy_mm_dd > '2026-01-01'"
    params = {"$where": where, "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 400}
    r = requests.get(API, params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()

    # garder la ligne la plus récente par marché
    latest = {}
    for row in rows:
        m = row.get("market_and_exchange_names")
        if m and m not in latest:
            latest[m] = row

    out = {}
    for sym, (market, sign) in MARKET_MAP.items():
        row = latest.get(market)
        if not row:
            continue
        lng = _num(row.get("noncomm_positions_long_all"))
        sht = _num(row.get("noncomm_positions_short_all"))
        oi  = _num(row.get("open_interest_all"), 1) or 1
        chg = (_num(row.get("change_in_noncomm_long_all"))
               - _num(row.get("change_in_noncomm_short_all")))
        net = (lng - sht) * sign
        chg *= sign
        pct = round(net / oi * 100, 1)
        bias = "HAUSSIER" if pct > 2 else "BAISSIER" if pct < -2 else "NEUTRE"
        out[sym] = {
            "market": market,
            "date": (row.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "bias": bias,
            "net": int(net),
            "net_pct": pct,
            "weekly_change": int(chg),
            "long": int(lng), "short": int(sht),
        }
    return {"ts": time.time(), "assets": out}


def get_cot(force=False) -> dict:
    """Renvoie les données COT (cache si frais, sinon rafraîchit)."""
    if not force and CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < CACHE_TTL and data.get("assets"):
                return data
        except Exception:
            pass
    try:
        data = _fetch_from_cftc()
        CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception as e:
        # en cas d'échec réseau, on ressert le vieux cache s'il existe
        if CACHE_FILE.exists():
            try:
                return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"ts": 0, "assets": {}, "error": str(e)[:150]}


def cot_bias(symbol: str) -> dict | None:
    """Biais COT pour un symbole XM (ou None si non couvert)."""
    return get_cot().get("assets", {}).get(symbol)


def cot_text() -> str:
    """Résumé Telegram du positionnement institutionnel."""
    data = get_cot()
    a = data.get("assets", {})
    if not a:
        return "🏦 COT indisponible" + (f" ({data['error']})" if data.get("error") else "")
    date = next(iter(a.values())).get("date", "?")
    t = f"🏦 *SMART MONEY — COT* (gros spéculateurs)\n_Rapport CFTC du {date}_\n\n"
    for sym, d in a.items():
        ic = "🟢" if d["bias"] == "HAUSSIER" else "🔴" if d["bias"] == "BAISSIER" else "⚪"
        mom = "↗️" if d["weekly_change"] > 0 else "↘️" if d["weekly_change"] < 0 else "→"
        t += (f"{ic} *{sym}* : {d['bias']} ({d['net_pct']:+}%) {mom}\n"
              f"   _net {d['net']:+} | semaine {d['weekly_change']:+}_\n")
    t += "\n💡 _Biais de fond des institutionnels — boussole, pas signal d'entrée._"
    return t


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(cot_text())
