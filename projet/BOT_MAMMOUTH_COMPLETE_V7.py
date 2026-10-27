# ============================================================================
# BOT_MAMMOUTH_COMPLETE_V7.py
# CONFIG + DATACLASSES + MT5 + AI CLIENTS + UTILITAIRES
# TRADING ENGINE + SMART POSITION MANAGER + TELEGRAM 
# ============================================================================

import os
import json
import pickle
import logging
import asyncio
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from anthropic import Anthropic

# 🚷 05/08 : ne JAMAIS ressusciter un MT5 fermé par le patron (la lib relance
# terminal64 si absent → piétinait les charts en pleine sauvegarde de sortie).
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
_mt5_init_brut_t64 = mt5.initialize
def _mt5_init_garde(*a, **k):
    if not _terminal_ouvert():
        return False
    return _mt5_init_brut_t64(*a, **k)
mt5.initialize = _mt5_init_garde

# ============================================================================
# ⚙️ MAPPING DES SYMBOLES (À mettre AVANT la fonction pour qu'elle le trouve)
# ============================================================================
# 🎯 25/09 — LES 4 MARCHÉS DU PATRON : «…».
# Raison MESURÉE, pas un goût : il veut X € par trade, et X € au lot
# minimum ne tiennent dans ~1 ATR H1 que sur l'or (0,6× ATR), le NAS100
# (1,0×), le pétrole (1,0×) et le BTC (1,9×, limite). Sur SP500 il faudrait
# 6,1× ATR et sur EURUSD+ 11,1× : viser X € là-bas, c'est demander au prix
# un mouvement quotidien qui n'existe pas — donc des objectifs jamais
# atteints et des stops toujours atteints. Les yeux continuent d'observer
# TOUS les marchés (information, pas risque) ; seuls les marchés TRADÉS
# sont réduits ici.
SYMBOLS = ["GOLD", "NAS", "OIL", "BTC"]

# 🟢 06/08 MIGRATION VANTAGE : leurs noms diffèrent (suffixe '+', CL-OIL, SP500).
# Plusieurs candidats par code court : le 1er réellement coté gagne. Sans ça,
# MAMMOUTH tournait en boucle «…» (il cherchait EURUSD#).
SYMBOL_MAP = {
    "EUR":      ["EURUSD+", "EURUSD", "EURUSD#"],
    "GOLD":     ["XAUUSD+", "XAUUSD", "GOLD#", "GOLD"],
    "OIL":      ["CL-OIL", "USOIL", "XTIUSD", "OILCash#"],
    "BTC":      ["BTCUSD", "BTCUSD+", "BTCUSD#"],
    "USD":      ["USDJPY+", "USDJPY", "USDJPY#"],
    "CRYPTO10": ["Crypto_10#", "BTCUSD"],          # pas d'indice crypto chez Vantage
    "SILVER":   ["XAGUSD", "XAGUSD+", "SILVER#"],
    "NAS":      ["NAS100", "NAS100Cash#", "USTEC", "US100"],   # 25/09 : absent = illisible
    "US500":    ["SP500", "US500", "US500Cash#"],
    "ETH":      ["ETHUSD", "ETHUSD+", "ETHUSD#"],
}
_sym_cache_mam = {}

def get_real_symbol(base_symbol: str) -> str:
    """Nom réellement coté chez le broker courant (cache : 1 résolution/symbole)."""
    if base_symbol in _sym_cache_mam:
        return _sym_cache_mam[base_symbol]
    cands = list(SYMBOL_MAP.get(base_symbol, []))
    cands += [base_symbol, base_symbol + "+", base_symbol + "#",
              base_symbol.rstrip("#+")]
    for c in cands:
        try:
            if c and mt5.symbol_info(c) is not None:
                mt5.symbol_select(c, True)
                _sym_cache_mam[base_symbol] = c
                return c
        except Exception:
            pass
    return base_symbol

# (imports telegram supprimés le 14/07 avec la classe TelegramBot — LE CERVEAU est
#  la seule voix Telegram depuis le 12/07)

# ============================================================================
# 🔧 LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('mammouth_v7.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# On cache le spam des requêtes HTTP (mais on garde les erreurs !)
logging.getLogger("httpx").setLevel(logging.WARNING)
# Au cas où ton bot utilise 'requests' et pas 'httpx', tu peux aussi ajouter celle-là :
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ============================================================================
# ⚙️ CONFIG CENTRALE
# ============================================================================

# 🔐 SECRETS (09/07) : tous dans secrets_acid.py — l'UNIQUE fichier hors git.
from secrets_acid import (TELEGRAM_TOKEN, ANTHROPIC_API_KEY, ANTHROPIC_API_KEY_BACKUP,
                          MAMMOUTH_API_KEY, ADMIN_ID, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER)
AI_MODEL          = "claude-haiku-4-5-20251001"   # 09/07 : Haiku en doublure (2.5s testé — sonnet jugé trop lent par le patron)

# Secours n°2 : mammouth.ai — même IA (claude-haiku) via une API compatible
# OpenAI. Mécanisme repris de l'ancien bot bridge (Tout de A a Z), testé OK
# le 06/07/2026. Ordre de bascule : Anthropic → clé backup → mammouth.
MAMMOUTH_ENDPOINT = "https://api.mammouth.ai/v1/chat/completions"
MAMMOUTH_MODEL    = "mistral-large-3"   # 09/07 choix patron : le sprinter (1.3s sur le format scalp, JSON strict, même verdict que 5.5/sonnet)

# Serveurs (ports exacts de tes fichiers)
ML_SERVER_URL     = "http://127.0.0.1:8001"   # server_ml.py
NEWS_SERVER_URL   = "http://127.0.0.1:5001"   # server.py

# MT5 : identifiants dans secrets_acid.py (importés plus haut)
# 17/07 : chemin EXPLICITE — la réinstall a renommé le dossier (XM Global MT5
# → XM MT5) et un initialize() nu peut s'accrocher au MAUVAIS terminal (celui
# d'AppData, symboles sans #, vu au log du 17/07 04:14). Le path= suffit pour ça.
# 20/07 : portable=True RETIRÉ. Il forçait le dossier de données sur
# C:\Program Files\XM MT5, qui ne contient AUCUN historique et n'est PAS
# inscriptible sans droits admin -> "file open error [3]" côté terminal et
# "Lecture MT5 vide" en boucle côté bot. Le terminal réel (PID sans /portable)
# écrit dans AppData\Roaming\MetaQuotes\Terminal\656C3515...\ qui, lui, a bien
# l'historique. Sans portable=True, bot et terminal partagent le même dossier.
MT5_TERMINAL_PATH = r"C:\Program Files\Vantage Markets MT5 Terminal\terminal64.exe"

# Trading
SYMBOLS      = ["GOLD", "NAS", "OIL", "BTC"]   # 25/09 : les 4 du patron
TIMEFRAME    = mt5.TIMEFRAME_M5
MAX_POSITIONS = 6
MAX_POSITIONS_RESCUE = 6   # quota étendu quand le bot rattrape les pertes du jour
RESCUE_TRIGGER_PCT   = 1.0 # % sous la balance de référence du jour pour passer en mode RESCUE
MIN_CONFIDENCE = 90.0   # 🎯 05/08 COMPTE RÉEL (patron : «…
                        # …») — 55→90. Ancien historique : 65→55 le 14/07 («…
                        # …»)

# Gestion risque
RISK_PCT_DEFAULT  = 2.0   # 🛡️ RÈGLE DES 2% : risque max par trade (plafond absolu)
ATR_PERIOD        = 14
ATR_TP_MULT       = 2.5
ATR_SL_MULT       = 1.5
BE_TRIGGER_PIPS   = 18    # pips profit avant breakeven (15→10 le 14/07 :
                          # patron «…»)
TRAIL_START_PIPS  = 30    # pips profit avant trailing
TRAIL_STEP_PIPS   = 16    # pas du trailing
# 🐘 21/07 patron : «…
# …». Un trade-monstre a besoin de RESPIRER : trail
# serré au début (protéger), trail large en tendance (ne pas se faire éjecter
# au premier pullback — leçon du rail GOLD de la nuit du 20-21/07).
TRAIL_WIDE_TRIGGER_PIPS = 100   # au-delà de +100 pips = trade-monstre
TRAIL_WIDE_STEP_PIPS    = 35    # …le trail suit par pas de 35 pips
# 🐘 FLOWRIDER (spec PDF p.8, codé le 21/07 après l'autopsie du rail GOLD de
# 843 pips raté) : sur une TENDANCE FORTE (ADX≥23) alignée avec le rail
# SuperTrend M15, une position gagnante CHEVAUCHE le mouvement — son SL suit
# le RAIL (jamais collé au prix), et elle est EXEMPTÉE des coupes rapides
# (mode X € + backstop). Sortie = cassage du rail. Le SL ne fait que se
# resserrer (jamais s'élargir) et le mode ne s'arme que sur un trade DÉJÀ
# en profit → on laisse courir les monstres, on ne sauve jamais un perdant.
FLOWRIDER_ENABLED  = True
FLOWRIDER_ADX_MIN  = 23.0   # seuil de tendance forte
FLOWRIDER_ATR_PER  = 10     # période ATR du SuperTrend
FLOWRIDER_MULT     = 3.0    # multiplicateur du SuperTrend
FLOWRIDER_ADX_PER  = 14     # période ADX
FLOWRIDER_MIN_PIPS = 5      # ne s'arme que si la position est déjà en profit
# 🪜 ÉCHELLE DE SORTIE (patron 21/07) : «…
# …». Vaut pour TOUS les
# trades (même FlowRider). ⚠️ pips FIXES : ok GOLD/indices ; forex 100 pips =
# gros move (rare), BTC 100 pips = 1$ (petit) — à passer en ×ATR si besoin.
LADDER_PARTIAL_PIPS = 100   # défaut (symbole hors table) : partial tous les 100 pips
LADDER_REENTRY_PIPS = 500   # défaut : clôture + reprise à 500 pips
LADDER_PARTIAL_FRAC = 0.5   # fraction fermée à chaque palier (capée par lot mini)
# 🪜 ÉCHELLE PAR SYMBOLE (patron 21/07 : «…
# …»). Calibré sur
# l'ATR M5 réel (relevé 21/07) : ~0.34×ATR par palier, comme le 100 de GOLD.
# (partial_pips, reentry_pips). Défaut = (100, 500). Facile à ajuster.
LADDER_TABLE = {
    "EURUSD#":    (2,    10),
    "USDJPY#":    (2,    10),
    "GOLD#":      (100,  500),
    "OILCash#":   (8,    40),
    "BTCUSD#":    (1000, 5000),   # ← chiffre patron
    "Crypto_10#": (400,  2000),
    "SILVER#":    (4,    20),
    "US500Cash#": (130,  650),
    # 🔗 04/09 — LES NOMS VANTAGE. MAMMOUTH résout ses symboles en XAUUSD+,
    # CL-OIL, BTCUSD… et cherchait GOLD#, OILCash# dans cette table : jamais
    # de correspondance, tous les marchés tombaient sur le défaut (100/500).
    "EURUSD+":    (2,    10),
    "USDJPY+":    (2,    10),
    "XAUUSD+":    (100,  500),
    "CL-OIL":     (8,    40),
    "BTCUSD":     (1000, 5000),
    "XAGUSD":     (4,    20),
    "SP500":      (130,  650),
    "NAS100":     (60,   300),    # absent de l'ancienne table : ~0,34×ATR H1 (41p), même règle
    "ETHUSD":     (50,   250),
    "ETHUSD#":    (100,  500),
}

def ladder_levels(symbol):
    return LADDER_TABLE.get(symbol, (LADDER_PARTIAL_PIPS, LADDER_REENTRY_PIPS))
PARTIAL_TP_PCT    = 0.5   # 50% fermé au TP1
CRASH_THRESHOLD   = 50    # points de mouvement = crash détecté
DAILY_DRAWDOWN_LIMIT_PCT = 10.0   # kill switch : % de perte journalière avant fermeture totale (arbitrage 2026-07-06, avant: 15.0)
OBJECTIF_JOUR_PCT        = 5.0    # 🏁 05/09 (patron «…») :
OBJECTIF_JOUR_EUR        = 100.0  # 💶 08/09 (patron : «…») — l'objectif
                                  # en EUROS prime sur le %. Sur un petit compte, +5 % ne valait
                                  # que X € : un seul trade gagnant et la journée était bouclée.
                                  # Mettre 0 pour revenir au pourcentage.
                                  # balance ≥ +5 % vs le début du jour → MAMMOUTH n'ouvre PLUS rien
                                  # jusqu'au lendemain (la gestion des positions ouvertes continue).
                                  # Compte entier (ŒIL + manuel inclus) : c'est le COMPTE qu'on protège.

# ⚡ MODE X € + coupe rapide (07/07) : corrige le R:R 0.51 (pertes 2× les gains).
# Petit gain certain encaissé vite, petite perte coupée vite — SAUF si le trade
# devient un runner (gros mouvement) : là on laisse courir BE + trailing.
QUICK_TP_EUR      = 1.0    # dès X € de profit → on encaisse…
QUICK_TP_MINPIPS  = 3      # …à condition d'au moins 3 pips (anti-fermeture dans le spread)
QUICK_SL_EUR      = 3.50   # coupe la perte à X € (1.2→3.0 le 14/07, patron :
                           # «…» — on laisse respirer le scalp)
QUICK_SL_MINPIPS  = 3      # …idem, plancher anti-spread
QUICK_SL_PIPS     = 70     # garde-fou dur en pips — MÉTAUX (15→50 le 14/07 :
                           # l'or a besoin de 50 pips pour respirer)
QUICK_SL_PIPS_FX  = 45     # 17/07 spec p.7 : le forex pur coupe plus court
QUICK_SL_PIPS_AUT = 60     # 17/07 spec p.7 : indices / crypto / énergie
RUNNER_PIPS       = 20     # au-delà de +20 pips = runner : on ne touche plus, BE/trailing gèrent
SCALP_TP_PIPS     = 6      # 🎯 CIBLE DE LOT : dimensionne le lot pour que X € tombe vers 6 pips

# ═══════════════════════════════════════════════════════════════════════════
# 🔁 ENCAISSE ET RECOMMENCE (patron 21/08) : «…
# …
# …
# …».
#
# L'idée : un scalp qui gagne encore au bout de 10 min a fait son travail. On
# encaisse, on note le point d'entrée, et on RE-RENTRE au même prix quand le
# marché y revient — tant que les conditions qui ont justifié le trade tiennent.
# Le même mouvement est mangé plusieurs fois par tranches, au lieu d'être gardé
# une fois et rendu.
# ═══════════════════════════════════════════════════════════════════════════
CYCLE_SCALP_ON        = True
CYCLE_APRES_MIN       = 10     # âge (minutes) à partir duquel on encaisse si positif
CYCLE_GAIN_MIN_EUR    = 0.50   # …à condition d'être vraiment en profit (frais couverts)
CYCLE_GAIN_MIN_PIPS   = 3      # …et hors du spread
CYCLE_TOLERANCE_PIPS  = 4      # «…» = à ce nombre de pips près
CYCLE_VALIDITE_MIN    = 240    # on guette le retour au niveau pendant 4 h max
CYCLE_MAX_REPETITIONS = 4      # nombre de re-entrées sur un même niveau
CYCLE_COOLDOWN_S      = 60     # version publique : réglage de base (60 s entre deux re-entrées) — 0 = sans pause


# ═══════════════════════════════════════════════════════════════════════════
# 🧪 MODE SIMULATION PARTAGÉ (27/08)
# LE CERVEAU avait son mode simulation, pas MAMMOUTH : le patron pouvait donc
# croire tester à blanc pendant que MAMMOUTH engageait le compte pour de vrai.
# Deux bots, un seul compte : ils doivent obéir au MÊME interrupteur.
# Le fichier est piloté depuis Telegram (/reel et /simu) — relu à chaque
# ordre, donc la bascule prend effet immédiatement, sans redémarrage.
# Défaut prudent : fichier absent ou illisible = SIMULATION.
# ═══════════════════════════════════════════════════════════════════════════
MODE_FICHIER = Path(__file__).resolve().parent / "mode_trading.txt"
SIM_FICHIER_MAM = Path(__file__).resolve().parent / "simulation_trades.jsonl"
_sim_ticket_mam = [800000]


def en_simulation() -> bool:
    try:
        return MODE_FICHIER.read_text(encoding="utf-8").strip().upper() != "REEL"
    except Exception:
        return True

# Les points d'entrée encaissés, en attente d'un retour du prix. Volontairement
# au niveau MODULE : le manager de positions les REMPLIT, le moteur de trading
# les CONSOMME — deux classes différentes, une seule liste.
_CYCLE_NIVEAUX = []
BAD_HOURS         = {6, 7, 8, 12, 13, 20}   # heure LOCALE (Paris) — 6h ajouté le 05/09 :
                                            # 2 ans de backtest donnent 6-7h et 12-13h Paris
                                            # comme creux (pré-Londres, midi) = mêmes fenêtres   # heures noires (WR 11-27%)
BAD_HOUR_MIN_CONF = 95.0                  # 🎯 patron 04/08 : heures noires OUVERTES mais entrée seulement si conf ≥ 90 («…»)

_FX_CODES = ("EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")

def quick_sl_pips(symbol: str) -> int:
    """🩸 Plancher SL scalp PAR CLASSE (spec p.7, relevé du 14/07) :
    métaux 50 / forex 30 / autres 40. Avant le 17/07 tout le monde
    était à 50 — le forex trainait sa perte 20 pips de trop."""
    s = symbol.upper().replace("#", "")
    if "GOLD" in s or "SILVER" in s or s.startswith(("XAU", "XAG")):
        return QUICK_SL_PIPS
    if len(s) == 6 and s[:3] in _FX_CODES and s[3:] in _FX_CODES:
        return QUICK_SL_PIPS_FX
    return QUICK_SL_PIPS_AUT

# 🩸 RÈGLES D'ACIER (08/07) — tirées de l'analyse des 19 661 VRAIS trades
# VTMarkets (X € en 3 ans) : le churn <5 min = 94% des pertes, les
# lots ≥0.11 = WR 34%, les séries de pertes = tilt/martingale émotionnelle,
# et trader CONTRE le COT fort = le désastre sell-or (X €).
SYMBOL_COOLDOWN_MIN = 15    # version publique : réglage de base (15 min avant de retoucher un symbole) — 0 = sans pause

# ══ 24/09 — LE DÉCLENCHEUR MÉCANIQUE «…» ═══════════════════════════
# LE PATRON : «…
# …».
# CE QUI L'EMPÊCHAIT DE TIRER : analyze_symbol n'examine un trade que si le ML
# donne une confiance >= 90, alors que server_ml_v2 plafonne à 70 (CONF_MAX).
# Seuil inatteignable → zéro trade depuis l'ouverture du compte.
# CE QU'ON MET À LA PLACE (bancs/banc_mammouth.py, 24/09) : la cassure du range
# d'ouverture, la règle de l'œil 3, comparée à cinq autres sur 9 marchés et
# ~12 mois de M5, protocole complet :
#     1 jambe, objectif 4 R : X € au lot mini · 33,5 % de réussite
#     moitié ancienne X € · moitié récente X € · 7 marchés sur 9
#     miroir X € · décalage identique · 13 348 entrées au hasard X €
#   (les cinq autres règles testées échouent : choc X €, momentum X €
#    mais moitié récente négative, retour moyenne miroir positif, etc.)
# Zéro token : aucune IA n'est consultée pour ces entrées.
# 🚦 24/09 (relecture) — EN OBSERVATION, ET VOICI POURQUOI.
# Le X € ci-dessus est mesuré SANS plafond de risque. Or budget_risque
# n'accorde que 3 % du solde par trade à une source non validée :X € avec
#X €. Ce plafond refuse 1 065 signaux sur 2 554 — précisément les grandes
# cassures de l'or et de l'argent qui faisaient le gain. Ce qui reste :
#     1 489 trades · X € sur 12 mois · MAIS le miroir devient POSITIF (X €)
# Un miroir qui ne perd plus veut dire qu'il n'y a plus d'avantage de sens : du
# bruit. On ne fait donc PAS trader ça. MAMMOUTH note ses signaux dans son
# journal ; quand le compte sera assez gros pour payer les cassures larges (ou
# si les signaux réels donnent raison à la règle), on passera RANGE_ACTIF à True.
RANGE_ACTIF = False           # False = il note le signal, il n'ouvre rien
RANGE_BARRES = 8              # les 8 premières M30 de la séance forment le range
RANGE_MARGE_ATR = 0.25        # le stop se pose un quart d'ATR au-delà du range
RANGE_TP_R = 4.0              # objectif = 4 x la distance de stop (mesuré)
RANGE_LARGEUR_MAX_ATR = 6.0   # un range trop large = stop inatteignable
_RANGE_FAIT = {}              # symbole -> jour déjà joué (une cassure par séance)


