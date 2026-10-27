# -*- coding: utf-8 -*-
# =====================================================
#  ACID BOT — Dashboard Server v1.0
#  Sert la page web + agrège les données réelles :
#   - MT5 (compte, positions, historique, symboles XM)
#   - Serveur ML   (127.0.0.1:8001)
#   - Serveur News (127.0.0.1:5001)
#   - Bot Telegram (heartbeat via mammouth_v7.log + getMe)
#   - Avis IA (Anthropic, même clé que le bot)
# =====================================================
import re
import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

import requests
from flask import Flask, jsonify, request, send_file, redirect

try:
    import MetaTrader5 as mt5
    # 20/07 : réinstall MT5 -> initialize() sans path ne retrouve plus le
    # terminal. Chemin injecté pour tout initialize() (voir ia_watchdog.py).
    _MT5_EXE = r"C:\Program Files\Vantage Markets MT5 Terminal\terminal64.exe"
    _mt5_init_brut = mt5.initialize
    def _mt5_init_chemin(*a, **k):
        if not a and "path" not in k:
            k["path"] = _MT5_EXE
        return _mt5_init_brut(*a, **k)
    mt5.initialize = _mt5_init_chemin
except ImportError:
    mt5 = None

# =====================================================
# CONFIG — les secrets sont lus dans le fichier du bot
# (une seule source de vérité, rien n'est dupliqué ici)
# =====================================================
HERE      = Path(__file__).resolve().parent
BOT_DIR   = HERE.parent
BOT_FILE  = BOT_DIR / "BOT_MAMMOUTH_COMPLETE_V7.py"
BOT_LOG   = BOT_DIR / "mammouth_v7.log"

# 🧮 compteur de tokens partagé (14/07) — module dans le dossier du bot
import sys
sys.path.insert(0, str(BOT_DIR))
try:
    from token_meter import compte as compte_tokens, jour_courant as tokens_du_jour
except Exception:
    compte_tokens = lambda *a, **k: None
    tokens_du_jour = lambda: {}

ML_URL    = "http://127.0.0.1:8001"
NEWS_URL  = "http://127.0.0.1:5001"
PORT      = 8050

def _parse_bot_const(name, default=None):
    """Lit une constante : d'abord le 🔐 coffre (secrets_acid.py, hors git),
    puis le fichier du bot (config non secrète) — refonte du 09/07."""
    for f in (BOT_DIR / "secrets_acid.py", BOT_FILE):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(rf'^\s*{name}\s*=\s*["\']?([^"\'\n#]+)', src, re.M)
            if m:
                return m.group(1).strip()
        except Exception:
            continue
    return default

