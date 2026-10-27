# -*- coding: utf-8 -*-
# =====================================================
#  🎚️ LA MÉMOIRE DES RÉGLAGES — décidée avec le patron le 08/09
#
#  SON CONSTAT, en regardant le journal :
#     «…»
#  Il avait raison. Rien que le 08/09, le cerveau a proposé :
#     05:31  scoremin 8.5 (global) · 14:55  8 sur XAUUSD+ · 15:46  8 sur EURUSD+
#     15:56  7 sur CL-OIL          · 16:06  7 sur EURUSD+
#  Il MONTE le curseur quand ça perd, il le BAISSE quand rien ne se déclenche, et il
#  recommence trois heures plus tard. Cause : il n'a AUCUN retour sur l'effet de son
#  propre réglage. Il tourne le bouton à l'aveugle.
#
#  CE MODULE LUI DONNE LA MÉMOIRE : chaque réglage appliqué est horodaté, puis on
#  mesure ce que les trades ont donné PENDANT qu'il était en vigueur. Le cerveau lit
#  le bilan avant de proposer autre chose.
#
#  Choix assumés :
#   · on n'attribue QUE les trades postérieurs au réglage et antérieurs au suivant ;
#   · en dessous de 3 trades, on n'ose aucune conclusion (on l'écrit «…») ;
#   · le bloc envoyé au cerveau tient en 6 lignes — la leçon du 08/09 sur les
#     prompts obèses (150 000 tokens par appel) vaut aussi ici.
# =====================================================
import json
import time
from pathlib import Path

FICHIER = Path(__file__).resolve().parent / "reglages_memoire.json"
MINI_TRADES = 3        # en dessous, aucune conclusion
GARDE_JOURS = 14       # on oublie au-delà
MAX_LIGNES = 6         # ce qu'on montre au cerveau


def _lire() -> list:
    try:
        d = json.loads(FICHIER.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _ecrire(d: list):
    try:
        limite = time.time() - GARDE_JOURS * 86400
        d = [x for x in d if x.get("ts", 0) >= limite][-300:]
        tmp = FICHIER.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(FICHIER)
    except Exception:
        pass


def noter(cle: str, valeur, symbole: str = "", par: str = "cerveau"):
    """Appelé à CHAQUE réglage réellement appliqué à l'EA."""
    d = _lire()
    d.append({"cle": str(cle), "valeur": str(valeur), "symbole": symbole or "*",
              "par": par, "ts": time.time()})
    _ecrire(d)


def _resultat(mt5, depuis: float, jusqua: float, symbole: str = "*"):
    """Ce que les trades ont donné entre deux instants. (n, gagnants, net €)"""
    try:
        import datetime as dt
        deals = mt5.history_deals_get(dt.datetime.fromtimestamp(depuis - 60),
                                      dt.datetime.fromtimestamp(jusqua + 60)) or []
        n = g = 0
        net = 0.0
        for x in deals:
            if getattr(x, "type", 9) > 1 or getattr(x, "entry", 0) != 1:
                continue
            if symbole != "*" and symbole not in getattr(x, "symbol", ""):
                continue
            v = x.profit + x.swap + x.commission
            n += 1
            net += v
            if v > 0:
                g += 1
        return n, g, net
    except Exception:
        return 0, 0, 0.0


def bilan(mt5) -> list:
    """Pour chaque réglage : ce qu'il a donné TANT QU'IL ÉTAIT EN VIGUEUR."""
    d = sorted(_lire(), key=lambda x: x.get("ts", 0))
    out = []
    for i, r in enumerate(d):
        # le réglage suivant SUR LA MÊME CLÉ et le même symbole met fin à celui-ci
        fin = time.time()
        for suiv in d[i + 1:]:
            if suiv["cle"] == r["cle"] and suiv["symbole"] == r["symbole"]:
                fin = suiv["ts"]
                break
        n, g, net = _resultat(mt5, r["ts"], fin, r["symbole"])
        out.append({**r, "fin": fin, "n": n, "gagnants": g, "net": net,
                    "heures": max(0.1, (fin - r["ts"]) / 3600.0)})
    return out


def contexte(mt5) -> str:
    """Le bloc lu par le cerveau AVANT de proposer un nouveau réglage."""
    b = [x for x in bilan(mt5) if x["n"] > 0]
    if not b:
        return ""
    b.sort(key=lambda x: -x["ts"])
    lignes = ["🎚️ TES RÉGLAGES PRÉCÉDENTS ET CE QU'ILS ONT DONNÉ "
              "(ne repropose pas un curseur que tu viens de bouger) :"]
    for x in b[:MAX_LIGNES]:
        ou = x["symbole"] if x["symbole"] != "*" else "partout"
        if x["n"] < MINI_TRADES:
            verdict = f"{x['n']} trade(s) — trop tôt pour conclure"
        else:
            verdict = (f"{x['n']} trades, {x['gagnants'] / x['n'] * 100:.0f}% gagnants, "
                       f"{x['net']:+.2f}€")
        lignes.append(f"  {x['cle']} = {x['valeur']} sur {ou} "
                      f"(il y a {(time.time() - x['ts']) / 3600:.0f} h) → {verdict}")
    lignes.append("Si un réglage n'a pas encore 3 trades derrière lui, LAISSE-LE VIVRE. "
                  "Ne le rebouge pas dans le même sens deux fois de suite.")
    return "\n".join(lignes)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import MetaTrader5 as mt5
    mt5.initialize()
    print(contexte(mt5) or "(aucun réglage mémorisé pour l'instant)")
    mt5.shutdown()


# ══════════════════════════════════════════════════════════════════════════
#  14/09 — LE VERROU DE PROPOSITION
#
#  Le patron, en lisant son Telegram : «…
#  …»
#  La réponse était dans le prompt : on lui présentait 25 boutons à chaque
#  cycle en lui demandant ce qu'il voulait changer. Un modèle à qui on tend
#  une carte commande quelque chose.
#
#  Ce module savait déjà REFUSER DE CONCLURE sous 3 trades. Il sait désormais
#  refuser de PROPOSER : tant qu'un réglage n'a pas 3 trades derrière lui, on
#  ne rebouge pas ce bouton-là. On ne tourne pas un curseur dont on ignore
#  encore l'effet.
# ══════════════════════════════════════════════════════════════════════════

def peut_reproposer(mt5, cle: str, symbole: str = "*") -> tuple:
    """(autorise, raison). Un réglage qui n'a pas encore 3 trades derrière lui
    ne se rebouge pas."""
    d = sorted(_lire(), key=lambda x: x.get("ts", 0))
    memes = [x for x in d if x.get("cle") == str(cle)
             and (x.get("symbole") == (symbole or "*") or symbole in ("*", ""))]
    if not memes:
        return True, ""
    dernier = memes[-1]
    age_h = (time.time() - dernier.get("ts", 0)) / 3600.0
    n, g, net = _resultat(mt5, dernier["ts"], time.time(), dernier.get("symbole", "*"))
    if n >= MINI_TRADES:
        return True, ""
    return False, (f"{cle} a été mis à {dernier.get('valeur')} il y a "
                   f"{age_h:.0f} h et n'a que {n} trade(s) derrière lui "
                   f"(il en faut {MINI_TRADES}) — on laisse vivre avant de "
                   f"rebouger ce curseur")
