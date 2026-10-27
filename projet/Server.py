# -*- coding: utf-8 -*-
# =====================================================
#  AcidGPT Signal Server — v5.3 + MT5 Routes
#  Fusion V5.2 (Base stable) + Flux RSS Qualité & NLP Bilingue
# =====================================================
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify, request
import requests
import threading
import os
import json
import time
import MetaTrader5 as mt5
# 20/07 : réinstall MT5 -> initialize() sans path ne retrouve plus le terminal.
# Chemin injecté pour tout initialize() de ce fichier (voir ia_watchdog.py).
_MT5_EXE = r"C:\Program Files\Vantage Markets MT5 Terminal\terminal64.exe"
# 🚷 05/08 : ne JAMAIS ressusciter un MT5 fermé par le patron (même garde que
# ia_watchdog — la lib relançait terminal64 et piétinait les charts).
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
                            capture_output=True, timeout=5,
                            creationflags=0x08000000)
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
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import feedparser
import re
import socket
import calendar
# 🔧 FIX audit 03/08 : borne réseau GLOBALE. Avant, aucun timeout sur les flux
# RSS (socket None = blocage INFINI) : un flux en trou noir gelait
# refresh_signals() et faisait exploser les threads jusqu'à l'asphyxie.
socket.setdefaulttimeout(8)

# --- Matcher MOT ENTIER (fix audit 03/08) ---------------------------------
# Avant, «…» faisait matcher "SEC" dans "cyberSECurity", "WAR"
# dans "toWARd"/"WARren", "FED" dans "conFEDerate" → jusqu'à 50 % du score
# baissier de chaque actif était du bruit permanent. On matche désormais en
# frontière de mot (lettre/chiffre interdit autour), avec cache de regex.
_RX_CACHE = {}
def _kw_in(word: str, text_upper: str) -> bool:
    rx = _RX_CACHE.get(word)
    if rx is None:
        rx = re.compile(r'(?<![A-Z0-9])' + re.escape(word) + r'(?![A-Z0-9])')
        _RX_CACHE[word] = rx
    return rx.search(text_upper) is not None

# =====================================================
# RSS FEEDS - SÉLECTION QUALITÉ > QUANTITÉ
# =====================================================
# 🧹 22/07 : audit des flux — 7 des 11 anciens étaient MORTS (404/403/301 :
# reuters, investing_crypto, forexfactory, ig, zonebourse, tradingsat,
# abcbourse). Nettoyés + ajout de flux FR vivants (testés en direct).
RSS_FEEDS = {
    # === INTERNATIONAL (EN) — tous testés vivants le 22/07 ===
    "bloomberg":             "https://feeds.bloomberg.com/markets/news.rss",
    "yahoo_finance":         "https://finance.yahoo.com/news/rssindex",
    "cnbc_markets":          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "cnbc_investing":        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
    "ft_markets":            "https://www.ft.com/markets?format=rss",
    "wsj_markets":           "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "marketwatch":           "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    "seekingalpha":          "https://seekingalpha.com/feed.xml",
    "investing_forex":       "https://www.investing.com/rss/forex.rss",
    "investing_commodities": "https://www.investing.com/rss/commodities.rss",
    # === CRYPTO (manquait — pour BTC/ETH) ===
    "coindesk":              "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph":         "https://cointelegraph.com/rss",
    "cryptoast_fr":          "https://cryptoast.fr/feed/",
    # === FRANCOPHONE (macro / marchés) ===
    "lerevenu":              "https://www.lerevenu.com/rss.xml",
    "investing_fr_eco":      "https://fr.investing.com/rss/news_25.rss",
    "latribune":             "https://www.latribune.fr/rss/rubriques/actualite.html",
    "bfm_business":          "https://www.bfmtv.com/rss/economie/",
    "cafedelabourse":        "https://www.cafedelabourse.com/feed",
    "lemonde_eco":           "https://www.lemonde.fr/economie/rss_full.xml",
    "france24_une":          "https://www.france24.com/fr/rss",   # géopolitique = risque or/pétrole
}