TELEGRAM_TOKEN    = _parse_bot_const("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = _parse_bot_const("ANTHROPIC_API_KEY")
AI_MODEL          = _parse_bot_const("AI_MODEL", "claude-haiku-4-5-20251001")
MT5_LOGIN         = _parse_bot_const("MT5_LOGIN")
MT5_PASSWORD      = _parse_bot_const("MT5_PASSWORD")
MT5_SERVER        = _parse_bot_const("MT5_SERVER")
# 🚪 14/07 : le dashboard suit la MÊME chaîne de secours que LE CERVEAU —
# mammouth (forfait) → Anthropic (payant) → Mistral direct. Fini le bouton
# «…» qui pleure «…» alors que le forfait vit.
MAMMOUTH_API_KEY  = _parse_bot_const("MAMMOUTH_API_KEY")
MAMMOUTH_URL      = _parse_bot_const("MAMMOUTH_ENDPOINT", "https://api.mammouth.ai/v1/chat/completions")
MISTRAL_API_KEY   = _parse_bot_const("MISTRAL_API_KEY")
MISTRAL_URL       = _parse_bot_const("MISTRAL_ENDPOINT", "https://api.mistral.ai/v1/chat/completions")
MISTRAL_MODEL     = _parse_bot_const("MISTRAL_MODEL", "mistral-large-latest")

def ask_ai_chain(prompt: str, max_tokens: int = 700):
    """Renvoie (texte, moteur) via la 1re porte qui répond ; lève la dernière
    erreur si les trois sont fermées. mammouth exige max_tokens >= 16."""
    derniere = None
    if MAMMOUTH_API_KEY:
        try:
            r = requests.post(MAMMOUTH_URL,
                              headers={"Authorization": f"Bearer {MAMMOUTH_API_KEY}",
                                       "Content-Type": "application/json"},
                              json={"model": "gpt-5.4-mini", "max_tokens": max(16, max_tokens),
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=45)
            r.raise_for_status()
            data = r.json()
            compte_tokens("gpt-5.4-mini", data.get("usage") or {}, "dashboard")
            return data["choices"][0]["message"]["content"], "gpt-5.4-mini (mammouth)"
        except Exception as e:
            derniere = e
    if ANTHROPIC_API_KEY:
        try:
            from anthropic import Anthropic
            resp = Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                model=AI_MODEL, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}])
            u = getattr(resp, "usage", None)
            compte_tokens(AI_MODEL, {"input_tokens": getattr(u, "input_tokens", 0),
                                     "output_tokens": getattr(u, "output_tokens", 0)}, "dashboard")
            return resp.content[0].text, AI_MODEL
        except Exception as e:
            derniere = e
    if MISTRAL_API_KEY:
        try:
            r = requests.post(MISTRAL_URL,
                              headers={"Authorization": f"Bearer {MISTRAL_API_KEY}",
                                       "Content-Type": "application/json"},
                              json={"model": MISTRAL_MODEL, "max_tokens": max(16, max_tokens),
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=45)
            r.raise_for_status()
            data = r.json()
            compte_tokens(MISTRAL_MODEL, data.get("usage") or {}, "dashboard")
            return data["choices"][0]["message"]["content"], f"{MISTRAL_MODEL} (direct)"
        except Exception as e:
            derniere = e
    raise derniere or RuntimeError("aucune clé IA dans le coffre")

app = Flask(__name__)

# =====================================================
# MOT DE PASSE (amis) — accès local libre (EA, page locale),
# mot de passe exigé pour le tunnel public et le réseau local.
# NB: les requêtes du tunnel Cloudflare arrivent depuis 127.0.0.1
# mais portent l'en-tête Cf-Ray → elles sont traitées comme externes.
# =====================================================
DASH_PASSWORD = _parse_bot_const("DASH_PASSWORD", "A_REMPLIR_DASH_PASSWORD")   # 🔐 lu dans le coffre

LOGIN_HTML = """<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ACID BOT — Accès</title>
<style>body{background:#0d1117;color:#c9d1d9;font:15px 'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:32px;text-align:center;width:300px}
h1{font-size:20px;margin:0 0 6px}p{color:#8b949e;font-size:13px;margin:0 0 18px}
input{width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:8px;padding:10px;margin-bottom:12px;outline:none}
button{width:100%;background:linear-gradient(90deg,#238636,#2ea043);border:none;color:#fff;border-radius:8px;padding:11px;font-weight:600;cursor:pointer}</style>
</head><body><form method="post"><h1>🧪 ACID BOT</h1><p>Dashboard privé — entre le mot de passe</p>
<input type="password" name="pwd" placeholder="Mot de passe" autofocus><button>Entrer</button></form></body></html>"""

def _is_local_request():
    return request.remote_addr in ("127.0.0.1", "::1") and not request.headers.get("Cf-Ray")

@app.before_request
def _auth():
    if request.method == "OPTIONS" or _is_local_request():
        return None
    if request.path == "/api/public_ask" and not DASH_PASSWORD.startswith("A_REMPLIR"):   # 🌍 vitrine publique : SEULE route (version publique : fermée tant que DASH_PASSWORD n'est pas choisi)
        return None                          # sans mot de passe (bridée côté ŒIL)
    if request.cookies.get("acid_auth") == DASH_PASSWORD and not DASH_PASSWORD.startswith("A_REMPLIR"):
        return None
    pwd = request.form.get("pwd") if request.method == "POST" else request.args.get("pwd")
    if pwd == DASH_PASSWORD and not DASH_PASSWORD.startswith("A_REMPLIR"):   # version publique : pas d'accès distant tant que le mot de passe n'est pas choisi
        resp = redirect(request.path if request.method == "POST" else request.path or "/")
        resp.set_cookie("acid_auth", DASH_PASSWORD, max_age=30 * 24 * 3600)
        return resp
    if request.path.startswith("/api/"):
        return jsonify({"error": "mot de passe requis"}), 401
    return LOGIN_HTML, 401

# La page doit fonctionner même ouverte en double-clic (file://) :
# on autorise les requêtes cross-origin vers l'API.
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp
_mt5_lock = threading.Lock()
_mt5_ready = False
_symbols_cache = {"t": 0.0, "data": None}
_telegram_cache = {"t": 0.0, "ok": False, "detail": ""}
_equity_samples = deque(maxlen=2000)   # (timestamp, equity) échantillonné en live

# =====================================================
# MT5
# =====================================================
def mt5_connect():
    """Attache le process au terminal MT5 (celui du bot). Thread-safe."""
    global _mt5_ready
    if mt5 is None:
        return False
    with _mt5_lock:
        if _mt5_ready and mt5.account_info() is not None:
            return True
        _mt5_ready = False
        try:
            if not mt5.initialize():
                return False
            # 🔒 14/09 — RECONNEXION AUTOMATIQUE COUPEE.
            # Elle relogeait le terminal sur les identifiants de secrets_acid.py.
            # Le jour ou le patron bascule MT5 sur un compte DEMO, la moindre
            # coupure le ramenait en REEL sans qu'il le sache. On se branche
            # desormais sur le terminal DEJA connecte, et sur lui seul.
            if mt5.account_info() is None:
                pass   # pas de login automatique : c'est au patron de choisir
            _mt5_ready = mt5.account_info() is not None
        except Exception:
            _mt5_ready = False
        return _mt5_ready

def _deal_net(d):
    return (d.profit or 0.0) + (d.swap or 0.0) + (d.commission or 0.0) + getattr(d, "fee", 0.0)

def get_deals(days=90):
    if not mt5_connect():
        return []
    frm = datetime.now() - timedelta(days=days)
    deals = mt5.history_deals_get(frm, datetime.now() + timedelta(days=1))
    return sorted(deals or [], key=lambda d: d.time)

# =====================================================
# HELPERS HTTP
# =====================================================
def ping(url, timeout=2.5):
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200, r.json() if "json" in r.headers.get("content-type", "") else {}
    except Exception as e:
        return False, {"error": str(e)[:120]}

# =====================================================
# ROUTES
# =====================================================
# =====================================================
# 👥 COMPTEUR DE VISITEURS (14/07, demande patron) : IP uniques + vues par
# jour, comptées sur la page d'accueil seulement (pas le polling /api).
# Derrière le tunnel Cloudflare, la vraie IP est dans CF-Connecting-IP.
# =====================================================
VISIT_FILE = HERE / "visitors.json"
_visit_lock = threading.Lock()

def _visiteurs_data() -> dict:
    try:
        return json.loads(VISIT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

@app.before_request
def _compte_visiteur():
    if request.path != "/":
        return
    ip = (request.headers.get("CF-Connecting-IP")
          or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip())
          or request.remote_addr or "?")
    jour = datetime.now().strftime("%Y-%m-%d")
    try:
        with _visit_lock:
            d = _visiteurs_data()
            j = d.setdefault(jour, {"ips": [], "vues": 0})
            j["vues"] += 1
            if ip not in j["ips"]:
                j["ips"].append(ip)
            for k in sorted(d)[:-31]:   # 31 jours d'historique
                d.pop(k, None)
            VISIT_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass

@app.route("/api/compteurs")
def api_compteurs():
    """🧮 tokens IA du jour (token_stats.json, tous process) + 👥 visiteurs."""
    jour = datetime.now().strftime("%Y-%m-%d")
    v = _visiteurs_data().get(jour, {})
    return jsonify({"tokens": tokens_du_jour(),
                    "visiteurs": {"uniques": len(v.get("ips", [])),
                                  "vues": v.get("vues", 0)}})

@app.route("/")
def index():
    return send_file(HERE / "dashboard.html")

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "ACID BOT Dashboard", "short_name": "ACID",
        "start_url": "/", "display": "standalone",
        "background_color": "#0d1117", "theme_color": "#0d1117",
        "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}],
    })