def signal_range_m30(conn, symbol):
    """Renvoie {sens, sl_pips, tp_pips, raison} sur une cassure FRAÎCHE du range
    d'ouverture, ou None. La bougie qui casse doit être la dernière clôturée :
    après un redémarrage, on ne rentre pas sur une cassure vieille de 3 heures."""
    try:
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, 0, 400)
        if r is None or len(r) < 60:
            return None
        r = r[:-1]                                   # bougies clôturées seulement
        T = r["time"].astype(np.int64)
        H = r["high"].astype(float)
        L = r["low"].astype(float)
        C = r["close"].astype(float)
        jours = T // 86400
        j = int(jours[-1])
        if _RANGE_FAIT.get(symbol) == j:
            return None
        deb = int(np.searchsorted(jours, j, side="left"))
        if len(C) - deb <= RANGE_BARRES:
            return None                              # le range n'est pas encore formé
        haut = float(H[deb:deb + RANGE_BARRES].max())
        bas = float(L[deb:deb + RANGE_BARRES].min())
        if haut <= bas:
            return None
        # ATR de Wilder (1/14), la même formule que les yeux
        tr = np.maximum(H[1:] - L[1:], np.maximum(np.abs(H[1:] - C[:-1]),
                                                  np.abs(L[1:] - C[:-1])))
        atr = float(H[0] - L[0])
        for x in tr:
            atr = x / 14.0 + atr * 13.0 / 14.0
        if atr <= 0 or (haut - bas) / atr > RANGE_LARGEUR_MAX_ATR:
            return None
        dernier, avant = float(C[-1]), float(C[-2])
        if dernier > haut and bas <= avant <= haut:
            sens, struct = "BUY", bas
        elif dernier < bas and bas <= avant <= haut:
            sens, struct = "SELL", haut
        else:
            return None
        pip = conn.pip(symbol)
        if pip <= 0:
            return None
        distance = abs(dernier - struct) + RANGE_MARGE_ATR * atr
        _RANGE_FAIT[symbol] = j
        return {"sens": sens,
                "sl_pips": max(1, int(round(distance / pip))),
                "tp_pips": max(2, int(round(RANGE_TP_R * distance / pip))),
                "raison": (f"cassure du range d'ouverture M30 "
                           f"({bas:.5f}-{haut:.5f}, {(haut - bas) / atr:.1f} ATR de large) "
                           f"— stop de l'autre côté du range, objectif 4 R")}
    except Exception:
        return None

MIN_HOLD_MIN        = 5     # un GAIN (mode X €) ne s'encaisse qu'après 5 min de vie
MAX_LOT_HARD        = 0.02  # plafond ABSOLU de lot (0.10→0.02 le 13/07 soir, patron :
                            # petits lots partout, 16 positions max compte entier)
MAX_POSITIONS_COMPTE = 30
MAMMOUTH_PAUSE_S     = 600   # 🚦 pause apres 3x 429 d'affilee (anti-hemorragie nocturne)
_mammouth_429        = 0
_mammouth_mute_until = 0.0   # 👑 plafond GLOBAL compte entier (ŒIL+mammouth+EA confondus)
TILT_LOSSES         = 3     # pertes consécutives…
TILT_PAUSE_MIN      = 60    # …déclenchent une pause anti-tilt (minutes)
COT_VETO_PCT        = 20.0  # 23/07 (patron) : COT compte 2× moins — veto seulement si biais ≥20% de l'OI (avant 10)
_anthropic_mort_jusqua = 0.0  # 💸 garde-crédits : secours Anthropic coupé jusqu'à ce ts si solde vide

_symbol_cooldown  = {}      # symbole -> ts de la dernière OUVERTURE (règle 1)
_tilt_pause_until = 0.0     # fin de la pause anti-tilt (règle 3)
_pos_seen         = {}      # ticket -> 1re observation, âge fiable (règle 2)

# ErrorMemory
ERROR_MEMORY_FILE = "error_memory.pkl"

# ============================================================================
# 📊 ENUMS & DATACLASSES
# ============================================================================

class Direction(Enum):
    BUY     = "BUY"
    SELL    = "SELL"
    NEUTRAL = "NEUTRAL"

class SignalEA(Enum):
    SAFE      = "safe"
    HIGH_VOL  = "high_vol"
    CRUCIAL   = "crucial"

@dataclass
class Position:
    ticket:         int
    symbol:         str
    direction:      Direction
    entry_price:    float
    volume:         float
    sl:             float
    tp:             float
    profit:         float
    entry_time:     datetime
    be_activated:   bool  = False
    trail_activated:bool  = False
    partial_done:   bool  = False
    flowrider:      bool  = False   # 🐘 chevauche une tendance forte (SL sur rail)
    ladder_rungs:   int   = 0       # 🪜 nb de paliers de 100 pips déjà encaissés
    tp1:            float = 0.0
    initial_volume: float = 0.0
    comment:        str   = ""      # 24/09 : d'où vient la position (RANGE…)
    magic:          int   = 0       # 🩹 24/09 (patron) : _cycle_encaisse lit pos.magic
                                    # pour laisser courir les swings — le champ
                                    # n'existait pas, donc manage() partait en
                                    # AttributeError à CHAQUE tour et la gestion
                                    # (partiels, BE, trailing) ne tournait jamais.

    def __post_init__(self):
        if self.initial_volume == 0.0:
            self.initial_volume = self.volume

@dataclass
class MLSignal:
    symbol:     str
    direction:  str       # BUY / SELL / HOLD / NEUTRAL
    confidence: float     # 0-100
    score:      float     # 0-100
    signal_ea:  str       # safe / high_vol / crucial
    tp:         float
    sl:         float
    blacklist:  bool
    highvol:    Optional[str]
    timestamp:  str

@dataclass
class NewsSignal:
    symbol:     str
    signal:     str       # BUY / SELL / NEUTRAL
    signal_ea:  str
    score:      float
    buy_score:  float
    sell_score: float
    confidence: float
    blacklist:  bool
    highvol:    Optional[str]
    warning:    str
    timestamp:  str

@dataclass
class BotState:
    auto_trade:          bool  = True   # ON au démarrage (Telegram déporté dans LE CERVEAU : /autotrade pour couper)
    paused:              bool  = False
    last_trade_time:     Optional[datetime] = None
    consecutive_losses:  int   = 0
    daily_profit:        float = 0.0
    daily_trades:        int   = 0
    crash_detected:      bool  = False
    last_candle_time:    Dict[str, datetime] = field(default_factory=dict)
    # --- Kill switch / drawdown journalier ---
    current_trading_day:  Optional[str] = None
    daily_start_balance:  float = 0.0
    kill_switch_triggered: bool = False
    objectif_jour_atteint: bool = False   # 🏁 05/09 : journée bouclée en gain
    crash_pause_until: float = 0.0        # 💥 05/09 : fin de la pause crash (avant : gel définitif)
    depots_ref: float = 0.0               # 💶 05/09 : mouvements de caisse déjà comptés à la capture

# ============================================================================
# 💾 ERROR MEMORY (Pickle)
# ============================================================================

class ErrorMemory:
    """Stocke les erreurs persistantes entre redémarrages"""

    def __init__(self, filepath: str = ERROR_MEMORY_FILE):
        self.filepath = filepath
        self.errors: List[Dict] = self._load()

    def _load(self) -> List[Dict]:
        try:
            if Path(self.filepath).exists():
                with open(self.filepath, 'rb') as f:
                    data = pickle.load(f)
                    logger.info(f"📂 ErrorMemory: {len(data)} erreurs chargées")
                    return data
        except Exception as e:
            logger.warning(f"⚠️ ErrorMemory load error: {e}")
        return []

    def _save(self):
        try:
            with open(self.filepath, 'wb') as f:
                pickle.dump(self.errors, f)
        except Exception as e:
            logger.error(f"❌ ErrorMemory save error: {e}")

    def add(self, source: str, message: str, data: Dict = None):
        entry = {
            "time":    datetime.now().isoformat(),
            "source":  source,
            "message": message,
            "data":    data or {}
        }
        self.errors.append(entry)
        if len(self.errors) > 500:
            self.errors = self.errors[-500:]
        self._save()
        logger.error(f"🧠 ErrorMemory [{source}]: {message}")

    def get_recent(self, n: int = 10) -> List[Dict]:
        return self.errors[-n:]

    def clear(self):
        self.errors = []
        self._save()

# ============================================================================
# 🔌 MT5 CONNECTOR
# ============================================================================

