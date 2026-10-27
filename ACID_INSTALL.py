# -*- coding: utf-8 -*-
# =====================================================
#  🛠️ INSTALLEUR — remonte l'écosystème ACID sur le nouveau portable
#
#  À LANCER SUR LE NOUVEAU PC, depuis le dossier du colis, MT5 FERMÉ :
#      python ACID_INSTALL.py
#      python ACID_INSTALL.py --vers "C:\AcidBot\BOT COMPLETO"    (destination)
#      python ACID_INSTALL.py --blanc                             (essai à blanc)
#
#  PRÉREQUIS, dans cet ordre (voir README.txt) :
#      1. Python 3.12.10 installé, cases "Add python.exe to PATH" ET "tcl/tk and IDLE" cochées
#      2. MetaTrader 5 (Vantage) installé
#      3. MT5 lancé UNE FOIS, connecté au compte — c'est ce lancement qui crée le
#         dossier de données du terminal. Sans lui, l'installeur n'a nulle part
#         où poser l'EA.
#      4. MT5 refermé
#
#  CE QU'IL FAIT, ET CE QU'IL NE FAIT PAS :
#    il pose · installe · répare les chemins · recompile l'EA · vérifie
#    il NE lance AUCUN bot, NE lance PAS MT5, NE passe PAS en réel.
#    Il force SIMULATION dans mode_trading.txt : le retour au réel est une
#    décision consciente, prise à la main, une fois le contrôle avant vol vert.
# =====================================================
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

COLIS = Path(__file__).resolve().parent
ARGS = sys.argv[1:]
BLANC = "--blanc" in [a.lower() for a in ARGS]
PY_ATTENDU = (3, 12)

DEFAUT = Path(r"C:\AcidBot\BOT COMPLETO")
PORTS = ((5001, "serveur News"), (8001, "serveur ML"), (8050, "dashboard"),
         (8060, "pont EA ← L'ŒIL"), (8061, "verrou d'instance unique"))

# ── le cataplasme injecté en tête des fichiers qui avaient un chemin gravé ───
SHIM = '''# --- posé par ACID_INSTALL.py : les chemins ne sont plus gravés en dur ---
def _acid_mt5_exe():
    """terminal64.exe, lu depuis origin.txt du terminal — jamais deviné."""
    try:
        import portabilite as _p
        return str(_p.terminal_exe() or "")
    except Exception:
        return ""


def _acid_mt5_dir():
    """Le dossier de DONNÉES du terminal. Ne renvoie JAMAIS None : le code appelant
    fait parfois Path(...) dessus, et Path(None) leve. Le repli pointe sur la base
    des terminaux — jamais sur le dossier d'INSTALLATION, qui etait l'ancien repli
    et une vraie erreur : on allait y chercher MQL5/Logs, qui n'y est pas."""
    try:
        import portabilite as _p
        _d = _p.terminal_dir()
        if _d:
            return _d
    except Exception:
        pass
    import os as _os
    from pathlib import Path as _P
    return _P(_os.environ.get("APPDATA", ".")) / "MetaQuotes" / "Terminal"
# --- fin du bloc posé par l'installeur ---
'''