@app.route("/icon.png")
def icon():
    p = HERE / "icon.png"
    return send_file(p) if p.exists() else ("", 404)


@app.route("/api/council")
def api_council():
    """🗨️ Chat de groupe : relaie vers LE CERVEAU (8060). ?roster=1 = liste des
    bots (autocomplétion /), sinon msg = message (ciblable via /handle).
    🔒 Réservé au patron (PC + réseau maison) — les INVITÉS du tunnel n'y ont
    pas accès (ils ont le bouton «…» plus haut)."""
    import urllib.parse
    if request.headers.get("Cf-Ray"):     # requête passée par le tunnel = invité
        return jsonify({"replies": [{"name": "🔒 réservé",
                                     "text": "Le chat des bots est privé (patron). Utilise le bouton « Avis du trader IA » plus haut 👆"}],
                        "bots": [], "guest": True})
    try:
        if request.args.get("roster"):
            r = requests.get("http://127.0.0.1:8060/api/council?roster=1", timeout=10)
            return jsonify(r.json())
        msg = request.args.get("msg", "").strip()
        if not msg:
            return jsonify({"replies": []})
        r = requests.get("http://127.0.0.1:8060/api/council?msg=" + urllib.parse.quote(msg), timeout=90)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"replies": [{"name": "⚠️ hors ligne",
                                     "text": f"LE CERVEAU ne répond pas (démarré ?) — {str(e)[:60]}"}], "bots": []})