# 🌐 user-agent navigateur : plusieurs flux (fr.investing, cafedelabourse…)
# renvoient 403/vide au user-agent par défaut de feedparser.
RSS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 🔧 FIX 04/08 : cooldown par flux. Un flux lent/mort (ex: cryptoast.fr en timeout
# à 7s) était rappelé à CHAQUE refresh (~45s) → 7s de latence + un ERROR rouge en
# boucle dans les logs. On le met au repos après un échec, on le réessaie plus tard.
_rss_skip = {}

def _fetch_one_rss(item) -> list:
    name, url = item
    if _rss_skip.get(name, 0) > time.time():
        return []                                    # flux en pause (a échoué récemment)
    try:
        # 🔧 FIX audit 03/08 : fetch via requests AVEC timeout borné (3s connexion,
        # 7s lecture) au lieu de feedparser sans timeout (blocage infini possible).
        r = requests.get(url, headers={"User-Agent": RSS_UA}, timeout=(3, 7))
        feed = feedparser.parse(r.content)
        if not feed.entries:
            _rss_skip[name] = time.time() + 300      # 5 min de repos
            _note_api("RSS:" + name, "morte", "0 article HTTP " + str(r.status_code))
            log_message("warn", "RSS " + name + " : 0 article (mort ?) HTTP " + str(r.status_code))
            return []
        # 🔧 FIX audit 03/08 : ne garder que les titres FRAIS (<= 48h). Avant, des
        # flux «…» (wsj/marketwatch) réinjectaient des articles de 2025 à
        # CHAQUE refresh → biais SELL permanent. Sans date → gardé mais plafonné.
        now = time.time()
        frais, sans_date = [], 0
        for e in feed.entries[:15]:
            pp = e.get("published_parsed") or e.get("updated_parsed")
            if pp is None:
                sans_date += 1
                frais.append(e.get("title", ""))
            elif (now - calendar.timegm(pp)) / 3600.0 <= 48:
                frais.append(e.get("title", ""))
            if len(frais) >= 10:
                break
        if sans_date and len(frais) == sans_date:
            frais = frais[:5]                       # flux sans dates : on plafonne
        if not frais:
            _note_api("RSS:" + name, "zombie", "aucun article < 48h")
            return []
        _note_api("RSS:" + name, "ok", str(len(frais)) + " art frais")
        return frais
    except Exception as e:
        _rss_skip[name] = time.time() + 600          # 10 min de repos (timeout / injoignable)
        _note_api("RSS:" + name, "injoignable", str(e)[:60])
        log_message("warn", "RSS " + name + " en pause 10 min: " + str(e)[:70])
        return []

def get_all_rss_news():
    # 🌐 récupération PARALLÈLE. Renvoie (titres, nb_flux_ok, nb_flux_total) pour
    # que refresh_signals connaisse la COUVERTURE réelle (fix audit 03/08 : sans
    # ça, 20 flux morts et 20 flux calmes donnaient le même «…»).
    from concurrent.futures import ThreadPoolExecutor
    items = list(RSS_FEEDS.items())
    all_news, nb_ok = [], 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for titres in ex.map(_fetch_one_rss, items):
            if titres:
                nb_ok += 1
                all_news.extend(titres)
    return all_news, nb_ok, len(items)

# =====================================================
# CONFIGURATION
# =====================================================
# 🔐 SECRETS (09/07) : centralisés dans secrets_acid.py — l'unique fichier hors git.
from secrets_acid import (API_KEYS, TELEGRAM_TOKEN, TELEGRAM_CHAT,
                          MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, ADMIN_PASSWORD)

CAPITAL    = 1000
RISK_PCT   = 2
STOP_PIPS  = 15
RR_RATIO   = 1.5

CACHE_DURATION  = 60
NEWS_COOLDOWN   = 28800
TRADING_ENABLED = True

# =====================================================
# MOTS CLÉS - DICTIONNAIRES BILINGUES (FR/EN)
# =====================================================
ASSETS = {
    "OILCash#": {"type":"commodity",
                "keywords_buy":  ["OIL SURGE", "OIL RISES", "PÉTROLE EN HAUSSE", "OR NOIR", "OPEC CUT", "OPEP BAISSE", "SUPPLY SHORTAGE", "PÉTROLE FLAMBE", "GEOPOLITICAL"],
                "keywords_sell": ["OIL FALLS", "OIL DROPS", "PÉTROLE EN BAISSE", "CHUTE DU PÉTROLE", "OPEC INCREASE", "OVERSUPPLY", "DEMAND WEAK"]},
    "BTCUSD":  {"type":"crypto",
                "keywords_buy":  ["BULLISH BTC", "BITCOIN RISES", "BTC HAUSSE", "BITCOIN EXPLOSE", "CRYPTO RALLY", "HALVING", "BITCOIN ETF", "BTC ETF", "SPOT ETF", "WHALE"],
                "keywords_sell": ["CRYPTO CRASH", "BITCOIN FALLS", "CHUTE DU BITCOIN", "BAISSE DES CRYPTOS", "REGULATION", "SEC", "LIQUIDATION"]},
    "GBPUSD":  {"type":"forex",
                "keywords_buy":  ["BOE DOVISH", "GBP RALLY", "RATE CUT", "RECOVERY", "POSITIVE GROWTH"],
                "keywords_sell": ["BOE HAWKISH", "INFLATION UK", "RATE HIKE", "GBP FALLS", "BREXIT"]},
    "USDJPY":  {"type":"forex",
                # fix audit 03/08 : RISK OFF / SAFE HAVEN → fuite vers le yen →
                # USDJPY BAISSE (ils étaient à tort en keywords_buy). RISK ON →
                # on vend le yen refuge → USDJPY MONTE (était à tort en sell).
                "keywords_buy":  ["BOJ DOVISH", "JPY WEAKNESS", "YEN FAIBLE", "RISK ON"],
                "keywords_sell": ["BOJ HAWKISH", "RATE HIKE", "JPY STRENGTH", "YEN FORT", "RISK OFF", "SAFE HAVEN"]},
    "EURUSD":  {"type":"forex",
                "keywords_buy":  ["ECB DOVISH", "EUR RALLY", "RATE CUT", "BAISSE DES TAUX", "RECOVERY"],
                "keywords_sell": ["ECB HAWKISH", "RATE HIKE", "EUR FALLS", "HAUSSE DES TAUX", "RECESSION"]},
    "XAUUSD":   {"type":"commodity",
                "keywords_buy":  ["GOLD SURGE", "GOLD RISES", "OR EN HAUSSE", "VALEUR REFUGE", "SAFE HAVEN", "GOLD RALLY", "ONCE D'OR", "UNCERTAINTY", "DOLLAR WEAK"],
                "keywords_sell": ["GOLD FALLS", "GOLD DROPS", "OR EN BAISSE", "CHUTE DE L'OR", "GOLD BEARISH", "RATE HIKE", "YIELDS UP"]},
    "USDX":     {"type":"index",
                "keywords_buy":  ["DOLLAR SURGE", "DOLLAR FORT", "USD STRENGTH", "BILLET VERT", "FED HAWKISH", "RATE HIKE", "HAUSSE DES TAUX", "STRONG JOBS"],
                "keywords_sell": ["DOLLAR FALLS", "DOLLAR FAIBLE", "USD WEAKNESS", "BAISSE DU DOLLAR", "FED DOVISH", "RATE CUT", "INFLATION COOLING"]},
    "Crypto_10#": {"type":"crypto_index",
                "keywords_buy":  ["CRYPTO RALLY", "BULL MARKET", "ADOPTION", "ETF APPROVED", "ALTCOIN SURGE", "MARKET CAP UP", "GREEN"],
                "keywords_sell": ["CRYPTO CRASH", "BEAR MARKET", "REGULATION", "SEC", "SELLOFF", "HACK", "LIQUIDATION"]},
    "SILVER":   {"type":"commodity",
                "keywords_buy":  ["SILVER SURGE", "SILVER RALLY", "SILVER RISES", "ARGENT EN HAUSSE", "SAFE HAVEN", "INDUSTRIAL DEMAND", "SOLAR DEMAND", "GOLD RALLY", "DOLLAR WEAK"],
                "keywords_sell": ["SILVER FALLS", "SILVER DROPS", "ARGENT EN BAISSE", "CHUTE DE L'ARGENT", "RATE HIKE", "YIELDS UP", "DOLLAR STRONG"]},
    "US500Cash#": {"type":"index",
                "keywords_buy":  ["STOCKS RALLY", "S&P RECORD", "WALL STREET RISES", "BOURSE EN HAUSSE", "EARNINGS BEAT", "FED DOVISH", "RATE CUT", "SOFT LANDING", "RISK ON"],
                "keywords_sell": ["STOCKS FALL", "WALL STREET DROPS", "SELLOFF", "RECESSION", "FED HAWKISH", "RATE HIKE", "EARNINGS MISS", "RISK OFF", "MARKET CRASH"]},
    # 🥇 22/08 (audit Vantage) : le NASDAQ avait sa lecture news renvoyée sur
    # celle du S&P 500. Les deux sont corrélés, mais le NAS100 est un indice
    # TECH : il réagit à Nvidia, aux semi-conducteurs et à l'IA bien avant que
    # le S&P ne bouge. Comme c'est devenu le marché n°1 mesuré (+41,4R sur
    # 252 trades), il lui faut ses propres mots-clés.
    "NAS100":   {"type":"index",
                "keywords_buy":  ["NASDAQ RALLY", "TECH RALLY", "TECH STOCKS RISE", "NVIDIA BEATS",
                                  "AI BOOM", "SEMICONDUCTOR DEMAND", "CHIP RALLY", "EARNINGS BEAT",
                                  "FED DOVISH", "RATE CUT", "YIELDS FALL", "RISK ON",
                                  "TECHNOLOGIE EN HAUSSE", "VALEURS TECH"],
                "keywords_sell": ["NASDAQ FALLS", "TECH SELLOFF", "TECH STOCKS DROP", "NVIDIA MISSES",
                                  "AI BUBBLE", "CHIP EXPORT BAN", "SEMICONDUCTOR GLUT",
                                  "EARNINGS MISS", "FED HAWKISH", "RATE HIKE", "YIELDS UP",
                                  "RISK OFF", "CHUTE DES VALEURS TECH", "KRACH TECH"]},
    "ETHUSD":   {"type":"crypto",
                "keywords_buy":  ["ETHEREUM RISES", "ETH RALLY", "ETHEREUM EXPLOSE", "ETHEREUM ETF", "ETH ETF", "STAKING", "UPGRADE", "ADOPTION", "CRYPTO RALLY"],
                "keywords_sell": ["CRYPTO CRASH", "ETHEREUM FALLS", "ETH DROPS", "CHUTE D'ETHEREUM", "REGULATION", "SEC", "HACK", "LIQUIDATION"]}
}

# Alias code-court -> clé ASSETS, pour les appelants qui envoient un code
# court (Mammouth/server_ml_v2 utilisent EUR/GOLD/OIL/BTC/USD/CRYPTO10 au
# lieu du nom de paire complet).
SHORT_CODE_ALIASES = {
    "EUR": "EURUSD", "GBP": "GBPUSD", "USD": "USDJPY",
    "BTC": "BTCUSD", "GOLD": "XAUUSD", "OIL": "OILCASH",
    "US500": "US500CASH", "ETH": "ETHUSD",
}

# clé "nettoyée" (upper, sans #/_) -> vraie clé ASSETS
_ASSET_KEY_LOOKUP = {k.upper().replace("#", "").replace("_", ""): k for k in ASSETS}

def resolve_asset_key(raw_asset: str) -> str:
    """Retrouve la clé ASSETS correspondant à un symbole, quel que soit le
    suffixe broker (XAUUSDm, EURUSD.pro...) ou l'alias utilisé par
    l'appelant (EUR/GOLD/OIL/BTC/USD/CRYPTO10). Avant ce correctif, tout
    symbole qui ne matchait pas EXACTEMENT une des règles explicites
    ci-dessous retombait sur un signal NEUTRAL par défaut sans la moindre
    erreur — cassant le filtre blacklist/highvol pour la plupart des paires
    forex (EA) et pour Mammouth, qui envoie des codes courts."""
    # 🟢 06/08 : on retire aussi '+' et '-' (Vantage : XAUUSD+, CL-OIL, SP500ft…)
    a = (raw_asset.upper().replace("#", "").replace("%23", "").replace("_", "")
         .replace("+", "").replace("-", "").replace(".", ""))

    # 🟢 06/08 VANTAGE : leurs noms diffèrent (CL-OIL, SP500, NAS100, suffixe +).
    # Le '+' et le '-' sont déjà retirés plus haut ; on mappe ici les nouveaux noms.
    if a in ["GOLD", "XAUUSD", "XAUUSD247", "XAUEUR", "XAUAUD", "XAUJPY"]: return "XAUUSD"
    if a in ["XAG", "XAGUSD", "SILVERUSD", "SILVER", "XAGAUD"]: return "SILVER"
    if a in ["OILCASH", "CLOIL", "CL-OIL", "USOIL", "XTIUSD", "WTI", "GASOIL"]: return "OILCash#"
    if a in ["SP500", "SP500FT", "US500", "US500CASH", "SPX500"]: return "US500Cash#"
    # 22/08 : NAS100 a désormais SA propre fiche (indice tech) — il ne renvoie
    # plus vers le S&P 500. Les autres alias du Nasdaq y sont rattachés.
    if a in ["NAS100", "US100", "USTEC", "NDX", "NASDAQ", "USTECH"]:  return "NAS100"
    if a in ["EURNOK", "EURSEK", "USDMXN", "USDZAR", "USDSEK", "USDNOK", "USDTRY"]:
        return "USDX"          # devises exotiques -> lecture par le dollar
    if a in ["EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"]:
        return "USDJPY"        # croisés yen -> lecture yen
    if a in ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"]:
        return "EURUSD"        # croisés euro -> lecture euro
    if a in ["AUDCAD", "AUDCHF", "AUDNZD", "AUDUSD", "NZDUSD", "NZDCAD",
             "NZDCHF", "CADCHF", "USDCAD", "USDCHF", "GBPAUD", "GBPCAD",
             "GBPCHF", "GBPNZD"]:
        return "USDX"          # majeures/croisés sans dico propre -> dollar
    if a == "OILCASH":          return "OILCash#"
    if a == "BTCUSD":           return "BTCUSD"
    if "USDX" in a:             return "USDX"
    if "CRYPTO" in a:           return "Crypto_10#"

    alias = SHORT_CODE_ALIASES.get(a)
    if alias:
        a = alias

    if a in _ASSET_KEY_LOOKUP:
        return _ASSET_KEY_LOOKUP[a]

    # Symbole avec suffixe broker (ex: EURUSDM, GBPUSDPRO...) : on cherche
    # une clé ASSETS connue en préfixe du symbole reçu.
    for cleaned, real_key in _ASSET_KEY_LOOKUP.items():
        if a.startswith(cleaned):
            return real_key

    return raw_asset.upper().replace("#", "").replace("%23", "")

# 🔓 DÉBLOCAGE DU TRADE (14/07, patron) : avant, UNE simple mention de la BCE
# (interview de Lagarde, article banal…) gelait TOUS les actifs pendant 8 h
# (NEWS_COOLDOWN) → le ML forcé à NEUTRAL/50 sur toute la planète, EA et bots
# à l'arrêt. Maintenant :
#   1. seuls les titres de DÉCISION IMMINENTE déclenchent la blacklist
#   2. elle ne touche que les actifs CONCERNÉS ("actifs": None = tous)
# Le HIGHVOL est affiné pareil : «…»/«…» seuls apparaissaient
# dans la moitié des titres business → mode high_vol quasi permanent.
BLACKLIST_EVENTS = {
    "BCE":  {"mots": ["ECB DECISION", "ECB MEETING", "ECB PRESS CONFERENCE",
                      "ECB RATE DECISION", "DECISION BCE", "RÉUNION BCE", "REUNION BCE"],
             "actifs": ["EURUSD", "GBPUSD", "USDX"]},   # la zone euro, pas l'or ni BTC
    "FOMC": {"mots": ["FOMC DECISION", "FOMC MEETING", "FED DECISION",
                      "FED RATE DECISION", "FOMC STATEMENT"],
             "actifs": None},   # le FOMC bouge TOUT : blackout global justifié
}
HIGHVOL_EVENTS = {"NFP": ["NFP", "NONFARM", "PAYROLLS", "JOBS REPORT"],
                  "CPI": ["CPI REPORT", "CPI DATA", "INFLATION REPORT", "INFLATION DATA"],
                  "FED": ["POWELL SPEECH", "POWELL TESTIMONY", "FOMC MINUTES"]}

RISK_HIGH = ["FED", "RATE HIKE", "HAUSSE DES TAUX", "INFLATION", "BREAKING", "WAR", "GUERRE", "BANK COLLAPSE",
             "RECESSION", "CRASH", "CHUTE", "SANCTIONS", "EMERGENCY", "CRISIS", "COLLAPSE", "DEFAULT",
             "PANIC", "SELLOFF", "SELL-OFF", "PLUNGE", "TARIFF", "NUCLEAR", "ATTACK", "BLACKOUT",
             "GEOPOLITICAL", "FOMC", "CPI MISS", "LOSSES"]
RISK_LOW  = ["RECOVERY", "OPTIMISM", "UPBEAT", "SOFT LANDING", "BULLISH", "MARKET RALLY", "HAUSSE",
             "GROWTH", "CROISSANCE", "STABLE", "RATE CUT", "BAISSE DES TAUX", "STIMULUS", "STRONG JOBS", 
             "BEAT EXPECTATIONS", "EARNINGS BEAT", "POSITIVE", "GAINS", "RALLY", "SURGE"]

# =====================================================
# FLASK + LOGGING
# =====================================================
app = Flask(__name__)

handler = RotatingFileHandler('acidgpt_server.log', maxBytes=1000000, backupCount=5, encoding='utf-8')
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

_cache      = {}
_cache_time = 0
_news_cache = {}
_start_time = time.time()

ACCOUNT_BALANCE = 1000.00
POSITIONS = []
ORDERS = []

def log_message(level: str, message: str) -> None:
    safe = message.encode('utf-8', errors='replace').decode('utf-8')
    getattr(app.logger, level, app.logger.info)(safe)

def send_telegram(msg: str) -> None:
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        log_message("error", "Telegram error: " + str(e))

# =====================================================
# MT5
# =====================================================
def connect_mt5() -> bool:
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        log_message("error", "MT5 init failed")
        return False
    return True

# Même table que MT5Connector.PIP_MAP dans BOT_MAMMOUTH_COMPLETE_V7.py —
# on la duplique ici pour que ce webhook calcule un lot cohérent quel que
# soit le symbole reçu, au lieu de supposer un pip fixe de 0.1 (= or) partout.
PIP_MAP = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01,
    "XAUUSD": 0.1,    "GOLD": 0.1,      "GOLD#": 0.1,
    "BTCUSD": 1.0,    "BTCUSD#": 1.0,   "BTC": 1.0,
    "OILCASH": 0.01,  "OILCash#": 0.01, "OIL": 0.01,
    "CRYPTO10": 1.0,  "Crypto_10#": 1.0,
    "DEFAULT": 0.0001
}

