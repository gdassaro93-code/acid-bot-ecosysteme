# -*- coding: utf-8 -*-
# =====================================================
#  ✈️ CONTRÔLE AVANT VOL — «…»
#  (demande patron 22/08, avant de remettre X € sur le compte)
#
#  Passe en revue tout ce qui doit être vrai pour que l'écosystème fonctionne,
#  et le DIT en clair. Aucun effet de bord : ce script ne modifie rien, ne
#  trade rien, n'ouvre rien. On peut le lancer autant de fois qu'on veut.
#
#      python controle_avant_vol.py
# =====================================================
import json
import socket
from pathlib import Path

HERE = Path(__file__).resolve().parent
ok_total, ko_total, alertes = [], [], []


def dire(bon, titre, detail=""):
    (ok_total if bon else ko_total).append(titre)
    print(f"  {'✅' if bon else '❌'} {titre}" + (f"\n       {detail}" if detail else ""))


def alerte(titre, detail=""):
    alertes.append(titre)
    print(f"  ⚠️  {titre}" + (f"\n       {detail}" if detail else ""))


print("=" * 66)
print("✈️  CONTRÔLE AVANT VOL — ÉCOSYSTÈME ACID")
print("=" * 66)

# le mode est lu TOUT DE SUITE : il decide de ce qui est bloquant ou non
_src = (HERE / "ia_watchdog.py").read_text(encoding="utf-8")
# 27/08 : le mode n'est plus écrit en dur — il vit dans mode_trading.txt et se
# bascule depuis Telegram (/reel, /simu). Lire le code donnerait une réponse
# FAUSSE (le contrôle a annoncé «…» alors que tout était en simu).
try:
    SIM = (HERE / "mode_trading.txt").read_text(encoding="utf-8").strip().upper() != "REEL"
except Exception:
    SIM = True          # défaut prudent : pas de fichier = on ne trade pas en réel

# ─── 1. Le code compile-t-il ? ────────────────────────────────────────────
print("\n【 1 】 CODE")
import ast
for f in ("ia_watchdog.py", "BOT_MAMMOUTH_COMPLETE_V7.py", "Server.py",
          "acid_center.py", "canaux_signaux.py", "chart_patterns.py",
          "signal_dollar.py", "budget_risque.py"):
    p = HERE / f
    if not p.exists():
        dire(False, f"{f} : FICHIER ABSENT")
        continue
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        dire(True, f"{f}")
    except SyntaxError as e:
        dire(False, f"{f} : erreur de syntaxe ligne {e.lineno}", str(e.msg))

# ─── 2. MT5 et le compte ──────────────────────────────────────────────────
print("\n【 2 】 BROKER")
try:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        dire(False, "MT5 ne répond pas", "Lance le terminal Vantage puis relance ce contrôle.")
    else:
        a = mt5.account_info()
        t = mt5.terminal_info()
        if a:
            _mode_c = {0: "DÉMO", 1: "CONCOURS", 2: "RÉEL"}.get(getattr(a, "trade_mode", 2), "?")
            if _mode_c == "RÉEL":
                alerte(f"Compte {a.login} — ARGENT RÉEL ({a.server})",
                       "Chaque perte est une vraie perte. Vérifie deux fois avant de lancer.")
            else:
                dire(True, f"Compte {a.login} — {_mode_c} ({a.server})",
                     "Argent fictif : tu peux tester librement.")
            if a.balance <= 0:
                alerte(f"Solde à {a.balance:.2f}€",
                       "Rien ne pourra s'exécuter en réel tant que le compte est vide "
                       "(la simulation, elle, fonctionne).")
            else:
                dire(True, f"Solde : {a.balance:.2f}€ (equity {a.equity:.2f}€)")
            dire(bool(a.trade_allowed), "Trading autorisé côté broker")
            algo = bool(t and t.trade_allowed)
            if algo:
                dire(True, "Algo-trading activé dans le terminal")
            elif SIM:
                alerte("Algo-trading DÉSACTIVÉ dans le terminal",
                       "Sans effet en simulation (aucun ordre n'est envoyé), mais il "
                       "faudra cliquer le bouton « Algo Trading » de MT5 avant le réel.")
            else:
                dire(False, "Algo-trading DÉSACTIVÉ — clique le bouton « Algo Trading » en haut de MT5")
        else:
            dire(False, "Pas de compte connecté dans MT5")

        # les symboles qui comptent
        print("\n【 3 】 SYMBOLES (les 2 marchés mesurés rentables + le dollar)")
        for sym, role in (("NAS100", "marché n°1 (+41,4R mesuré)"),
                          ("XAUUSD+", "marché n°2 (+35,7R mesuré)"),
                          ("USDX", "signal fondamental dollar")):
            i = mt5.symbol_info(sym)
            if not i:
                dire(False, f"{sym} INTROUVABLE — {role}")
            elif sym != "USDX" and i.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                dire(False, f"{sym} non tradable (trade_mode={i.trade_mode}) — {role}")
            else:
                r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20)
                if r is None or len(r) < 15:
                    dire(False, f"{sym} : pas d'historique H1 — {role}")
                else:
                    dire(True, f"{sym} coté et alimenté — {role}")
        mt5.shutdown()
except ImportError:
    dire(False, "MetaTrader5 non installé")

# ─── 4. Les réglages de sécurité ──────────────────────────────────────────
print("\n【 4 】 SÉCURITÉ")
src, sim = _src, SIM
if sim:
    dire(True, "MODE SIMULATION ACTIF — aucun ordre réel ne partira",
         "C'est ce qu'on veut pour tester. Passer à False pour trader.")