@app.route("/api/public_ask")
def api_public_ask():
    """🌍 Vitrine publique (page tiiny.host) : relaie la question au CERVEAU,
    qui porte TOUT le bridage (5 questions/h par IP, plafond 150/jour,
    300 caractères, prompt verrouillé sans pilotage). Seule route sans mot
    de passe — elle ne sait QUE poser une question, aucun accès aux
    données du dashboard."""
    import urllib.parse
    ip = (request.headers.get("CF-Connecting-IP")
          or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
          or request.remote_addr or "?")
    try:
        r = requests.get("http://127.0.0.1:8060/api/public_ask?msg="
                         + urllib.parse.quote(request.args.get("msg", "")),
                         headers={"CF-Connecting-IP": ip}, timeout=90)
        return jsonify(r.json())
    except Exception:
        return jsonify({"error": "le cerveau du bot est éteint pour le moment"})


@app.route("/api/status")
def api_status():
    ml_ok, ml_data     = ping(f"{ML_URL}/health")
    news_ok, news_data = ping(f"{NEWS_URL}/health")

    # Bot Telegram : heartbeat = fraîcheur du log du bot + validité du token (caché 60 s)
    bot_alive, bot_detail = False, "log introuvable"
    try:
        age = time.time() - BOT_LOG.stat().st_mtime
        bot_alive = age < 300
        bot_detail = f"dernière activité il y a {int(age)} s"
    except Exception:
        pass

    now = time.time()
    if TELEGRAM_TOKEN and now - _telegram_cache["t"] > 60:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=4)
            j = r.json()
            _telegram_cache.update(t=now, ok=bool(j.get("ok")),
                                   detail="@" + j.get("result", {}).get("username", "?") if j.get("ok") else "token invalide")
        except Exception as e:
            _telegram_cache.update(t=now, ok=False, detail=str(e)[:80])

    mt5_ok = mt5_connect()
    acc = mt5.account_info() if mt5_ok else None

    # 🚦 EA ACID IA : en pause (mis au silence par LE CERVEAU) ou actif ?
    # Fichier oeil_status.json écrit par ia_watchdog.cmd_to_ea à chaque PAUSE/RESUME.
    acid = {"ok": True, "detail": "actif (aucune pause signalée)"}
    try:
        sj = json.loads((BOT_DIR / "oeil_status.json").read_text(encoding="utf-8"))
        if sj.get("ea_paused"):
            duree = int((now - sj.get("since", now)) / 60)
            ar = sj.get("auto_resume_at", 0)
            if ar:
                reste = max(0, int((ar - now) / 60))
                acid = {"ok": False, "detail": f"EN PAUSE (LE CERVEAU) depuis {duree} min — reprise auto ~{reste} min"}
            else:
                acid = {"ok": False, "detail": f"EN PAUSE (manuelle) depuis {duree} min"}
        else:
            acid = {"ok": True, "detail": "actif"}
    except Exception:
        pass

    return jsonify({
        "ml":       {"ok": ml_ok,   "detail": ml_data.get("status", ml_data.get("error", ""))},
        "news":     {"ok": news_ok, "detail": news_data.get("status", news_data.get("error", "")),
                     "trading": news_data.get("trading", "")},
        "telegram": {"ok": bot_alive and _telegram_cache["ok"],
                     "detail": f"{_telegram_cache['detail']} — {bot_detail}"},
        "mt5":      {"ok": mt5_ok,
                     "detail": f"{acc.server} #{acc.login}" if acc else "terminal non connecté"},
        "acid":     acid,
        "sonnet":   acid,   # compat : ancien nom de clé, à retirer plus tard
        "ts": now,
    })

