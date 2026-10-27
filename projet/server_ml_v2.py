# =====================================================
# 🧠 SERVEUR ML — LE SEUL ML DE L'ÉCOSYSTÈME (port 8001)
# =====================================================
#
# 16/09/26 — REFONDU. Le patron : «…
# …» et «…
# …
# …».
#
# ── CE QUI TOURNAIT AVANT, MESURÉ LE 16/09 SUR 2 546 BOUGIES JAMAIS VUES ──
#   ce serveur + acidgpt_ml_model.pkl (trades VTMarkets 2022-2025, 6 données)
#       AUC 0,507 = pile ou face. Suivre ses choix : 30,4 % de gagnants contre
#       30,0 % au hasard. C'est lui que l'EA consultait à chaque entrée.
#   ml_avis.py + modele_prix.pkl (bougies Vantage, 16 données)
#       AUC 0,560 · 40,2 % contre 30,0 % au hasard. Le seul qui portait un
#       signal — mais en service il recevait 0 pour 3 de ses 16 données :
#       il appelait chart_patterns._impulsion, qui n'existe pas.
#
# ── CE QUI TOURNE MAINTENANT ─────────────────────────────────────────────
#   ml_data/modele_v2.pkl, produit par ml_v2_entrainer.py :
#   395 794 exemples de bougies H1/H4 Vantage (mai 2023 → septembre 2026),
#   question «…», spread réel.
#   Validé sur SIX mois glissants, chacun jugé par un modèle qui ne l'avait
#   jamais vu, puis sur une réserve finale de 30 jours :
#       règle p ≥ 0,42 : +0,281 R/trade, positive 6 mois sur 6
#       réserve : 160 trades, 48,1 % de gagnants, +0,444 R
#
# ── CE QUE CE SERVEUR NE CHANGE PAS : LE CONTRAT ─────────────────────────
# Relevé le 16/09 par une cartographie de chaque consommateur (EA, cerveau,
# arbitre, MAMMOUTH, dashboard, Centre). Chaque ligne ci-dessous a un lecteur :
#   · GET /predict + les 7 paramètres de l'EA, 200 pour une vraie réponse
#   · "prediction" BUY|SELL|HOLD|NEUTRAL et "confidence" en nombre 0..1 centré
#     sur 0,5 — ce sont les DEUX PREMIÈRES clés : l'EA les cherche avec
#     StringFind et lit la première occurrence, sans espace après les «…»
#   · score 0..100 directionnel, tp/sl en DISTANCES, signal_ea, blacklist,
#     highvol, symbol, timestamp, technical_vote, news_vote
#   · POST /predict/json, /health (503 sans modèle), /api/ml/signals,
#     /api/ml/analysis, /force_retrain, port 8001, nom de fichier inchangé
#
# ── LA CALIBRATION : LE POINT QUI PORTE DE L'ARGENT ──────────────────────
# Le modèle sort une probabilité d'atteindre 2R (~30 % de base). La brancher
# telle quelle sur «…» aurait été une catastrophe silencieuse :
#   · l'EA refuse tous les pendings sous 0,53 → plus aucun pending
#   · le cerveau passe des ORDRES RÉELS, discipline sautée (de_patron=True),
#     dès que confidence ≥ 0,78 (sniper_check)
#   · MAMMOUTH ne consulte l'IA qu'au-dessus de 0,90
# Le modèle A plafonnait autour de 0,61 : ni le sniper ni MAMMOUTH ne se
# déclenchaient jamais. On garde CETTE enveloppe, pour qu'un changement de
# modèle ne devienne pas en douce un changement de comportement :
#       p < 0,34            → HOLD, 0,50
#       p ≥ 0,34            → BUY/SELL, 0,54 + (p − 0,34), plafonné à 0,70
# Le seuil 0,34 n'est pas choisi au hasard : sur les six mois glissants, les
# trades à p ≥ 0,34 rapportent +0,110 R et gagnent six mois sur six. Chaque
# BUY/SELL émis est donc dans une zone mesurée rentable. Et le veto «…»
# de l'EA, écrit en dur à 0,58, correspond à p ≥ 0,38 (+0,198 R).
# Ouvrir le sniper ou MAMMOUTH est une décision du patron — pas un effet de
# bord d'un changement de modèle. Le plafond est dans CONF_MAX.
# =====================================================
import json
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ml_v2_entrainer as V      # les formules EXACTES qui ont produit l'entraînement