# (motif, remplacement, a-besoin-du-shim) — appliqué à tous les .py
SUBS = [
    # le chemin d'installation du terminal, gravé dans 6 fichiers
    (re.compile(r'r"C:\\Program Files\\Vantage Markets MT5 Terminal\\terminal64\.exe"'),
     '_acid_mt5_exe()', True),
    (re.compile(r'r"C:\\Program Files\\Vantage Markets MT5 Terminal"'),
     '_acid_mt5_dir()', True),
    # le GUID du terminal, gravé dans acid_center.py et controle_avant_vol.py
    (re.compile(r'Path\(\s*r"C:\\Users\\[^"\\]+\\AppData\\Roaming\\MetaQuotes\\Terminal'
                r'\\[0-9A-Fa-f]{32}\\MQL5\\Files"\s*\)'),
     '__import__("portabilite").mql5_files()', False),
    (re.compile(r'Path\(\s*r"C:\\Users\\[^"\\]+\\AppData\\Roaming\\MetaQuotes\\Terminal"?\s*'
                r'r?"?\\?[0-9A-Fa-f]{32}\\MQL5\\Experts"\s*\)'),
     '__import__("portabilite").mql5_experts()', False),
    (re.compile(r'Path\(\s*r"C:\\Users\\[^"\\]+\\AppData\\Roaming\\MetaQuotes\\Terminal"?\s*'
                r'r?"?\\?[0-9A-Fa-f]{32}\\Profiles\\Charts"\s*\)'),
     '__import__("portabilite").profils_charts()', False),
    # le dossier du projet, gravé dans la pile ML
    (re.compile(r'r?"C:[/\\]{1,2}AcidBot[/\\]{1,2}BOT COMPLETO[/\\]{1,2}ml_data"'),
     'str(__import__("pathlib").Path(__file__).resolve().parent / "ml_data")', False),
    (re.compile(r'r?"C:[/\\]{1,2}AcidBot[/\\]{1,2}BOT COMPLETO"'),
     'str(__import__("pathlib").Path(__file__).resolve().parent)', False),
    # "python" nu -> l'interpréteur courant (sur un Windows neuf, "python"
    # pointe très souvent vers le raccourci Microsoft Store, qui ouvre le Store)
    (re.compile(r'subprocess\.Popen\(\[\s*"python"\s*,'),
     'subprocess.Popen([sys.executable,', False),
    (re.compile(r'subprocess\.run\(\[\s*"python"\s*,'),
     'subprocess.run([sys.executable,', False),
    # ffmpeg nu -> celui qu'embarque imageio-ffmpeg (il n'est pas dans le PATH)
    (re.compile(r'\[\s*"ffmpeg"\s*,'),
     '[__import__("imageio_ffmpeg").get_ffmpeg_exe(),', False),
]

MANUEL = """
  ┌────────────────────────────────────────────────────────────────────────┐
  │  CE QUE JE NE PEUX PAS FAIRE À TA PLACE — dans MetaTrader 5            │
  └────────────────────────────────────────────────────────────────────────┘

   1. Outils ▸ Options ▸ Expert Advisors
        ☑ Autoriser WebRequest pour les URL listées
          ajouter   http://127.0.0.1:8060      (le pont de L'ŒIL)
          ajouter   http://127.0.0.1:8001      (le serveur ML)
          ajouter   http://127.0.0.1:5001      (le serveur News)
      Sans ça, l'EA reçoit l'erreur 4014 à chaque appel et reste muet côté IA.

   2. Le bouton « Algo Trading » de la barre d'outils doit être VERT.

   3. Observation du marché — afficher ces symboles, aux noms EXACTS
      (le « + » fait partie du nom chez Vantage) :
        NAS100   BTCUSD   XAUUSD+   USDX   SP500   CL-OIL   EURUSD+
        XAGUSD   USDJPY+   GBPUSD+   ETHUSD
      Puis ouvrir un graphique H1 sur chacun et faire défiler vers la gauche,
      pour que MT5 télécharge l'historique. Un symbole absent renvoie None et
      le bot conclut que le marché n'existe pas.

   4. Connecte-toi à TON compte MT5 (numéro de compte + serveur de ton broker).

   5. Pare-feu Windows : autoriser python.exe et pythonw.exe (réseau privé).

  ┌────────────────────────────────────────────────────────────────────────┐
  │  PUIS, DANS CET ORDRE                                                  │
  └────────────────────────────────────────────────────────────────────────┘
        python portabilite.py          ▸ tout doit être OK
        "CONTROLE AVANT VOL.bat"       ▸ vert de bout en bout
        DEMARRER_ECOSYSTEME.bat

   Le mode est sur SIMULATION. Repasse en réel depuis Telegram, à la main,
   une fois seulement que le contrôle avant vol est vert.
"""


def log(m=""):
    print(m, flush=True)


def etape(n, t):
    log("")
    log(f"  ── [{n}] {t} " + "─" * max(0, 58 - len(t)))