@app.route("/api/overview")
def api_overview():
    if not mt5_connect():
        return jsonify({"ok": False, "error": "MT5 non connecté"})
    acc = mt5.account_info()

    _equity_samples.append((time.time(), acc.equity))

    deals = get_deals(90)
    trade_deals = [d for d in deals if d.entry in (1, 3)]  # sorties de position

    # Courbe de balance reconstruite à rebours depuis la balance actuelle
    total_change = sum(_deal_net(d) for d in deals)
    bal = acc.balance - total_change
    curve = []
    for d in deals:
        bal += _deal_net(d)
        curve.append({"t": d.time, "v": round(bal, 2)})
    curve.append({"t": int(time.time()), "v": round(acc.equity, 2)})

    # KPIs
    today = datetime.now().date()
    closed = [(d, _deal_net(d)) for d in trade_deals]
    today_deals = [(d, p) for d, p in closed if datetime.fromtimestamp(d.time).date() == today]
    wins   = [p for _, p in closed if p > 0]
    losses = [p for _, p in closed if p < 0]
    gross_w, gross_l = sum(wins), abs(sum(losses))

    peak, max_dd = float("-inf"), 0.0
    for pt in curve:
        peak = max(peak, pt["v"])
        if peak > 0:
            max_dd = max(max_dd, (peak - pt["v"]) / peak * 100)

    positions = []
    for p in (mt5.positions_get() or []):
        positions.append({
            "ticket": p.ticket, "symbol": p.symbol,
            "dir": "BUY" if p.type == 0 else "SELL",
            "volume": p.volume, "open": p.price_open, "current": p.price_current,
            "sl": p.sl, "tp": p.tp, "profit": round(p.profit + p.swap, 2),
            "t": p.time,
        })

    history = []
    for d in reversed(trade_deals[-25:]):
        history.append({
            "t": d.time, "symbol": d.symbol,
            "dir": "BUY" if d.type == 1 else "SELL",   # deal SELL clôture un BUY
            "volume": d.volume, "price": d.price,
            "profit": round(_deal_net(d), 2), "comment": d.comment,
        })

    return jsonify({
        "ok": True,
        "account": {
            "login": acc.login, "server": acc.server, "currency": acc.currency,
            "balance": acc.balance, "equity": acc.equity,
            "margin_free": acc.margin_free, "floating": round(acc.profit, 2),
        },
        "kpis": {
            "today_pnl": round(sum(p for _, p in today_deals), 2),
            "trades_today": len(today_deals),
            "trades_total": len(closed),
            "winrate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else (round(gross_w, 2) if gross_w else 0),
            "max_dd": round(max_dd, 2),
        },
        "equity_curve": curve[-500:],
        "live_equity": [{"t": t, "v": v} for t, v in list(_equity_samples)],
        "positions": positions,
        "history": history,
    })

@app.route("/api/events")
def api_events():
    n = min(int(request.args.get("n", 60)), 300)
    lines = []
    try:
        raw = BOT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        pat = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[(\w+)\] (.*)$")
        for line in raw[-n:]:
            m = pat.match(line)
            if m:
                lines.append({"time": m.group(1), "level": m.group(2), "msg": m.group(3)})
            elif line.strip():
                lines.append({"time": "", "level": "RAW", "msg": line.strip()})
    except Exception as e:
        lines.append({"time": "", "level": "ERROR", "msg": f"log illisible: {e}"})
    return jsonify({"events": lines})

LOG_SOURCES = {
    "bot":  BOT_DIR / "mammouth_v7.log",
    "news": BOT_DIR / "acidgpt_server.log",
    "ml":   BOT_DIR / "ml_server.log",
}

@app.route("/api/logs")
def api_logs():
    src = request.args.get("src", "bot")
    n = min(int(request.args.get("n", 100)), 400)
    path = LOG_SOURCES.get(src)
    if path is None:
        return jsonify({"lines": [f"source inconnue: {src}"]})
    if not path.exists():
        hint = " — redémarrez ce serveur pour activer son journal" if src == "ml" else ""
        return jsonify({"lines": [f"⏳ {path.name} absent{hint}"]})
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": [l for l in lines if l.strip()][-n:]})
    except Exception as e:
        return jsonify({"lines": [f"❌ lecture impossible: {e}"]})

# =====================================================
# SIGNAUX ML — même calcul que la commande /signaux du bot
# (vraies bougies M5 MT5 + IndicatorEngine + /predict/json)
# =====================================================
BOT_SYMBOLS = ["EURUSD#", "GOLD#", "OILCash#", "BTCUSD#", "USDJPY#", "Crypto_10#",
               "SILVER#", "US500Cash#", "ETHUSD#"]