PORT = int(os.environ.get("ACID_ML_PORT", "8001"))
ESSAI = PORT != 8001             # une instance d'essai ne touche à rien de partagé

MODELE = V.MODELE
CARTE = V.CARTE

SEUIL_ACTION = 0.34     # p sous ce niveau : pas d'avantage mesuré → HOLD
CONF_MIN = 0.54         # BUY/SELL au plus bas (au-dessus de MLMinConfidence 0,53 de l'EA)
CONF_MAX = 0.70         # jamais au-delà : sniper_check (0,78) et MAMMOUTH (0,90) restent muets
CACHE_S = 60            # les 16 données ne bougent qu'à la clôture H1 ; 60 s suffit au spread

app = FastAPI(title="AcidGPT ML Server", version="2.1")
SIGNAL_SERVER_URL = "http://127.0.0.1:5001"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        # chemin ABSOLU : lancé depuis un autre dossier, l'ancien démarrait
        # sans modèle et sans journal (le dashboard affichait «…»)
        RotatingFileHandler(HERE / ("ml_server_essai.log" if ESSAI else "ml_server.log"),
                            maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# =====================================================
# MT5 EN DIRECT
# =====================================================
try:
    import MetaTrader5 as mt5
    _MT5_EXE = r"C:\Program Files\Vantage Markets MT5 Terminal\terminal64.exe"
    # 🚷 05/08 : ne JAMAIS ressusciter un MT5 fermé par le patron
    import subprocess as _sp_t64
    _t64 = {"t": 0.0, "on": True}

    def _terminal_ouvert() -> bool:
        # 🩸 02/10 : 10 s de cache = 10 s pendant lesquelles le garde croit encore
        # que MT5 tourne alors que le patron vient de le fermer — et initialize()
        # le ressuscite. Ramené à 1 s (un tasklist/seconde au pire, c'est gratuit).
        if time.time() - _t64["t"] > 1:
            _t64["t"] = time.time()
            try:
                r = _sp_t64.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                                capture_output=True, timeout=5, creationflags=0x08000000)
                _t64["on"] = b"terminal64" in (r.stdout or b"")
            except Exception:
                _t64["on"] = True
        return _t64["on"]

    _mt5_init_brut = mt5.initialize

    def _mt5_init_chemin(*a, **k):
        if not _terminal_ouvert():
            return False
        if not a and "path" not in k:
            k["path"] = _MT5_EXE
        return _mt5_init_brut(*a, **k)

    mt5.initialize = _mt5_init_chemin
except ImportError:
    mt5 = None

INDICS_NEUTRES = {"rsi": 50.0, "ema_ratio": 1.0, "atr": 0.02,
                  "macd": 0.0, "bollinger_width": 0.0}

# =====================================================
# 🔤 LES NOMS DE MARCHÉ
# =====================================================
# 🩹 16/09 — L'EA envoie «…» sans encoder le «…». Toute URL décode
# un «…» en espace : ce serveur recevait «…», que rien ne résolvait.
# Vérifié en direct le 16/09 : envoyé 'XAUUSD+' → reçu 'XAUUSD '. L'or et les
# paires forex n'atteignaient jamais le ML sous leur vrai nom.
# On résout donc à partir de ce qui arrive, espaces compris, et on accepte les
# noms des anciens brokers que certains appelants envoient encore.
ALIAS = {
    "GOLD": "XAUUSD+", "XAUUSD": "XAUUSD+", "SILVER": "XAGUSD", "XAGUSD+": "XAGUSD",
    "OIL": "CL-OIL", "OILCASH": "CL-OIL", "USOIL": "CL-OIL", "WTI": "CL-OIL", "CLOIL": "CL-OIL",
    "US500": "SP500", "US500CASH": "SP500", "SPX500": "SP500", "SPX": "SP500",
    "US100": "NAS100", "USTEC": "NAS100", "NAS100CASH": "NAS100", "NASDAQ": "NAS100",
    "EURUSD": "EURUSD+", "GBPUSD": "GBPUSD+", "USDJPY": "USDJPY+",
    "BTC": "BTCUSD", "ETH": "ETHUSD", "EUR": "EURUSD+", "GBP": "GBPUSD+",
}
_resolu = {}