def _normalize_symbol(s: str) -> str:
    return s.upper().replace("#", "").replace("_", "").replace("%23", "")

# Certaines clés de PIP_MAP (ex: "OILCash#", "Crypto_10#") sont en casse
# mixte : symbol.upper() ne pouvait donc JAMAIS les matcher (bug latent).
# On normalise clés ET symbole reçu de la même façon, et on retombe sur un
# préfixe connu si le symbole a un suffixe broker (ex: "XAUUSDm").
_PIP_LOOKUP = {_normalize_symbol(k): v for k, v in PIP_MAP.items() if k != "DEFAULT"}

def get_pip(symbol: str) -> float:
    s = _normalize_symbol(symbol)
    if s in _PIP_LOOKUP:
        return _PIP_LOOKUP[s]
    for key, val in _PIP_LOOKUP.items():
        if s.startswith(key):
            return val
    return PIP_MAP["DEFAULT"]

def calculate_lot(capital: float, risk_pct: float, stop_pips: float, pip: float) -> float:
    risk_amount = capital * (risk_pct / 100)
    lot = risk_amount / (stop_pips * pip * 100000)
    return round(max(lot, 0.01), 2)

def place_order_mt5(signal: str, price: float, symbol: str = "XAUUSDm") -> dict:
    if not connect_mt5():
        return {"status": "error", "msg": "MT5 non connecte"}

    # Solde reel du compte plutot que la constante CAPITAL figee a 1000 -
    # sinon le lot calcule ne suit jamais l'evolution reelle du capital.
    account = mt5.account_info()
    capital = account.balance if account else CAPITAL

    pip = get_pip(symbol)
    lot = calculate_lot(capital, RISK_PCT, STOP_PIPS, pip)

    if signal == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        sl = round(price - STOP_PIPS * pip, 2)
        tp = round(price + STOP_PIPS * RR_RATIO * pip, 2)
    else:
        order_type = mt5.ORDER_TYPE_SELL
        sl = round(price + STOP_PIPS * pip, 2)
        tp = round(price - STOP_PIPS * RR_RATIO * pip, 2)

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    20,
        "magic":        20260613,
        "comment":      "AcidBot " + signal,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(req)
    mt5.shutdown()

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = f"<b>ORDRE {signal} EXECUTE</b>\nPaire: {symbol}\nPrix: {price}\nLot: {lot}\nSL: {sl}\nTP: {tp}"
        log_message("info", "Ordre OK")
        send_telegram(msg)
        return {"status": "ok", "lot": lot, "sl": sl, "tp": tp}
    else:
        msg = "Ordre echoue"
        log_message("error", msg)
        send_telegram(msg)
        return {"status": "error"}

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data   = request.get_json(force=True)
        signal = data.get("signal", "").upper()
        pair   = data.get("pair", "XAUUSDm").upper()
        price  = float(data.get("price", 0))

        if not TRADING_ENABLED or open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode_trading.txt"), encoding="utf-8").read().strip().upper() != "REEL":   # version publique : la SIMULATION couvre aussi /webhook
            return jsonify({"status": "blocked", "reason": "trading disabled"}), 200

        if signal in ["BUY", "SELL"] and price > 0:
            result = place_order_mt5(signal, price, symbol=pair)
            return jsonify({"status": "ok", "order": result}), 200
        return jsonify({"status": "signal invalide"}), 400

    except Exception as e:
        return jsonify({"status": "erreur", "detail": str(e)}), 500

