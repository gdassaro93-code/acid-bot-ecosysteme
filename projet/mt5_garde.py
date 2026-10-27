# -*- coding: utf-8 -*-
"""
🚷 LE GARDE DE MT5 — un seul, partagé  (30/09/2026)

LE PATRON : «…
…».

CE QUI LE RELANÇAIT
mt5.initialize() DÉMARRE le terminal quand il n'est pas lancé — c'est le
comportement documenté du module Python, pas un bug. Un scan du 30/09 a trouvé
22 fichiers de l'écosystème qui l'appellent sans aucune garde, dont LES SIX
YEUX, qui tournent en permanence. Le patron fermait MT5, un œil faisait son
tour de veille dans la seconde, et MT5 revenait.

POURQUOI UN FICHIER PARTAGÉ ET PAS UNE COPIE PAR BOT
Le 30/09 au matin, j'ai écrit une deuxième garde dans ia_watchdog.py sans voir
que la première existait déjà. Les deux réutilisaient le même nom de variable :
l'ancienne s'est mise à s'appeler elle-même, `maximum recursion depth exceeded`
toutes les 15 secondes, et le cerveau est mort 8 h 35. D'où ce fichier unique
et IDEMPOTENT : on peut l'importer dix fois, il ne pose sa garde qu'une seule
fois et refuse d'en empiler une deuxième.

USAGE — une ligne, tout en haut, juste après l'import de MetaTrader5 :

    import MetaTrader5 as mt5
    import mt5_garde          # MT5 ne sera jamais ressuscité par ce programme

Si le terminal est fermé, mt5.initialize() rend False et le programme passe son
tour au lieu de forcer l'ouverture. Seul LE PATRON ouvre MT5 (ou le bouton
«…» du Centre, ou la tâche planifiée de reprise après reboot).
"""
import subprocess
import time

_ETAT = {"t": 0.0, "on": True}
_CACHE_S = 5.0


def terminal_ouvert(frais: bool = False) -> bool:
    """MT5 tourne-t-il DÉJÀ ?
    🩸 02/10 — le cache était le trou. Le patron ferme MT5, et pendant la durée
    du cache le garde croit encore qu'il tourne : initialize() passe, et MT5
    ressuscite. Avec frais=True on ne fait confiance qu'à une mesure de moins
    d'une seconde — c'est le cas avant chaque initialize()."""
    if time.time() - _ETAT["t"] < (1.0 if frais else _CACHE_S):
        return _ETAT["on"]
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                           capture_output=True, timeout=5, creationflags=0x08000000)
        _ETAT["on"] = b"terminal64" in (r.stdout or b"")
    except Exception:
        _ETAT["on"] = True      # dans le doute on ne bloque pas le trading
    _ETAT["t"] = time.time()
    return _ETAT["on"]


def poser(mt5) -> bool:
    """Pose la garde sur ce module mt5. Rend True si elle vient d'être posée,
    False si elle y était déjà (idempotent : jamais deux gardes empilées)."""
    brut = getattr(mt5, "initialize", None)
    if brut is None or getattr(brut, "_acid_garde", False):
        return False

    def initialize(*a, **k):
        if not terminal_ouvert(frais=True):
            return False
        return brut(*a, **k)

    initialize._acid_garde = True
    initialize._brut = brut          # récupérable si besoin, jamais relu par nom global
    mt5.initialize = initialize
    return True


# pose automatique à l'import : «…» suffit
try:
    import MetaTrader5 as _mt5
    poser(_mt5)
except Exception:
    pass