def resoudre_symbole(brut) -> Optional[str]:
    """Le nom tel qu'il arrive → le nom réellement coté chez le broker, ou None."""
    s = str(brut or "").upper().replace("#", "").replace(" ", "").replace("%23", "")
    if not s:
        return None
    if s in _resolu:
        return _resolu[s]
    if mt5 is None or not mt5.initialize():
        return None                  # MT5 muet : on ne met RIEN en cache, on réessaiera
    trouve = None
    sans_cash = s.replace("CASH", "")
    candidats = [c for c in (s, s + "+", ALIAS.get(s), ALIAS.get(sans_cash), sans_cash,
                             sans_cash + "+", s.rstrip("+")) if c]
    # 🩹 16/09 — D'ABORD les noms que le modèle connaît. Vantage cote DEUX
    # EURUSD : «…» (spread 14) et «…» (spread 1), idem GBPUSD et
    # USDJPY. L'EA envoie «…», qui arrive ici en «…» ; le premier
    # nom coté trouvé était donc le mauvais instrument, hors de l'univers appris.
    # Constaté à l'essai du 16/09 : EURUSD+ ressortait «…».
    for passe in (lambda c: c in V.SYMBOLES, lambda c: True):
        for cand in candidats:
            if not passe(cand):
                continue
            try:
                if mt5.symbol_info(cand):
                    trouve = cand
                    break
            except Exception:
                pass
        if trouve:
            break
    # 🩹 16/09 (relecture) — on ne mémorise QUE ce qu'on a trouvé. Un None dû à
    # une panne passagère (terminal en plein chargement, délai IPC) restait
    # gravé jusqu'au redémarrage : l'or répondait HOLD pour toujours, sans alerte.
    if trouve:
        _resolu[s] = trouve
    return trouve


def clean_symbol(symbol: str) -> str:
    """Affichage (Telegram, dashboard). Garde le «…» de Vantage : le dashboard
    compare ce nom à ses propres symboles de graphique."""
    return str(symbol).upper().replace("#", "").replace("CASH", "").replace("_", "").strip()


# =====================================================
# 🧠 LE MODÈLE
# =====================================================
paquet = None
_annul = {"motif": None}
model = None          # gardé sous ce nom : /health et les appelants testent «…»
_charge_le = None


def charger_modele() -> bool:
    """Charge ml_data/modele_v2.pkl et VÉRIFIE qu'il parle la même langue que
    les formules. Un paquet dont la liste de données diffère d'une seule
    colonne donnerait des prédictions fausses sans aucune erreur visible."""
    global paquet, model, _charge_le
    try:
        import joblib
        p = joblib.load(MODELE)
        if not isinstance(p, dict) or "modele" not in p:
            raise ValueError("paquet illisible (pas de clé 'modele')")
        if list(p.get("features", [])) != list(V.FEATURES):
            raise ValueError(f"données du modèle {p.get('features')} ≠ formules {V.FEATURES}")
        if 1 not in list(p["modele"].classes_):
            raise ValueError(f"classes inattendues {p['modele'].classes_}")
        paquet, model, _charge_le = p, p["modele"], time.time()
        # 🚫 16/09 — la fiche peut porter «…» (fuite du futur
        # découverte à la relecture). Le modèle continue de répondre, mais plus
        # rien n'est déclaré «…» : ce mot voulait dire «…».
        try:
            _annul["motif"] = (json.loads(CARTE.read_text(encoding="utf-8"))
                               .get("validation_annulee") or {}).get("pourquoi")
        except Exception:
            _annul["motif"] = None
        if _annul["motif"]:
            logger.warning(f"🚫 VALIDATION ANNULÉE : {_annul['motif']} — plus aucun avis « favorable »")
        regle = p.get("regle") or {}
        logger.info(f"✅ Modèle {p.get('version', '?')} chargé — créé le {p.get('cree_le', '?')} "
                    f"· règle {regle}")
        _cache.clear()
        return True
    except Exception as e:
        logger.error(f"❌ Modèle non chargé ({MODELE.name}) : {e} — le serveur répondra HOLD")
        return False