@app.route("/admin/trading", methods=["POST"])
def admin_trading():
    # ADMIN_PASSWORD existait deja mais n'etait utilise nulle part : il n'y
    # avait aucun moyen de couper TRADING_ENABLED sans editer le fichier et
    # relancer le process. Cette route ne pilote QUE ce flag Python (donc le
    # /webhook ci-dessus) - elle n'a aucun effet sur l'input TradingEnabled
    # de l'EA MQL5, qui reste le seul vrai interrupteur du bot MT5.
    global TRADING_ENABLED
    data = request.get_json(force=True, silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"status": "erreur", "detail": "mot de passe invalide"}), 403
    enabled = data.get("enabled")
    if enabled is None:
        return jsonify({"status": "erreur", "detail": "champ 'enabled' manquant"}), 400
    TRADING_ENABLED = bool(enabled)
    log_message("info", f"TRADING_ENABLED -> {TRADING_ENABLED} (via /admin/trading)")
    return jsonify({"status": "ok", "trading_enabled": TRADING_ENABLED})

# =====================================================
# SOURCES NEWS
# =====================================================
# =====================================================
#  CALENDRIER REEL (08/09) — idee du patron : «…
#  …»
#  Le paquet Python de MT5 n'expose aucune fonction calendrier ; l'EA le lit
#  (CalendarValueHistory) et le publie dans MQL5/Files/acid_calendrier.txt.
#  On prefere TOUJOURS ce fait a une devinette sur les titres de presse.
# =====================================================
import glob as _glob

CAL_MOTIF = os.path.join("C:" + os.sep, "Users", "*", "AppData", "Roaming",
                         "MetaQuotes", "Terminal", "*", "MQL5", "Files",
                         "acid_calendrier.txt")