else:
    alerte("MODE RÉEL — les ordres partiront pour de vrai")
dire("FILET_SL_MANUEL       = True" in src,
     "Filet SL sur tes trades manuels (celui qui manquait)")
# 🧠 16/09 : UN SEUL ML, servi par le port 8001 (ml_data/modele_v2.pkl).
# Deux vérifications, parce qu'un port qui répond ne dit rien du modèle chargé :
#   1. le FICHIER se charge et parle la même langue que les formules
#   2. si le serveur tourne, c'est bien CE modèle qu'il sert (et pas l'ancien
#      à pile ou face, qui passait «…» avec un simple test de port)
try:
    import joblib as _jl, json as _json, ml_v2_entrainer as _V
    _p = _jl.load(HERE / "ml_data" / "modele_v2.pkl")
    _c = {}
    try:
        _c = _json.loads((HERE / "ml_data" / "modele_v2_carte.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    if list(_p.get("features", [])) != list(_V.FEATURES):
        dire(False, "ML v2 : les données du modèle ne correspondent plus aux formules",
             "relancer : python ml_v2_entrainer.py")
    else:
        _wf = _c.get("regle_sur_6_mois") or {}
        dire(True, f"ML v2 prêt — règle {_p.get('regle')}, créé le {_p.get('cree_le')}",
             f"{_wf.get('esperance_R', '?')}R/trade sur 6 mois glissants · CONSULTATIF, aucun droit de veto")
    try:
        import ml_client as _mc
        _h = _mc.sante()
        if _h is None:
            alerte("ML : le serveur 8001 ne répond pas encore (normal s'il n'est pas lancé)")
        elif _h.get("modele") != "v2":
            alerte(f"ML : le serveur 8001 sert un AUTRE modèle ({_h.get('modele')})",
                   "relancer le service ML depuis le Centre")
        else:
            dire(True, "ML : le serveur 8001 sert bien le modèle v2")
    except Exception:
        pass
except FileNotFoundError:
    alerte("ML v2 : modèle introuvable (ml_data/modele_v2.pkl)", "lancer : python ml_v2_entrainer.py")
except Exception as _e:
    alerte(f"ML illisible : {_e}")
try:
    import budget_risque as B
    dire(True, f"Enveloppe commune : {B.ENVELOPPE_TOTALE_PCT:g}% max, "
               f"{B.RISQUE_PAR_TRADE_PCT:g}%/trade, plancher jour -{B.PERTE_JOUR_MAX_PCT:g}%")
except Exception as e:
    dire(False, f"budget_risque illisible : {e}")

# ─── 5. Les services ──────────────────────────────────────────────────────
print("\n【 5 】 SERVICES")
for port, nom, vital in ((5001, "serveur News", False), (8001, "serveur ML", False),
                         (8050, "dashboard", False), (8060, "pont EA", True)):
    s = socket.socket()
    s.settimeout(1)
    vivant = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    if vivant:
        dire(True, f"{nom} (port {port})")
    elif vital:
        alerte(f"{nom} (port {port}) éteint", "L'EA ne recevra pas les validations IA.")
    else:
        alerte(f"{nom} (port {port}) éteint", "Non bloquant.")

# ─── 6. L'EA ──────────────────────────────────────────────────────────────
print("\n【 6 】 EA ACID IA V1")
ea = Path(__import__("portabilite").mql5_experts() or "MQL5_Experts_introuvable")
# (version publique : dossier Experts lu par portabilite.py, plus de chemin gravé en dur)
mq5, ex5 = ea / "ACID IA V1.mq5", ea / "ACID IA V1.ex5"
if ex5.exists() and mq5.exists():
    if ex5.stat().st_mtime >= mq5.stat().st_mtime:
        dire(True, "EA compilé et à jour")
    else:
        dire(False, "EA PAS RECOMPILÉ depuis la dernière modification du code")
    if "MaxDailyLossPct   = 0.0" in mq5.read_text(encoding="utf-8", errors="ignore"):
        dire(True, "Limite de perte journalière retirée (ton choix)")
else:
    dire(False, "EA introuvable dans le terminal Vantage")

# ─── verdict ──────────────────────────────────────────────────────────────
print("\n" + "=" * 66)
print(f"  {len(ok_total)} contrôles OK · {len(alertes)} avertissements · {len(ko_total)} bloquants")
if ko_total:
    print("\n  ❌ À CORRIGER AVANT DE LANCER :")
    for k in ko_total:
        print(f"     • {k}")
elif sim:
    print("\n  ✅ PRÊT POUR LA SIMULATION.")
    print("     Lance LE CERVEAU, laisse tourner 2-3 jours, puis :")
    print("     python bilan_simulation.py 100")
else:
    print("\n  ✅ PRÊT — et en mode RÉEL. Les ordres partiront.")
print("=" * 66)

# 🖱️ 02/09 (patron : «…
# …»). Lancé par
# double-clic, la fenêtre se refermait avant qu'on ait pu lire quoi que ce
# soit. On attend donc une touche — sauf si le script tourne dans un pipe
# ou en tâche de fond, où il n'y a personne pour appuyer.
try:
    import sys as _sys
    if _sys.stdin is not None and _sys.stdin.isatty():
        print()
        input("  ⏎  Appuie sur Entrée pour fermer cette fenêtre...")
except Exception:
    pass