def seuil_favorable() -> float:
    """Le seuil de la règle VALIDÉE. 🩹 16/09 (relecture) : une règle «…»
    n'a pas de clé «…» ; on retombait en silence sur 0,42, jamais validé.
    Désormais : son seuil équivalent mesuré à l'entraînement, sinon RIEN n'est
    favorable (un seuil inventé est pire qu'un ML muet)."""
    if _annul["motif"]:
        return 9.99
    try:
        regle = (paquet or {}).get("regle") or {}
        v = regle.get("seuil", regle.get("seuil_equivalent"))
        return float(v) if v is not None else 9.99   # rien ne l'atteint ; inf casserait le JSON
    except Exception:
        return 9.99


_cache = {}


def probabilites(symbole_mt5: str) -> Optional[dict]:
    """P(2R avant le stop) pour un ACHAT et pour une VENTE, calculées sur la
    dernière bougie H1 CLÔTURÉE — exactement la situation de l'entraînement
    (données à la bougie k, entrée à l'ouverture de k+1).
    Retourne None si le marché est hors de l'univers appris ou si MT5 ne
    répond pas : le modèle ne sait rien d'un marché qu'il n'a jamais vu."""
    if model is None or mt5 is None or symbole_mt5 not in V.SYMBOLES:
        return None
    c = _cache.get(symbole_mt5)
    if c and time.time() - c["calcule_a"] < CACHE_S:
        return c
    try:
        if not mt5.initialize():
            return None
        mt5.symbol_select(symbole_mt5, True)
        r = mt5.copy_rates_from_pos(symbole_mt5, mt5.TIMEFRAME_H1, 0, 501)
        r4 = mt5.copy_rates_from_pos(symbole_mt5, mt5.TIMEFRAME_H4, 0, 130)
        info = mt5.symbol_info(symbole_mt5)
        tick = mt5.symbol_info_tick(symbole_mt5)
        if r is None or len(r) < 200 or info is None:
            return None
        r = r[:-1]                                  # la bougie en formation n'existe pas encore
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
        spread = (tick.ask - tick.bid) if (tick and tick.ask and tick.bid) \
            else (info.spread * info.point)
        # 🩹 16/09 (relecture) — la donnée spread_pct_risque doit être calculée
        # comme à l'entraînement : avec LE spread de l'entraînement. Le spread en
        # direct explose au rollover et aux news (x3 à x10), une valeur jamais
        # apprise, qui faisait basculer p_buy/p_sell au pire moment.
        spread = float(((paquet or {}).get("spreads") or {}).get(symbole_mt5) or spread)
        S = V._series(O, H, L, C)
        k = len(C) - 1
        atr, base = V._features_k(k, O, H, L, C, T, S, T4, C4, spread)
        if base is None or atr <= 0:
            return None
        lignes = []
        for sens in (1, -1):
            d = dict(base, sens=sens,
                     spread_pct_risque=round(100 * spread / (V.SL_ATR * atr), 3))
            lignes.append([d[f] for f in paquet["features"]])
        idx = list(model.classes_).index(1)
        p = model.predict_proba(lignes)[:, idx]
        res = {"p_buy": float(p[0]), "p_sell": float(p[1]), "atr_h1": float(atr),
               "bougie": T[k], "calcule_a": time.time()}
        _cache[symbole_mt5] = res
        return res
    except Exception as e:
        logger.warning(f"⚠️ probabilités {symbole_mt5} : {e}")
        return None


def verdict(pr: Optional[dict]) -> dict:
    """Probabilités → ce que les consommateurs comprennent.
    Voir l'en-tête : l'enveloppe 0,54-0,70 est un garde-fou, pas une esthétique."""
    if not pr:
        return {"prediction": "HOLD", "confidence": 0.5, "directionnel": 0.5,
                "sens": None, "p": None, "favorable": False}
    sens = "BUY" if pr["p_buy"] >= pr["p_sell"] else "SELL"
    p = max(pr["p_buy"], pr["p_sell"])
    if p < SEUIL_ACTION:
        return {"prediction": "HOLD", "confidence": 0.5, "directionnel": 0.5,
                "sens": sens, "p": p, "favorable": False}
    conf = max(CONF_MIN, min(CONF_MAX, CONF_MIN + (p - SEUIL_ACTION)))
    return {"prediction": sens, "confidence": conf,
            "directionnel": conf if sens == "BUY" else 1.0 - conf,
            "sens": sens, "p": p, "favorable": p >= seuil_favorable()}