CAL_FRAICHEUR_S  = 900     # au-dela, fichier perime -> on retombe sur les titres
CAL_BLACKOUT_MIN = 15      # +/- 15 min d'un event majeur : on ne touche a rien
CAL_HIGHVOL_MIN  = 60      # +/- 60 min : volatilite elevee, mais on peut trader
CAL_MAJEURS = ("FOMC", "FED INTEREST RATE", "INTEREST RATE DECISION",
               "RATE DECISION", "NONFARM", "NON-FARM", "PAYROLL",
               "ECB INTEREST", "CPI")


def calendrier_mt5():
    """[(timestamp, devise, nom)] des events HAUTE importance publies par l'EA,
    ou None si le fichier est absent/perime."""
    for f in _glob.glob(CAL_MOTIF):
        try:
            if time.time() - os.path.getmtime(f) > CAL_FRAICHEUR_S:
                continue
            out = []
            for ligne in open(f, encoding="ansi", errors="replace").read().splitlines():
                if not ligne or ligne.startswith("#"):
                    continue
                p = ligne.split("|")
                if len(p) >= 4:
                    try:
                        out.append((int(p[0]), p[1].strip().upper(), p[3].strip().upper()))
                    except ValueError:
                        pass
            return out
        except Exception:
            continue
    return None


def verdict_calendrier(asset=None):
    """(blacklist, highvol) d'apres le VRAI calendrier. (None, None) si indisponible."""
    ev = calendrier_mt5()
    if ev is None:
        return (None, None)
    maintenant = time.time()
    bl, hv = False, None
    for ts, dev, nom in ev:
        ecart = abs(ts - maintenant) / 60.0
        if ecart <= CAL_HIGHVOL_MIN and hv is None:
            hv = nom[:40]
        if ecart <= CAL_BLACKOUT_MIN and any(k in nom for k in CAL_MAJEURS):
            bl = True
    return (bl, hv)


# =====================================================
#  LA PETITE IA DES NEWS (08/09) — elle INTERPRETE, elle ne bloque jamais.
#  Repartition des roles, volontaire :
#     calendrier MT5  -> les BLOCAGES (fait)
#     cette IA        -> le SENS et la FORCE (interpretation)
#  Un mot-cle ne distingue pas «…» de «…
#  …» : c'est ce qui a fait declarer un NFP un mardi
#  et mis le ML a confiance 0,0 toute la journee du 08/09.
#  Silencieuse : aucun message Telegram, aucun log bruyant. Si elle ne repond
#  pas, on retombe sur les mots-cles sans rien casser.
# =====================================================
IA_NEWS_ACTIVE   = True
IA_NEWS_PERIODE  = 900        # un seul appel toutes les 15 min
IA_NEWS_TITRES   = 30         # au plus 30 titres envoyes
_ia_news_cache   = {"ts": 0.0, "avis": {}}


def _ia_appel(prompt, max_tokens=400):
    """Appel discret, via le compte Mammouth du patron puis Mistral en secours."""
    try:
        import secrets_acid as _sec
    except Exception:
        return ""
    tentatives = [
        ("https://api.mammouth.ai/v1/chat/completions",
         getattr(_sec, "MAMMOUTH_API_KEY", ""), "gpt-4o-mini"),
        ("https://api.mistral.ai/v1/chat/completions",
         getattr(_sec, "MISTRAL_API_KEY", ""), "mistral-small-latest"),
    ]
    for url, cle, modele in tentatives:
        if not cle:
            continue
        try:
            r = requests.post(url, timeout=20,
                              headers={"Authorization": "Bearer " + cle,
                                       "Content-Type": "application/json"},
                              json={"model": modele, "max_tokens": max_tokens,
                                    "temperature": 0.1,
                                    "messages": [{"role": "user", "content": prompt}]})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            continue
    return ""


def avis_ia_news(titres):
    """{actif: {"biais": -1..+1, "force": 0..3, "pourquoi": "..."}}.
    Renvoie {} si l'IA est indisponible : l'appelant retombe sur les mots-cles."""
    if not IA_NEWS_ACTIVE or not titres:
        return {}
    if time.time() - _ia_news_cache["ts"] < IA_NEWS_PERIODE:
        return _ia_news_cache["avis"]
    _ia_news_cache["ts"] = time.time()
    liste = chr(10).join("- " + t[:150] for t in titres[:IA_NEWS_TITRES])
    prompt = (
        "Tu lis des titres de presse financiere et tu en tires un biais de marche.\n"
        "ACTIFS : GOLD, SILVER, OIL, BTC, ETH, US500, US100, EUR, GBP, USD.\n"
        "REGLES STRICTES :\n"
        "- biais : -1 (baissier), 0 (neutre), +1 (haussier) pour l'ACTIF, pas pour l'economie.\n"
        "- force : 0 = bavardage, 1 = information, 2 = important, 3 = majeur et IMMINENT.\n"
        "- Un titre qui ANNONCE un evenement FUTUR (la semaine prochaine, le mois "
        "prochain) a une force de 0 ou 1 : il ne se passe rien maintenant.\n"
        "- Si un actif n'est pas concerne, ne le cite pas.\n"
        "- Aucune phrase hors du JSON.\n"
        'Reponds UNIQUEMENT : {"GOLD":{"biais":-1,"force":2,"pourquoi":"..."}, ...}\n\n'
        "TITRES :\n" + liste)
    brut = _ia_appel(prompt)
    if not brut:
        return _ia_news_cache["avis"]
    try:
        d = brut[brut.index("{"):brut.rindex("}") + 1]
        avis = json.loads(d)
        if isinstance(avis, dict):
            _ia_news_cache["avis"] = avis
    except Exception:
        pass
    return _ia_news_cache["avis"]


def check_blacklist_event(title, asset=None):
    """asset = clé ASSETS de l'appelant : la blacklist ne s'applique que si
    l'événement le VISE ("actifs": None = tous). asset=None = conservateur."""
    text = title.upper()
    for source, cfg in BLACKLIST_EVENTS.items():
        if any(_kw_in(kw, text) for kw in cfg["mots"]):
            vises = cfg.get("actifs")
            if vises is None or asset is None or asset in vises:
                return ("BLACKLIST", source)
    for event, keywords in HIGHVOL_EVENTS.items():
        if any(_kw_in(kw, text) for kw in keywords): return ("HIGHVOL", event)
    return (None, None)

def get_coingecko_sentiment():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        d = r.json().get("data", {})
        btc = d.get("market_cap_percentage", {}).get("btc", 0)
        chg = d.get("market_cap_change_percentage_24h_usd", 0)
        if btc > 50 and chg > 0: return "CRYPTO_BULLISH"
        if btc < 40 and chg < 0: return "CRYPTO_BEARISH"
        return "CRYPTO_NEUTRAL"
    except:
        return "CRYPTO_NEUTRAL"

def cached_fetch(name, func, ttl=None):
    # 📡 06/08 : TTL par source, calé sur le QUOTA de chacune.
    #   finnhub    : 60 appels/MINUTE  -> 15 min (news vraiment fraîches)
    #   mediastack : 100 appels/MOIS ! -> 12 h (≈60/mois, marge de sécurité)
    #   les autres : NEWS_COOLDOWN (8 h)
    if ttl is None:
        ttl = 900 if name.startswith("finnhub") else (43200 if name == "mediastack" else NEWS_COOLDOWN)
    now = time.time()
    if name in _news_cache and now - _news_cache[name]['timestamp'] < ttl:
        return _news_cache[name]['data']
    data = func()
    _news_cache[name] = {'timestamp': now, 'data': data}
    return data

