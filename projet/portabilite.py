# -*- coding: utf-8 -*-
# =====================================================
#  🧭 PORTABILITÉ — le seul endroit qui sait OÙ SONT LES CHOSES
#
#  Écrit le 08/09/2026 au soir, pour la migration vers le nouveau portable.
#
#  LE PROBLÈME, mesuré et pas supposé :
#    · le GUID du dossier terminal MT5 (725B72F25E46C780EF59F57016D58156) est gravé
#      en dur dans acid_center.py (×2) et controle_avant_vol.py. MT5 le RÉGÉNÈRE à
#      la première ouverture sur une autre machine : ces trois chemins pointeront
#      dans le vide. Et acid_center.restore_charts() fait un shutil.rmtree() dessus.
#    · le chemin d'installation «…
#      …» est gravé dans 5 fichiers + le .bat de démarrage.
#    · «…» est gravé dans 4 fichiers — le portable aura peut-être
#      un autre nom de session.
#    · ia_watchdog.py choisit le dossier terminal par date de modification parmi
#      les 5 GUID présents sur cette machine. Ça marche aujourd'hui par chance.
#
#  LA SOLUTION : on ne devine plus, on LIT LE DISQUE.
#  Chaque dossier terminal contient un fichier origin.txt (encodé UTF-16) qui donne
#  le chemin d'installation exact du terminal auquel il appartient. C'est la source
#  de vérité, elle est fournie par MT5 lui-même et elle est vraie sur toute machine.
#
#  Rien ici ne lance MT5, n'importe MetaTrader5, ni n'écrit quoi que ce soit.
#  Lecture de disque uniquement.
# =====================================================
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Le broker qu'on cherche. Si un jour il change, c'est LA ligne à modifier.
BROKER = "Vantage"

# Repli si l'on veut forcer la main : une variable d'environnement gagne sur tout.
#   set ACID_MT5_TERMINAL=C:\Users\<toi>\AppData\Roaming\MetaQuotes\Terminal\<GUID>
ENV_TERMINAL = "ACID_MT5_TERMINAL"
ENV_EXE      = "ACID_MT5_EXE"

_cache = {}


def _appdata() -> Path:
    """%APPDATA% sans jamais graver le nom d'utilisateur."""
    v = os.environ.get("APPDATA")
    if v:
        return Path(v)
    return Path.home() / "AppData" / "Roaming"


def _lire_origin(dossier: Path) -> str:
    """origin.txt est écrit par MT5 en UTF-16. On tente aussi utf-8 par prudence :
    une version future pourrait changer, et un chemin lu à moitié vaut mieux que rien."""
    f = dossier / "origin.txt"
    for enc in ("utf-16", "utf-16-le", "utf-8", "mbcs"):
        try:
            t = f.read_text(encoding=enc).strip().replace("\x00", "")
            if t and ":" in t:
                return t
        except Exception:
            continue
    return ""


def terminaux() -> list:
    """Tous les dossiers de données MT5 de la machine, avec leur origine.
    Renvoie [{'dir': Path, 'guid': str, 'origin': str, 'broker': bool, 'vivant': bool}]
    Trié : le broker cherché d'abord, puis le plus récemment utilisé."""
    base = _appdata() / "MetaQuotes" / "Terminal"
    out = []
    try:
        candidats = [d for d in base.iterdir() if d.is_dir()]
    except Exception:
        return out
    for d in candidats:
        # Common/, Community/, Help/ ne sont pas des terminaux : un terminal a un GUID
        # de 32 caractères hexadécimaux.
        g = d.name
        if len(g) != 32 or not all(c in "0123456789ABCDEFabcdef" for c in g):
            continue
        origin = _lire_origin(d)
        mql5 = d / "MQL5"
        # «…» = MT5 a réellement initialisé ce dossier (MQL5\Files existe)
        vivant = (mql5 / "Files").is_dir()
        try:
            recent = max((p.stat().st_mtime for p in (d / "config", mql5) if p.exists()),
                         default=0.0)
        except Exception:
            recent = 0.0
        out.append({"dir": d, "guid": g, "origin": origin,
                    "broker": BROKER.lower() in origin.lower(),
                    "vivant": vivant, "recent": recent})
    out.sort(key=lambda x: (not x["broker"], not x["vivant"], -x["recent"]))
    return out


def terminal_dir(obligatoire: bool = False):
    """Le dossier de DONNÉES du terminal Vantage (celui qui contient MQL5\\Files).
    C'est lui qui porte l'EA, les presets, les profils et le pont EA↔Python.

    ATTENTION : ce n'est PAS le dossier d'installation. La confusion entre les deux
    est un vrai bug du projet (ia_watchdog.py:285 renvoyait le dossier d'install en
    dernier recours, puis allait y chercher MQL5\\Logs — qui n'y est pas)."""
    if "dir" in _cache:
        return _cache["dir"]
    forced = os.environ.get(ENV_TERMINAL)
    if forced and Path(forced).is_dir():
        _cache["dir"] = Path(forced)
        return _cache["dir"]
    for t in terminaux():
        if t["broker"] and t["vivant"]:
            _cache["dir"] = t["dir"]
            return t["dir"]
    # aucun Vantage : on prend le plus plausible plutôt que de mentir
    for t in terminaux():
        if t["vivant"]:
            _cache["dir"] = t["dir"]
            return t["dir"]
    if obligatoire:
        raise RuntimeError(
            "Aucun dossier terminal MT5 trouvé sous %APPDATA%\\MetaQuotes\\Terminal. "
            "Lance MetaTrader 5 une première fois : c'est lui qui crée ce dossier.")
    return None