# =====================================================
# ⏳ RECHARGEMENT DU DIMANCHE + FICHE DU TABLEAU
# =====================================================
_last_sunday_refresh = None


def _boucle_entretien():
    global _last_sunday_refresh
    while True:
        try:
            now = time.localtime()
            today = time.strftime("%Y-%m-%d", now)
            if now.tm_wday == 6 and _last_sunday_refresh != today:
                if charger_modele():
                    _last_sunday_refresh = today
                    logger.info("🔄 Rechargement hebdomadaire du modèle (dimanche) ✅")
        except Exception as e:
            logger.error(f"❌ Rechargement dominical échoué : {e}")
        # 📋 LA FICHE — toutes les 2 minutes et plus toutes les heures : le
        # cerveau ne lit que les fiches de moins de 5 minutes, il ne la voyait
        # donc que 5 minutes par heure.
        if not ESSAI:
            try:
                import tableau as _tab
                age = None
                try:
                    age = round((time.time() - MODELE.stat().st_mtime) / 3600.0, 1)
                except Exception:
                    pass
                _tab.ecrire("ml", modele_charge=model is not None,
                            version=(paquet or {}).get("version"),
                            age_modele_h=age, seuil_favorable=seuil_favorable(),
                            port=PORT, dernier_refresh=_last_sunday_refresh)
            except Exception:
                pass
        time.sleep(120)


charger_modele()
threading.Thread(target=_boucle_entretien, daemon=True).start()


# =====================================================
# CONTRAT DE RÉPONSE
# =====================================================
class PredictionRequest(BaseModel):
    symbol: str = "EURUSD"
    rsi: float = 50.0
    ema_ratio: float = 1.0
    atr: float = 0.02
    macd: float = 0.0
    bollinger_width: float = 0.0
    news_score: float = 50.0


class PredictionResponse(BaseModel):
    # ⚠️ ORDRE DES CHAMPS = ordre dans le JSON. «…» et «…»
    # doivent rester les deux premières clés : l'EA prend la PREMIÈRE occurrence.
    symbol: str
    prediction: str
    confidence: float
    score: float
    signal_ea: str
    technical_vote: dict
    news_vote: dict
    highvol: Optional[str]
    blacklist: bool
    tp: float
    sl: float
    timestamp: str
    # ajoutés le 16/09, EN DERNIER, et sans aucune clé imbriquée
    source: str
    p_buy: Optional[float]
    p_sell: Optional[float]


_NEUTRE_SIGNAL = {"signal": "NEUTRAL", "signal_ea": "safe", "score": 50.0,
                  "highvol": None, "blacklist": False}


def fetch_signal_data(symbol: str) -> dict:
    """Blacklist / highvol / score news depuis le serveur News (5001). Il
    résout lui-même tous les noms (vérifié le 16/09 : XAUUSD+, GOLD, CL-OIL,
    SP500…). Échoue ouvert, comme avant — ni aggravé ni corrigé ici."""
    try:
        r = requests.get(f"{SIGNAL_SERVER_URL}/signal", params={"symbol": symbol}, timeout=3)
        if r.status_code != 200:
            logger.warning(f"⚠️ Serveur signal a répondu {r.status_code} pour {symbol}")
            return dict(_NEUTRE_SIGNAL)
        d = r.json()
        return d if isinstance(d, dict) else dict(_NEUTRE_SIGNAL)
    except Exception as e:
        logger.error(f"❌ fetch_signal_data {symbol} : {e}")
        return dict(_NEUTRE_SIGNAL)