# 🗝️ SANTÉ DES CLÉS API (14/07, demande patron) : les clés presse périment
# en silence (_fetch renvoyait [] sans un bruit). Chaque fetch note ici
# l'état de sa clé ; /health l'expose et LE CERVEAU (seule voix Telegram) alerte.
_api_sante = {}
_sym_inconnu_log = {}   # 🤫 anti-spam «…» (1 log / symbole / 10 min)

def _note_api(label, etat, detail=""):
    _api_sante[label] = {"etat": etat, "detail": str(detail)[:80],
                         "ts": time.strftime("%Y-%m-%d %H:%M:%S")}

def _fetch(url, key_path, title_key, label):
    if "A_REMPLIR" in url:   # version publique : clé non renseignée = source ignorée, sans alerte
        _note_api(label, "non configurée", "clé non renseignée dans secrets_acid.py")
        return []
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        d = r.json()
        for k in key_path: d = d.get(k, [])
        titres = [a.get(title_key, "") for a in d]
        # 🔧 FIX audit 03/08 : un 200 avec 0 article n'est PAS «…».
        etat = "ok" if len(titres) >= 3 else ("vide" if not titres else "degrade")
        _note_api(label, etat, f"{len(titres)} titres")
        return titres
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (401, 402, 403) or "invalid" in str(e).lower() or "expired" in str(e).lower():
            _note_api(label, "morte", f"HTTP {code or '?'} - cle refusee/perimee")
        elif code == 429:
            _note_api(label, "quota", "HTTP 429 - quota epuise")
        else:
            _note_api(label, "injoignable", str(e)[:60])
        return []

def get_thenewsapi_signal():
    url = f"https://api.thenewsapi.com/v1/news/top?api_token={API_KEYS['THENEWSAPI_KEY']}&language=en&categories=business,politics,world&limit=15"
    return _fetch(url, ["data"], "title", "TheNewsAPI")

def get_currents_signal():
    url = f"https://api.currentsapi.services/v1/latest-news?apiKey={API_KEYS['CURRENTS_API_KEY']}&language=en&category=business"
    return _fetch(url, ["news"], "title", "Currents")

def get_gnews_signal():
    url = f"https://gnews.io/api/v4/top-headlines?token={API_KEYS['GNEWS_API_KEY']}&lang=en&topic=business&max=10"
    return _fetch(url, ["articles"], "title", "GNews")

# =====================================================
# 📡 FINNHUB (06/08) — la clé dormait dans secrets_acid.py sans être branchée.
# Deux apports que les RSS ne savent PAS faire :
#   1. des news par CATÉGORIE (forex / crypto / merger) — déjà ciblées marché
#   2. des news TAGGÉES PAR SYMBOLE (company-news) → on demande «…
#      …» au lieu de deviner dans 200 titres génériques.
# Tier gratuit : 60 appels/min — on en fait ~4 par refresh, large.
# =====================================================
# =====================================================
# 🧹 FILTRE MACRO (06/08) — Guardian / NewsAPI / Mediastack sont des sources
# GÉNÉRALISTES («…», «…», «…»…). L'audit du 03/08 a
# prouvé que ce bruit ÉCRASE le signal spécifique (les 11 actifs sortaient SELL
# ensemble). On ne garde donc QUE les titres qui parlent vraiment macro/marché.
# =====================================================
MACRO_MOTS = ["FED", "FOMC", "ECB", "BCE", "BOJ", "BOE", "RATE", "TAUX", "INFLATION",
              "CPI", "PPI", "JOBS", "PAYROLL", "NFP", "GDP", "PIB", "RECESSION",
              "DOLLAR", "USD", "EURO", "YEN", "GOLD", "OR ", "BULLION", "SILVER",
              "OIL", "CRUDE", "OPEC", "OPEP", "PETROLE", "PÉTROLE", "BITCOIN",
              "CRYPTO", "ETHEREUM", "BTC", "ETH", "STOCKS", "MARKET", "MARCHE",
              "MARCHÉ", "BOURSE", "TREASURY", "YIELD", "WAR", "GUERRE", "TARIFF",
              "SANCTIONS", "GEOPOLITICAL", "CENTRAL BANK", "BANQUE CENTRALE"]

def _garder_macro(titres: list) -> list:
    """Ne laisse passer que les titres à teneur macro/marché (mot entier)."""
    out = []
    for t in titres or []:
        txt = (t or "").upper()
        if any(_kw_in(m.strip(), txt) for m in MACRO_MOTS):
            out.append(t)
    return out

def get_guardian_signal():
    url = ("https://content.guardianapis.com/search?section=business&page-size=20"
           f"&api-key={API_KEYS['GUARDIAN_API_KEY']}")
    return _garder_macro(_fetch(url, ["response", "results"], "webTitle", "Guardian"))

def get_newsapi_signal():
    url = ("https://newsapi.org/v2/top-headlines?category=business&language=en&pageSize=20"
           f"&apiKey={API_KEYS['NEWSAPI_KEY']}")
    return _garder_macro(_fetch(url, ["articles"], "title", "NewsAPI"))

def get_mediastack_signal():
    # ⚠️ 100 appels/MOIS seulement → cache 12 h (voir cached_fetch). HTTPS obligatoire.
    url = (f"https://api.mediastack.com/v1/news?access_key={API_KEYS['MEDIASTACK_API_KEY']}"
           "&categories=business&languages=en&limit=25")
    return _garder_macro(_fetch(url, ["data"], "title", "Mediastack"))

def get_finnhub_categorie(cat: str) -> list:
    url = f"https://finnhub.io/api/v1/news?category={cat}&token={API_KEYS['FINNHUB_API_KEY']}"
    return _fetch(url, [], "headline", "Finnhub:" + cat)

def get_finnhub_signal():
    """Titres marché des catégories utiles au bot (forex + crypto + fusions)."""
    titres = []
    for cat in ("forex", "crypto", "merger"):
        titres.extend(get_finnhub_categorie(cat)[:15])
    return titres

# Actif ACID -> tickers Finnhub qui portent SA news (ETF/proxies cotés US).
# L'or n'a pas de flux propre côté gratuit : GLD (ETF or) est son miroir fidèle.
FINNHUB_PROXIES = {
    "XAUUSD":     ["GLD"],
    "SILVER":     ["SLV"],
    "OILCash#":   ["USO"],
    "BTCUSD":     ["COIN", "MSTR"],
    "ETHUSD":     ["COIN"],
    "Crypto_10#": ["COIN"],
    "US500Cash#": ["SPY"],
    "USDX":       ["UUP"],
}

def get_finnhub_actif(asset: str) -> list:
    """News SPÉCIFIQUES à un actif (le gros manque des RSS génériques)."""
    tickers = FINNHUB_PROXIES.get(asset) or []
    if not tickers:
        return []
    jour = time.strftime("%Y-%m-%d")
    hier = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    titres = []
    for tk in tickers:
        url = (f"https://finnhub.io/api/v1/company-news?symbol={tk}"
               f"&from={hier}&to={jour}&token={API_KEYS['FINNHUB_API_KEY']}")
        titres.extend(_fetch(url, [], "headline", "Finnhub:" + tk)[:10])
    return titres

