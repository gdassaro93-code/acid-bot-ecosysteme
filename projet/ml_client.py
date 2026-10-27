# -*- coding: utf-8 -*-
# =====================================================
#  🧠 ML CLIENT — comment on parle au SEUL ML de l'écosystème (16/09/26)
#
#  Le patron : «…
#  …».
#
#  Avant, deux ML donnaient deux avis :
#    · l'EA et MAMMOUTH interrogeaient server_ml_v2 (port 8001) — un modèle
#      VTMarkets à pile ou face (AUC 0,507 mesurée le 16/09) ;
#    · le cerveau et l'arbitre lisaient ml_avis.py en direct — un modèle
#      Vantage, mais qui recevait 0 pour 3 de ses 16 données (il appelait
#      chart_patterns._impulsion, qui n'existe pas).
#  Maintenant le modèle ne vit plus qu'à UN endroit, le serveur 8001, et tout le
#  monde lui pose la question. Ce fichier ne contient AUCUN modèle : seulement
#  la façon de demander, avec un délai court et un repli muet.
#
#  POURQUOI UN DÉLAI COURT ET UN CACHE : le cerveau appelle l'arbitre à chaque
#  cycle et à chaque validation de rotation. Un serveur lent ne doit jamais
#  figer une décision : au pire le ML se tait, il n'est que consultatif.
# =====================================================
import json
import os
import time
from pathlib import Path

import requests

URL = os.environ.get("ACID_ML_URL", "http://127.0.0.1:8001")
DELAI_S = (0.5, 2.0)     # (connexion, lecture)
CACHE_S = 60
PANNE_S = 30
# 🩹 16/09 — Sous Windows, une connexion REFUSÉE en local n'échoue pas tout de
# suite : mesuré 2 012 ms serveur éteint, à chaque appel. Le cerveau interroge
# le ML à chaque cycle et à chaque validation de rotation — une panne du ML
# aurait ralenti tout le cerveau. Connexion bornée à 0,5 s, et une panne est
# mémorisée 30 s : on ne repaie pas l'attente à chaque question.
HERE = Path(__file__).resolve().parent
CARTE = HERE / "ml_data" / "modele_v2_carte.json"

_cache = {}
_panne = {"jusqua": 0.0}


def avis_lot(symboles) -> dict:
    """{nom demandé: avis} pour plusieurs marchés en UNE requête.

    Chaque avis : p_buy, p_sell (probabilités d'atteindre 2R avant un stop
    1×ATR), sens (le plus probable), p, favorable (p ≥ seuil validé),
    prediction et confidence (l'échelle que lit l'EA).
    Renvoie {} si le serveur ne répond pas — jamais d'exception."""
    noms = [str(s) for s in symboles if s]
    if not noms:
        return {}
    cle = ("lot", tuple(noms))
    c = _cache.get(cle)
    if c and time.time() - c[0] < CACHE_S:
        return c[1]
    if time.time() < _panne["jusqua"]:
        return {}
    try:
        r = requests.get(f"{URL}/api/ml/avis", params={"symbols": ",".join(noms)},
                         timeout=DELAI_S)
        if r.status_code != 200:
            _panne["jusqua"] = time.time() + PANNE_S
            return {}
        d = r.json()
        out = {}
        for a in d.get("avis", []):
            if a.get("p") is None:
                continue                 # marché inconnu du modèle : il se tait
            a["_seuil_favorable"] = d.get("seuil_favorable")
            a["_seuil_action"] = d.get("seuil_action")
            out[a.get("demande")] = a
        _cache[cle] = (time.time(), out)
        return out
    except Exception:
        _panne["jusqua"] = time.time() + PANNE_S
        return {}


def sante():
    """/health du serveur ML, ou None s'il est muet ou sans modèle (503)."""
    try:
        r = requests.get(f"{URL}/health", timeout=DELAI_S)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def carte() -> dict:
    """La fiche du modèle en service (ml_data/modele_v2_carte.json)."""
    try:
        return json.loads(CARTE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def contexte(symboles) -> str:
    """Le bloc ML du prompt du cerveau. CONSULTATIF : il informe, il n'interdit
    rien — le patron le 29/08 : «…».

    Les probabilités sont affichées avec le taux de base : «…» d'atteindre
    2R est un BON setup (le hasard fait ~30 %), pas un mauvais. Sans ce repère,
    un humain ou une IA qui lit «…» croit à un signal faible."""
    c = carte()
    if c.get("validation_annulee"):
        # 🚫 16/09 — ne plus présenter au cerveau des chiffres qui ne valent rien
        return ("🧠 ML v2 : VALIDATION ANNULÉE le 16/09 — "
                f"{c['validation_annulee'].get('pourquoi', 'fuite du futur')}. "
                "Réentraîné proprement, il ne passe pas son propre test. "
                "Ses probabilités ne sont PAS prouvées : ne t'appuie pas dessus.")
    lot = avis_lot(list(symboles)[:8])
    if not lot:
        return ""
    wf = (c.get("regle_sur_6_mois") or {})
    res = (c.get("reserve_finale") or {})
    seuil_f = next(iter(lot.values())).get("_seuil_favorable") or 0.42
    seuil_a = next(iter(lot.values())).get("_seuil_action") or 0.34
    forts, faibles = [], []
    for nom, a in lot.items():
        ligne = f"  {nom} {a['sens']} → {100 * a['p']:.0f} %"
        if a.get("favorable"):
            forts.append(ligne)
        elif a["p"] >= seuil_a:
            faibles.append(ligne)
    tete = (f"🧠 ML v2 (bougies Vantage {c.get('periode', '?')} ; question : un trade stop 1×ATR "
            f"atteint-il 2R ? — le hasard fait ~30 %). Validé sur 6 mois glissants : "
            f"{wf.get('esperance_R', '?')} R/trade au seuil {seuil_f:.2f} ; 30 derniers jours : "
            f"{res.get('reussite_filtre', '?')} % de gagnants.\n"
            f"⚠️ CONSULTATIF — aucun droit de veto : son silence n'interdit RIEN, "
            f"son accord ne dispense pas des autres juges.")
    if not forts and not faibles:
        return (tete + "\nAucun setup au-dessus de son seuil en ce moment. Si tes autres "
                       "juges sont alignés, tu peux tirer sans lui.")
    blocs = [tete]
    if forts:
        blocs.append(f"Setups qu'il juge favorables (≥ {100 * seuil_f:.0f} %) :\n" + "\n".join(forts))
    if faibles:
        blocs.append(f"Penchants plus faibles ({100 * seuil_a:.0f}-{100 * seuil_f:.0f} %) :\n"
                     + "\n".join(faibles))
    return "\n".join(blocs)