def _atr14(highs, lows, closes):
    trs = []
    for i in range(max(1, len(closes) - 14), len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    return sum(trs) / len(trs) if trs else 0.0

def _boll_width(closes, period=20, mult=2):
    if len(closes) < period:
        return 0.0
    win = closes[-period:]
    m = sum(win) / period
    std = (sum((c - m) ** 2 for c in win) / period) ** 0.5
    return (2 * mult * std) / closes[-1] if closes[-1] else 0.0

@app.route("/api/mlsignals")
def api_mlsignals():
    if not mt5_connect():
        return jsonify({"ok": False, "error": "MT5 non connecté"})
    out = []
    for sym in BOT_SYMBOLS:
        try:
            mt5.symbol_select(sym, True)
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 100)
            if rates is None or len(rates) < 30:
                out.append({"symbol": sym, "error": "lecture MT5 impossible"})
                continue
            closes = [float(r["close"]) for r in rates]
            highs  = [float(r["high"]) for r in rates]
            lows   = [float(r["low"]) for r in rates]

            rsi = _rsi(closes) or 50.0
            e20, e50 = _ema(closes, 20), _ema(closes, 50)
            e12, e26 = _ema(closes, 12), _ema(closes, 26)
            ema_ratio = max(0.5, min(1.5, (e20 / e50) if e20 and e50 else 1.0))
            macd = (e12 - e26) if e12 and e26 else 0.0
            atr = _atr14(highs, lows, closes)

            ok, news = ping(f"{NEWS_URL}/signal?symbol={sym.replace('#','')}", timeout=3)
            news_score = float(news.get("score", 50.0)) if ok and isinstance(news, dict) else 50.0

            direction, score, conf = "HOLD", 50.0, 50.0
            tp_off = sl_off = None
            try:
                r = requests.post(f"{ML_URL}/predict/json", timeout=5, json={
                    "symbol": sym, "rsi": rsi, "ema_ratio": ema_ratio, "atr": atr,
                    "macd": macd, "bollinger_width": _boll_width(closes),
                    "news_score": max(0.0, min(100.0, news_score)),
                })
                if r.status_code == 200:
                    p = r.json()
                    direction = p.get("prediction", p.get("direction", "HOLD"))
                    score = p.get("score", 50.0)
                    conf = float(p.get("confidence", 50.0))
                    if conf <= 1.0:   # le serveur ML renvoie une fraction 0-1
                        conf *= 100
                    tp_off, sl_off = p.get("tp"), p.get("sl")
            except Exception:
                pass

            # TP/SL du serveur ML (offsets ATR) convertis en niveaux de prix
            price = closes[-1]
            if tp_off is None:
                tp_off, sl_off = atr * 2.5, atr * 1.0   # fallback: mêmes formules que le ML
            info = mt5.symbol_info(sym)
            digits = info.digits if info else 5
            tp_price = sl_price = None
            if direction == "BUY":
                tp_price, sl_price = round(price + tp_off, digits), round(price - sl_off, digits)
            elif direction == "SELL":
                tp_price, sl_price = round(price - tp_off, digits), round(price + sl_off, digits)

            out.append({"symbol": sym, "direction": direction,
                        "score": round(float(score), 1), "confidence": round(float(conf), 1),
                        "rsi": round(rsi, 1), "ema_ratio": round(ema_ratio, 3),
                        "news": round(news_score), "price": round(price, digits),
                        "tp": tp_price, "sl": sl_price})
        except Exception as e:
            out.append({"symbol": sym, "error": str(e)[:80]})
    return jsonify({"ok": True, "signals": out, "ts": time.time()})

@app.route("/api/mlinfo")
def api_mlinfo():
    """Bloc d'infos ML : état du serveur, modèle, analyse globale."""
    ok_h, health = ping(f"{ML_URL}/health", timeout=4)
    ok_a, analysis = ping(f"{ML_URL}/api/ml/analysis", timeout=8)
    model_file = BOT_DIR / "ml_data" / "modele_v2.pkl"   # 16/09 : le seul modèle servi
    model_date = None
    try:
        model_date = model_file.stat().st_mtime
    except Exception:
        pass
    return jsonify({
        "online": ok_h,
        "version": health.get("version") if ok_h else None,
        "model_loaded": health.get("model_loaded") if ok_h else None,
        "symbols": health.get("symbols", []) if ok_h else [],
        "model_file_date": model_date,
        "refresh_rule": "actualisation auto du modèle : chaque dimanche (si le serveur est allumé)",
        "analysis": analysis if ok_a else None,
        "ts": time.time(),
    })

import sys as _sys
_sys.path.insert(0, str(BOT_DIR))
try:
    import cot_data
except Exception:
    cot_data = None

@app.route("/api/cot")
def api_cot():
    """🏦 Smart Money — biais institutionnel COT (même source que LE CERVEAU)."""
    if cot_data is None:
        return jsonify({"assets": {}})
    try:
        return jsonify(cot_data.get_cot())
    except Exception as e:
        return jsonify({"assets": {}, "error": str(e)[:120]})

@app.route("/api/vois")
def api_vois():
    """👁️ Que vois-tu — systèmes & experts détectés sur MT5."""
    day = datetime.now().strftime("%Y%m%d")
    charts = {}
    try:
        ti = mt5.terminal_info()          # 20/07 : plus de chemin figé
        base = Path(ti.data_path) if (ti and getattr(ti, "data_path", "")) \
               else Path(r"C:\Program Files\Vantage Markets MT5 Terminal")
        p = base / "MQL5" / "Logs" / f"{day}.log"
        for line in p.read_text(encoding="utf-16", errors="replace").splitlines()[-600:]:
            m = re.search(r"([A-Za-z0-9 _.\-]+?) \(([A-Za-z0-9#._]+),([A-Z0-9]+)\)", line)
            if m:
                charts.setdefault(m.group(1).strip(), set()).add(f"{m.group(2)} {m.group(3)}")
    except Exception:
        pass
    py = False
    try:
        py = (time.time() - BOT_LOG.stat().st_mtime) < 120
    except Exception:
        pass
    # 🚨 CALL DU JOUR (écrit par LE CERVEAU dans oeil_call.json) — visible le jour
    # même uniquement ; après 6 h il passe en «…» (barré).
    call = None
    try:
        cj = json.loads((BOT_DIR / "oeil_call.json").read_text(encoding="utf-8"))
        if cj.get("date") == datetime.now().strftime("%Y-%m-%d"):
            age_min = int((time.time() - cj.get("ts", 0)) / 60)
            cj["age_min"] = max(0, age_min)
            cj["frais"] = age_min <= 360
            call = cj
    except Exception:
        pass
    return jsonify({
        "python": py,
        "charts": {k: sorted(v) for k, v in charts.items()},
        "ml":   ping(f"{ML_URL}/health")[0],
        "news": ping(f"{NEWS_URL}/health")[0],
        "call": call,
    })