def technical_voting(rsi: float, ema_ratio: float, atr: float) -> dict:
    """Conservé pour l'affichage (champ technical_vote). Depuis le 16/09 il
    ne pèse PLUS sur la décision : jamais mesuré, il pesait 40 % du score."""
    votes = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    if rsi < 30:
        votes["BUY"] += 2; votes["HOLD"] += 0.5
    elif rsi > 70:
        votes["SELL"] += 2; votes["HOLD"] += 0.5
    elif rsi < 40:
        votes["BUY"] += 0.5
    elif rsi > 60:
        votes["SELL"] += 0.5
    else:
        votes["HOLD"] += 1.5
    if ema_ratio > 1.02:
        votes["BUY"] += 2
    elif ema_ratio < 0.98:
        votes["SELL"] += 2
    else:
        votes["HOLD"] += 1
    if atr > 0.05:
        votes["HOLD"] += 1
    elif atr < 0.01:
        votes["HOLD"] += 0.5
    return votes


def news_voting(news_score: float) -> dict:
    """Conservé pour l'affichage (champ news_vote), sans poids dans la décision."""
    votes = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    buy_prob = max(0.0, min(1.0, news_score / 100))
    sell_prob = 1.0 - buy_prob
    if buy_prob > 0.6:
        votes["BUY"] += buy_prob * 2
    elif sell_prob > 0.6:
        votes["SELL"] += sell_prob * 2
    else:
        votes["HOLD"] += 1
    return votes


def get_highvol_multiplier(highvol: Optional[str]) -> float:
    if not highvol:
        return 1.0
    if highvol in ["NFP", "FOMC"]:
        return 0.3
    return 0.5


def calculate_tp_sl(prediction: str, atr: float, highvol: Optional[str] = None) -> tuple:
    """INCHANGÉ : des DISTANCES en prix, sur l'ATR envoyé par l'appelant. Le
    cerveau et le dashboard les ajoutent au prix ; changer leur sens déplacerait
    les TP/SL affichés dans le plan du jour."""
    mult = get_highvol_multiplier(highvol)
    if prediction in ("BUY", "SELL"):
        return atr * 2.5 * mult, atr * 1.0 * mult
    return atr * 2.5 * 0.5, atr * 1.0 * 0.5


def predict_ml(symbol: str, rsi: float, ema_ratio: float, atr: float, macd: float,
               bollinger_width: float, news_score: float) -> PredictionResponse:
    t0 = time.time()
    sym_mt5 = resoudre_symbole(symbol)
    sig = fetch_signal_data(sym_mt5 or clean_symbol(symbol))
    highvol = sig.get("highvol")
    if highvol is not None and not isinstance(highvol, str):
        highvol = str(highvol)
    blacklist = bool(sig.get("blacklist", False))

    pr = probabilites(sym_mt5) if sym_mt5 else None
    v = verdict(pr)
    if model is None:
        source = "modele_absent"
    elif sym_mt5 is None:
        source = "symbole_inconnu"
    elif sym_mt5 not in V.SYMBOLES:
        source = "hors_univers"
    elif pr is None:
        source = "donnees_indisponibles"
    else:
        source = "v2"

    if blacklist:
        prediction, confidence, signal_ea, score = "NEUTRAL", 0.0, "crucial", 50.0
    elif v["prediction"] in ("BUY", "SELL"):
        prediction, confidence = v["prediction"], v["confidence"]
        signal_ea = "sniper_mode" if highvol else "safe"
        score = round(v["directionnel"] * 100, 1)
    else:
        prediction, confidence, signal_ea, score = "HOLD", 0.5, "safe", 50.0

    tp, sl = calculate_tp_sl(prediction, atr, highvol)
    logger.info(f"✅ {symbol!r}→{sym_mt5} | {prediction} | conf {confidence:.3f} | "
                f"p_buy {pr['p_buy'] if pr else float('nan'):.3f} "
                f"p_sell {pr['p_sell'] if pr else float('nan'):.3f} | {source} | "
                f"{time.time() - t0:.3f}s")
    return PredictionResponse(
        symbol=clean_symbol(sym_mt5 or symbol),
        prediction=prediction,
        confidence=round(float(confidence), 3),
        score=float(score),
        signal_ea=signal_ea,
        technical_vote=technical_voting(rsi, ema_ratio, atr),
        news_vote=news_voting(news_score),
        highvol=highvol,
        blacklist=blacklist,
        tp=round(float(tp), 5),
        sl=round(float(sl), 5),
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        source=source,
        p_buy=round(pr["p_buy"], 4) if pr else None,
        p_sell=round(pr["p_sell"], 4) if pr else None,
    )