class MT5Connector:

    PIP_MAP = {
        "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01,
        "XAUUSD": 0.1,    "GOLD": 0.1,      "GOLD#": 0.1,
        "BTCUSD": 1.0,    "BTCUSD#": 1.0,   "BTC": 1.0,
        "OILCASH": 0.01,  "OILCash#": 0.01, "OIL": 0.01,
        "CRYPTO10": 1.0,  "Crypto_10#": 1.0,
        "SILVER": 0.01,   "SILVER#": 0.01,  "XAGUSD": 0.01,
        "US500": 1.0,     "US500Cash#": 1.0, "US500CASH": 1.0,
        "ETH": 1.0,       "ETHUSD#": 1.0,   "ETHUSD": 1.0,
        # 🩸 05/09 noms VANTAGE (ils tombaient tous sur DEFAULT = 0,0001 : SL/TP à 0,002 $ sur l'or…)
        "XAUUSD+": 0.1, "EURUSD+": 0.0001, "GBPUSD+": 0.0001, "USDJPY+": 0.01,
        "CL-OIL": 0.01, "SP500": 1.0, "NAS100": 1.0, "BTCUSD": 1.0, "NAS": 1.0,
        "DEFAULT": 0.0001
    }

    def __init__(self, login: int, password: str, server: str,
                 error_memory: ErrorMemory):
        self.login        = login
        self.password     = password
        self.server       = server
        self.em           = error_memory
        self.connected    = False

    _PIP_FAMILLES = (("XAU", 0.1), ("GOLD", 0.1), ("BTC", 1.0), ("ETH", 1.0), ("NAS", 1.0), ("US100", 1.0),
                     ("SP500", 1.0), ("US500", 1.0), ("XAG", 0.01), ("SILVER", 0.01), ("OIL", 0.01))

    def pip(self, symbol: str) -> float:
        """🩸 05/09 — plus de repli muet sur 0,0001 : nom exact, puis nom sans suffixe (+/#),
        puis famille, puis les décimales du broker. Un pip faux = SL/TP faux, gain_pips ×1000."""
        s = (symbol or "").upper()
        if symbol in self.PIP_MAP:
            return self.PIP_MAP[symbol]
        base = s.replace("+", "").replace("#", "")
        if base in self.PIP_MAP:
            return self.PIP_MAP[base]
        for cle, val in self._PIP_FAMILLES:
            if cle in s:
                return val
        try:
            info = mt5.symbol_info(symbol)
            if info and info.point > 0:
                return info.point * 10 if info.digits in (3, 5) else info.point
        except Exception:
            pass
        logger.warning(f"pip inconnu pour {symbol} — repli {self.PIP_MAP['DEFAULT']}")
        return self.PIP_MAP["DEFAULT"]

    def connect(self) -> bool:
        try:
            if not mt5.initialize(path=MT5_TERMINAL_PATH):
                self.em.add("MT5", "initialize() failed", {"error": str(mt5.last_error())})
                return False
            # 🔒 14/09 — ON NE FORCE PLUS DE COMPTE.
            # Avant : MAMMOUTH relogeait le terminal sur les identifiants de
            # secrets_acid.py. Le jour ou le patron bascule MT5 sur une DEMO,
            # la moindre coupure le ramenait en REEL sans qu'il le sache.
            # Desormais : si aucun identifiant n'est fourni, on se contente du
            # terminal DEJA connecte — c'est le patron qui choisit son compte.
            if self.login:
                if not mt5.login(self.login, self.password, self.server):
                    self.em.add("MT5", "login() failed", {"error": str(mt5.last_error())})
                    return False
            elif mt5.account_info() is None:
                self.em.add("MT5", "aucun compte connecte dans le terminal",
                            {"aide": "connecte-toi dans MT5, je suis le terminal"})
                return False
            self.connected = True
            logger.info("✅ MT5 connecté")

            # ==== AJOUT MAGIQUE ICI ====
            global SYMBOLS
            vrais_symboles = []
            for s in SYMBOLS:
                base = s.replace("#", "")
                vrai = get_real_symbol(base)
                vrais_symboles.append(vrai)
            SYMBOLS = vrais_symboles
            logger.info(f"🔄 Symboles : {SYMBOLS}")
            # ===========================

            return True
        except Exception as e:
            self.em.add("MT5", f"connect exception: {e}")
            return False

    def get_rates(self, symbol: str, timeframe, count: int) -> pd.DataFrame:
        try:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None or len(rates) == 0:
                # Session MT5 morte (terminal redémarré ?) → reconnexion auto,
                # au plus une tentative par minute pour ne pas spammer.
                now = time.time()
                if now - getattr(self, "_last_reconnect", 0) > 60:
                    self._last_reconnect = now
                    logger.warning(f"⚠️ Lecture MT5 vide pour {symbol} — tentative de reconnexion")
                    if self.connect():
                        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None or len(rates) == 0:
                return pd.DataFrame()
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
        except Exception as e:
            self.em.add("MT5", f"get_rates error: {e}", {"symbol": symbol})
            return pd.DataFrame()

    def get_balance(self) -> float:
        try:
            info = mt5.account_info()
            return info.balance if info else 0.0
        except:
            return 0.0

    def get_equity(self) -> float:
        try:
            info = mt5.account_info()
            return info.equity if info else 0.0
        except:
            return 0.0

    MAGIC       = 777777  # scalp (numero historique) — tag des ordres Mammouth,
                          # pour ne jamais toucher aux positions d'un autre
                          # systeme (ex: l'EA MQL5, magic 20260613).
    MAGIC_SWING = 777999  # 17/07 idee patron : les trades de CONVICTION
                          # (confiance >=95, lot dynamique, hors dump tactique)
                          # ont leur propre number — scalp et swing se lisent
                          # d'un coup d'oeil dans MT5 (777777 scalp / 777999
                          # swing / 999111 OEIL / 2026xxxx EA).
    OWN_MAGICS  = (777777, 777999)

    def get_positions(self) -> List[Position]:
        """Toutes les positions du compte (tous systemes confondus). A
        n'utiliser QUE pour des decisions qui doivent tenir compte de
        l'exposition globale du compte (ex: plafond MAX_POSITIONS) — jamais
        pour fermer/modifier, sous peine de toucher les positions d'un
        autre bot (voir get_own_positions)."""
        try:
            positions = mt5.positions_get()
            if not positions:
                return []
            result = []
            for pos in positions:
                p = Position(
                    ticket      = pos.ticket,
                    symbol      = pos.symbol,
                    direction   = Direction.BUY if pos.type == 0 else Direction.SELL,
                    entry_price = pos.price_open,
                    volume      = pos.volume,
                    sl          = pos.sl,
                    tp          = pos.tp,
                    profit      = pos.profit,
                    entry_time  = datetime.fromtimestamp(pos.time)
                )
                result.append(p)
            return result
        except Exception as e:
            self.em.add("MT5", f"get_positions error: {e}")
            return []

    def get_own_positions(self) -> List[Position]:
        """Positions ouvertes par Mammouth (magics 777777 scalp et
        777999 swing conviction) uniquement.
        C'est la liste a utiliser pour tout ce qui modifie/ferme des
        positions (SmartPositionManager, kill switch, stop max perte) :
        avant ce filtre, ces methodes agissaient sur TOUTES les positions
        du compte sans distinction, y compris celles ouvertes par l'EA
        MQL5 (magic 20260613) qui tourne en parallele sur le meme compte —
        le kill switch de drawdown journalier pouvait ainsi fermer des
        positions gerees par l'EA (hedge, swing en cours...) sans que
        celui-ci en soit informe."""
        try:
            positions = mt5.positions_get()
            if not positions:
                return []
            return [self._to_position(pos) for pos in positions
                    if pos.magic in self.OWN_MAGICS]
        except Exception as e:
            self.em.add("MT5", f"get_own_positions error: {e}")
            return []

    @staticmethod
    def _to_position(pos) -> Position:
        return Position(
            ticket      = pos.ticket,
            symbol      = pos.symbol,
            direction   = Direction.BUY if pos.type == 0 else Direction.SELL,
            entry_price = pos.price_open,
            volume      = pos.volume,
            sl          = pos.sl,
            tp          = pos.tp,
            profit      = pos.profit,
            entry_time  = datetime.fromtimestamp(pos.time),
            comment     = getattr(pos, "comment", "") or "",
            magic       = int(getattr(pos, "magic", 0) or 0)
        )

    def calculate_lot(self, symbol: str, risk_pct: float, sl_pips: float) -> float:
        try:
            balance       = self.get_balance()
            risk_amt      = balance * (risk_pct / 100.0)
            pip_value     = self.pip(symbol)

            info          = mt5.symbol_info(symbol)
            contract_size = info.trade_contract_size if info else 100000

            value_per_pip = pip_value * contract_size
            if value_per_pip <= 0:
                return 0.01

            lot = risk_amt / (sl_pips * value_per_pip)
            lot = max(0.01, round(lot, 2))
            return lot
        except Exception as e:
            self.em.add("MT5", f"calculate_lot error: {e}")
            return 0.01

    def calculate_scalp_lot(self, symbol: str) -> float:
        """🎯 Lot petit et DYNAMIQUE pour le mode X € : dimensionné pour que
        +QUICK_TP_EUR (X €) tombe vers SCALP_TP_PIPS (6) pips — donc des dizaines
        de petits gains certains par jour. PLAFONNÉ à la règle des 2% (la perte
        au backstop QUICK_SL_PIPS ne dépasse jamais 2% du capital)."""
        try:
            balance       = self.get_balance()
            info          = mt5.symbol_info(symbol)
            contract_size = info.trade_contract_size if info else 100000
            value_per_pip = self.pip(symbol) * contract_size   # € par pip pour 1.0 lot
            if value_per_pip <= 0 or balance <= 0:
                return 0.01
            # lot pour que X € soit atteint à ~SCALP_TP_PIPS pips
            lot_cible  = QUICK_TP_EUR / (SCALP_TP_PIPS * value_per_pip)
            # plafond règle des 2% : perte au backstop <= 2% du capital
            lot_max2pc = (balance * RISK_PCT_DEFAULT / 100.0) / (quick_sl_pips(symbol) * value_per_pip)
            # 🪜 05/08 (patron, COMPTE RÉEL) : paliers de lots — <X € → 0.01 fixe,
            # 200-X € → 0.02, >X € → dynamique borné par MAX_LOT_HARD.
            _palier = 0.01 if balance < 200 else (0.02 if balance < 500 else MAX_LOT_HARD)
            lot = min(lot_cible, lot_max2pc, MAX_LOT_HARD, _palier)   # 🩸 règle d'acier
            step = info.volume_step if info and info.volume_step > 0 else 0.01
            lot = int(lot / step + 1e-9) * step   # arrondi VERS LE BAS : jamais au-dessus des caps
            vol_min = (info.volume_min if info else 0) or 0.01
            if lot < vol_min - 1e-9:
                # 🏛️ EXCEPTION INDICES (14/07, patron : «…
                # …») : minimum broker accepté jusqu'à 0.10
                # (l'ancien cap d'acier des 19 661 trades) — même si ça dépasse
                # la règle des 2% ; le backstop SL en pips limite la casse.
                # Au-delà de 0.10 : refus, la revue du 08/07 reste vraie.
                if vol_min <= 0.10 + 1e-9:
                    logger.info(f"🏛️ {symbol} : lot minimum broker {vol_min} accepté (exception indices)")
                    lot = vol_min
                else:
                    logger.info(f"🩸 {symbol} : volume_min broker ({vol_min}) > 0.10 — trade refusé")
                    return 0.0
            lot = min(lot, info.volume_max if info else 100.0)
            return round(lot, 2)
        except Exception as e:
            self.em.add("MT5", f"calculate_scalp_lot error: {e}")
            return 0.01

    def calculate_atr(self, symbol: str, period: int = ATR_PERIOD) -> float:
        try:
            df = self.get_rates(symbol, TIMEFRAME, period + 5)
            if df.empty or len(df) < period:
                return 0.0   # 🩸 05/09 : indisponible = 0, jamais une fausse valeur
            high  = df['high'].values
            low   = df['low'].values
            close = df['close'].values
            tr = np.maximum(
                high[1:] - low[1:],
                np.maximum(
                    np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:]  - close[:-1])
                )
            )
            return float(np.mean(tr[-period:]))
        except Exception as e:
            self.em.add("MT5", f"calculate_atr error: {e}")
            return 0.0

    def open_position(self, symbol: str, direction: Direction, volume: float,
                      sl: float, tp: float, magic: int = None,
                      comment: str = None) -> Optional[int]:
        try:
            magic = magic or self.MAGIC

            # 💰 27/08 — ENVELOPPE COMMUNE. MAMMOUTH ouvrait sans jamais
            # demander au budget partagé : il pouvait donc engager le compte
            # alors que le plancher de perte du jour était déjà atteint par
            # LE CERVEAU. Trois bots, un seul compte, un seul portefeuille.
            try:
                import budget_risque as _b
                # 🩹 04/09 — RISQUE RÉEL. On passait 0.0 : le plafond par trade
                # ne pouvait jamais mordre (le même bug que dans LE CERVEAU, corrigé
                # le 02/09 après un XAGUSD à 92% du compte). Le broker calcule
                # la perte exacte au SL pour ce lot — c'est LUI qui fait foi.
                _perte = 0.0
                try:
                    _tk = mt5.symbol_info_tick(symbol)
                    _px = (_tk.ask if direction == Direction.BUY else _tk.bid) if _tk else 0.0
                    if _px and sl:
                        _perte = mt5.order_calc_profit(
                            mt5.ORDER_TYPE_BUY if direction == Direction.BUY else mt5.ORDER_TYPE_SELL,
                            symbol, volume, _px, sl) or 0.0
                except Exception:
                    _perte = 0.0
                _ok, _pq = _b.peut_ouvrir(mt5, "mammouth", abs(min(_perte, 0.0)),
                                          source="scalp_ia")   # 08/09 : source non validée → 3 %
                if not _ok:
                    logger.warning(f"💰 {symbol} : ouverture refusée — {_pq}")
                    return None
            except ImportError:
                pass

            # 🧪 27/08 : même interrupteur que LE CERVEAU. On n'envoie rien, on note.
            if en_simulation():
                _sim_ticket_mam[0] += 1
                tk = _sim_ticket_mam[0]
                try:
                    t = mt5.symbol_info_tick(symbol)
                    px = (t.ask if direction == Direction.BUY else t.bid) if t else 0.0
                    with open(SIM_FICHIER_MAM, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "ts": time.time(),
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "ticket": tk, "action": "MARCHE", "symbol": symbol,
                            "type": 0 if direction == Direction.BUY else 1,
                            "volume": volume, "prix": px, "sl": sl, "tp": tp,
                            "magic": magic, "comment": "MAMMOUTH",
                        }, ensure_ascii=False) + "\n")
                    logger.info(f"🧪 SIMULÉ #{tk} {symbol} "
                                f"{'BUY' if direction == Direction.BUY else 'SELL'} "
                                f"{volume} @ {px} SL={sl} TP={tp} — rien n'est parti au broker")
                except Exception as e:
                    logger.error(f"simulation MAMMOUTH : {e}")
                return tk

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                self.em.add("MT5", f"No tick for {symbol}")
                return None

            price      = tick.ask if direction == Direction.BUY else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if direction == Direction.BUY else mt5.ORDER_TYPE_SELL

            # 🩹 24/07 : «…» — le broker exige une distance mini
            # (trade_stops_level) entre prix et SL/TP, et le spread peut la
            # dépasser. On CLAMPE : jamais plus près que stops_level+spread+2 pts.
            info = mt5.symbol_info(symbol)
            if info:
                pt = info.point
                dist = (max(info.trade_stops_level,
                            int(round((tick.ask - tick.bid) / pt)) + 2) + 2) * pt
                if direction == Direction.BUY:
                    if sl: sl = min(sl, price - dist)
                    if tp: tp = max(tp, price + dist)
                else:
                    if sl: sl = max(sl, price + dist)
                    if tp: tp = min(tp, price - dist)
                sl = round(sl, info.digits) if sl else sl
                tp = round(tp, info.digits) if tp else tp

            request = {
                "action":    mt5.TRADE_ACTION_DEAL,
                "symbol":    symbol,
                "volume":    volume,
                "type":      order_type,
                "price":     price,
                "sl":        sl,
                "tp":        tp,
                "deviation": 20,
                "magic":     magic,
                "comment":   comment or ("MammouthV7_swing" if magic == self.MAGIC_SWING
                                         else "MammouthV7"),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Ordre ouvert {symbol} {direction.value} "
                            f"vol={volume} ticket={result.order}")
                return result.order
            else:
                self.em.add("MT5", f"open_position failed: {result.comment}",
                            {"symbol": symbol, "retcode": result.retcode})
                return None
        except Exception as e:
            self.em.add("MT5", f"open_position exception: {e}")
            return None

    def close_position(self, ticket: int) -> bool:
        try:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            pos      = pos[0]
            tick     = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return False
            price    = tick.bid if pos.type == 0 else tick.ask
            opp_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY

            request = {
                "action":    mt5.TRADE_ACTION_DEAL,
                "symbol":    pos.symbol,
                "volume":    pos.volume,
                "type":      opp_type,
                "position":  ticket,
                "price":     price,
                "deviation": 20,
                "magic":     pos.magic,
                "comment":   "MammouthV7_close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Position {ticket} fermée")
                return True
            else:
                self.em.add("MT5", f"close_position failed: {result.comment}",
                            {"ticket": ticket})
                return False
        except Exception as e:
            self.em.add("MT5", f"close_position exception: {e}")
            return False

    def close_partial(self, ticket: int, volume: float) -> bool:
        try:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            pos      = pos[0]
            tick     = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return False
            price    = tick.bid if pos.type == 0 else tick.ask
            opp_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
            # 17/07 : caler le volume sur les contraintes DU SYMBOLE — ETHUSD#
            # refusait le demi-lot (Invalid volume). Arrondi au pas du broker,
            # et ni la part fermée ni le reste ne peuvent passer sous le lot mini.
            info = mt5.symbol_info(pos.symbol)
            if not info:
                return False
            step    = info.volume_step or 0.01
            vol_min = info.volume_min or 0.01
            vol     = min(volume, pos.volume)
            vol     = round(int(vol / step + 1e-9) * step, 8)
            reste   = round(pos.volume - vol, 8)
            if vol < vol_min or (0 < reste < vol_min):
                logger.info(f"⏭️ Partial sauté {pos.symbol} #{ticket} : "
                            f"vol={vol} / mini broker={vol_min} / pas={step} — lot trop petit")
                return False

            request = {
                "action":    mt5.TRADE_ACTION_DEAL,
                "symbol":    pos.symbol,
                "volume":    vol,
                "type":      opp_type,
                "position":  ticket,
                "price":     price,
                "deviation": 20,
                "magic":     pos.magic,
                "comment":   "MammouthV7_partialTP",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Partial TP {ticket} vol={vol}")
                return True
            else:
                self.em.add("MT5", f"close_partial failed: {result.comment}",
                            {"ticket": ticket})
                return False
        except Exception as e:
            self.em.add("MT5", f"close_partial exception: {e}")
            return False

    def close_all_positions(self) -> int:
        """Ferme toutes les positions ouvertes PAR MAMMOUTH (magics 777777
        scalp / 777999 swing). Retourne le nombre de positions fermées.

        Avant ce correctif, cette methode fermait TOUTES les positions du
        compte sans distinction — utilisee par le kill switch de drawdown
        journalier (check_daily_drawdown), qui tourne meme quand auto_trade
        est desactive, ca pouvait fermer en urgence des positions ouvertes
        et gerees par l'EA MQL5 (magic 20260613) tournant en parallele sur
        le meme compte, sans que l'EA en soit informe (hedge coupe en
        plein milieu, swing ferme prematurement, etc)."""
        closed = 0
        try:
            for pos in self.get_own_positions():
                if self.close_position(pos.ticket):
                    closed += 1
        except Exception as e:
            self.em.add("MT5", f"close_all_positions exception: {e}")
        return closed

    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        try:
            request = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl":       sl,
                "tp":       tp,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Modified {ticket} SL={sl:.5f} TP={tp:.5f}")
                return True
            else:
                self.em.add("MT5", f"modify_position failed: {result.comment}",
                            {"ticket": ticket})
                return False
        except Exception as e:
            self.em.add("MT5", f"modify_position exception: {e}")
            return False

# ============================================================================
# 📡 ML SERVER CLIENT
# ============================================================================

class MLClient:
    def __init__(self, base_url: str, em: ErrorMemory):
        self.base_url = base_url
        self.em       = em

    def predict(self, symbol: str, rsi: float = 50.0,
                ema_ratio: float = 1.0, atr: float = 0.02,
                macd: float = 0.0, bollinger_width: float = 0.0,  # 🟢 AJOUT ICI
                news_score: float = 50.0) -> Optional[MLSignal]:
        try:
            # 🟢 AJOUT DANS LES PARAMÈTRES
            params = {
                "symbol":          symbol,
                "rsi":             rsi,
                "ema_ratio":       ema_ratio,
                "atr":             atr,
                "macd":            macd,             # Nouveau
                "bollinger_width": bollinger_width,  # Nouveau
                "news_score":      news_score
            }
            r = requests.get(f"{self.base_url}/predict", params=params, timeout=10)
            if r.status_code != 200:
                return None
            d = r.json()
            return MLSignal(
                symbol     = d.get("symbol", symbol),
                direction  = d.get("prediction", "NEUTRAL"),
                confidence = float(d.get("confidence", 0)) * 100,
                score      = float(d.get("score", 50)),
                signal_ea  = d.get("signal_ea", "safe"),
                tp         = float(d.get("tp", 0)),
                sl         = float(d.get("sl", 0)),
                blacklist  = bool(d.get("blacklist", False)),
                highvol    = d.get("highvol"),
                timestamp  = d.get("timestamp", "")
            )
        except Exception as e:
            self.em.add("MLClient", f"predict error: {e}", {"symbol": symbol})
            return None

    def get_all_signals(self) -> List[MLSignal]:
        try:
            r = requests.get(f"{self.base_url}/api/ml/signals", timeout=10)
            if r.status_code != 200:
                return []
            data = r.json().get("signals", [])
            result = []
            for d in data:
                result.append(MLSignal(
                    symbol     = d.get("symbol", ""),
                    direction  = d.get("direction", "NEUTRAL"),
                    # ×100 : même échelle que predict() — avant, le contexte
                    # marché donné à l'IA affichait «…» au lieu de 68%
                    confidence = float(d.get("confidence", 0)) * 100,
                    score      = float(d.get("score", 50)),
                    signal_ea  = d.get("signal_ea", "safe"),
                    tp         = 0.0,
                    sl         = 0.0,
                    blacklist  = False,
                    highvol    = None,
                    timestamp  = d.get("timestamp", "")
                ))
            return result
        except Exception as e:
            self.em.add("MLClient", f"get_all_signals error: {e}")
            return []

    def get_market_analysis(self) -> Dict:
        try:
            r = requests.get(f"{self.base_url}/api/ml/analysis", timeout=10)
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception as e:
            self.em.add("MLClient", f"get_market_analysis error: {e}")
            return {}

    def health(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=3)
            return r.status_code == 200
        except:
            return False

# ============================================================================
# 📰 NEWS CLIENT
# ============================================================================

class NewsClient:
    def __init__(self, base_url: str, em: ErrorMemory):
        self.base_url = base_url
        self.em       = em

    def get_signal(self, symbol: str) -> Optional[NewsSignal]:
        try:
            r = requests.get(
                f"{self.base_url}/signal",
                params={"symbol": symbol},
                timeout=10
            )
            if r.status_code != 200:
                return None
            d = r.json()

            assets = d.get("assets", {})
            data   = assets.get(symbol, d)

            return NewsSignal(
                symbol     = symbol,
                signal     = data.get("signal",    "NEUTRAL"),
                signal_ea  = data.get("signal_ea", "safe"),
                score      = float(data.get("score",      50)),
                buy_score  = float(data.get("buy_score",   0)),
                sell_score = float(data.get("sell_score",  0)),
                confidence = float(data.get("confidence",  0)),
                blacklist  = bool(data.get("blacklist",  False)),
                highvol    = data.get("highvol"),
                warning    = data.get("warning", "NO MAJOR EVENTS"),
                timestamp  = data.get("timestamp", "")
            )
        except Exception as e:
            self.em.add("NewsClient", f"get_signal error: {e}",
                        {"symbol": symbol})
            return None

    def get_all_signals(self) -> Dict:
        for endpoint in ["/signal", "/signals/all"]:
            try:
                r = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                if r.status_code == 200:
                    return r.json()
            except Exception as e:
                self.em.add("NewsClient",
                            f"get_all_signals error ({endpoint}): {e}")
        return {}

    def health(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=3)
            return r.status_code == 200
        except:
            return False

# ============================================================================
# 🧠 MAMMOUTH AI'CID
# ============================================================================

class MammouthAI:
    SYSTEM_PROMPT = """Tu es MAMMOUTH AI'CID — IA de trading haute gamme et haute fréquence, connectée DIRECTEMENT à MetaTrader5.
Tu es une machine à trader : froide, précise, sans émotion. Tu surveilles les marchés 24h/24 comme un hawk. 🦅
Expert en forex, or, crypto et indices. Tu analyses en temps réel avec signaux ML, news, reseaux sociaux, internet et indicateurs techniques.
Tu réponds en français. Si la question est courte → réponse courte. Tu n'inventes JAMAIS de données.

=== TES CAPACITÉS ACTIVES ===
Tu as accès DIRECT à MT5 : c'est le système LE CERVEAU, branché au compte, qui EXÉCUTE tes décisions.
Les ordres de trading ne passent PAS par des commandes : le patron te parle librement
(« vends l'or », « double la position », « mode agressif ») et TOI tu émets les lignes ###ACTION###
de ton protocole — LE CERVEAU les exécute sur MT5, en direct.
Les commandes Telegram qui existent servent à CONSULTER et APPRENDRE :
  /status /positions /signals /news /briefing  → l'état réel du compte et du marché
  /plan                                        → le plan de journée vivant (4 refresh/jour)
  /cot /figures /gardefous /presets /modes     → Smart Money, patterns, règles live, réglages
  /lecon <texte>                               → on t'enseigne une leçon (gravée dans chaque verdict)
  /youtu <lien>                                → tu REGARDES la vidéo YouTube entière et tu en tires des leçons
  /resetai /closeall /emergency /autotrade     → maintenance et urgence
N'invente JAMAIS d'autres commandes : cette liste est exhaustive.

=== COMPTE ACTIF ===
Capital et solde : lis TOUJOURS le contexte temps réel, jamais un chiffre de mémoire.
Tu ne sais pas — et tu n'as pas à savoir — si ce compte est réel ou de démonstration.
Règle du patron : les décisions doivent être IDENTIQUES dans les deux cas. Un bot qui
se relâche parce qu'il se croit en démo ne vaut rien le jour où il passe en réel.
Règles d'acier (issues de 19 661 vrais trades — le code les fait respecter) :
  cap lot 0.02 (exception broker jusqu'à 0.10 sur les indices) · 16 positions max compte entier
  cooldown 15 min/symbole · anti-tilt 3 pertes → pause 60 min · SL obligatoire sur toute position
Coupe-circuit journalier -10% → plus d'ouverture automatique ce jour-là.
👑 LOI DU PATRON : son ordre direct s'exécute TOUJOURS — ton avis en UNE phrase, puis tu obéis.

=== TES SOURCES DE DONNÉES ===
Tu reçois en temps réel :
  • Signaux ML AcidGPT (direction, force, score de confiance — calculés sur les VRAIS indicateurs MT5)
  • Indicateurs techniques (RSI, EMA, ATR, MACD, Bollinger) + digest H1 (tendance + bougie en cours)
  • 📖 ORDER FLOW : pression achat/vente des ticks + VRAI carnet Binance (BTC/ETH, murs d'ordres)
  • Actualités marchés + événements à fort impact (NFP, FOMC, ECB, BOE)
  • 🏦 Biais institutionnel COT hebdo (Smart Money)
  • 🎓 Tes leçons apprises (/lecon, /youtu) — ta mentalité, injectée dans chaque verdict
Tu CROISES ces sources avant chaque décision. Tu n'inventes rien.

=== RÈGLES DE TRADING ===
1. Les seuils du bloc RÉGLAGES ACTUELS (mode, confiance, trades/jour) PRIMENT sur tout chiffre par défaut
2. Signal fort + confluence (ML + COT + news + flux) → Tu EXÉCUTES sans hésiter
3. Signal contradictoire News/ML → Tu attends
4. Contre le COT : abstention — SAUF dump tactique validé (M15 opposée + RSI extrême + MACD + flux confirmé : lot mini, SL serré)
5. Sortie en profit par stop + momentum intact → continuation ; perte sèche → recovery calculée (lot ÉGAL, jamais doublé)
6. Les caps (0.02 lot / 16 positions) sont incontournables pour TOI — seul le patron passe outre, et c'est annoncé
7. Toujours SL/TP définis avant d'ouvrir

=== SURVEILLANCE NEWS — PRIORITÉ ABSOLUE ===

🔴 ALERTES ROUGES — Impact immédiat :
  • Discours Fed/BCE/BOJ inattendu → Impact USD/EUR/JPY
  • NFP, CPI, GDP hors consensus → Trade immédiat
  • Crash boursier, faillite bancaire → Short agressif
  • Conflit armé, attentat majeur → Or/JPY BUY, indices SELL
  • Tweet/déclaration Trump, sanctions → USD volatile
  • Accord/rupture OPEP → Pétrole direct

🟡 ALERTES JAUNES — Opportunités à surveiller :
  • Tensions géopolitiques montantes → Or BUY progressif
  • Données économiques mitigées → Attendre confirmation
  • Changement de politique monétaire anticipé

🟢 OPPORTUNITÉS SPÉCIALES :
  • Or (XAUUSD) : inflation, guerre, dollar faible, banques centrales
  • Bitcoin (BTCUSD) : régulation crypto, ETF news, adoption institutionnelle
  • Si >80% confiant qu'un actif va exploser → Tu le signales FORT

=== FORMAT ALERTE NEWS ===
🚨 NEWS CRITIQUE | [TITRE COURT]
Impact: [actifs concernés]
Direction: [BULLISH/BEARISH + raison 1 ligne]
Confiance: [X%]
Action: [ce que tu fais]

Exemple:
🚨 NEWS CRITIQUE | FED MONTE +0.5% SURPRISE
Impact: USD, Or, indices US
Direction: USD BULLISH / XAUUSD BEARISH fort
Confiance: 94%
Action: ⚡ SELL XAUUSD 0.05 | SELL EURUSD 0.03

=== FORMAT JSON TRADE (analyze_trade) ===
Retourne UNIQUEMENT ce JSON :
{
  "action": "TRADE" ou "SKIP",
  "signal": "BUY" ou "SELL",
  "confidence": 0-100,
  "entry_price": float,
  "sl_pips": entier,
  "tp_pips": entier,
  "reason": "max 20 mots"
}

=== PERSONNALITÉ ===
Confiant, direct, sans fioritures. Tu assumes tes décisions en 1 ligne.
En cas de perte : analyser, ajuster, continuer.
Tu penses comme Soros, Druckenmiller. Pas de panique, pas d'euphorie.
Chaque opportunité manquée coûte autant qu'une perte.

=== ⚠️ ORDRE DU PATRON (06/08) : SOIS RENTABLE ET INTELLIGENT ===
Le compte est RÉEL et PETIT. Ton seul juge, c'est le solde à la fin de la journée.
Ce ne sont pas des règles théoriques : ce sont les RÉSULTATS MESURÉS de la nuit
du 05→06/08 sur ce compte. Tu t'en sers.

CE QUI T'A FAIT GAGNER — tu y retournes :
  • BTCUSD : 8 gagnants sur 9 trades (+X €)
  • XAGUSD : +X € en UN seul trade
  • XAUUSD : 2 gagnants sur 2 (+X €)
  → tendance claire sur un actif que tu lis bien, position tenue, tu laisses courir.

CE QUI T'A RUINÉ — tu ne le refais JAMAIS :
  • CL-OIL : 0 gagnant sur 3 → -X € à lui seul (plus que toute la perte du jour).
    Cause : contrat trop lourd pour ce capital. Un instrument est écarté
    automatiquement si son lot MINIMUM risque plus de 40% du compte par jour.
  • EURUSD : 3 gagnants sur 20 → tu as EMPILÉ 12 positions sur une conviction
    faible en espérant un rebond. C'est de la moyenne à la baisse déguisée.
  • CADCHF : 0 sur 3 → tu as tiré sur un actif que tu ne lis pas.

LES 4 RÈGLES QUI DÉCOULENT DE TES PROPRES CHIFFRES :
1. QUALITÉ > QUANTITÉ. 3 gagnants sur 9 trades vaut moins qu'1 gagnant sur 1.
   Si le signal n'est pas net, tu ne tires pas. Une journée à 0 trade est une
   BONNE journée quand rien n'était clair.
2. JAMAIS d'empilement pour "récupérer". Si une position est perdante, tu ne la
   renforces pas — tu la coupes ou tu la laisses mourir à son stop. Point.
3. TU RESTES SUR TON TERRAIN. Les actifs où tu as un historique gagnant d'abord.
   Un actif inconnu ou trop lourd = tu passes ton tour.
4. TU LAISSES COURIR LES GAGNANTS. Tes pertes sont bornées par le stop ; tes
   gains ne doivent pas l'être. Coupe vite ce qui perd, tiens ce qui gagne.

Objectif : finir la journée AU-DESSUS. Pas le plus de trades — le plus de solde."""

    def __init__(self, api_key: str, em: ErrorMemory,
                 model: str = AI_MODEL):
        self.client        = Anthropic(api_key=api_key)
        # Clé de secours optionnelle : si la principale renvoie quota épuisé /
        # erreur serveur, _call_claude() refait l'appel avec celle-ci.
        self.client_backup = Anthropic(api_key=ANTHROPIC_API_KEY_BACKUP) if ANTHROPIC_API_KEY_BACKUP else None
        self.model         = model
        self.em            = em
        # Ne contient QUE les tours user/assistant : le system prompt part
        # séparément à chaque appel (voir _system_block) et n'est donc jamais
        # dupliqué dans l'historique.
        self.user_contexts: Dict[int, List[Dict]] = {}

    def _get_context(self, user_id: int) -> List[Dict]:
        return self.user_contexts.setdefault(user_id, [])

    def clear_context(self, user_id: int):
        self.user_contexts[user_id] = []

    def _trim_context(self, user_id: int):
        ctx = self.user_contexts[user_id]
        if len(ctx) > 20:
            self.user_contexts[user_id] = ctx[-20:]

    def _system_block(self) -> List[Dict]:
        # cache_control="ephemeral" : Claude met en cache ce bloc système
        # (~700 mots, identique à chaque appel). Seul le 1er appel après
        # expiration du cache le facture en entier ; tous les suivants ne
        # paient qu'une fraction du prix normal dessus. Vu le volume d'appels
        # de la trading loop, c'est le plus gros levier d'économie de tokens.
        return [{
            "type": "text",
            "text": self.SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }]

    def _check_quota_headers(self, headers):
        """Avertit dans le terminal quand le quota API approche de l'épuisement
        (en-têtes anthropic-ratelimit-* renvoyés à chaque réponse)."""
        try:
            checks = [
                ("anthropic-ratelimit-input-tokens-remaining",
                 "anthropic-ratelimit-input-tokens-limit", "tokens d'entrée"),
                ("anthropic-ratelimit-requests-remaining",
                 "anthropic-ratelimit-requests-limit", "requêtes"),
            ]
            for rem_h, lim_h, label in checks:
                rem, lim = headers.get(rem_h), headers.get(lim_h)
                if rem is None or lim is None or int(lim) <= 0:
                    continue
                ratio = int(rem) / int(lim)
                if ratio < 0.15 and time.time() - getattr(self, "_last_quota_warn", 0) > 600:
                    self._last_quota_warn = time.time()
                    reset = headers.get(rem_h.replace("remaining", "reset"), "?")
                    logger.warning(
                        f"⚠️ QUOTA API ANTHROPIC BIENTÔT ÉPUISÉ : il reste {int(ratio * 100)}% "
                        f"des {label} ({rem}/{lim}) — recharge de la fenêtre : {reset}")
        except Exception:
            pass

    def _avec_capital(self, messages):
        """Colle l'état RÉEL du compte en tête du dernier message utilisateur.
        Lu en direct sur MT5 : aucun risque de raisonner sur un solde périmé."""
        try:
            a = mt5.account_info()
            if not a or not messages:
                return messages
            libres = a.margin_free
            bandeau = (f"[COMPTE RÉEL — LIS CECI AVANT DE RÉPONDRE] "
                       f"solde {a.balance:.2f} {a.currency}, equity {a.equity:.2f}, "
                       f"marge libre {libres:.2f}. "
                       f"Lot plafonné à {MAX_LOT_HARD:g} et risque max "
                       f"{RISK_PCT_DEFAULT:g}% = {a.balance * RISK_PCT_DEFAULT / 100:.2f} "
                       f"{a.currency} par trade. N'annonce JAMAIS un lot supérieur, "
                       f"et ne parle pas de « poser du lourd » avec ce capital.]"
                       + chr(10))
            out = list(messages)
            for k in range(len(out) - 1, -1, -1):
                if out[k].get("role") == "user":
                    c = out[k].get("content")
                    if isinstance(c, str):
                        out[k] = dict(out[k], content=bandeau + c)
                    break
            return out
        except Exception:
            return messages

    def _call_claude(self, messages: List[Dict], max_tokens: int = 1200) -> str:
        # 💰 27/08 (patron) : «…
        # …». Le bot avait
        # annoncé «…» sur un compte de
        #X € — soit 442% du compte. L'exécution l'aurait bridé (MAX_LOT_HARD
        # = 0.02), mais il ne faut pas qu'il le PENSE ni qu'il le DISE.
        #
        # Le solde va dans le MESSAGE, jamais dans SYSTEM_PROMPT : celui-ci est
        # mis en cache (cache_control ephemeral) et le modifier à chaque euro
        # gagné casserait le cache — donc ferait payer ~700 mots à chaque appel.
        # Ici c'est deux lignes, sur un message déjà facturé de toute façon.
        try:
            messages = self._avec_capital(messages)
        except Exception:
            pass
        def _create(client):
            raw = client.messages.with_raw_response.create(
                model      = self.model,
                max_tokens = max_tokens,
                system     = self._system_block(),
                messages   = messages
            )
            self._check_quota_headers(raw.headers)
            return raw.parse()

        # PRINCIPAL = mammouth.ai (abonnement) — Anthropic passe en SECOURS
        # (décision du 07/07 : «…»)
        # 🚦 29/07 (patron : «…») COUPE-CIRCUIT :
        # mammouth.ai rate-limite quand on interroge 9 symboles en rafale. On
        # arrete de le harceler pendant MAMMOUTH_PAUSE_S apres 3 429 d'affilee,
        # et SURTOUT on ne bascule plus sur Anthropic PAYANT pour une analyse
        # de routine : on saute le tour (le bot ne trade pas ce symbole cette
        # minute, ca ne coute rien). Economie mesuree : ~73 % de la conso.
        global _mammouth_429, _mammouth_mute_until
        if time.time() < _mammouth_mute_until:
            raise RuntimeError("mammouth.ai en pause (rate-limit) — analyse sautee, zero token paye")
        if MAMMOUTH_API_KEY:
            try:
                r = self._call_mammouth(messages, max_tokens)
                _mammouth_429 = 0
                return r
            except Exception as e:
                if "429" in str(e):
                    _mammouth_429 += 1
                    if _mammouth_429 >= 3:
                        _mammouth_mute_until = time.time() + MAMMOUTH_PAUSE_S
                        _mammouth_429 = 0
                        logger.warning(f"🚦 mammouth.ai sature — je le laisse respirer "
                                       f"{MAMMOUTH_PAUSE_S//60} min (pas de bascule payante)")
                        raise RuntimeError("mammouth.ai sature — analyse sautee")
                # 🚦 429 = compte mammouth saturé un instant : retenter après
                # 2.5 s coûte X € ; basculer sur Anthropic coûte des CRÉDITS.
                if "429" in str(e):
                    time.sleep(2.5)
                    try:
                        return self._call_mammouth(messages, max_tokens)
                    except Exception:
                        pass
                logger.warning(f"🦣 mammouth.ai indisponible ({str(e)[:90]}) — secours Anthropic")
        # 💸 GARDE-CRÉDITS (13/07) : solde Anthropic vide = secours coupé 6 h
        # au lieu de payer des erreurs 400 en boucle (anti-hémorragie).
        global _anthropic_mort_jusqua
        if time.time() < _anthropic_mort_jusqua:
            raise RuntimeError("mammouth saturé et crédits Anthropic épuisés — analyse sautée")
        try:
            response = _create(self.client)
            try:
                from token_meter import compte as _compte_tokens
                _u = getattr(response, "usage", None)
                _compte_tokens(AI_MODEL, {"input_tokens": getattr(_u, "input_tokens", 0),
                                          "output_tokens": getattr(_u, "output_tokens", 0)}, "bot", "MAMMOUTH")
            except Exception:
                pass
            return response.content[0].text
        except Exception as e:
            if "credit balance" in str(e) or "billing" in str(e).lower():
                _anthropic_mort_jusqua = time.time() + 6 * 3600
                logger.error("💸 Crédits Anthropic ÉPUISÉS — secours coupé 6 h (anti-hémorragie)")
            retriable = any(k in str(e).lower() for k in
                            ("rate_limit", "429", "overloaded", "529", "credit", "insufficient", "billing"))
            if retriable and self.client_backup is not None:
                logger.warning(f"🔁 Clé Anthropic principale indisponible ({str(e)[:90]}) "
                               f"— bascule sur la clé de secours")
                response = _create(self.client_backup)
                return response.content[0].text
            raise

    def _call_mammouth(self, messages: List[Dict], max_tokens: int = 1200) -> str:
        """Secours n°2 : même IA (claude-haiku) mais servie par mammouth.ai —
        API compatible OpenAI, mécanisme repris de l'ancien bot bridge."""
        r = requests.post(
            MAMMOUTH_ENDPOINT,
            headers={"Authorization": f"Bearer {MAMMOUTH_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": MAMMOUTH_MODEL,
                  "messages": [{"role": "system", "content": self.SYSTEM_PROMPT}] + messages,
                  "temperature": 0.4,
                  "max_tokens": max_tokens},
            timeout=45,
        )
        r.raise_for_status()
        data = r.json()
        try:
            from token_meter import compte as _compte_tokens   # 🧮 compteur (14/07)
            _compte_tokens(MAMMOUTH_MODEL, data.get("usage") or {}, "bot", "MAMMOUTH")
        except Exception:
            pass
        return data["choices"][0]["message"]["content"]

    async def ask(self, user_id: int, message: str,
                  market_context: str = "") -> str:
        try:
            ctx = self._get_context(user_id)
            full_msg = message
            if market_context:
                full_msg = (f"[CONTEXTE MARCHÉ]\n{market_context}"
                            f"\n\n[QUESTION]\n{message}")

            ctx.append({"role": "user", "content": full_msg})
            self._trim_context(user_id)

            loop    = asyncio.get_event_loop()
            content = await loop.run_in_executor(
                None, lambda: self._call_claude(ctx)
            )

            ctx.append({"role": "assistant", "content": content})
            return content

        except Exception as e:
            self.em.add("MammouthAI", f"ask() exception: {e}")
            return f"❌ Erreur: {e}"

    async def analyze_trade(self, symbol: str, price: float,
                            indicators: Dict,
                            ml_signal:   Optional[MLSignal],
                            news_signal: Optional[NewsSignal]) -> Dict:
        try:
            ml_block = "ML Server indisponible"
            if ml_signal:
                ml_block = (
                    f"Direction: {ml_signal.direction} | "
                    f"Confidence: {ml_signal.confidence:.1f}% | "
                    f"Score: {ml_signal.score:.1f} | "
                    f"Signal EA: {ml_signal.signal_ea} | "
                    f"Blacklist: {ml_signal.blacklist} | "
                    f"HighVol: {ml_signal.highvol}"
                )

            news_block = "News Server indisponible"
            if news_signal:
                news_block = (
                    f"Signal: {news_signal.signal} | "
                    f"Score: {news_signal.score:.1f} | "
                    f"Buy: {news_signal.buy_score} | "
                    f"Sell: {news_signal.sell_score} | "
                    f"Warning: {news_signal.warning}"
                )

            # 🏦 Partage de cerveau (07/07) : biais institutionnel COT écrit
            # par LE CERVEAU dans oeil_context.json — injecté dans chaque décision.
            cot_block = "indisponible"
            try:
                _ctx = Path(__file__).resolve().parent / "oeil_context.json"
                if _ctx.exists() and time.time() - _ctx.stat().st_mtime < 3600 * 24:
                    _c = json.loads(_ctx.read_text(encoding="utf-8")).get("cot", {})
                    if symbol in _c:
                        cot_block = f"{_c[symbol]['bias']} ({_c[symbol]['pct']:+}% de l'open interest)"
            except Exception:
                pass

            prompt = f"""ANALYSE DE TRADE — {datetime.now().strftime('%H:%M:%S')}

Symbole: {symbol}
Prix actuel: {price:.5f}

=== INDICATEURS TECHNIQUES ===
RSI: {indicators.get('rsi', 50):.1f}
EMA20: {indicators.get('ema20', 0):.5f}
EMA50: {indicators.get('ema50', 0):.5f}
EMA200: {indicators.get('ema200', 0):.5f}
ATR: {indicators.get('atr', 0):.5f}
MACD: {indicators.get('macd', 0):.5f}
Signal MACD: {indicators.get('macd_signal', 0):.5f}
BB Upper: {indicators.get('bb_upper', 0):.5f}
BB Lower: {indicators.get('bb_lower', 0):.5f}
Trend: {indicators.get('trend', 'NEUTRAL')}

=== MULTI-TIMEFRAME (chirurgie scalp) ===
{(lambda m: f"M15 (boussole): tendance {m.get('m15_trend', '?')}, RSI {m.get('m15_rsi', 0):.1f} | M1 (gâchette): RSI {m.get('m1_rsi', 0):.1f}, MACD {m.get('m1_macd', 0):.5f}" if m else "indisponible")(indicators.get('mtf'))}
(Règle : on ne scalpe QUE dans le sens de la tendance M15 ; le M1 sert à affiner le timing d'entrée, pas à contredire la boussole.)

=== SIGNAL ML (AcidGPT) ===
{ml_block}

=== SMART MONEY (COT — gros spéculateurs) ===
Biais institutionnel: {cot_block}
(Privilégie les trades ALIGNÉS avec ce biais ; méfiance si contre-tendance.)

=== SIGNAL NEWS ===
{news_block}

Retourne UNIQUEMENT ce JSON (rien d'autre) :
{{
  "action": "TRADE" ou "SKIP",
  "signal": "BUY" ou "SELL",
  "confidence": 0-100,
  "entry_price": {price:.5f},
  "sl_pips": entier,
  "tp_pips": entier,
  "reason": "max 20 mots"
}}"""

            # ⚠️ Appel STATELESS, volontairement : contrairement à ask(), on
            # ne touche PAS à self.user_contexts. Chaque décision de trade est
            # indépendante (nouvelle bougie / nouveau symbole) — faire traîner
            # 20 échanges précédents dans chaque appel ne sert à rien et
            # gonfle la facture en tokens pour rien. Le system prompt reste
            # mis en cache (voir _system_block), donc le coût par appel reste
            # minimal : juste le prompt du jour + une petite réponse JSON.
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._call_claude(
                    [{"role": "user", "content": prompt}], max_tokens=300
                )
            )

            try:
                start = response.find('{')
                end   = response.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass

            return {
                "action":     "SKIP",
                "signal":     "NEUTRAL",
                "confidence": 0,
                "sl_pips":    20,
                "tp_pips":    40,
                "reason":     "Parse JSON failed"
            }

        except Exception as e:
            self.em.add("MammouthAI", f"analyze_trade exception: {e}")
            # 🦅 FALLBACK INTELLIGENT (restauré 07/07 depuis l'ancien bot) :
            # IA injoignable ≠ bot aveugle. Si le ML a une vraie conviction,
            # on trade quand même sur son signal (comme avant).
            if ml_signal and ml_signal.direction in ("BUY", "SELL") \
                    and ml_signal.confidence >= MIN_CONFIDENCE:
                logger.warning(f"🦅 IA HS — fallback ML : {ml_signal.direction} "
                               f"({ml_signal.confidence:.0f}%) sur {symbol}")
                return {
                    "action":     "TRADE",
                    "signal":     ml_signal.direction,
                    "confidence": ml_signal.confidence,
                    "sl_pips":    20,
                    "tp_pips":    40,
                    "reason":     f"Fallback ML (IA indisponible): {str(e)[:60]}"
                }
            return {
                "action":     "SKIP",
                "signal":     "NEUTRAL",
                "confidence": 0,
                "sl_pips":    20,
                "tp_pips":    40,
                "reason":     str(e)
            }

    async def build_market_context(self, ml_client: "MLClient",
                                   news_client: "NewsClient") -> str:
        try:
            lines = [
                f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                "=== MARCHÉ EN TEMPS RÉEL ==="
            ]

            ml_signals = ml_client.get_all_signals()
            if ml_signals:
                lines.append("\n📊 Signaux ML (AcidGPT):")
                for s in ml_signals[:5]:
                    lines.append(
                        f"  {s.symbol}: {s.direction} "
                        f"conf={s.confidence:.0f}% "
                        f"ea={s.signal_ea}"
                    )

            all_news = news_client.get_all_signals()
            assets   = all_news.get("assets", {})
            if assets:
                lines.append("\n📰 Signaux News:")
                for sym, data in list(assets.items())[:5]:
                    lines.append(
                        f"  {sym}: {data.get('signal', '?')} "
                        f"score={data.get('score', 0):.0f}"
                    )

            return "\n".join(lines)
        except Exception as e:
            self.em.add("MammouthAI", f"build_market_context error: {e}")
            return ""