def terminal_exe(obligatoire: bool = False):
    """terminal64.exe, lu depuis origin.txt du terminal retenu — jamais deviné.
    Repli : les emplacements d'installation habituels."""
    if "exe" in _cache:
        return _cache["exe"]
    forced = os.environ.get(ENV_EXE)
    if forced and Path(forced).is_file():
        _cache["exe"] = Path(forced)
        return _cache["exe"]
    d = terminal_dir()
    if d:
        o = _lire_origin(d)
        if o:
            p = Path(o) / "terminal64.exe"
            if p.is_file():
                _cache["exe"] = p
                return p
    for racine in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                   os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                   str(Path.home() / "AppData" / "Roaming")):
        try:
            for sous in Path(racine).iterdir():
                p = sous / "terminal64.exe"
                if p.is_file() and (BROKER.lower() in sous.name.lower() or True):
                    _cache["exe"] = p
                    return p
        except Exception:
            continue
    if obligatoire:
        raise RuntimeError("terminal64.exe introuvable. Installe MetaTrader 5, "
                           "ou définis la variable " + ENV_EXE + ".")
    return None


def metaeditor_exe():
    """metaeditor64.exe, à côté du terminal. Le patron compile en CLI, jamais depuis
    MetaEditor ouvert (MetaEditor réécrit le fichier à chaque F7 et écrase les
    corrections faites hors de lui)."""
    e = terminal_exe()
    if e:
        m = e.parent / "metaeditor64.exe"
        if m.is_file():
            return m
    return None


def mql5_files(obligatoire: bool = False):
    """Le bac à sable MQL5\\Files : le pont EA ↔ Python.
    (acidbot_commands.txt, acid_plan.txt, acid_cot.txt, acid_calendrier.txt,
     acid_trade_journal.csv, acid_error_memory.csv, acidbot_feedback.txt)"""
    d = terminal_dir(obligatoire)
    return (d / "MQL5" / "Files") if d else None


def mql5_experts():
    d = terminal_dir()
    return (d / "MQL5" / "Experts") if d else None


def mql5_presets():
    d = terminal_dir()
    return (d / "MQL5" / "Presets") if d else None


def profils_charts():
    """Le plan de travail : quels graphiques, quels timeframes, quel EA attaché avec
    quels paramètres.

    ⚠️ 08/09 — VÉRIFIÉ SUR LE DISQUE, et ce n'est pas là où le projet le croyait.
    Le vrai chemin est <terminal>\\MQL5\\Profiles\\Charts (profils Default, Euro,
    British Pound, Market Overview ; Default porte 9 graphiques).
    acid_center.py:442 vise <terminal>\\Profiles\\Charts — SANS le MQL5. Ce dossier
    n'existe sur AUCUNE des cinq installations de cette machine : le bouton
    «…» du Centre de contrôle ne restaure donc rien depuis le début, en
    silence (restore_charts() est enveloppé dans un except).
    On garde l'ancien chemin en repli au cas où une version de MT5 l'utiliserait."""
    d = terminal_dir()
    if not d:
        return None
    vrai = d / "MQL5" / "Profiles" / "Charts"
    if vrai.is_dir():
        return vrai
    ancien = d / "Profiles" / "Charts"
    return ancien if ancien.is_dir() else vrai


def python_exe() -> str:
    """L'interpréteur COURANT, jamais le mot «…» lâché dans le PATH.
    Sur un Windows neuf, «…» pointe très souvent vers le raccourci du
    Microsoft Store, qui ouvre le Store au lieu d'exécuter quoi que ce soit."""
    return sys.executable or "python"


def pythonw_exe() -> str:
    """Le même, sans console (pour acid_center.py)."""
    p = Path(python_exe())
    w = p.with_name("pythonw.exe")
    return str(w) if w.is_file() else str(p)


def ffmpeg_exe():
    """ffmpeg n'est PAS dans le PATH de cette machine : les appels nus à «…»
    sont déjà morts silencieusement. Le paquet imageio-ffmpeg en embarque un."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def diagnostic() -> str:
    """Ce que la machine courante offre. C'est la première chose à lire quand
    quelque chose ne marche pas sur une machine neuve."""
    L = ["🧭 PORTABILITÉ — ce que je vois sur CETTE machine", ""]
    L.append(f"  projet        : {HERE}")
    L.append(f"  python        : {python_exe()}")
    L.append(f"  version       : {sys.version.split()[0]}")
    ts = terminaux()
    L.append(f"  terminaux MT5 : {len(ts)} dossier(s) sous %APPDATA%\\MetaQuotes\\Terminal")
    for t in ts:
        marque = "◀ RETENU" if t["dir"] == terminal_dir() else ""
        L.append(f"     {t['guid'][:8]}…  "
                 f"{'vivant' if t['vivant'] else 'vide  '}  "
                 f"{t['origin'] or '(origin.txt illisible)'} {marque}")
    L.append("")
    for nom, v in (("dossier données", terminal_dir()), ("terminal64.exe", terminal_exe()),
                   ("metaeditor64.exe", metaeditor_exe()), ("MQL5\\Files", mql5_files()),
                   ("MQL5\\Experts", mql5_experts()), ("MQL5\\Presets", mql5_presets()),
                   ("Profiles\\Charts", profils_charts())):
        etat = "OK " if v and Path(v).exists() else "MANQUE"
        L.append(f"  {etat}  {nom:18} {v or '—'}")
    return "\n".join(L)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(diagnostic())