@app.route("/api/symbols")
def api_symbols():
    if _symbols_cache["data"] and time.time() - _symbols_cache["t"] < 600:
        return jsonify(_symbols_cache["data"])
    out = []
    if mt5_connect():
        for s in (mt5.symbols_get() or []):
            out.append({"name": s.name, "desc": s.description, "group": s.path.split("\\")[0]})
    if not out:  # fallback : symboles du bot
        out = [{"name": n, "desc": "", "group": "Bot"} for n in BOT_SYMBOLS]
    data = {"symbols": out, "count": len(out)}
    _symbols_cache.update(t=time.time(), data=data)
    return jsonify(data)

@app.route("/api/signals")
def api_signals():
    _, news = ping(f"{NEWS_URL}/signals", timeout=4)
    _, ml   = ping(f"{ML_URL}/api/ml/signals", timeout=4)
    return jsonify({"news": news, "ml": ml})

# =====================================================
# AVIS IA — trader confirmé (Anthropic, clé du bot)
# =====================================================
def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0: gains += diff
        else: losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return round(100 - 100 / (1 + rs), 1)

def _ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for c in closes[period:]:
        e = c * k + e * (1 - k)
    return e

@app.route("/api/ai/opinion", methods=["POST"])
def api_ai_opinion():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip()
    if not symbol:
        return jsonify({"ok": False, "error": "symbole manquant"}), 400
    if not (MAMMOUTH_API_KEY or ANTHROPIC_API_KEY or MISTRAL_API_KEY):
        return jsonify({"ok": False, "error": "aucune clé IA dans le coffre"}), 500

    # ---- Données marché réelles (MT5) ----
    market = ""
    if mt5_connect():
        try:
            mt5.symbol_select(symbol, True)
            r15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 120)
            rh1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 48)
            if r15 is not None and len(r15) > 20:
                closes = [float(x["close"]) for x in r15]
                highs  = [float(x["high"]) for x in r15]
                lows   = [float(x["low"]) for x in r15]
                last   = closes[-1]
                rsi    = _rsi(closes)
                e20, e50 = _ema(closes, 20), _ema(closes, 50)
                atr = sum(h - l for h, l in zip(highs[-14:], lows[-14:])) / 14
                var24 = None
                if rh1 is not None and len(rh1) >= 25:
                    var24 = (last / float(rh1[-25]["close"]) - 1) * 100
                tick = mt5.symbol_info_tick(symbol)
                spread = (tick.ask - tick.bid) if tick else None
                parts = [f"Prix actuel: {last}"]
                if var24 is not None:
                    parts.append(f"Variation 24h: {round(var24, 2)}%")
                trend = ("prix > EMAs = tendance haussière" if e20 and e50 and last > e20 > e50
                         else "prix < EMAs = tendance baissière" if e20 and e50 and last < e20 < e50
                         else "EMAs mixtes")
                parts += [
                    f"RSI(14) M15: {rsi}",
                    f"EMA20 M15: {round(e20, 5) if e20 else '?'} | EMA50 M15: {round(e50, 5) if e50 else '?'} ({trend})",
                    f"ATR(14) M15: {round(atr, 5)}",
                    f"Spread: {round(spread, 5) if spread else '?'}",
                    f"Range 48h: {min(lows)} - {max(highs)}",
                ]
                market = "\n".join(parts) + "\n"
        except Exception as e:
            market = f"(données MT5 indisponibles: {e})"

    # ---- Signaux news + ML ----
    news_txt = ml_txt = pos_txt = ""
    ok, news = ping(f"{NEWS_URL}/signal?symbol={symbol.replace('#','')}", timeout=4)
    if ok and isinstance(news, dict):
        news_txt = f"Signal news: {news.get('signal')} (score {news.get('score')}) {news.get('warning','')}"
    ok, ml = ping(f"{ML_URL}/api/ml/signals", timeout=4)
    if ok:
        clean = symbol.replace("#", "").upper()
        for s in ml.get("signals", []):
            if s.get("symbol", "").upper() in (clean, clean.replace("CASH", "")):
                ml_txt = f"Signal ML: {s.get('direction')} (score {s.get('score')}, confiance {s.get('confidence')})"
                break
    if mt5 and _mt5_ready:
        for p in (mt5.positions_get(symbol=symbol) or []):
            pos_txt += f"Position ouverte: {'BUY' if p.type == 0 else 'SELL'} {p.volume} lots @ {p.price_open}, P&L flottant {round(p.profit, 2)}\n"

    prompt = f"""Tu es un trader professionnel avec 20 ans d'expérience sur les marchés (forex, métaux, indices, crypto). Tu donnes ton avis sur {symbol} à partir de données RÉELLES ci-dessous. Sois direct, concret, sans langue de bois.

DONNÉES MARCHÉ:
{market or '(indisponibles)'}
{news_txt}
{ml_txt}
{pos_txt}

Réponds en français, format court (max 250 mots):
1. 📖 Lecture du marché (2-3 phrases)
2. 🎯 Biais: HAUSSIER / BAISSIER / NEUTRE + conviction sur 10
3. 📐 Niveaux clés à surveiller
4. 💡 Plan de trade possible (entrée, stop, objectif) — ou "on ne touche pas" si c'est le cas
5. ⚠️ Risque principal du moment"""

    try:
        opinion, moteur = ask_ai_chain(prompt, 700)
        return jsonify({"ok": True, "symbol": symbol, "model": moteur,
                        "opinion": opinion})
    except Exception as e:
        return jsonify({"ok": False, "error": f"appel IA échoué: {e}"}), 502