# ============================================================================
# 📈 INDICATOR ENGINE (Version Unifiée & Complète pour le ML)
# ============================================================================
import pandas as pd
import numpy as np
from typing import Dict

class IndicatorEngine:
    def calculate(self, df: pd.DataFrame) -> Dict:
        try:
            closes = df['close'].values
            highs  = df['high'].values
            lows   = df['low'].values

            rsi    = self._rsi(closes, 14)
            ema20  = self._ema(closes, 20)
            ema50  = self._ema(closes, 50)
            ema200 = self._ema(closes, 200)
            macd, signal = self._macd(closes)
            bb_u, bb_l   = self._bollinger(closes, 20, 2)
            atr    = self._atr(highs, lows, closes, 14)

            price     = closes[-1]
            ema20_val = ema20[-1]
            ema50_val = ema50[-1]
            ema200_val= ema200[-1]
            ema_ratio = ema20_val / ema50_val if ema50_val != 0 else 1.0

            # 🟢 AJOUT POUR LE ML : Calcul de la largeur de Bollinger
            bb_upper_val = bb_u[-1]
            bb_lower_val = bb_l[-1]
            # Formule: (Upper - Lower) / Close (On vérifie que le prix n'est pas 0 pour éviter une erreur mathématique)
            if price != 0 and not np.isnan(bb_upper_val) and not np.isnan(bb_lower_val):
                bollinger_width = (bb_upper_val - bb_lower_val) / price
            else:
                bollinger_width = 0.0

            # Trend simple
            if ema20_val > ema50_val and price > ema20_val:
                trend = "BULLISH"
            elif ema20_val < ema50_val and price < ema20_val:
                trend = "BEARISH"
            else:
                trend = "NEUTRAL"

            return {
                "price":           float(price),
                "rsi":             float(rsi[-1]),
                "ema20":           float(ema20_val),
                "ema50":           float(ema50_val),
                "ema200":          float(ema200_val),
                "ema_ratio":       float(ema_ratio),
                "macd":            float(macd[-1]),
                "macd_signal":     float(signal[-1]),
                "bb_upper":        float(bb_upper_val),
                "bb_lower":        float(bb_lower_val),
                "bollinger_width": float(bollinger_width),  # 🟢 AJOUTÉ ICI POUR LE MACHINE LEARNING
                "atr":             float(atr),
                "trend":           trend
            }
        except Exception as e:
            # logger.error(f"IndicatorEngine error: {e}")
            return {
                "price": 0.0, "rsi": 50.0, "ema20": 0.0, "ema50": 0.0,
                "ema200": 0.0, "ema_ratio": 1.0, "macd": 0.0, "macd_signal": 0.0,
                "bb_upper": 0.0, "bb_lower": 0.0,
                "bollinger_width": 0.0,  # 🟢 VALEUR PAR DÉFAUT AJOUTÉE ICI
                "atr": 0.002, "trend": "NEUTRAL"
            }

    @staticmethod
    def _rsi(prices, period=14):
        if len(prices) < period:
            return np.full(len(prices), 50.0)
        deltas = np.diff(prices)
        up     = np.maximum(deltas, 0)
        down   = np.maximum(-deltas, 0)
        
        # On calcule les moyennes avec convolution
        up_avg = np.convolve(up, np.ones(period)/period, mode='full')[:len(up)]
        down_avg = np.convolve(down, np.ones(period)/period, mode='full')[:len(down)]
        
        # On ajoute + 1e-9 au diviseur (down_avg) pour éviter la division par zéro !
        rs     = up_avg / (down_avg + 1e-9)
        rsi    = 100 - (100 / (1 + rs))
        
        return np.append([50.0], rsi)

    @staticmethod
    def _ema(prices, period):
        return pd.Series(prices).ewm(span=period, adjust=False).mean().values

    @staticmethod
    def _macd(prices, fast=12, slow=26, signal=9):
        ema_fast   = pd.Series(prices).ewm(span=fast,   adjust=False).mean()
        ema_slow   = pd.Series(prices).ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line= macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line.values, signal_line.values

    @staticmethod
    def _bollinger(prices, period=20, std_mult=2):
        s     = pd.Series(prices)
        mid   = s.rolling(period).mean()
        std   = s.rolling(period).std()
        upper = (mid + std_mult * std).values
        lower = (mid - std_mult * std).values
        return upper, lower

    @staticmethod
    def _atr(highs, lows, closes, period=14):
        try:
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:]  - closes[:-1])
                )
            )
            return float(np.mean(tr[-period:]))
        except:
            return 0.002