# =====================================================
# ANALYSE
# =====================================================
def analyze_for_asset(titles, asset):
    spec_buy = spec_sell = 0     # mots-clés SPÉCIFIQUES à l'actif (poids 3)
    gen_buy  = gen_sell  = 0     # RISK_LOW / RISK_HIGH GÉNÉRIQUES (poids 1)
    blacklist = False
    highvol   = None
    cfg = ASSETS.get(asset, {})
    # le VRAI calendrier prime sur les titres de presse
    _cal_bl, _cal_hv = verdict_calendrier(asset)
    _cal_dispo = _cal_bl is not None
    for title in titles:
        text = title.upper()
        if not _cal_dispo:            # sans calendrier, on retombe sur les mots-cles
            et, en = check_blacklist_event(title, asset)
            if et == "BLACKLIST": blacklist = True
            elif et == "HIGHVOL": highvol = en
        for w in cfg.get("keywords_buy",  []): spec_buy  += 3 if _kw_in(w, text) else 0
        for w in cfg.get("keywords_sell", []): spec_sell += 3 if _kw_in(w, text) else 0
        for w in RISK_LOW:  gen_buy  += 1 if _kw_in(w, text) else 0
        for w in RISK_HIGH: gen_sell += 1 if _kw_in(w, text) else 0
    # 🔧 FIX audit 03/08 : le générique (RISK_HIGH/LOW, communs à TOUS les actifs)
    # écrasait le spécifique (~15:1) → les 11 actifs sortaient SELL en même temps
    # (or et dollar, pourtant anticorrélés, même verdict). On plafonne la
    # contribution générique à (spécifique + 5) pour lui rendre un rôle d'appoint.
    buy_score  = spec_buy  + min(gen_buy,  spec_buy  + 5)
    sell_score = spec_sell + min(gen_sell, spec_sell + 5)
    # la petite IA : elle pese sur le SENS, jamais sur le blocage
    try:
        _a = avis_ia_news(titles).get(asset or "", {})
        _b, _f = int(_a.get("biais", 0)), max(0, min(3, int(_a.get("force", 0))))
        if _b > 0:   buy_score  += 3 * _f
        elif _b < 0: sell_score += 3 * _f
    except Exception:
        pass
    if _cal_dispo:                    # le fait remplace la devinette
        blacklist, highvol = _cal_bl, _cal_hv
    return buy_score, sell_score, blacklist, highvol

def compute_signal(b, s):
    # 🔧 FIX audit 03/08 : seuil RELATIF au volume + minimum de matière. Avant, un
    # écart fixe de 2 points suffisait à basculer BUY/SELL (le signal sautait sur
    # du bruit) et 1 seul titre pouvait décider du sens.
    t = b + s
    if t < 4: return "NEUTRAL"                 # pas assez de matière
    seuil = max(3, 0.15 * t)
    if b - s > seuil: return "BUY"
    if s - b > seuil: return "SELL"
    return "NEUTRAL"

def compute_confidence(b, s, sig):
    # 🔧 FIX audit 03/08 : pondérée par le VOLUME de preuve, pas seulement la
    # pureté. Avant, 1 seul titre donnait confiance 1.0 et score 95 («…
    # …» — l'inverse du bon sens).
    t = b + s
    if t == 0: return 0.0
    purete = abs(b - s) / t
    volume = min(1.0, t / 40.0)                # 40 points de score = preuve pleine
    return round(purete * volume, 3)

def compute_score_ea(sig, conf, bl, hv):
    if bl: return 5.0
    if hv: return 30.0
    if sig == "NEUTRAL": return 55.0
    return round(60.0 + conf * 35.0, 1)

def compute_signal_ea(bl, hv):
    if bl: return "crucial"
    if hv: return "high_vol"
    return "safe"

_refresh_lock = threading.Lock()

def refresh_signals():
    global _cache, _cache_time
    # 🔧 FIX audit 03/08 : verrou anti-concurrence. Avant, _cache_time n'étant posé
    # qu'à la FIN, chaque requête arrivant pendant un refresh (EA 60s + Mammouth +
    # LE CERVEAU) en relançait un → 60-80 requêtes RSS d'un coup, rate-limiting garanti.
    # On sérialise et on marque l'heure AVANT la collecte pour couper la ruée.
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        _cache_time = time.time()
        log_message("info", "REFRESH DES SIGNAUX")
        all_titles = []

        for name, func in [("thenewsapi", get_thenewsapi_signal), ("currents", get_currents_signal),
                           ("gnews", get_gnews_signal), ("finnhub", get_finnhub_signal),
                           # 06/08 : les 3 clés qui dormaient — filtrées macro (voir _garder_macro)
                           ("guardian", get_guardian_signal), ("newsapi", get_newsapi_signal),
                           ("mediastack", get_mediastack_signal)]:
            all_titles.extend(cached_fetch(name, func))

        rss_titles, rss_ok, rss_total = get_all_rss_news()
        all_titles.extend(rss_titles)
        crypto_sentiment = get_coingecko_sentiment()

        # 🔧 FIX audit 03/08 : COUVERTURE des sources. Réseau coupé / flux tous HS
        # ne doit PAS produire le même «…» qu'un marché
        # calme. Sous 50 % de flux vivants (ou < 30 titres) → on force la PRUDENCE.
        couverture   = rss_ok / rss_total if rss_total else 0.0
        news_indispo = (couverture < 0.5) or (len(all_titles) < 30)

        # 📡 Finnhub par ACTIF (06/08) : les titres qui parlent VRAIMENT de l'or,
        # du pétrole, du BTC… via leurs proxies cotés. Mis en cache 15 min pour
        # rester très loin des 60 appels/min du tier gratuit.
        finnhub_actif = {}
        for asset in ASSETS:
            if asset in FINNHUB_PROXIES:
                finnhub_actif[asset] = cached_fetch(
                    "finnhub_" + asset, lambda a=asset: get_finnhub_actif(a))

        asset_signals = {}
        for asset in ASSETS:
            # les titres ciblés de l'actif s'ajoutent au corpus général pour LUI
            b, s, bl, hv = analyze_for_asset(all_titles + finnhub_actif.get(asset, []), asset)
            sig   = compute_signal(b, s)
            conf  = compute_confidence(b, s, sig)
            score = compute_score_ea(sig, conf, bl, hv)
            s_ea  = compute_signal_ea(bl, hv)
            warn  = ("BLACKLIST EVENT" if bl else ("HIGHVOL: " + str(hv)) if hv else "NO MAJOR EVENTS")

            # Données news indisponibles → PRUDENCE, pas «…». On renvoie
            # "high_vol" (déjà géré par l'EA) plutôt qu'un faux calme rassurant.
            if news_indispo and not bl:
                s_ea  = "high_vol"
                score = 30.0
                warn  = "DONNEES NEWS INDISPONIBLES (couverture %.0f%%)" % (couverture * 100)

            asset_signals[asset] = {
                "signal":     sig,
                "signal_ea":  s_ea,
                "score":      score,
                "buy_score":  b,
                "sell_score": s,
                "confidence": conf,
                "blacklist":  bl,
                "highvol":    hv,
                "warning":    warn,
                "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S")
            }
        _cache = {
            "timestamp":        time.strftime("%Y-%m-%d %H:%M:%S"),
            "trading_enabled":  TRADING_ENABLED,
            "crypto_sentiment": crypto_sentiment,
            "data_quality":     round(couverture, 2),
            "rss_vivants":      "%d/%d" % (rss_ok, rss_total),
            "news_indispo":     news_indispo,
            "assets":           asset_signals
        }
        _cache_time = time.time()
        log_message("info", "Signaux mis a jour (%d titres, RSS %d/%d)" % (len(all_titles), rss_ok, rss_total))
    finally:
        _refresh_lock.release()