# =====================================================
# ROUTES
# =====================================================
@app.get("/")
async def root():
    return {"name": "AcidGPT ML Server", "version": "2.1", "status": "online"}


@app.get("/health")
async def health():
    if model is None:
        raise HTTPException(status_code=503, detail="modèle ML absent — relancer ml_v2_entrainer.py")
    return {
        "status": "✅ OK",
        "version": "2.1",                       # CHAÎNE : un nombre casse le bloc Infos ML du dashboard
        "model_loaded": True,
        "modele": (paquet or {}).get("version", "v2"),
        "cree_le": (paquet or {}).get("cree_le"),
        "regle": (paquet or {}).get("regle"),
        "validation": ("ANNULÉE — " + _annul["motif"]) if _annul["motif"] else "valide",
        "signal_server": SIGNAL_SERVER_URL,
        "symbols": list(V.SYMBOLES),            # TABLEAU : un objet casse le même bloc
    }


@app.api_route("/predict", methods=["GET", "POST"])
async def predict(request: Request):
    try:
        if request.method == "GET":
            params = request.query_params
        else:
            params = await request.json()
        raw_sym = params.get("symbol", "EURUSD") or "EURUSD"
        rsi = float(params.get("rsi", 50.0))
        ema_ratio = float(params.get("ema_ratio", 1.0))
        atr = float(params.get("atr", 0.02))
        macd = float(params.get("macd", 0.0))
        bollinger_width = float(params.get("bollinger_width", 0.0))
        news_score = float(params.get("news_score", 50.0))
        if not 0 <= rsi <= 100:
            raise HTTPException(status_code=400, detail=f"RSI invalide: {rsi}")
        if not 0.5 <= ema_ratio <= 1.5:
            raise HTTPException(status_code=400, detail=f"EMA ratio invalide: {ema_ratio}")
        if atr < 0:
            raise HTTPException(status_code=400, detail=f"ATR invalide: {atr}")
        if not 0 <= news_score <= 100:
            raise HTTPException(status_code=400, detail=f"News score invalide: {news_score}")
        return predict_ml(str(raw_sym), rsi, ema_ratio, atr, macd, bollinger_width, news_score)
    except HTTPException:
        raise                                   # un 400 reste un 400 (il ressortait en 500)
    except ValueError as e:
        logger.error(f"❌ ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Erreur dans /predict: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict/json")
async def predict_json(req: PredictionRequest):
    return predict_ml(req.symbol, req.rsi, req.ema_ratio, req.atr, req.macd,
                      req.bollinger_width, req.news_score)


@app.get("/force_retrain")
async def force_retrain():
    """Recharge ml_data/modele_v2.pkl. Le nom est historique : ça ne
    réentraîne rien — l'entraînement, c'est ml_v2_entrainer.py."""
    if charger_modele():
        return {"status": "success", "message": f"Modèle {(paquet or {}).get('version')} rechargé"}
    return {"status": "error", "message": f"rechargement impossible — {MODELE.name}"}


def _indicateurs_mt5(symbol: str) -> dict:
    """RSI/ATR M5 pour l'AFFICHAGE du panneau (champs rsi et atr de
    /api/ml/signals). Le modèle, lui, calcule ses propres données en H1/H4."""
    if mt5 is None or not mt5.initialize():
        return dict(INDICS_NEUTRES)
    try:
        mt5.symbol_select(symbol, True)
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 120)
        if r is None or len(r) < 60:
            return dict(INDICS_NEUTRES)
        c = [float(x["close"]) for x in r][:-1]
        h = [float(x["high"]) for x in r][:-1]
        l = [float(x["low"]) for x in r][:-1]
        d = [c[i] - c[i - 1] for i in range(1, len(c))]
        up = sum(x for x in d[-14:] if x > 0) / 14
        dn = sum(-x for x in d[-14:] if x < 0) / 14
        rsi = 100 - 100 / (1 + up / (dn + 1e-9))
        tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
              for i in range(1, len(c))]
        return {"rsi": round(rsi, 1), "ema_ratio": 1.0, "atr": sum(tr[-14:]) / 14,
                "macd": 0.0, "bollinger_width": 0.0}
    except Exception:
        return dict(INDICS_NEUTRES)