# ============================================================================
# 🐘 FLOWRIDER — ADX + SuperTrend (le rail des tendances fortes)
# ============================================================================

def flowrider_calc(highs, lows, closes,
                   atr_p=FLOWRIDER_ATR_PER, mult=FLOWRIDER_MULT, adx_p=FLOWRIDER_ADX_PER):
    """Retourne {adx, rail, trend} sur les bougies fournies (M15).
    rail = valeur du SuperTrend ; trend = +1 (haussier) / -1 (baissier).
    ADX Wilder (lissage ewm alpha=1/p), SuperTrend classique (ATR, bandes
    reportées). Déterministe, sans dépendance externe (numpy/pandas déjà là)."""
    n = len(closes)
    if n < max(atr_p, adx_p) + 5:
        return {"adx": 0.0, "rail": 0.0, "trend": 0}
    h = np.asarray(highs, float); l = np.asarray(lows, float); c = np.asarray(closes, float)
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).ewm(alpha=1.0 / atr_p, adjust=False).mean().values
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    fu = upper.copy(); fl = lower.copy()
    for i in range(1, n):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
    st = np.zeros(n); trend = np.ones(n, dtype=int)
    st[0] = fu[0]; trend[0] = -1
    for i in range(1, n):
        if st[i - 1] == fu[i - 1]:
            if c[i] > fu[i]: st[i], trend[i] = fl[i], 1
            else:            st[i], trend[i] = fu[i], -1
        else:
            if c[i] < fl[i]: st[i], trend[i] = fu[i], -1
            else:            st[i], trend[i] = fl[i], 1
    # ADX (Wilder)
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm  = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr2 = tr[1:]
    atrw = pd.Series(tr2).ewm(alpha=1.0 / adx_p, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm).ewm(alpha=1.0 / adx_p, adjust=False).mean() / (atrw + 1e-9)
    mdi = 100 * pd.Series(minus_dm).ewm(alpha=1.0 / adx_p, adjust=False).mean() / (atrw + 1e-9)
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    adx = dx.ewm(alpha=1.0 / adx_p, adjust=False).mean().values
    return {"adx": float(adx[-1]), "rail": float(st[-1]), "trend": int(trend[-1])}


# ============================================================================
# 💥 CRASH CATCHER
# ============================================================================

class CrashCatcher:
    def __init__(self, em: ErrorMemory):
        self.em = em
        self.last_prices: Dict[str, float] = {}

    def check(self, symbol: str, current_price: float) -> Tuple[bool, float]:
        # 1. Si c'est la première fois qu'on voit l'actif, on enregistre le prix et on passe
        if symbol not in self.last_prices:
            self.last_prices[symbol] = current_price
            return False, 0.0

        # 2. Calcul du mouvement
        last = self.last_prices[symbol]
        movement = abs(current_price - last)
        
        # On met à jour le dernier prix pour le prochain tick
        self.last_prices[symbol] = current_price

        # 3. LE SEUIL SE MESURE (08/09). Avant, une table de noms en dur : elle
        # testait «…» alors que le symbole Vantage est SP500 → aucune
        # correspondance → défaut FOREX 0,005 point sur un indice à 7 700, donc
        # «…» à chaque respiration. Six faux krachs en 30 min le 08/09,
        # cinq minutes d'analyse suspendue chacun. Un krach, c'est un mouvement
        # anormal POUR CE MARCHÉ : 2,5 × son ATR M5, mesuré en direct.
        seuil_mesure = None
        try:
            _r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, 15)
            if _r is not None and len(_r) >= 15:
                _H = [float(x["high"]) for x in _r]
                _L = [float(x["low"]) for x in _r]
                _C = [float(x["close"]) for x in _r]
                _tr = [max(_H[i] - _L[i], abs(_H[i] - _C[i - 1]), abs(_L[i] - _C[i - 1]))
                       for i in range(1, len(_r))]
                _atr = sum(_tr) / len(_tr)
                if _atr > 0:
                    seuil_mesure = 2.5 * _atr
        except Exception:
            pass

        # secours si l'ATR est illisible — avec les noms VANTAGE cette fois
        if "BTC" in symbol:
            threshold = 300.0   # Le BTC doit bouger de 300$ d'un coup
        elif "ETHUSD" in symbol:
            threshold = 10.0    # L'ETH (~1800$) doit bouger de 10$ d'un coup
        elif "XAU" in symbol or "GOLD" in symbol:
            threshold = 10.0    # L'or doit bouger de 10$ d'un coup
        elif "SILVER" in symbol or "XAG" in symbol:
            threshold = 0.80    # L'argent (~60$) : 0.80$ = ~1.3% (0.25 = respiration normale, faux krachs en boucle)
        elif "US500" in symbol:
            threshold = 25.0    # Le S&P 500 (~7500) doit bouger de 25 pts d'un coup
        elif "CRYPTO" in symbol.upper():
            threshold = 50.0    # Crypto_10 (~12750) doit bouger de 50 pts d'un coup
                                # (avant: seuil forex 0.005 -> "crash" permanent, découvert par LE CERVEAU 👁️)
        elif "OIL" in symbol:
            threshold = 2.0     # Le pétrole doit bouger de 2$ d'un coup
        elif "JPY" in symbol:
            threshold = 0.50    # Les paires JPY (ex: USDJPY) doivent bouger de 50 pips
        elif "SP500" in symbol or "US500" in symbol:
            threshold = 25.0    # 08/09 : le nom VANTAGE est SP500 — «…» seul ne matchait rien
        elif "NAS" in symbol or "US100" in symbol:
            threshold = 60.0    # NAS100 (~29 700) : 60 points d'un coup
        elif "USDX" in symbol:
            threshold = 0.50
        else:
            threshold = 0.0050  # Par défaut (Forex normal) : 50 pips (ex: 1.0800 -> 1.0850)

        # la mesure prime sur la table : elle suit la volatilité du jour
        if seuil_mesure:
            threshold = seuil_mesure

        # 4. Vérification du Crash
        if movement >= threshold:
            self.em.add("CrashCatcher",
                        f"💥 CRASH détecté {symbol}: mouvement={movement:.5f}",
                        {"symbol": symbol, "movement": movement,
                         "last": last, "current": current_price})
            
            # On logge l'avertissement avec le bon seuil
            logger.warning(f"💥 CrashCatcher: {symbol} "
                           f"mouvement={movement:.5f} (seuil={threshold:.5f})")
            return True, movement

        # Si tout va bien
        return False, movement

# ============================================================================
# 🕯️ NEW CANDLE DETECTOR
# ============================================================================

class NewCandleDetector:
    def __init__(self):
        self._last_times: Dict[str, pd.Timestamp] = {}

    def is_new_candle(self, symbol: str, df: pd.DataFrame) -> bool:
        if df.empty:
            return False
        current_time = df['time'].iloc[-1]
        if symbol not in self._last_times:
            self._last_times[symbol] = current_time
            return True
        if current_time != self._last_times[symbol]:
            self._last_times[symbol] = current_time
            return True
        return False


# ============================================================================
# 🛡️ SMART POSITION MANAGER
# ============================================================================

class SmartPositionManager:
    def __init__(self, mt5_conn: MT5Connector,
                 state: BotState, em: ErrorMemory):
        self.mt5   = mt5_conn
        self.state = state
        self.em    = em
        self._tbe: Dict[int, float] = {}   # ticket -> 1er instant en profit (BE temporel)
        self._fr_cache: Dict[str, dict] = {}   # 🐘 cache FlowRider par symbole (30 s)

    def _flowrider(self, symbol: str) -> dict:
        """🐘 État du rail sur ce symbole (M15) : {actif, adx, rail, trend}.
        Caché 30 s pour ne pas recalculer à chaque tick de chaque position."""
        if not FLOWRIDER_ENABLED:
            return {"actif": False, "adx": 0.0, "rail": 0.0, "trend": 0}
        now = time.time()
        c = self._fr_cache.get(symbol)
        if c and now - c["t"] < 30:
            return c["v"]
        try:
            bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 120)
            if bars is None or len(bars) < 40:
                v = {"actif": False, "adx": 0.0, "rail": 0.0, "trend": 0}
            else:
                r = flowrider_calc([b["high"] for b in bars],
                                   [b["low"] for b in bars],
                                   [b["close"] for b in bars])
                r["actif"] = r["adx"] >= FLOWRIDER_ADX_MIN
                v = r
        except Exception as e:
            self.em.add("FlowRider", f"calc error {symbol}: {e}")
            v = {"actif": False, "adx": 0.0, "rail": 0.0, "trend": 0}
        self._fr_cache[symbol] = {"t": now, "v": v}
        return v

    # ═══════════════════════════════════════════════════════════════════
    # 🔁 CYCLE «…» (patron 21/08)
    # ═══════════════════════════════════════════════════════════════════
    def _cycle_encaisse(self, pos, tick) -> bool:
        """Scalp encore positif après 10 min → on encaisse et on note le niveau.
        Retourne True si la position a été fermée (le reste de manage() est alors
        sans objet)."""
        if not CYCLE_SCALP_ON or pos.magic == self.mt5.MAGIC_SWING:
            return False                      # les swings de conviction courent
        if getattr(pos, "flowrider", False):
            return False                      # un monstre en cours : on ne coupe pas
        try:
            if not pos.entry_time:
                return False
            age_min = (datetime.now() - pos.entry_time).total_seconds() / 60.0
            if age_min < CYCLE_APRES_MIN:
                return False

            pip = self.mt5.pip(pos.symbol)
            is_buy = pos.direction == Direction.BUY
            cur = tick.bid if is_buy else tick.ask
            gain_pips = ((cur - pos.entry_price) if is_buy
                         else (pos.entry_price - cur)) / pip
            gain_eur = 0.0
            for p in (mt5.positions_get(ticket=pos.ticket) or []):
                gain_eur = p.profit + p.swap
            if gain_eur < CYCLE_GAIN_MIN_EUR or gain_pips < CYCLE_GAIN_MIN_PIPS:
                return False                  # pas assez : on laisse vivre

            if not self.mt5.close_position(pos.ticket):
                return False

            niveau = {
                "symbol": pos.symbol, "direction": pos.direction,
                "prix": pos.entry_price, "sl": pos.sl, "tp": pos.tp,
                "volume": pos.volume, "expire": time.time() + CYCLE_VALIDITE_MIN * 60,
                "restant": CYCLE_MAX_REPETITIONS, "dernier": 0.0,
            }
            _CYCLE_NIVEAUX.append(niveau)
            logger.info(f"🔁 ENCAISSÉ #{pos.ticket} {pos.symbol} "
                        f"{'BUY' if is_buy else 'SELL'} après {age_min:.0f} min : "
                        f"+{gain_eur:.2f}€ ({gain_pips:.0f} pips). "
                        f"Point d'entrée {pos.entry_price} sous surveillance — "
                        f"j'y reviens si le prix repasse et que les signaux tiennent "
                        f"({CYCLE_MAX_REPETITIONS} reprises max).")
            return True
        except Exception as e:
            logger.error(f"cycle encaisse {getattr(pos, 'symbol', '?')} : {e}")
            return False

    def _seuils_atr(self, symbol: str, pip: float) -> dict:
        """🩸 04/09 — LES SORTIES EN ATR, PLUS EN PIPS FIXES.
        BE_TRIGGER_PIPS=18 valait 0,14 ATR sur l'or (on encaisse dans le bruit)
        et 3 ATR sur EURUSD (on n'encaisse jamais). Mêmes multiples que les
        presets de l'EA. Jamais sous 3× le spread. Repli sur les anciennes
        constantes si l'ATR est indisponible — on ne casse jamais la gestion."""
        try:
            atr = self.mt5.calculate_atr(symbol)
            atr_pips = (atr / pip) if (atr and pip) else 0.0
            info = mt5.symbol_info(symbol)
            spread_pips = ((info.spread * info.point) / pip) if (info and pip) else 0.0
            if atr_pips <= 0:
                raise ValueError("atr indisponible")
            plancher = max(3.0 * spread_pips, 1.0)
            # 🎓 08/09 — MÊME TECHNIQUE QUE LE CERVEAU ET L'EA (celle du patron) :
            # avant, BE à 1,2 ATR = 10,8 $ sur l'or, soit le double de ce qu'il
            # sécurise à la main. Trois bots, trois techniques : on unifie.
            return {"be": max(0.55 * atr_pips, plancher),
                    "trail_start": max(1.2 * atr_pips, plancher),
                    "trail_step": max(0.5 * atr_pips, plancher),
                    "wide_trigger": max(4.0 * atr_pips, plancher),
                    "wide_step": max(1.2 * atr_pips, plancher),
                    "atr_pips": atr_pips}
        except Exception:
            return {"be": BE_TRIGGER_PIPS, "trail_start": TRAIL_START_PIPS,
                    "trail_step": TRAIL_STEP_PIPS, "wide_trigger": TRAIL_WIDE_TRIGGER_PIPS,
                    "wide_step": TRAIL_WIDE_STEP_PIPS, "atr_pips": 0.0}

    def manage(self, pos: Position):
        try:
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return

            # 🔁 ENCAISSE ET RECOMMENCE (patron 21/08) — avant toute autre
            # gestion : un scalp encore gagnant après CYCLE_APRES_MIN minutes
            # est encaissé, et son point d'entrée est mis SOUS SURVEILLANCE
            # pour une re-entrée au même prix (voir _guetter_retour).
            if self._cycle_encaisse(pos, tick):
                return

            pip          = self.mt5.pip(pos.symbol)
            current_price= tick.bid if pos.direction == Direction.BUY else tick.ask
            _s           = self._seuils_atr(pos.symbol, pip)     # 🩸 04/09 : en ATR
            be_trigger   = _s["be"]          * pip
            trail_start  = _s["trail_start"] * pip
            trail_step   = _s["trail_step"]  * pip

            # 🩸 RÈGLE D'ACIER (spec p.7, posée le 17/07) : AUCUNE position nue
            # au-delà de 30 s (60→30 le 17/07, patron : «…
            # …») — l'audit des 19 661 vrais trades : 37% sans
            # SL =X € de pertes. MAMMOUTH ouvre toujours avec SL, mais
            # un SL peut sauter (modif manuelle, requote, crash) : filet ici.
            # SL d'urgence au plancher de la classe (50/30/40 pips).
            if pos.sl == 0:
                age_nue = (datetime.now() - pos.entry_time).total_seconds() if pos.entry_time else 0
                if age_nue > 30:
                    dist   = quick_sl_pips(pos.symbol) * pip
                    sl_urg = (pos.entry_price - dist if pos.direction == Direction.BUY
                              else pos.entry_price + dist)
                    if self.mt5.modify_position(pos.ticket, sl_urg, pos.tp):
                        pos.sl = sl_urg
                        logger.warning(f"🚨 Position NUE >30s #{pos.ticket} {pos.symbol} — "
                                       f"SL d'urgence posé ({quick_sl_pips(pos.symbol)} pips)")
                    else:
                        self.em.add("SmartPM", "SL urgence refuse (position nue)",
                                    {"ticket": pos.ticket, "symbol": pos.symbol})

            # 🐘 FLOWRIDER : tendance forte (ADX≥23) alignée avec le rail
            # SuperTrend M15 → la position CHEVAUCHE le mouvement. Son SL suit le
            # RAIL (stop qui respire, pas collé au prix) et elle est exemptée des
            # coupes rapides (flag pos.flowrider lu dans monitor_positions).
            # Ne s'arme qu'en profit ; une fois armé, le rail ne fait que se
            # resserrer, jamais aller contre nous. C'est le «…
            # …» de la spec p.8 — la réponse au rail GOLD raté du 20-21/07.
            is_buy = pos.direction == Direction.BUY
            profit_pips_fr = ((current_price - pos.entry_price) if is_buy
                              else (pos.entry_price - current_price)) / pip
            fr = self._flowrider(pos.symbol)
            aligned = (fr["trend"] == 1 and is_buy) or (fr["trend"] == -1 and not is_buy)
            if fr["actif"] and aligned and profit_pips_fr >= FLOWRIDER_MIN_PIPS:
                rail = fr["rail"]
                ok_side = (rail < current_price) if is_buy else (rail > current_price)
                if ok_side:
                    newly = not pos.flowrider
                    # 1re activation : SL posé SUR le rail (même plus large qu'un
                    # stop serré — c'est le but). Ensuite : le rail ne se resserre
                    # que dans notre sens (trail), jamais contre nous.
                    tighten = (rail > pos.sl) if is_buy else (pos.sl == 0 or rail < pos.sl)
                    if (newly or tighten) and abs(rail - (pos.sl or rail)) > 1e-9:
                        if self.mt5.modify_position(pos.ticket, rail, pos.tp):
                            pos.sl = rail
                    pos.flowrider = True
                    if newly:
                        logger.info(f"🐘 FlowRider ON #{pos.ticket} {pos.symbol} "
                                    f"{'BUY' if is_buy else 'SELL'} SL→rail {rail:.5f} "
                                    f"(ADX {fr['adx']:.0f}, +{profit_pips_fr:.0f} pips) — laisse courir")
                    return   # mode rail : on saute BE/trail/partial classiques
            elif pos.flowrider:
                pos.flowrider = False   # rail cassé ou ADX retombé → gains verrouillés
                logger.info(f"🐘 FlowRider OFF #{pos.ticket} {pos.symbol} "
                            f"(ADX {fr['adx']:.0f}, trend {fr['trend']}) — gestion normale reprise")

            # ⏱️ BE TEMPOREL (sync EA 07/07) : position âgée de 2 min ET en
            # profit continu depuis 1 min → SL verrouillé à l'entrée ±1 pip,
            # même si le seuil classique en pips n'est jamais atteint.
            try:
                is_buy = pos.direction == Direction.BUY
                profit_abs = (current_price - pos.entry_price) if is_buy else (pos.entry_price - current_price)
                now_ts = time.time()
                if profit_abs <= 0:
                    self._tbe.pop(pos.ticket, None)
                else:
                    self._tbe.setdefault(pos.ticket, now_ts)
                    age = (datetime.now() - pos.entry_time).total_seconds() if pos.entry_time else 0
                    lock = pos.entry_price + pip if is_buy else pos.entry_price - pip
                    locked = (pos.sl >= lock) if is_buy else (0 < pos.sl <= lock)
                    if age >= 120 and now_ts - self._tbe[pos.ticket] >= 60 and not locked:
                        if self.mt5.modify_position(pos.ticket, lock, pos.tp):
                            pos.be_activated = True
                            pos.sl = lock
                            logger.info(f"🔒 BE temporel #{pos.ticket} SL→{lock:.5f} (sortie en bénef assurée)")
            except Exception:
                pass

            if pos.direction == Direction.BUY:
                profit_pips = (current_price - pos.entry_price) / pip

                # PARTIAL TP
                if (not pos.partial_done and pos.tp1 > 0
                        and current_price >= pos.tp1):
                    partial_vol = round(pos.initial_volume * PARTIAL_TP_PCT, 2)
                    _info = mt5.symbol_info(pos.symbol)
                    _vmin = (_info.volume_min if _info else 0) or 0.01
                    # 21/07 : si la part OU le reste < lot mini broker (ex ETH 0.02),
                    # le partial est impossible → on arme partial_done pour couper le
                    # retry en boucle (spam ~130 logs/2h vu à l'autopsie de la nuit)
                    if partial_vol < _vmin or (pos.initial_volume - partial_vol) < _vmin - 1e-9:
                        pos.partial_done = True
                        logger.info(f"⏭️ Partial impossible BUY #{pos.ticket} (lot {pos.initial_volume}/mini {_vmin}) — TP1 laissé courir")
                    elif self.mt5.close_partial(pos.ticket, partial_vol):
                        pos.partial_done = True
                        logger.info(f"✅ Partial TP BUY #{pos.ticket} vol={partial_vol}")

                # SMART BE
                if (not pos.be_activated
                        and profit_pips >= _s["be"]
                        and pos.sl < pos.entry_price):
                    new_sl = pos.entry_price + pip
                    if self.mt5.modify_position(pos.ticket, new_sl, pos.tp):
                        pos.be_activated = True
                        pos.sl           = new_sl
                        logger.info(f"🔒 SmartBE BUY #{pos.ticket} SL→{new_sl:.5f}")

                # TRAILING STOP — 🐘 palier large : > TRAIL_WIDE_TRIGGER_PIPS,
                # le trade est un monstre → pas de 35 pips (respiration)
                if profit_pips >= _s["trail_start"]:
                    step = (_s["wide_step"] if profit_pips >= _s["wide_trigger"]
                            else _s["trail_step"]) * pip
                    new_sl = current_price - step
                    if new_sl > pos.sl + step:
                        if self.mt5.modify_position(pos.ticket, new_sl, pos.tp):
                            pos.trail_activated = True
                            pos.sl              = new_sl
                            logger.info(f"📈 Trail BUY #{pos.ticket} SL→{new_sl:.5f}"
                                        + (" (palier LARGE 🐘)" if step > trail_step else ""))

            else:  # SELL
                profit_pips = (pos.entry_price - current_price) / pip

                # PARTIAL TP
                if (not pos.partial_done and pos.tp1 > 0
                        and current_price <= pos.tp1):
                    partial_vol = round(pos.initial_volume * PARTIAL_TP_PCT, 2)
                    _info = mt5.symbol_info(pos.symbol)
                    _vmin = (_info.volume_min if _info else 0) or 0.01
                    if partial_vol < _vmin or (pos.initial_volume - partial_vol) < _vmin - 1e-9:
                        pos.partial_done = True
                        logger.info(f"⏭️ Partial impossible SELL #{pos.ticket} (lot {pos.initial_volume}/mini {_vmin}) — TP1 laissé courir")
                    elif self.mt5.close_partial(pos.ticket, partial_vol):
                        pos.partial_done = True
                        logger.info(f"✅ Partial TP SELL #{pos.ticket} vol={partial_vol}")

                # SMART BE (fix 07/07 : pos.sl == 0 = position sans SL,
                # l'ancienne condition la laissait sans breakeven à vie)
                if (not pos.be_activated
                        and profit_pips >= _s["be"]
                        and (pos.sl == 0 or pos.sl > pos.entry_price)):
                    new_sl = pos.entry_price - pip
                    if self.mt5.modify_position(pos.ticket, new_sl, pos.tp):
                        pos.be_activated = True
                        pos.sl           = new_sl
                        logger.info(f"🔒 SmartBE SELL #{pos.ticket} SL→{new_sl:.5f}")

                # TRAILING STOP (fix 07/07 : gère aussi pos.sl == 0)
                # 🐘 palier large : > TRAIL_WIDE_TRIGGER_PIPS → pas de 35 pips
                if profit_pips >= _s["trail_start"]:
                    step = (_s["wide_step"] if profit_pips >= _s["wide_trigger"]
                            else _s["trail_step"]) * pip
                    new_sl = current_price + step
                    if pos.sl == 0 or new_sl < pos.sl - step:
                        if self.mt5.modify_position(pos.ticket, new_sl, pos.tp):
                            pos.trail_activated = True
                            pos.sl              = new_sl
                            logger.info(f"📉 Trail SELL #{pos.ticket} SL→{new_sl:.5f}"
                                        + (" (palier LARGE 🐘)" if step > trail_step else ""))

        except Exception as e:
            self.em.add("SmartPositionManager",
                        f"manage error ticket={pos.ticket}: {e}")