# =====================================================
# DISPOSITION DU DASHBOARD — le propriétaire (accès local)
# la modifie, tout le monde la voit.
# =====================================================
LAYOUT_FILE = HERE / "layout.json"

@app.route("/api/layout", methods=["GET", "POST"])
def api_layout():
    if request.method == "POST":
        if not _is_local_request():
            return jsonify({"ok": False, "error": "lecture seule pour les invités"}), 403
        try:
            data = request.get_json(force=True)
            LAYOUT_FILE.write_text(json.dumps(data), encoding="utf-8")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:120]}), 500
    try:
        return jsonify(json.loads(LAYOUT_FILE.read_text(encoding="utf-8")))
    except Exception:
        return jsonify({})

@app.route("/api/ai/validate")
def api_ai_validate():
    """Validation TRADE/SKIP pour le EA MQL5 (equivalent MammouthAI.analyze_trade).
    Toujours HTTP 200 avec un JSON plat, parseable par le mini-parseur du EA."""
    a = request.args
    symbol = a.get("symbol", "")
    if not (MAMMOUTH_API_KEY or ANTHROPIC_API_KEY or MISTRAL_API_KEY):
        return jsonify({"action": "SKIP", "confidence": 0, "reason": "cle API absente"})

    ok, news = ping(f"{NEWS_URL}/signal?symbol={symbol.replace('#','')}", timeout=3)
    news_txt = f"{news.get('signal')} (score {news.get('score')})" if ok and isinstance(news, dict) else "indisponible"
    price_txt = ""
    if mt5_connect():
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            price_txt = f"Prix actuel: bid {tick.bid} / ask {tick.ask}."

    prompt = f"""Tu es le validateur de trades du bot ACID (memes regles que le bot Mammouth V7 : strict, on ne trade que les setups nets). Un EA propose ce trade :
Symbole: {symbol} | Direction: {a.get('dir')} | Type: {a.get('kind')} | Score technique: {a.get('score')}/12
RSI: {a.get('rsi')} | Signal ML: {a.get('ml')} (confiance {a.get('mlconf')}) | News: {news_txt} {price_txt}
Decide TRADE ou SKIP en trader professionnel. Reponds UNIQUEMENT ce JSON:
{{"action":"TRADE" ou "SKIP","confidence":<0-100>,"reason":"une phrase courte"}}"""

    try:
        import json as _json
        texte, _moteur = ask_ai_chain(prompt, 150)
        m = re.search(r"\{.*\}", texte, re.S)
        d = _json.loads(m.group(0)) if m else {}
        return jsonify({"action": d.get("action", "SKIP"),
                        "confidence": float(d.get("confidence", 0)),
                        "reason": str(d.get("reason", ""))[:200]})
    except Exception as e:
        return jsonify({"action": "SKIP", "confidence": 0, "reason": f"erreur IA: {e}"[:200]})

# =====================================================
if __name__ == "__main__":
    # 🔇 (12/07) plus de spam «…» dans le terminal du dashboard
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.ERROR)
    print("=" * 60)
    print("  ACID BOT — Dashboard : http://127.0.0.1:%d" % PORT)
    print("  (accessible aussi sur le reseau local via l'IP de ce PC)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORT, debug=False)