@app.get("/api/ml/signals")
async def get_ml_signals():
    """Le panneau du dashboard. Les noms sont ceux de Vantage : le dashboard
    les compare aux symboles de ses graphiques («…»). Avant le 16/09
    il recevait «…» et ne trouvait jamais l'or."""
    signals = []
    for symbol in V.SYMBOLES:
        try:
            sig = fetch_signal_data(symbol)
            ind = _indicateurs_mt5(symbol)
            res = predict_ml(symbol, max(0.0, min(100.0, ind["rsi"])), 1.0, ind["atr"],
                             0.0, 0.0, float(sig.get("score", 50.0) or 50.0))
            signals.append({"symbol": res.symbol, "direction": res.prediction,
                            "score": res.score, "signal_ea": res.signal_ea,
                            "confidence": res.confidence, "highvol": res.highvol,
                            "timestamp": res.timestamp, "rsi": ind["rsi"], "atr": ind["atr"]})
        except Exception as e:
            logger.error(f"❌ Erreur pour {symbol}: {e}")
    return {"signals": signals, "count": len(signals)}


@app.get("/api/ml/analysis")
async def get_ml_analysis():
    signals = (await get_ml_signals())["signals"]
    buys = [s for s in signals if s["direction"] == "BUY"]
    sells = [s for s in signals if s["direction"] == "SELL"]
    return {
        "total": len(signals),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "hold_count": len([s for s in signals if s["direction"] == "HOLD"]),
        "neutral_count": len([s for s in signals if s["direction"] == "NEUTRAL"]),
        "buy_signals": buys,
        "sell_signals": sells,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/ml/avis")
async def avis(symbols: str = ""):
    """🧠 16/09 — CE QUE ml_avis.py FOURNISSAIT AU CERVEAU ET À L'ARBITRE,
    rapatrié ici. Un seul modèle, une seule source : le cerveau, l'arbitre et
    l'EA lisent désormais le même avis.
    Pour chaque marché : les deux probabilités, le sens le plus probable, et
    «…» quand il franchit la règle validée (p ≥ 0,42)."""
    out = []
    for demande in [s for s in symbols.split(",") if s.strip()][:16]:
        sym = resoudre_symbole(demande)
        pr = probabilites(sym) if sym else None
        v = verdict(pr)
        out.append({"demande": demande.strip(), "symbol": sym,
                    "p_buy": round(pr["p_buy"], 4) if pr else None,
                    "p_sell": round(pr["p_sell"], 4) if pr else None,
                    "sens": v["sens"], "p": round(v["p"], 4) if v["p"] is not None else None,
                    "favorable": bool(v["favorable"]), "prediction": v["prediction"],
                    "confidence": round(v["confidence"], 3),
                    # 🩹 16/09 : l'heure d'ouverture de la bougie H1 jugée — le
                    # sniper vérifie que c'est bien celle qui vient de clôturer
                    "bougie": int(pr["bougie"]) if pr else None})
    return {"modele": (paquet or {}).get("version"), "seuil_favorable": seuil_favorable(),
            "seuil_action": SEUIL_ACTION, "avis": out}


if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info(f"🚀 Serveur ML v2.1 — port {PORT}{' (ESSAI)' if ESSAI else ''}")
    logger.info(f"🤖 Modèle : {(paquet or {}).get('version', 'ABSENT')} · {MODELE}")
    logger.info("=" * 70)
    import socket
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            logger.warning(f"⚠️ Le port {PORT} est déjà occupé — cette instance se ferme.")
            raise SystemExit(0)
    except OSError:
        pass
    # 🔥 PRÉCHAUFFAGE, AVANT d'ouvrir le port et dans ce seul fil : à l'essai du
    # 16/09 le tout premier /predict a pris 1 712 ms (initialisation MT5 +
    # premières bougies) — l'EA abandonne à 2 000 ms. Les suivants : ~16 ms.
    t0 = time.time()
    for _s in V.SYMBOLES:
        probabilites(_s)
    logger.info(f"🔥 {len(_cache)}/{len(V.SYMBOLES)} marchés préchauffés en {time.time() - t0:.1f} s")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False)