# ============================================================================
# 🔄 AUTO TRADING ENGINE
# ============================================================================

class AutoTradingEngine:
    def __init__(self, mt5_conn: MT5Connector, mammouth: MammouthAI,
                 ml_client: MLClient, news_client: NewsClient,
                 state: BotState, em: ErrorMemory):
        self.mt5       = mt5_conn
        self.mammouth  = mammouth
        self.ml        = ml_client
        self.news      = news_client
        self.state     = state
        self.em        = em
        self.candle_d  = NewCandleDetector()
        self.crash_c   = CrashCatcher(em=em)
        self.spm       = SmartPositionManager(mt5_conn, state, em)
        self.ind_eng   = IndicatorEngine()
        self._pos_meta: Dict[int, Position] = {}
        # Canal express du CERVEAU 👁️ : alertes de prix temps réel écrites par
        # ia_watchdog.py — permet d'analyser un symbole sans attendre la bougie
        self._oeil_file = Path(__file__).resolve().parent / "oeil_signals.json"
        self._oeil_seen: set = set()

    def _oeil_express(self, symbol: str) -> bool:
        """True si LE CERVEAU a émis une alerte fraîche (<90 s) non consommée sur ce
        symbole → le bot lance une analyse immédiate, hors cadence des bougies."""
        try:
            if not self._oeil_file.exists():
                return False
            if time.time() - self._oeil_file.stat().st_mtime > 120:
                return False
            data = json.loads(self._oeil_file.read_text(encoding="utf-8"))
            for a in data.get("alerts", []):
                key = (a.get("symbol"), a.get("ts"))
                if (a.get("symbol") == symbol
                        and time.time() - float(a.get("ts", 0)) < 90
                        and key not in self._oeil_seen):
                    self._oeil_seen.add(key)
                    if len(self._oeil_seen) > 200:
                        self._oeil_seen.clear()
                    logger.info(f"👁️⚡ Alerte du CERVEAU sur {symbol} "
                                f"({a.get('kind')}, mouvement {a.get('move')}) — analyse express")
                    return True
        except Exception:
            pass
        return False

    def _enrich_positions(self, raw_positions: List[Position]) -> List[Position]:
        result = []
        for pos in raw_positions:
            if pos.ticket in self._pos_meta:
                meta = self._pos_meta[pos.ticket]
                pos.be_activated    = meta.be_activated
                pos.trail_activated = meta.trail_activated
                pos.partial_done    = meta.partial_done
                pos.initial_volume  = meta.initial_volume
                pos.tp1             = meta.tp1
                pos.sl              = meta.sl 
            else:
                self._pos_meta[pos.ticket] = pos
            result.append(pos)

        active_tickets = {p.ticket for p in raw_positions}
        for t in list(self._pos_meta.keys()):
            if t not in active_tickets:
                del self._pos_meta[t]

        return result

    async def _guetter_retour(self):
        """Le prix est-il revenu sur un point d'entrée encaissé ? Si oui et si
        les signaux sont TOUJOURS bons, on remet la même position."""
        if not CYCLE_SCALP_ON or not _CYCLE_NIVEAUX:
            return
        if not self._entree_autorisee():   # 🩸 05/09 : le cycle n'ouvre pas pendant une pause
            return
        maintenant = time.time()
        vivants = []
        for niv in _CYCLE_NIVEAUX:
            if maintenant > niv["expire"] or niv["restant"] <= 0:
                logger.info(f"🔁 niveau {niv['symbol']} @{niv['prix']} abandonné "
                            f"({'expiré' if maintenant > niv['expire'] else 'quota épuisé'})")
                continue
            vivants.append(niv)
            try:
                if maintenant - niv["dernier"] < CYCLE_COOLDOWN_S:
                    continue
                tick = mt5.symbol_info_tick(niv["symbol"])
                if not tick:
                    continue
                pip = self.mt5.pip(niv["symbol"])
                is_buy = niv["direction"] == Direction.BUY
                cur = tick.ask if is_buy else tick.bid
                if abs(cur - niv["prix"]) > CYCLE_TOLERANCE_PIPS * pip:
                    continue                  # pas encore revenu au point d'entrée

                # déjà une position sur ce symbole ? on n'empile pas
                if [p for p in (mt5.positions_get(symbol=niv["symbol"]) or [])
                        if p.magic in self.mt5.OWN_MAGICS]:
                    continue

                # ⚖️ «…» — on revérifie AVANT
                # de reprendre : la re-entrée n'est pas automatique.
                avis = await self.analyze_symbol(niv["symbol"])
                if not avis:
                    continue
                sens_ok = str(avis.get("action", "")).upper().startswith(
                    "BUY" if is_buy else "SELL")
                conf = float(avis.get("confidence", 0) or 0)
                if not sens_ok or conf < MIN_CONFIDENCE:
                    logger.info(f"🔁 {niv['symbol']} revenu à {niv['prix']} mais les "
                                f"signaux ont tourné (sens_ok={sens_ok}, conf={conf:.0f} "
                                f"< {MIN_CONFIDENCE:.0f}) — je ne reprends PAS")
                    niv["dernier"] = maintenant
                    continue

                ok = self.mt5.open_position(
                    niv["symbol"], niv["direction"], niv["volume"],
                    niv["sl"], niv["tp"], magic=self.mt5.MAGIC)
                niv["dernier"] = maintenant
                if ok:
                    niv["restant"] -= 1
                    logger.info(f"🔁 REPRISE {niv['symbol']} au point d'entrée "
                                f"{niv['prix']} (conf {conf:.0f}) — "
                                f"il reste {niv['restant']} reprise(s) sur ce niveau")
            except Exception as e:
                logger.error(f"guet retour {niv.get('symbol', '?')} : {e}")
        _CYCLE_NIVEAUX[:] = vivants

    async def analyze_symbol(self, symbol: str) -> Optional[Dict]:
        # (symbol arrive déjà RÉSOLU par connect()/get_real_symbol — l'ancien
        #  mt5_symbol recalculé ici ne servait à rien, supprimé 14/07)
        try:
            df = self.mt5.get_rates(symbol, TIMEFRAME, 250)
            if df.empty:
                return None

            if not self.candle_d.is_new_candle(symbol, df):
                if not self._oeil_express(symbol):
                    return None

            price      = float(df['close'].iloc[-1])
            indicators = self.ind_eng.calculate(df)

            # 🔬 MULTI-TF (09/07) : précision chirurgicale du scalp — la
            # tendance M15 sert de boussole, le M1 de gâchette fine.
            try:
                d15 = self.mt5.get_rates(symbol, mt5.TIMEFRAME_M15, 250)
                d1  = self.mt5.get_rates(symbol, mt5.TIMEFRAME_M1, 250)
                if not d15.empty and not d1.empty:
                    i15 = self.ind_eng.calculate(d15)
                    i1  = self.ind_eng.calculate(d1)
                    indicators['mtf'] = {
                        'm15_trend': i15.get('trend', 'NEUTRAL'),
                        'm15_rsi':   i15.get('rsi', 50),
                        'm1_rsi':    i1.get('rsi', 50),
                        'm1_macd':   i1.get('macd', 0),
                    }
            except Exception:
                pass

            crash, movement = self.crash_c.check(symbol, price)
            if crash:
                logger.warning(f"💥 Crash {symbol} — analyse suspendue")
                self.state.crash_detected = True
                return None
            else:
                self.state.crash_detected = False

            # 1. On récupère les news
            news_signal = self.news.get_signal(symbol)
            vrai_news_score = news_signal.score if news_signal else 50.0
            
            # 2. On sécurise MACD et Bollinger
            vrai_macd = indicators.get('macd', 0.0)
            vrai_bollinger_width = indicators.get('bollinger_width', 0.0)

            # 3. UN SEUL appel ML avec tous les paramètres !
            ml_signal = self.ml.predict(
    symbol          = symbol,
    rsi             = indicators['rsi'],
    ema_ratio       = indicators['ema_ratio'],
    atr             = indicators['atr'],
    macd            = indicators['macd'],  # ✅ Ajouté
    bollinger_width = indicators['bollinger_width'],  # ✅ Ajouté
    news_score      = vrai_news_score
)

            if ml_signal and ml_signal.blacklist:
                return None
            if news_signal and news_signal.blacklist:
                return None
            if ml_signal and ml_signal.signal_ea == "crucial":
                return None

            # 🎯 24/09 — LE DÉCLENCHEUR MÉCANIQUE, AVANT LA PORTE ML.
            # La porte ML (>= 90) est INATTEIGNABLE depuis que le serveur plafonne
            # à 70 : MAMMOUTH n'a pas tiré une seule fois depuis l'ouverture du
            # compte. Ici passe la seule règle qui tient le protocole complet
            # (voir signal_range_m30 en tête de fichier). Tous les garde-fous de
            # execute_trade s'appliquent ensuite : palier, cooldown, quotas,
            # veto COT, anti-tilt, kill switch journalier.
            rg = signal_range_m30(self.mt5, symbol)
            if rg and not RANGE_ACTIF:
                logger.info(f"👁️ RANGE (observation, aucun ordre) {symbol} {rg['sens']} · "
                            f"stop {rg['sl_pips']} pips · objectif {rg['tp_pips']} pips — {rg['raison']}")
                rg = None
            if rg:
                logger.info(f"🎯 RANGE {symbol} {rg['sens']} — {rg['raison']}")
                return {"action": "TRADE", "signal": rg["sens"], "confidence": 95.0,
                        "sl_pips": rg["sl_pips"], "tp_pips": rg["tp_pips"],
                        "source": "RANGE", "reason": rg["raison"],
                        "symbol": symbol, "price": price, "indicators": indicators}

            # 💰 Économie de tokens (06/07) : l'IA n'est consultée que si le ML
            # a une vraie conviction directionnelle (BUY/SELL avec confiance >=
            # MIN_CONFIDENCE). Bougie molle ou serveur ML éteint => skip direct,
            # zéro appel API. Coupe ~80-90% des appels Claude de la boucle.
            if (ml_signal is None
                    or ml_signal.direction in ("HOLD", "NEUTRAL")
                    or ml_signal.confidence < MIN_CONFIDENCE):
                return None

            decision = await self.mammouth.analyze_trade(
                symbol      = symbol,
                price       = price,
                indicators  = indicators,
                ml_signal   = ml_signal,
                news_signal = news_signal
            )

            decision['symbol']     = symbol
            decision['price']      = price
            decision['indicators'] = indicators

            return decision
        except Exception as e:
            self.em.add("TradingEngine", f"analyze_symbol error: {e}",
                        {"symbol": symbol})
            return None

    async def execute_trade(self, decision: Dict) -> bool:
        try:
            if decision.get('action') != 'TRADE':
                return False
            # 📅 WEEK-END (12/07) : samedi/dimanche = pas de nouvelle entrée
            # (la crypto reste ouverte mais le patron veut analyse seule).
            if datetime.now().weekday() >= 5:
                return False

            confidence = float(decision.get('confidence', 0))
            if confidence < MIN_CONFIDENCE:
                return False

            # 🕐 FILTRE HORAIRE (patron 04/08 : «…») : les
            # heures noires (7-8h Londres, 12-13h US/news, 20h clôture, WR 11-27%)
            # ne sont PLUS bloquées → on peut y entrer, MAIS seulement sur du béton :
            # confiance ≥ BAD_HOUR_MIN_CONF (90). Le reste du temps, seuil normal.
            if datetime.now().hour in BAD_HOURS and confidence < BAD_HOUR_MIN_CONF:
                logger.info(f"🕐 {datetime.now().hour}h = heure noire — entrée SEULEMENT si conf ≥ "
                            f"{BAD_HOUR_MIN_CONF:.0f} (là : {confidence:.0f}) → skip")
                return False

            # 🪜 04/09 — LE PALIER DE LE CERVEAU S'APPLIQUE AUSSI À MAMMOUTH.
            # (patron : «…»). LE CERVEAU écrit
            # dans oeil_context.json les marchés que le capital autorise
            # VRAIMENT (lot mini finançable). MAMMOUTH tradait son propre
            # univers sans regarder : trois bots, un compte, deux règles.
            _sym = decision.get('symbol', '')
            try:
                _ctxp = Path(__file__).resolve().parent / "oeil_context.json"
                _autor = None
                if _ctxp.exists() and time.time() - _ctxp.stat().st_mtime < 600:
                    _pal = json.loads(_ctxp.read_text(encoding="utf-8")).get("palier")
                    if isinstance(_pal, dict) and "symboles" in _pal:
                        _autor = list(_pal.get("symboles") or [])
                if _autor is None:
                    # 🪜 05/09 : LE CERVEAU absent ou périmé → MAMMOUTH calcule le palier LUI-MÊME (avant :
                    # «…»). Et une liste VIDE veut dire «…»,
                    # pas «…» — c'était lu à l'envers.
                    import paliers as _paliers
                    _autor = list(_paliers.palier(self.mt5.get_balance(), mt5).get("symboles") or [])
                if _sym not in _autor and get_real_symbol(_sym) not in _autor:
                    logger.info(f"🪜 {_sym} pas autorisé à ce palier "
                                f"({', '.join(_autor) or 'aucun marché finançable'}) — MAMMOUTH n'ouvre pas")
                    return False
            except Exception as _e:
                logger.warning(f"🪜 palier illisible ({_e}) — MAMMOUTH n'ouvre pas {_sym}")
                return False

            # 🧊 RÈGLE D'ACIER 1 : cooldown par symbole — le churn (ré-entrer
            # sans arrêt sur le même actif) = 94% des pertes historiques.
            _last = _symbol_cooldown.get(_sym, 0)
            if time.time() - _last < SYMBOL_COOLDOWN_MIN * 60:
                logger.info(f"🧊 {_sym} en cooldown — prochaine entrée possible dans "
                            f"~{int((SYMBOL_COOLDOWN_MIN * 60 - (time.time() - _last)) / 60) + 1} min")
                return False

            # 🛑 RÈGLE D'ACIER 3 : pause anti-tilt (armée par trading_loop dès
            # 3 pertes d'affilée — voir la revue 08/07) : ici on ne fait que
            # vérifier, en double sécurité du skip fait dans la boucle.
            if time.time() < _tilt_pause_until:
                return False
            if self.state.objectif_jour_atteint:     # 🏁 journée bouclée en gain
                return False

            # get_own_positions() (magic 777777 uniquement) : Mammouth dispose
            # de son propre quota, independamment de l'EA MQL5 (magic 20260613).
            # Quota DYNAMIQUE : 3 en regime normal, 6 en mode RESCUE (equity
            # sous la balance de reference du jour de plus de RESCUE_TRIGGER_PCT)
            # pour laisser le bot rattraper ses pertes. Le kill switch journalier
            # (DAILY_DRAWDOWN_LIMIT_PCT) reste le garde-fou final au-dessus.
            positions = self.mt5.get_own_positions()
            max_pos = MAX_POSITIONS
            try:
                acc = mt5.account_info()
                ref = self.state.daily_start_balance
                if acc and ref > 0:
                    dd_pct = (ref - acc.equity) / ref * 100.0
                    if dd_pct >= RESCUE_TRIGGER_PCT:
                        max_pos = MAX_POSITIONS_RESCUE
                        logger.info(f"🚑 Mode RESCUE ({dd_pct:.1f}% sous la référence du jour) "
                                    f"— quota étendu à {MAX_POSITIONS_RESCUE} positions")
            except Exception:
                pass
            if len(positions) >= max_pos:
                return False

            # 👑 13/07 soir : plafond GLOBAL compte entier (ŒIL+mammouth+EA) —
            # tout le monde trade en même temps, mais jamais plus de 16.
            if len(mt5.positions_get() or []) >= MAX_POSITIONS_COMPTE:
                logger.info(f"👑 Plafond global {MAX_POSITIONS_COMPTE} positions (compte entier) atteint — pas d'ouverture")
                return False

            signal = decision.get('signal', 'NEUTRAL')
            if signal not in ('BUY', 'SELL'):
                return False
            dump_tactique = False   # 🔓 posé par l'exception dump du veto COT

            # 🦎 MULTI-DIRECTIONNEL AUTORISÉ (24/07, patron : «…
            # …
            # …»). L'ancien HIVE MIND annulait tout scalp opposé
            # à une position ŒIL/EA déjà tenue ; c'est levé. On se contente
            # d'INFORMER (hedge/contre-position) sans jamais bloquer.
            try:
                for _p in (mt5.positions_get(symbol=decision['symbol']) or []):
                    if (20260000 <= _p.magic <= 20269999) or _p.magic == 999111:
                        _autre = "BUY" if _p.type == 0 else "SELL"
                        if _autre != signal:
                            logger.info(f"🦎 Multi-dir {decision['symbol']} : {_autre} déjà tenu "
                                        f"(magic {_p.magic}) — j'ouvre {signal} quand même (hedge/martingale patron)")
                        else:
                            logger.info(f"🤝 magic {_p.magic} déjà {_autre} sur {decision['symbol']} — on rejoint")
                        break
            except Exception:
                pass

            # 🐋 RÈGLE D'ACIER 4 : veto COT — ne JAMAIS trader contre un biais
            # institutionnel marqué (le sell-or contre COT acheteur a coûté
            # X € en 3 ans). Lecture du fichier écrit par LE CERVEAU.
            # ⚠️ ASSUMÉ : l'or étant structurellement net-long (>10% OI depuis des
            # années), les SELL GOLD# sont durablement interdits — c'est le but
            # («…»). Chaque refus est loggé «…».
            try:
                _ctx = Path(__file__).resolve().parent / "oeil_context.json"
                if _ctx.exists() and time.time() - _ctx.stat().st_mtime < 3600 * 24 * 8:
                    _cd = json.loads(_ctx.read_text(encoding="utf-8")).get("cot", {}).get(decision['symbol'])
                    # bias de cot_data = HAUSSIER/BAISSIER/NEUTRE → traduit en sens
                    _sens = {'HAUSSIER': 'BUY', 'BAISSIER': 'SELL'}.get((_cd or {}).get('bias'))
                    # fraîcheur du RAPPORT CFTC lui-même (pas du fichier, réécrit
                    # toutes les 5 min même si l'API CFTC est en panne)
                    _frais = True
                    try:
                        _rd = (_cd or {}).get('date', '')
                        if _rd:
                            _frais = (datetime.now() - datetime.strptime(_rd[:10], "%Y-%m-%d")).days <= 12
                    except Exception:
                        pass
                    if (_frais and _sens and _sens != signal
                            and abs(float(_cd.get('pct', 0))) >= COT_VETO_PCT):
                        # 🔓 EXCEPTION DUMP (14/07, patron : «…
                        # …» sur la chute de l'or) : momentum violent
                        # CONTRE le biais instit = scalp ENCADRÉ (lot mini +
                        # SL serré, appliqués plus bas) au lieu du refus sec.
                        # Conditions : tendance M15 opposée + RSI M5 extrême +
                        # MACD dans le sens du mouvement.
                        _ind = decision.get('indicators', {}) or {}
                        _mtf = _ind.get('mtf', {}) or {}
                        _rsi = float(_ind.get('rsi', 50) or 50)
                        _macd = float(_ind.get('macd', 0) or 0)
                        _m15 = _mtf.get('m15_trend', 'NEUTRAL')
                        if ((signal == 'SELL' and _m15 == 'BEARISH' and _rsi <= 35 and _macd < 0)
                                or (signal == 'BUY' and _m15 == 'BULLISH' and _rsi >= 65 and _macd > 0)):
                            dump_tactique = True
                            logger.info(f"🔓 Dump tactique {decision['symbol']} : {signal} contre COT "
                                        f"{_cd['bias']} ({_cd['pct']:+}%) — momentum validé, lot mini + SL serré")
                        else:
                            logger.info(f"🐋 Veto COT : {decision['symbol']} biais institutionnel "
                                        f"{_cd['bias']} ({_cd['pct']:+}% OI, rapport {_cd.get('date', '?')}) "
                                        f"— {signal} refusé")
                            return False
            except Exception:
                pass

            symbol    = decision['symbol']
            price     = decision['price']
            direction = Direction.BUY if signal == 'BUY' else Direction.SELL
            sl_pips   = int(decision.get('sl_pips', 20))
            tp_pips   = int(decision.get('tp_pips', 40))
            if dump_tactique:
                sl_pips = min(sl_pips, 12)   # 🔓 contre-COT = SL serré, pas de câlin

            pip = self.mt5.pip(symbol)

            if direction == Direction.BUY:
                sl = price - sl_pips * pip
                tp = price + tp_pips * pip
            else:
                sl = price + sl_pips * pip
                tp = price - tp_pips * pip

            # 🎯 Petit lot dynamique «…» (mode X €), plafonné à 2%
            volume = self.mt5.calculate_scalp_lot(symbol)
            if volume < 0.01:
                return False   # lot refusé (volume_min broker au-dessus des plafonds)
            # 🎚️ 13/07 soir, patron : le lot DYNAMIQUE ne s'active qu'à 95% de
            # confiance — en dessous, plancher 0.01, SAUF si le minimum broker
            # est plus haut (🏛️ exception indices : on s'aligne sur lui).
            if confidence < 95 and volume > 0.01:
                _i = mt5.symbol_info(symbol)
                _vmin = (_i.volume_min if _i else 0) or 0.01
                volume = round(max(0.01, _vmin), 2)
            if dump_tactique:   # 🔓 contre-COT = TOUJOURS lot mini (même à 95%+)
                _i = mt5.symbol_info(symbol)
                _vmin = (_i.volume_min if _i else 0) or 0.01
                volume = round(max(0.01, _vmin), 2)
            if decision.get('source') == "RANGE":
                # 🎯 24/09 : la règle a été MESURÉE au lot minimum (X € sur
                # 12 mois). Un lot dynamique changerait le risque sans qu'on
                # sache ce que ça vaut — on garde exactement ce qui est mesuré.
                _i = mt5.symbol_info(symbol)
                volume = round(max(0.01, (_i.volume_min if _i else 0) or 0.01), 2)

            tp1 = (price + (tp_pips / 2) * pip
                   if direction == Direction.BUY
                   else price - (tp_pips / 2) * pip)

            # 🏷️ 17/07 idee patron : un number par style — conviction (>=95%,
            # hors dump tactique) = swing 777999, tout le reste = scalp 777777.
            magic = (self.mt5.MAGIC_SWING
                     if (confidence >= 95 and not dump_tactique)
                     else self.mt5.MAGIC)
            ticket = self.mt5.open_position(
                symbol, direction, volume, sl, tp, magic=magic,
                # 🎯 24/09 : une entrée RANGE se reconnaît à son commentaire, et
                # c'est ce qui la fait échapper à la gestion (voir monitor_positions).
                comment=("MammouthV7_range" if decision.get('source') == "RANGE" else None))
            if ticket:
                pos_meta = Position(
                    ticket         = ticket,
                    symbol         = symbol,
                    direction      = direction,
                    entry_price    = price,
                    volume         = volume,
                    sl             = sl,
                    tp             = tp,
                    profit         = 0.0,
                    entry_time     = datetime.now(),
                    initial_volume = volume,
                    tp1            = tp1
                )
                self._pos_meta[ticket] = pos_meta
                self.state.last_trade_time = datetime.now()
                self.state.daily_trades   += 1
                _symbol_cooldown[symbol] = time.time()   # 🧊 arme le cooldown 15 min
                return True
            return False
        except Exception as e:
            self.em.add("TradingEngine", f"execute_trade error: {e}")
            return False

    def _check_daily_reset(self):
        """Réinitialise les compteurs journaliers et capture la balance de référence
        au premier passage de la journée (utilisée pour calculer le drawdown %)."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.current_trading_day != today:
            _bal = self.mt5.get_balance()
            if _bal <= 0:   # 🩸 05/09 : MT5 débranché → on réessaie au tour suivant (avant : référence 0 = garde-fous morts jusqu'à minuit)
                logger.warning("⚠️ balance illisible au changement de jour — référence reportée au tour suivant")
                return
            self.state.current_trading_day   = today
            self.state.daily_start_balance   = _bal
            self.state.depots_ref            = self._depots_du_jour()
            self.state.daily_profit          = 0.0
            self.state.daily_trades          = 0
            self.state.consecutive_losses    = 0
            self.state.kill_switch_triggered = False
            self.state.objectif_jour_atteint = False
            logger.info(f"🔄 Nouveau jour de trading — balance de référence: "
                        f"{self.state.daily_start_balance:.2f}")

    def check_daily_drawdown(self) -> bool:
        """KILL SWITCH — si l'equity chute de plus de DAILY_DRAWDOWN_LIMIT_PCT % par
        rapport à la balance de début de journée, on ferme TOUT et on bloque le
        trading jusqu'au lendemain. Retourne True si le kill switch est actif."""
        self._check_daily_reset()

        if self.state.kill_switch_triggered:
            try:   # 🩸 05/09 : ce que close_all n'a pas pu fermer (marché en pause) est retenté à chaque tour
                if self.mt5.get_own_positions():
                    self.mt5.close_all_positions()
            except Exception:
                pass
            return True

        if self.state.daily_start_balance <= 0:
            return False

        equity = self.mt5.get_equity()
        # 🛡️ Anti-faux-positif (09/07) : equity à 0 = MT5 momentanément
        # DÉBRANCHÉ (redémarrage du terminal…), PAS un compte ruiné. Avant,
        # ça déclenchait un kill switch «…» fantôme.
        if equity <= 0:
            logger.warning("⚠️ Equity illisible (MT5 déconnecté ?) — kill switch suspendu ce tour")
            return self.state.kill_switch_triggered
        # 🔧 04/08 (patron «…») : la limite NORMALE compte les pertes
        # RÉALISÉES (balance), plus le flottant — le panier assumé du CERVEAU
        # (risque 10%, magic 999111) gelait MAMMOUTH au démarrage («…
        # …» alors que RIEN n'était perdu). Garde-fou d'URGENCE conservé :
        # équity -25% (vrai crash) → on coupe quand même.
        start = self._reference_jour()
        if start <= 0:
            return False
        balance = self.mt5.get_balance()
        try:   # 🩸 05/09 : l'urgence -25 % ne regarde QUE le flottant de MAMMOUTH — avant, l'equity du
               # compte entier : 14 des 40 kill switch du journal à «…» à cause des positions ŒIL/EA
            _flottant = sum(float(getattr(p, "profit", 0.0) or 0.0) for p in self.mt5.get_own_positions())
        except Exception:
            _flottant = equity - balance
        drawdown_pct = ((start - balance) / start) * 100.0
        equity_dd_pct = ((start - (balance + _flottant)) / start) * 100.0

        if drawdown_pct >= DAILY_DRAWDOWN_LIMIT_PCT or equity_dd_pct >= 25.0:
            closed = self.mt5.close_all_positions()
            self.state.kill_switch_triggered = True
            logger.error(
                f"🛑 KILL SWITCH DÉCLENCHÉ — drawdown journalier {drawdown_pct:.1f}% "
                f"(limite {DAILY_DRAWDOWN_LIMIT_PCT}%) — {closed} position(s) fermée(s)"
            )
            self.em.add("KillSwitch",
                         f"Drawdown journalier {drawdown_pct:.1f}% — fermeture totale",
                         {"equity": equity,
                          "daily_start_balance": self.state.daily_start_balance,
                          "positions_closed": closed})
            return True

        return False

    def _depots_du_jour(self) -> float:
        """💶 Somme des mouvements de caisse (dépôt +, retrait −) depuis minuit local."""
        try:
            minuit = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            deals = mt5.history_deals_get(minuit, datetime.now() + timedelta(days=1)) or []
            return float(sum(d.profit for d in deals if d.type == mt5.DEAL_TYPE_BALANCE))
        except Exception:
            return 0.0

    def _reference_jour(self) -> float:
        """🩸 05/09 — LA balance de début de journée. D'abord celle de budget_risque.json (ancrée
        par LE CERVEAU au premier passage du jour, recalée des dépôts/retraits par ajuster_depots) :
        elle survit à nos redémarrages — avant, chaque restart remettait le compteur de perte à
        zéro. Sinon la nôtre, corrigée des dépôts vus depuis sa capture (un dépôt n'est pas un
        gain, un retrait pas une perte). Jamais le statut du compte : juste des euros."""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            import budget_risque as _budget
            # 🩹 08/09 — UN DÉPÔT N'EST PAS UN GAIN. La référence de budget_risque est
            # figée au changement de jour ; si le patron recharge ensuite, elle reste
            # sur l'ancien solde. Mesuré ce matin :X € de référence contre X €
            # de balance après une recharge de X € = «…»,
            # et MAMMOUTH s'est bouclé pour la journée sans passer un ordre.
            # ajuster_depots répercute les mouvements de caisse sur la référence et
            # ne compte chaque mouvement QU'UNE FOIS (il suit caisse_vue).
            try:
                _budget.ajuster_depots(mt5)
            except Exception:
                pass
            d = _budget._lire()
            ref = float(d.get("solde_debut") or 0.0)
            if d.get("jour") == today and ref > 0:
                return ref
        except Exception:
            pass
        base = float(self.state.daily_start_balance or 0.0)
        if base <= 0:
            return 0.0
        return base + (self._depots_du_jour() - float(self.state.depots_ref or 0.0))

    def _entree_autorisee(self) -> bool:
        """🩸 05/09 — UNE porte pour TOUTES les ouvertures (execute_trade, _reopen_like, _guetter_retour).
        Avant, l'échelle et le cycle rouvraient pendant l'anti-tilt, le kill switch, la pause,
        le crash ou la journée bouclée."""
        if self.state.kill_switch_triggered or self.state.objectif_jour_atteint:
            return False
        if not self.state.auto_trade or self.state.paused or self.state.crash_detected:
            return False
        if time.time() < _tilt_pause_until:
            return False
        if datetime.now().weekday() >= 5:
            return False
        return True

    def journee_bouclee(self) -> bool:
        """🏁 05/09 — LA JOURNÉE EST GAGNÉE, ON ARRÊTE D'OUVRIR (patron : «…
        …
        …»). Miroir du kill switch : lui coupe à −10 %, ici on
        boucle à +OBJECTIF_JOUR_PCT %. Les positions ouvertes gardent leur
        gestion (mode X €, BE, trailing) — on n'entre plus, c'est tout.
        Mesuré sur la BALANCE (gains réalisés), jamais sur le statut du compte."""
        self._check_daily_reset()
        if self.state.objectif_jour_atteint:
            return True
        start = self._reference_jour()
        if start <= 0:
            return False
        balance = self.mt5.get_balance()
        if balance <= 0:                      # MT5 débranché : on ne conclut rien
            return False
        gain_eur = balance - start
        gain_pct = gain_eur / start * 100.0
        if OBJECTIF_JOUR_EUR and OBJECTIF_JOUR_EUR > 0:
            atteint, cible = gain_eur >= OBJECTIF_JOUR_EUR, f"{OBJECTIF_JOUR_EUR:.0f}€"
        else:
            atteint, cible = gain_pct >= OBJECTIF_JOUR_PCT, f"{OBJECTIF_JOUR_PCT:g}%"
        if atteint:
            self.state.objectif_jour_atteint = True
            logger.info(f"🏁 OBJECTIF DU JOUR ATTEINT ({cible}) : {gain_eur:+.2f}€ / {gain_pct:+.1f}% "
                        f"({start:.2f} → {balance:.2f}) — plus d'entrée jusqu'à demain, "
                        f"la gestion des positions continue")
            try:
                self.em.add("ObjectifJour",
                            f"Journée bouclée à {gain_eur:+.2f}€ ({gain_pct:+.1f}%) — plus d'entrée",
                            {"balance": balance, "daily_start_balance": start})
            except Exception:
                pass
            return True
        return False

    async def monitor_positions(self):
        try:
            # get_own_positions() (magic=777777) et non get_positions() : la
            # gestion active (breakeven/trailing/partial TP/stop max perte)
            # ne doit toucher QUE les positions ouvertes par Mammouth, pas
            # celles de l'EA MQL5 qui tourne en parallele sur le meme compte.
            raw_positions = self.mt5.get_own_positions()
            positions     = self._enrich_positions(raw_positions)

            for pos in positions:
                # 🎯 24/09 — ON NE TOUCHE PAS AUX POSITIONS «…».
                # Trouvé à la relecture : toute la gestion de MAMMOUTH (BE,
                # trailing, partiels, échelle, et surtout la coupe rapide
                # IMMÉDIATE à 60-70 pips qui ignore le stop réel) ferait sortir
                # ces positions bien avant leur stop ou leur objectif 4 R. Sur
                # BTC, où 1 pip = 1 $, un simple recul de 60 $ les coupait vers
                # 0,1 R : le X € mesuré n'aurait jamais pu se produire, et
                # trois coupes de ce genre déclenchent la pause anti-tilt d'1 h.
                # Elles vivent donc avec leur stop et leur objectif, comme les
                # positions RETOUR du cerveau, exactement comme mesuré au banc.
                if "range" in (pos.comment or "").lower():
                    continue
                self.spm.manage(pos)                 # partial TP + BE + trailing (runners)
                self._pos_meta[pos.ticket] = pos

                pip           = self.mt5.pip(pos.symbol)
                info          = mt5.symbol_info(pos.symbol)
                contract_size = info.trade_contract_size if info else 100000
                value_per_pip = pos.volume * contract_size * pip
                gain_pips     = (pos.profit / value_per_pip) if value_per_pip > 0 else 0
                try:
                    _atrq = self.mt5.calculate_atr(pos.symbol) / pip if pip else 0.0
                except Exception:
                    _atrq = 0.0
                # 🩸 05/09 : le seuil «…» suit l'ATR (1,5×) — sinon sur l'or/BTC (ATR ≫ 20 pips)
                # la fenêtre du mode X € (0,8×ATR) n'existait jamais : que la coupe à X €, jamais le gain
                _runner_pips  = max(RUNNER_PIPS, 1.5 * _atrq)
                runner        = (pos.be_activated or pos.trail_activated
                                 or gain_pips >= _runner_pips or pos.flowrider)   # 🐘 FlowRider = runner

                # 🪜 ÉCHELLE DE SORTIE PAR SYMBOLE (patron 21/07) — vaut pour TOUS
                # les trades, même FlowRider : à reentry_pips on encaisse le
                # monstre et on repart frais ; tous les partial_pips un partiel.
                _lad_part, _lad_reentry = ladder_levels(pos.symbol)
                if gain_pips >= _lad_reentry:
                    if self.mt5.close_position(pos.ticket):
                        logger.info(f"🪜 +{gain_pips:.0f} pips → CLÔTURE & reprise directe #{pos.ticket} {pos.symbol}")
                        self.state.consecutive_losses = 0
                        _pos_seen.pop(pos.ticket, None)
                        await self._reopen_like(pos)
                    continue
                _rung = int(gain_pips // _lad_part)
                if _rung > pos.ladder_rungs and gain_pips >= _lad_part:
                    _info = mt5.symbol_info(pos.symbol)
                    _vmin = (_info.volume_min if _info else 0) or 0.01
                    _part = round(pos.volume * LADDER_PARTIAL_FRAC, 2)
                    if _part >= _vmin and (pos.volume - _part) >= _vmin - 1e-9:
                        if self.mt5.close_partial(pos.ticket, _part):
                            pos.ladder_rungs = _rung
                            logger.info(f"🪜 TP partiel palier {_rung}×{_lad_part}p #{pos.ticket} {pos.symbol} vol={_part}")
                    else:
                        pos.ladder_rungs = _rung   # lot trop petit pour un partiel → on marque le palier

                # ⚡ MODE X € : petit gain certain encaissé vite — SAUF runner
                # (gros mouvement > 20 pips) que BE/trailing laissent courir.
                # 🧊 RÈGLE D'ACIER 2 : jamais d'encaissement avant MIN_HOLD_MIN
                # minutes de vie (les sorties <5 min = 25.8% de WR historique) ;
                # les coupes de PERTE, elles, restent immédiates : protection d'abord.
                _pos_seen.setdefault(pos.ticket, time.time())
                assez_vieux = time.time() - _pos_seen[pos.ticket] >= MIN_HOLD_MIN * 60
                # 🩸 04/09 — LE MODE X € N'ENCAISSE PLUS DANS LE BRUIT. Avant :
                # X € et 3 pips suffisaient (3 pips = 0,02 ATR sur l'or). Et
                # X € de gain contre X € de perte au backstop = ratio 0,33 par
                # construction — mesuré ce soir : 0 à 1% de configs rentables
                # dans cette famille. Deux gardes : au moins 0,8×ATR de gain,
                # et un gain jamais inférieur à la perte maximale (ratio ≥ 1).
                _mini_pips = max(QUICK_TP_MINPIPS, 0.8 * _atrq)
                _mini_eur  = max(QUICK_TP_EUR, QUICK_SL_EUR)
                if not runner and assez_vieux and pos.profit >= _mini_eur and gain_pips >= _mini_pips:
                    if self.mt5.close_position(pos.ticket):
                        logger.info(f"⚡ +{pos.profit:.2f}€ encaissé (mode 1€) #{pos.ticket} {pos.symbol}")
                        self.state.consecutive_losses = 0   # 🛑 un gain casse la série anti-tilt
                        _pos_seen.pop(pos.ticket, None)
                    continue

                # ✂️ Coupe rapide : perte plafonnée à ~X € (proportionnel au
                # petit lot, anti-spread 3 pips) OU backstop dur à 15 pips.
                # 🧊 Revue 08/07 : la coupe à l'euro respecte AUSSI le min-hold
                # (sinon la fenêtre 0-5 min ne pouvait sortir QU'EN perte —
                # asymétrie qui transformait des gains en pertes). Le backstop
                # 15 pips, lui, reste IMMÉDIAT : protection d'abord.
                # 🐘 FlowRider : PAS de coupe rapide (le SL rail gère la sortie)
                if not pos.flowrider and pos.profit < 0 and (
                        (assez_vieux and pos.profit <= -QUICK_SL_EUR and -gain_pips >= QUICK_SL_MINPIPS)
                        or -gain_pips >= quick_sl_pips(pos.symbol)):
                    logger.info(f"✂️ {pos.profit:.2f}€ coupé à {abs(gain_pips):.0f} pips #{pos.ticket}")
                    if self.mt5.close_position(pos.ticket):
                        self.state.consecutive_losses += 1
                        _pos_seen.pop(pos.ticket, None)

            # 🧹 purge de _pos_seen : les tickets fermés autrement (SL broker,
            # partial TP, LE CERVEAU, kill switch…) ne doivent pas s'accumuler à vie
            _actifs = {pos.ticket for pos in positions}
            for _t in list(_pos_seen):
                if _t not in _actifs:
                    _pos_seen.pop(_t, None)

        except Exception as e:
            self.em.add("TradingEngine", f"monitor_positions error: {e}")

    async def _reopen_like(self, old: Position):
        """🪜 Réouvre immédiatement une position même sens/symbole après une
        clôture à LADDER_REENTRY_PIPS (SL au plancher de classe, TP large).
        Pas d'augmentation nette d'exposition : on ferme une, on rouvre une."""
        if not self._entree_autorisee():
            logger.info(f"🪜 {old.symbol} : pas de réouverture (pause / kill / objectif / anti-tilt / week-end)")
            return
        try:
            tick = mt5.symbol_info_tick(old.symbol)
            if not tick:
                return
            pip    = self.mt5.pip(old.symbol)
            is_buy = old.direction == Direction.BUY
            price  = tick.ask if is_buy else tick.bid
            sl_d   = quick_sl_pips(old.symbol) * pip
            sl     = price - sl_d if is_buy else price + sl_d
            _reentry = ladder_levels(old.symbol)[1]
            tp     = (price + _reentry * pip if is_buy
                      else price - _reentry * pip)
            vol    = min(old.initial_volume or 0.01, MAX_LOT_HARD)
            ticket = self.mt5.open_position(old.symbol, old.direction, vol, sl, tp)
            if ticket:
                logger.info(f"🪜↻ Reprise {old.symbol} {old.direction.value} vol={vol} @ {price:.5f}")
                self._pos_meta[ticket] = Position(
                    ticket=ticket, symbol=old.symbol, direction=old.direction,
                    entry_price=price, volume=vol, sl=sl, tp=tp, profit=0.0,
                    entry_time=datetime.now(), initial_volume=vol)
                _pos_seen[ticket] = time.time()
        except Exception as e:
            self.em.add("TradingEngine", f"reopen error: {e}")

    def _check_oeil_commands(self):
        """Applique les ordres de pilotage envoyés par LE CERVEAU (ia_watchdog.py)
        via oeil_commands.json : autotrade on/off/toggle, pause, emergency."""
        f = Path(__file__).resolve().parent / "oeil_commands.json"
        try:
            if not f.exists():
                return
            cmd = json.loads(f.read_text(encoding="utf-8"))
            f.unlink()  # consommé une seule fois
            # 🩹 08/09 — UNE COMMANDE PÉRIMÉE NE S'APPLIQUE PAS. LE CERVEAU horodate
            # (cmd_to_python pose "ts"), MAMMOUTH ne regardait pas : un «…
            # …» écrit hier soir se déclenchait au démarrage du lendemain, sans
            # que personne ne l'ait demandé ce jour-là. L'arrêt d'urgence, lui,
            # reste toujours valable : dans le doute on s'arrête, on ne démarre pas.
            _age = time.time() - float(cmd.get("ts") or 0)
            if _age > 600 and not cmd.get("emergency"):
                logger.info(f"👁️→🐍 commande ignorée : {int(_age/60)} min d'âge "
                            f"(plus de 10 min) — {cmd}")
                return
            if "autotrade" in cmd:
                v = cmd["autotrade"]
                self.state.auto_trade = (not self.state.auto_trade) if v == "toggle" else bool(v)
                self.state.paused = False
                logger.info(f"👁️→🐍 LE CERVEAU règle auto-trade = {self.state.auto_trade}")
            if cmd.get("paused") is not None:
                self.state.paused = bool(cmd["paused"])
                logger.info(f"👁️→🐍 LE CERVEAU règle pause = {self.state.paused}")
            if cmd.get("emergency"):
                self.state.auto_trade = False
                self.state.paused = True
                logger.warning("👁️→🐍 LE CERVEAU déclenche l'arrêt d'urgence du bot Python")
        except Exception as e:
            self.em.add("TradingEngine", f"_check_oeil_commands error: {e}")

    def _deposer_etat(self):
        """🦣 04/09 — MAMMOUTH DIT CE QU'IL FAIT (patron : «…
        …»). Jusqu'ici LE CERVEAU ne savait rien de
        lui : ni ses positions, ni s'il était en pause anti-tilt. Il dépose
        son état ici, LE CERVEAU le lit et le donne à son cerveau. Zéro token."""
        try:
            pos = []
            for p in (mt5.positions_get() or []):
                if p.magic not in self.mt5.OWN_MAGICS:   # 🩹 16/09 : self.MAGIC n'existe pas ici (AttributeError avalé → état figé dès la 1re position)
                    continue
                pos.append({"symbol": p.symbol, "sens": "BUY" if p.type == 0 else "SELL",
                            "lot": p.volume, "pnl": round(p.profit, 2),
                            "sl": p.sl, "tp": p.tp, "ticket": p.ticket})
            etat = {"ts": time.time(), "auto_trade": bool(self.state.auto_trade),
                    "paused": bool(self.state.paused),
                    "pertes_consecutives": int(self.state.consecutive_losses),
                    "tilt_jusqua": float(globals().get("_tilt_pause_until", 0) or 0),
                    "objectif_jour": bool(self.state.objectif_jour_atteint),
                    "positions": pos}
            (Path(__file__).resolve().parent / "mammouth_etat.json").write_text(
                json.dumps(etat), encoding="utf-8")
        except Exception as e:
            logger.debug(f"depot etat mammouth : {e}")

    def _poser_fiche(self):
        """📋 16/09 — LA FICHE DE MAMMOUTH SUR LE TABLEAU.

        Idee du patron : «…
        …»

        Ce que lui seul sait : s'il est en pause, s'il est en tilt, combien de
        pertes il enchaine. Le cerveau lisait deja mammouth_etat.json, mais ce
        fichier n'etait pas HORODATE : un mammouth plante laissait son dernier
        etat passer pour l'etat du moment. Une fiche dit toujours son age."""
        try:
            import tableau
            tableau.ecrire(
                "mammouth",
                paused=bool(self.state.paused),
                auto_trade=bool(self.state.auto_trade),
                pertes_consecutives=int(self.state.consecutive_losses),
                objectif_jour=bool(self.state.objectif_jour_atteint),
                tilt=bool(float(globals().get("_tilt_pause_until", 0) or 0)
                          > time.time()),
                positions=len([1 for _p in (mt5.positions_get() or [])
                               if _p.magic in self.mt5.OWN_MAGICS]),   # 🩹 16/09 : idem
            )
        except Exception:
            pass

    async def trading_loop(self):
        logger.info("🚀 Trading loop démarré")
        while True:
            try:
                # Ordres de pilotage du CERVEAU (la seule voix Telegram)
                self._check_oeil_commands()
                self._deposer_etat()          # 🦣 04/09 : LE CERVEAU sait ce que je fais
                self._poser_fiche()           # 📋 16/09 : sa fiche sur le tableau

                # Kill switch drawdown journalier — tourne en continu, même si
                # auto_trade est coupé, pour rester à jour dès la reprise.
                if self.check_daily_drawdown():
                    await asyncio.sleep(60)
                    continue

                if not self.state.auto_trade or self.state.paused:
                    await self.monitor_positions()   # 🩸 05/09 : en pause on n'OUVRE pas, mais on GÈRE
                    await asyncio.sleep(10)
                    continue

                # 🛑 RÈGLE D'ACIER 3 (revue 08/07) : 3 pertes d'affilée → pause
                # anti-tilt de TILT_PAUSE_MIN sur les NOUVELLES entrées seulement.
                # (Avant : sleep(600) qui gelait AUSSI mode X €/BE/trailing —
                # les positions ouvertes restaient sans gestion pendant 10 min.)
                global _tilt_pause_until
                if self.state.consecutive_losses >= TILT_LOSSES:
                    _tilt_pause_until = time.time() + TILT_PAUSE_MIN * 60
                    self.state.consecutive_losses = 0
                    logger.warning(f"🛑 {TILT_LOSSES} pertes d'affilée — pause anti-tilt "
                                   f"{TILT_PAUSE_MIN} min (la gestion des positions continue)")

                if self.state.crash_detected:
                    # 🩸 05/09 : avant, sleep(300) + continue SANS gestion, et crash_detected n'était
                    # remis à False que par analyze_symbol… jamais atteint depuis ici → gel définitif.
                    if not self.state.crash_pause_until:
                        self.state.crash_pause_until = time.time() + 300
                    await self.monitor_positions()
                    if time.time() >= self.state.crash_pause_until:
                        self.state.crash_detected = False
                        self.state.crash_pause_until = 0.0
                        logger.info("💥 pause crash terminée — reprise de l'analyse")
                    else:
                        await asyncio.sleep(30)
                        continue

                if self.journee_bouclee():
                    await self.monitor_positions()
                    await asyncio.sleep(30)
                    continue

                for symbol in SYMBOLS:
                    # 🧊/🛑 règles d'acier vérifiées AVANT l'analyse : pas d'appel
                    # IA payant pour un trade refusé d'avance (revue 08/07)
                    if time.time() < _tilt_pause_until:
                        break
                    if time.time() - _symbol_cooldown.get(symbol, 0) < SYMBOL_COOLDOWN_MIN * 60:
                        continue
                    decision = await self.analyze_symbol(symbol)
                    if decision:
                        await self.execute_trade(decision)
                    await asyncio.sleep(5)   # 🚦 29/07 : 1s->5s entre symboles (la rafale declenchait le 429)

                await self.monitor_positions()
                # 🔁 21/08 : le prix est-il revenu sur un point d'entrée
                # encaissé ? Si oui et si les signaux tiennent, on remet ça.
                await self._guetter_retour()
                await asyncio.sleep(30)

            except Exception as e:
                self.em.add("TradingEngine", f"trading_loop error: {e}")
                await asyncio.sleep(10)

# ============================================================================
# 🤖 TELEGRAM BOT — SUPPRIMÉ le 14/07 (audit patron : «…»).
#    ~600 lignes jamais lancées depuis que LE CERVEAU est la seule voix Telegram
#    (12/07). Le code complet vit dans l'historique git si besoin.
# ============================================================================

# ============================================================================
# 🚀 MAIN BOT CLASS
# ============================================================================

class MammouthBotV7:
    def __init__(self):
        self.em       = ErrorMemory()
        self.state    = BotState()
        # 🔒 14/09 — on passe des identifiants VIDES : MT5Connector se branche
        # alors sur le terminal DEJA connecte au lieu de forcer un compte.
        # Sinon, basculer MT5 en demo ne servait a rien : a la premiere
        # coupure, il reloggait le patron sur le compte REEL.
        self.mt5_conn = MT5Connector(0, "", "", self.em)
        self.mammouth = MammouthAI(ANTHROPIC_API_KEY, self.em, model=AI_MODEL)
        self.ml       = MLClient(ML_SERVER_URL,   self.em)
        self.news     = NewsClient(NEWS_SERVER_URL, self.em)
        self.telegram = None
        self.engine   = None

    async def _check_servers(self):
        ml_ok   = self.ml.health()
        news_ok = self.news.health()
        logger.info(f"🖥️  ML Server   : {'✅ OK' if ml_ok   else '⚠️  OFFLINE'}")
        logger.info(f"📰 News Server : {'✅ OK' if news_ok else '⚠️  OFFLINE'}")
        if not ml_ok:
            self.em.add("Main", "ML Server offline au démarrage")
        if not news_ok:
            self.em.add("Main", "News Server offline au démarrage")

    async def run(self):
        logger.info("=" * 65)
        logger.info("🦣  MAMMOUTH BOT COMPLETE V7 — DÉMARRAGE")
        logger.info("=" * 65)

        # 🕰️ 05/08 : PATIENT au démarrage — avant, un seul échec (MT5 encore en
        # train de booter lors d'un «…») = abandon définitif du
        # process. On réessaie toutes les 10 s pendant 3 min avant de renoncer.
        _essais = 0
        while not self.mt5_conn.connect():
            _essais += 1
            if _essais >= 18:
                logger.error("❌ Connexion MT5 impossible après 3 min — abandon")
                return
            logger.info(f"⏳ MT5 pas prêt (essai {_essais}/18) — nouvelle tentative dans 10 s…")
            await asyncio.sleep(10)

        await self._check_servers()

        # 👁️ TELEGRAM DÉPORTÉ DANS LE CERVEAU (ia_watchdog.py) — le bot Python ne
        # parle plus sur Telegram. Il garde tout son cerveau
        # (MammouthAI.analyze_trade) et son moteur de trading, et obéit aux
        # ordres du CERVEAU via le pont oeil_commands.json. (Classe TelegramBot
        # supprimée le 14/07 — audit «…», voir git.)

        self.engine = AutoTradingEngine(
            self.mt5_conn, self.mammouth,
            self.ml, self.news,
            self.state, self.em
        )

        balance = self.mt5_conn.get_balance()
        logger.info(f"🦣 Bonjour ! MAMMOUTH V7 en ligne — balance ${balance:.2f}. "
                    f"Telegram géré par LE CERVEAU. Auto-trade piloté à distance.")

        # 🕐 RÈGLES DE TIR AU DÉMARRAGE (14/07, patron : «…
        # …») — plus de mystère sur qui peut tirer quand.
        logger.info("🕐 HORAIRES & RÈGLES DE TIR :")
        logger.info(f"   • Heures noires {', '.join(f'{h}h' for h in sorted(BAD_HOURS))} (WR 11-27%) : "
                    f"entrée SEULEMENT si conf ≥ {BAD_HOUR_MIN_CONF:.0f} — reste du temps, tir normal")
        logger.info("   • Week-end (sam/dim) : analyse seule, aucune entrée")
        logger.info(f"   • Cooldown {SYMBOL_COOLDOWN_MIN} min/symbole · quota {MAX_POSITIONS} pos "
                    f"(rescue {MAX_POSITIONS_RESCUE}) · plafond compte {MAX_POSITIONS_COMPTE} · "
                    f"lot max {MAX_LOT_HARD:g} (min broker accepté jusqu'à 0.10)")
        try:
            _cot = json.loads((Path(__file__).resolve().parent / "oeil_context.json")
                              .read_text(encoding="utf-8")).get("cot", {})
            gel = []
            for _s, _d in _cot.items():
                _interdit = {"HAUSSIER": "SELL", "BAISSIER": "BUY"}.get(_d.get("bias"))
                if _interdit and abs(float(_d.get("pct", 0))) >= COT_VETO_PCT:
                    gel.append(f"{_s} {_interdit} interdit ({_d['bias']} {_d['pct']:+}%)")
            if gel:
                logger.info("   • Veto COT du moment (s'efface sur DUMP TACTIQUE validé) : "
                            + " | ".join(gel))
            else:
                logger.info("   • Veto COT : aucun biais fort — toutes directions ouvertes")
        except Exception:
            logger.info("   • Veto COT : contexte indisponible (oeil_context.json)")

        try:
            await self.engine.trading_loop()
        except KeyboardInterrupt:
            logger.info("🛑 Arrêt demandé")
        except Exception as e:
            self.em.add("Main", f"Erreur fatale: {e}")
            logger.critical(f"💀 Erreur fatale: {e}")
        finally:
            mt5.shutdown()
            logger.info("👋 MT5 déconnecté — au revoir")

# ============================================================================
# 🏁 ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        bot = MammouthBotV7()
        asyncio.run(bot.run())
    except Exception as e:
        print(f"ERREUR: {e}")
        input("Appuie sur ENTREE pour fermer...")