def demande(q, defaut=True):
    # À blanc on répond OUI à tout et on continue : l'essai n'a d'intérêt que s'il
    # parcourt TOUTES les étapes. Rien n'est écrit de toute façon.
    if BLANC:
        log(f"     {q}  → (à blanc : on continue)")
        return True
    r = input(f"     {q} [{'O/n' if defaut else 'o/N'}] ").strip().lower()
    return (r != "n") if defaut else (r == "o")


def main():
    log("=" * 74)
    log("  🛠️  INSTALLATION DE L'ÉCOSYSTÈME ACID SUR CETTE MACHINE")
    log("=" * 74)
    if BLANC:
        log("  (essai à blanc : rien ne sera écrit)")

    # ── 0. le colis est-il complet ? ─────────────────────────────────────────
    etape(0, "vérification du colis")
    man_f = COLIS / "manifest.json"
    if not man_f.is_file():
        log("  ⛔ manifest.json introuvable. Lance-moi depuis le dossier du colis")
        log("     (celui qui contient projet\\, mt5\\ et secrets\\).")
        return 1
    man = json.loads(man_f.read_text(encoding="utf-8"))
    for d in ("projet", "mt5"):
        if not (COLIS / d).is_dir():
            log(f"  ⛔ dossier « {d} » manquant dans le colis.")
            return 1
    log(f"  colis du {man['fait_le']} · source : Python {man['source']['python']}")
    log(f"  ancien terminal : {(man['source']['terminal_guid'] or '?')[:8]}…")
    if not (COLIS / "secrets" / "secrets_acid.py").is_file():
        log("  ⚠️  secrets_acid.py absent du colis. Sans lui : pas de Telegram,")
        log("     pas d'IA, et L'ŒIL ne démarre pas du tout. À copier à la main.")

    # ── 1. Python ────────────────────────────────────────────────────────────
    etape(1, "Python")
    v = sys.version_info
    log(f"  version : {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if (v.major, v.minor) != PY_ATTENDU:
        log(f"  ⛔ il faut Python {PY_ATTENDU[0]}.{PY_ATTENDU[1]} (3.12.10 sur l'ancienne")
        log("     machine). MetaTrader5 ne publie de roue que pour cp312, et les")
        log("     modèles ML sont marqués numpy 2.4.6 / scikit-learn 1.9.0.")
        if not demande("Continuer quand même ?", False):
            return 1
    try:
        import tkinter  # noqa: F401
        log("  tkinter : présent")
    except Exception:
        log("  ⚠️  tkinter ABSENT — le Centre de contrôle et ia_dialogue ne s'ouvriront")
        log("     pas. tkinter NE s'installe PAS par pip : il faut relancer")
        log("     l'installeur Python et cocher « tcl/tk and IDLE ».")

    # ── 2. le terminal MT5 de CETTE machine ──────────────────────────────────
    etape(2, "recherche du terminal MetaTrader 5")
    sys.path.insert(0, str(COLIS))
    try:
        import portabilite as P
    except Exception as e:
        log(f"  ⛔ portabilite.py illisible : {e}")
        return 1
    ts = P.terminaux()
    if not ts:
        log("  ⛔ aucun dossier terminal sous %APPDATA%\\MetaQuotes\\Terminal.")
        log("     Lance MetaTrader 5 une fois, connecte-toi au compte, ferme-le,")
        log("     puis relance-moi. C'est ce premier lancement qui crée le dossier.")
        return 1
    for t in ts:
        log(f"     {t['guid'][:8]}…  {'vivant' if t['vivant'] else 'vide  '}  "
            f"{t['origin'] or '(origin.txt illisible)'}")
    td = P.terminal_dir()
    if not td:
        log("  ⛔ aucun terminal exploitable.")
        return 1
    log(f"  ▸ retenu : {td.name[:8]}…   {P._lire_origin(td)}")
    if man["source"]["terminal_guid"] and td.name != man["source"]["terminal_guid"]:
        log("    (GUID différent de l'ancienne machine — c'est NORMAL et attendu :")
        log("     MT5 en génère un nouveau. C'est exactement ce que je gère.)")

    # ── 3. destination ───────────────────────────────────────────────────────
    etape(3, "destination du projet")
    dest = DEFAUT
    for i, a in enumerate(ARGS):
        if a.lower() == "--vers" and i + 1 < len(ARGS):
            dest = Path(ARGS[i + 1])
    log(f"  {dest}")
    if dest.exists() and any(dest.iterdir()):
        log("  ⚠️  le dossier existe et n'est pas vide.")
        if not demande("Écraser les fichiers du colis par-dessus ?", False):
            return 1

    # ── 4. les paquets ───────────────────────────────────────────────────────
    etape(4, "installation des paquets Python")
    req = COLIS / "projet" / "requirements.txt"
    if not req.is_file():
        req = COLIS / "requirements.txt"
    if req.is_file():
        log(f"  {req.name} — versions épinglées (les .pkl exigent numpy 2.4.6 et")
        log("  scikit-learn 1.9.0 : une autre version ne les recharge pas)")
        if not BLANC and demande("Installer maintenant ?"):
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)])
            log("  pip : " + ("OK" if r.returncode == 0 else
                              f"ÉCHEC (code {r.returncode}) — à reprendre à la main"))
    else:
        log("  ⚠️  requirements.txt absent du colis")

    # ── 5. pose du projet ────────────────────────────────────────────────────
    etape(5, "pose du projet")
    if not BLANC:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(COLIS / "projet", dest, dirs_exist_ok=True)
        shutil.copy2(COLIS / "portabilite.py", dest / "portabilite.py")
        sec = COLIS / "secrets"
        n = 0
        if sec.is_dir():
            for f in sec.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest / f.name)
                    n += 1
        log(f"  projet posé · {n} fichier(s) de secrets remis en place")
    else:
        log("  (à blanc)")

    # ── 6. réparation des chemins gravés en dur ──────────────────────────────
    etape(6, "réparation des chemins gravés en dur")
    total, touches = 0, []
    for f in sorted((dest if not BLANC else COLIS / "projet").rglob("*.py")):
        if "__pycache__" in f.parts or f.name in ("portabilite.py", "ACID_INSTALL.py"):
            continue
        try:
            s0 = f.read_text(encoding="utf-8")
        except Exception:
            continue
        s, n, shim = s0, 0, False
        for motif, rempl, besoin in SUBS:
            s, k = motif.subn(rempl, s)
            n += k
            shim = shim or (k and besoin)
        if not n:
            continue
        if shim and "_acid_mt5_exe" not in s0:
            lignes = s.split("\n")
            i = 1 if lignes and lignes[0].startswith("#!") else 0
            if i < len(lignes) and "coding" in lignes[i]:
                i += 1
            s = "\n".join(lignes[:i] + [""] + SHIM.split("\n") + lignes[i:])
        # «…» doit exister si on a injecté sys.executable
        if "sys.executable" in s and not re.search(r"^\s*import sys", s, re.M):
            s = "import sys\n" + s
        if not BLANC:
            f.with_suffix(f.suffix + ".avant_migration").write_text(s0, encoding="utf-8")
            f.write_text(s, encoding="utf-8", newline="")
        total += n
        touches.append(f"{f.name} ({n})")
    log(f"  {total} chemin(s) réparé(s) dans {len(touches)} fichier(s)")
    for t in touches:
        log("     " + t)
    if not touches:
        log("     (aucun — le code est déjà portable)")

    # le lanceur .bat : il appelait terminal64.exe à un chemin gravé
    bat = (dest if not BLANC else COLIS / "projet") / "DEMARRER_ECOSYSTEME.bat"
    if bat.is_file():
        b0 = bat.read_text(encoding="utf-8", errors="replace")
        if "Vantage Markets MT5 Terminal" in b0:
            b = b0.replace(
                'start "" "C:\\Program Files\\Vantage Markets MT5 Terminal\\terminal64.exe"',
                'for /f "delims=" %%i in (\'python -c "import portabilite;'
                'print(portabilite.terminal_exe() or \'\')"\') do set "MT5EXE=%%i"\r\n'
                '    if defined MT5EXE start "" "%MT5EXE%"')
            if not BLANC:
                bat.with_suffix(".bat.avant_migration").write_text(b0, encoding="utf-8")
                bat.write_text(b, encoding="utf-8", newline="")
            log("  DEMARRER_ECOSYSTEME.bat : lancement de MT5 rendu dynamique")

    # ── 7. le contenu du terminal MT5 ────────────────────────────────────────
    etape(7, "pose de l'EA, des presets, du pont et des graphiques")
    paires = [
        (COLIS / "mt5" / "Experts", td / "MQL5" / "Experts", "EA (source .mq5)"),
        (COLIS / "mt5" / "Presets", td / "MQL5" / "Presets", "presets .set"),
        (COLIS / "mt5" / "Files", td / "MQL5" / "Files", "pont EA ↔ Python"),
        (COLIS / "mt5" / "Charts", td / "MQL5" / "Profiles" / "Charts", "graphiques"),
    ]
    for src, dst, quoi in paires:
        if not src.is_dir():
            log(f"  ⚠️  {quoi} : absent du colis")
            continue
        n = sum(1 for _ in src.rglob("*") if _.is_file())
        if not BLANC:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
        log(f"  {quoi} : {n} fichier(s) → {dst}")

    # ── 8. recompilation de l'EA ─────────────────────────────────────────────
    etape(8, "recompilation de l'EA")
    me = P.metaeditor_exe()
    mq5 = td / "MQL5" / "Experts" / "ACID IA V1.mq5"
    if not me:
        log("  ⚠️  metaeditor64.exe introuvable — à recompiler à la main.")
    elif not mq5.is_file():
        log("  ⚠️  « ACID IA V1.mq5 » absent du dossier Experts.")
    elif BLANC:
        log(f"  (à blanc) {me}")
    else:
        # version publique : /compile:"chemin" entre guillemets — sous forme de liste, Python
        # enveloppait tout l'argument et MetaEditor ignorait le nom avec espaces ("ACID IA V1").
        r = subprocess.run(f'"{me}" /compile:"{mq5}" /log',
                           capture_output=True, text=True, timeout=300)
        ex5 = mq5.with_suffix(".ex5")
        if ex5.is_file() and ex5.stat().st_mtime >= mq5.stat().st_mtime:
            log(f"  ✅ compilé : {ex5.name} ({ex5.stat().st_size // 1024} Ko)")
        else:
            log("  ⚠️  la compilation n'a pas produit de .ex5 à jour.")
            log("     Recompile à la main EN LIGNE DE COMMANDE (jamais depuis")
            log("     MetaEditor ouvert : il réécrit le fichier à chaque F7) :")
            log(f'       "{me}" /compile:"{mq5}" /log')

    # ── 9. mode SIMULATION ───────────────────────────────────────────────────
    etape(9, "mode de trading")
    mt = dest / "mode_trading.txt"
    log(f"  ancienne machine : {man.get('mode_trading', '?')}")
    if not BLANC:
        mt.write_text("SIMULATION", encoding="utf-8")
    log("  ▸ forcé sur SIMULATION pour le premier démarrage.")
    log("    Le retour au réel se fait depuis Telegram, à la main, une fois le")
    log("    contrôle avant vol vert. C'est volontaire : un écosystème qui")
    log("    redémarre en réel sur une machine non vérifiée, c'est de l'argent.")

    # ── 10. les ports ────────────────────────────────────────────────────────
    etape(10, "ports")
    occupes = []
    for port, nom in PORTS:
        s = socket.socket()
        s.settimeout(0.3)
        pris = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        log(f"  {port}  {nom:26} {'OCCUPÉ ⛔' if pris else 'libre'}")
        if pris:
            occupes.append(port)
    if occupes:
        log("  ⚠️  ports occupés : " + ", ".join(map(str, occupes)))
        log("     8061 est le verrou d'instance unique : s'il est pris, L'ŒIL se")
        log("     ferme immédiatement en disant qu'il tourne déjà.")
        log("     Trouve le coupable : netstat -ano | findstr \"" +
            " ".join(map(str, occupes)) + "\"")

    # ── fin ──────────────────────────────────────────────────────────────────
    log("")
    log("=" * 74)
    log("  ✅ INSTALLATION TERMINÉE" + ("  (essai à blanc)" if BLANC else ""))
    log("=" * 74)
    log(MANUEL)
    for l in man.get("a_refaire_a_la_main", []):
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