# =====================================================
# ROUTES
# =====================================================
@app.route("/signal")
def signal_route():
    global _cache, _cache_time
    if not TRADING_ENABLED:
        # 🔧 FIX audit 03/08 : renvoyer 200 (pas 403). L'EA abandonne le corps sur
        # un code != 200 et se rabat sur «…» → couper le trading le rendait
        # PLUS permissif. Le blocage est déjà porté par signal_ea="crucial".
        return jsonify({"signal":"NEUTRAL","signal_ea":"crucial","score":0.0, "status":"TRADING DISABLED"}), 200
    
    raw_asset = request.args.get("symbol", "ALL").upper().replace("#", "").replace("%23", "")
    
    if time.time() - _cache_time > CACHE_DURATION: refresh_signals()
    
    if raw_asset == "ALL":
        return jsonify(_cache)
    
    asset = resolve_asset_key(raw_asset)

    d   = _cache.get("assets", {}).get(asset, {})
    # 🔧 FIX audit 03/08 : symbole NON suivi → réponse EXPLICITE prudente. Avant,
    # d={} donnait une réponse sans signal_ea → l'EA lisait «…» (fail-open).
    if not d:
        # 🤫 06/08 : 1 alerte par symbole / 10 min (avant : à CHAQUE appel — l'EA
        # et les bots interrogent en boucle, le log devenait illisible).
        _cle = str(raw_asset)
        if time.time() - _sym_inconnu_log.get(_cle, 0) > 600:
            _sym_inconnu_log[_cle] = time.time()
            log_message("warn", "Symbole non suivi: " + _cle)
        return jsonify({"symbol": asset, "signal": "NEUTRAL", "signal_ea": "high_vol",
                        "score": 30.0, "warning": "SYMBOLE NON SUIVI",
                        "assistant_message": "Actif non suivi par le filtre news — prudence.",
                        "trading_enabled": TRADING_ENABLED}), 200
    sig = d.get("signal", "NEUTRAL")

    if   "BLACKLIST" in d.get("warning", ""): chat = "Touche a rien ! " + d.get("warning", "")
    elif "HIGHVOL" in d.get("warning", ""): chat = "Prepare-toi Boss ! " + d.get("warning", "")
    elif "DONNEES NEWS" in d.get("warning", ""): chat = "News indispo — prudence."
    elif sig == "BUY": chat = "Les news sont Bullish, on cherche des longs !"
    elif sig == "SELL": chat = "Ca saigne dans les news, on short !"
    else: chat = "C'est calme. On attend."

    return jsonify({**d, "symbol": asset, "assistant_message": chat, "trading_enabled": TRADING_ENABLED})

@app.route("/signals")
def signals_route():
    global _cache, _cache_time
    if time.time() - _cache_time > CACHE_DURATION: refresh_signals()
    return jsonify(_cache)

@app.route("/signals/all")
def signals_all_route():
    # Ajouté au cas où Mammouth appelle précisément ça selon tes logs
    global _cache, _cache_time
    if time.time() - _cache_time > CACHE_DURATION: refresh_signals()
    return jsonify(_cache)

@app.route("/health")
def health():
    # 🔧 FIX audit 03/08 : exposer l'état des flux RSS (95 % du corpus). Avant,
    # /health ne montrait que les 3 API presse → l'effondrement de 7 flux RSS
    # (incident du 31/07) ne déclenchait AUCUNE alerte, invisible pour LE CERVEAU.
    rss = {k: v for k, v in _api_sante.items() if k.startswith("RSS:")}
    rss_ok = sum(1 for v in rss.values() if v.get("etat") == "ok")
    return jsonify({"status": "OK", "trading": "ENABLED" if TRADING_ENABLED else "DISABLED",
                    "data_quality": _cache.get("data_quality"),
                    "rss_vivants": f"{rss_ok}/{len(RSS_FEEDS)}",
                    "cles_api": {k: v for k, v in _api_sante.items() if not k.startswith("RSS:")},
                    "rss": rss})

@app.route('/api/trading/status', methods=['GET'])
def get_status():
    return jsonify({"status": "connected", "mt5": "online", "trading_enabled": TRADING_ENABLED}), 200

def keepalive():
    """♨️ 14/07 : 300→45 s. Le cache des signaux expire à 60 s mais n'était
    re-chauffé que toutes les 5 min → 4 min sur 5, le premier appelant (le
    bot mammouth) déclenchait le refresh INLINE et mangeait des timeouts de
    10 s (vu 3x dans mammouth_v7.log cette nuit). À 45 s, le cache est
    toujours chaud — les requêtes ne bloquent plus. Les APIs presse restent
    protégées par leur propre cooldown de 8 h (NEWS_COOLDOWN)."""
    while True:
        time.sleep(45)
        try:
            refresh_signals()
        except:
            pass
        # 📋 16/09 — LA FICHE DU SERVEUR NEWS.
        # Quand ce serveur decroche, ses reponses perimees ressemblent trait
        # pour trait a des reponses valides. Sa fiche porte son age : un
        # lecteur voit desormais qu'il s'est tu.
        try:
            import sys as _sys
            if r"C:\AcidBot\BOT COMPLETO" not in _sys.path:     # 16/09 : une fois, pas toutes les 45 s
                _sys.path.insert(0, r"C:\AcidBot\BOT COMPLETO")
            import tableau as _tab
            _age = None
            try:
                # 🩹 16/09 (relecture) : l'age de la derniere collecte REUSSIE.
                # _cache_time est pose AVANT la collecte (anti-ruee) : si elle
                # plante, il avance quand meme et la fiche disait «…».
                _age = round(time.time() - time.mktime(
                    time.strptime(_cache.get("timestamp"), "%Y-%m-%d %H:%M:%S")), 0)
            except Exception:
                pass
            _tab.ecrire("serveur", port=5001, cache_age_s=_age,
                        cache_rempli=bool(_cache))
        except Exception:
            pass

if __name__ == "__main__":
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    log_message("info", "AcidGPT Signal Server v5.3 - Demarrage...")
    threading.Thread(target=keepalive, daemon=True).start()
    
    refresh_signals()
    
    log_message("info", " Serveur Prêt ✅ En écoute sur le port 5001 !")
    app.run(host="127.0.0.1", port=5001, debug=False)   # version publique : local seulement (/webhook passe des ordres réels sans mot de passe)
