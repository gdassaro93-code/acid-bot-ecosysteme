# -*- coding: utf-8 -*-
# =====================================================
# 📖 ORDER FLOW (15/07, demande patron) : le carnet d'ordres UTILE.
# Constat testé en live : XM ne fournit AUCUNE profondeur de marché
# (market_book refusé sur tous les symboles — broker CFD market-maker).
# Donc deux sources RÉELLES à la place :
#   1. le FLUX DE TICKS MT5 (tous les actifs) — pression achat/vente
#      reconstituée par la règle du tick (uptick/downtick du mid), vitesse
#      du flux, et efficacité du mouvement (directionnel vs churn)
#   2. le VRAI CARNET BINANCE (crypto seulement, API publique sans clé) —
#      déséquilibre bid/ask des 20 premiers niveaux + murs d'ordres
# Zéro token IA — que du calcul. Cache 45 s pour ne marteler personne.
# =====================================================
import time
from datetime import datetime, timedelta

import requests
import MetaTrader5 as mt5

# 🩹 15/09 — LE CARNET ETAIT MORT EN SILENCE.
# La table ne connaissait que les noms de l'ANCIEN broker ("BTCUSD#"), avec le
# diese. Sur Vantage le symbole s'appelle "BTCUSD" : carnet_binance() rendait
# {} depuis le changement de broker, sans jamais se plaindre. Verifie en direct
# le 15/09 : avec le diese -> imbalance 14,8 % et deux murs a 78 026 ; sans le
# diese -> rien du tout.
# On ne liste donc plus des noms exacts : on NORMALISE. Le prochain broker
# pourra l'appeler BTCUSD.x ou BTC/USD, ca marchera quand meme.
BINANCE_MAP = {"BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT",
               "XRPUSD": "XRPUSDT", "SOLUSD": "SOLUSDT",
               "LTCUSD": "LTCUSDT", "ADAUSD": "ADAUSDT"}


def _binance_nom(symbol: str):
    """Le symbole du broker -> la paire Binance, quel que soit l'habillage."""
    b = "".join(c for c in str(symbol).upper() if c.isalnum())
    for suffixe in ("USDT", "USD"):
        if b.endswith(suffixe):
            pass
    return BINANCE_MAP.get(b) or BINANCE_MAP.get(b.replace("USDT", "USD"))
CACHE_S = 45
_cache = {}   # clé -> (ts, valeur)


def _memo(cle, calc):
    v = _cache.get(cle)
    if v and time.time() - v[0] < CACHE_S:
        return v[1]
    r = calc()
    _cache[cle] = (time.time(), r)
    return r


def flux_ticks(symbol: str, minutes: int = 3) -> dict:
    """Pression achat/vente reconstituée depuis les ticks MT5 (règle du
    tick : mid qui monte = pression acheteuse). Renvoie {} si indisponible."""
    def calc():
        try:
            ticks = mt5.copy_ticks_from(symbol, datetime.now() - timedelta(minutes=minutes),
                                        200000, mt5.COPY_TICKS_ALL)
            if ticks is None or len(ticks) < 30:
                return {}
            mids = [(float(t["bid"]) + float(t["ask"])) / 2 for t in ticks]
            up = dn = 0
            chemin = 0.0
            for i in range(1, len(mids)):
                d = mids[i] - mids[i - 1]
                if d > 0:
                    up += 1
                elif d < 0:
                    dn += 1
                chemin += abs(d)
            total = up + dn
            if not total:
                return {}
            net = mids[-1] - mids[0]
            return {"ticks_min": round(len(ticks) / minutes),
                    "pression_achat": round(100.0 * up / total, 1),
                    # efficacité : 100 = le prix va tout droit, 0 = pur churn
                    "efficacite": round(abs(net) / chemin * 100, 1) if chemin > 0 else 0.0,
                    "net": net}
        except Exception:
            return {}
    return _memo(f"flux|{symbol}", calc)


def carnet_binance(symbol: str) -> dict:
    """Déséquilibre + murs du VRAI carnet Binance (crypto uniquement)."""
    b = _binance_nom(symbol)
    if not b:
        return {}
    def calc():
        try:
            r = requests.get("https://api.binance.com/api/v3/depth",
                             params={"symbol": b, "limit": 20}, timeout=5)
            r.raise_for_status()
            d = r.json()
            vb = sum(float(q) for _, q in d["bids"])
            va = sum(float(q) for _, q in d["asks"])
            if vb + va <= 0:
                return {}
            vols = sorted(float(q) for _, q in d["bids"] + d["asks"])
            mediane = vols[len(vols) // 2] or 1e-9
            murs = []
            for cote, niveaux in (("achat", d["bids"]), ("vente", d["asks"])):
                for prix, q in niveaux:
                    if float(q) >= 8 * mediane:   # 8x la médiane = un vrai mur
                        murs.append((cote, float(prix), float(q)))
            murs.sort(key=lambda m: -m[2])
            return {"imbalance_achat": round(100.0 * vb / (vb + va), 1),
                    "murs": murs[:2]}
        except Exception:
            return {}
    return _memo(f"carnet|{symbol}", calc)


def contexte_flux(symbol: str) -> str:
    """Une ligne de contexte prête pour un prompt IA. '' si rien de dispo."""
    parts = []
    f = flux_ticks(symbol)
    if f:
        sens = "acheteur" if f["pression_achat"] >= 50 else "vendeur"
        pct = f["pression_achat"] if sens == "acheteur" else 100 - f["pression_achat"]
        parts.append(f"flux {sens} {pct:.0f}% ({f['ticks_min']} ticks/min, "
                     f"efficacité {f['efficacite']:.0f}%)")
    c = carnet_binance(symbol)
    if c:
        sens = "acheteur" if c["imbalance_achat"] >= 50 else "vendeur"
        pct = c["imbalance_achat"] if sens == "acheteur" else 100 - c["imbalance_achat"]
        parts.append(f"carnet Binance {sens} {pct:.0f}%")
        parts.extend(f"mur {cote} à {prix:g}" for cote, prix, _ in c["murs"])
    return ", ".join(parts)


def flux_confirme(symbol: str, sens: str, seuil: float = 60.0):
    """Pour le dump tactique : le flux confirme-t-il le sens voulu ?
    True/False si les données parlent, None si indisponibles (ne bloque pas —
    l'absence de donnée n'est pas une preuve contre)."""
    f = flux_ticks(symbol)
    if not f:
        return None
    p = f["pression_achat"] if sens == "BUY" else 100 - f["pression_achat"]
    return p >= seuil
