# -*- coding: utf-8 -*-
# =====================================================
# 🧮 COMPTEUR DE TOKENS JOURNALIER (14/07, demande patron)
# Chaque process (ŒIL, bot mammouth, arène, dashboard) appelle compte()
# après un appel IA réussi — tout atterrit dans token_stats.json, par jour,
# par moteur, par process ET (23/07) PAR FONCTION (cerveau, charts, chat de
# groupe, plan du jour…). Le dashboard l'affiche (/api/compteurs).
# Best-effort ASSUMÉ : jamais d'exception (les stats ne doivent JAMAIS
# casser la trading-loop) ; une écriture perdue en cas d'accès simultané
# est tolérable pour un compteur.
# =====================================================
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FICHIER = HERE / "token_stats.json"

# 🧵 les fonctions "tuyau" qu'on saute pour remonter au VRAI appelant métier
_WRAPPERS = {"compte", "_auto_fonction", "ask_ia", "ask_acid_ai", "_ask_mistral",
             "<lambda>", "wrapper", "in_thread"}

# 🏷️ noms de code -> étiquettes lisibles (le reste garde son nom brut)
_JOLI = {
    "ai_validate":            "charts (validation EA)",
    "_council_reply_locked":  "chat de groupe",
    "council_reply":          "chat de groupe",
    "daily_plan":             "plan du jour",
    "charts_call_du_jour":    "call charts 15h/19h",
    "briefing_text":          "briefing",
    "sniper_check":           "sniper du jour",
    "rapport_6h":             "rapport 6h",
    "pending_planner":        "pending planner",
    "plan_executor":          "plan exécuté",
    "valider_lecons":         "école",
    "corriger_lecons":        "école",
    "analyze_trade":          "MAMMOUTH analyse",
    "cerveau":                "cerveau (décision)",
}


def _auto_fonction() -> str:
    """Remonte la pile d'appels et renvoie le 1er appelant qui n'est pas un
    tuyau (ask_ia/ask_acid_ai/…). Best-effort : «…» si rien de net."""
    try:
        f = sys._getframe(2)   # 0=_auto_fonction, 1=compte, 2=le tuyau appelant
        for _ in range(12):
            if f is None:
                break
            nom = f.f_code.co_name
            if nom not in _WRAPPERS:
                return _JOLI.get(nom, nom)
            f = f.f_back
    except Exception:
        pass
    return "autre"


def compte(moteur: str, usage: dict, process: str = "?", fonction: str = None,
           duree_s: float = None):
    """usage = dict OpenAI/mammouth/mistral (prompt_tokens/completion_tokens)
    ou Anthropic (input_tokens/output_tokens). fonction : étiquette métier
    (auto-détectée si None). duree_s (16/09) : le temps que l'APPELANT a
    attendu, relances comprises. Ne lève JAMAIS."""
    try:
        e = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        s = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        fonction = fonction or _auto_fonction()
        jour = datetime.now().strftime("%Y-%m-%d")
        try:
            d = json.loads(FICHIER.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        j = d.setdefault(jour, {"entree": 0, "sortie": 0, "appels": 0,
                                "moteurs": {}, "process": {}, "fonctions": {}})
        j.setdefault("fonctions", {})   # rétro-compat fichiers d'avant 23/07
        j["entree"] += e
        j["sortie"] += s
        j["appels"] += 1
        m = j["moteurs"].setdefault(str(moteur), {"entree": 0, "sortie": 0, "appels": 0})
        m["entree"] += e
        m["sortie"] += s
        m["appels"] += 1
        fo = j["fonctions"].setdefault(str(fonction), {"entree": 0, "sortie": 0, "appels": 0})
        fo["entree"] += e
        fo["sortie"] += s
        fo["appels"] += 1
        # ⏱️ 16/09 — LA LATENCE à côté des tokens (GPT, relayé par le patron :
        # «…»). «…» compte les appels
        # chronométrés : les jours d'avant n'en ont pas, la moyenne reste juste.
        if duree_s is not None:
            fo["duree_s"] = round(fo.get("duree_s", 0.0) + float(duree_s), 2)
            fo["duree_max_s"] = round(max(fo.get("duree_max_s", 0.0), float(duree_s)), 2)
            fo["chrono"] = fo.get("chrono", 0) + 1
        j["process"][process] = j["process"].get(process, 0) + 1
        for k in sorted(d)[:-31]:   # on garde 31 jours d'historique
            d.pop(k, None)
        FICHIER.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def jour_courant() -> dict:
    """Les compteurs du jour (pour le dashboard). Ne lève jamais."""
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8")).get(
            datetime.now().strftime("%Y-%m-%d"), {})
    except Exception:
        return {}


def rapport_fonctions(jour: str = None) -> str:
    """🧾 Tableau texte de la conso PAR FONCTION du jour (pour Telegram /tokens
    ou le Centre). Trié par tokens totaux décroissants. Ne lève jamais."""
    try:
        jour = jour or datetime.now().strftime("%Y-%m-%d")
        d = json.loads(FICHIER.read_text(encoding="utf-8")).get(jour, {})
        fonctions = d.get("fonctions", {})
        if not fonctions:
            return f"🧮 Tokens {jour} : aucune donnée encore (redémarre L'ŒIL puis attends les 1ers appels)."
        tot_e, tot_s, tot_a = d.get("entree", 0), d.get("sortie", 0), d.get("appels", 0)
        # % relatif à la somme des fonctions ATTRIBUÉES (cohérent même si de
        # vieilles lignes d'avant le 23/07 n'ont pas d'étiquette de fonction).
        base = sum(v["entree"] + v["sortie"] for v in fonctions.values()) or 1
        lignes = []
        for nom, v in sorted(fonctions.items(),
                             key=lambda kv: kv[1]["entree"] + kv[1]["sortie"], reverse=True):
            tt = v["entree"] + v["sortie"]
            moy = tt // v["appels"] if v["appels"] else 0
            lat = (f" · {v['duree_s'] / v['chrono']:.1f} s/appel (max {v.get('duree_max_s', 0):.0f} s)"
                   if v.get("chrono") else "")
            lignes.append(f"• {nom} : {tt:,} tok ({100 * tt / base:.0f}%) — {v['appels']}× · ~{moy:,}/appel{lat}")
        return (f"🧮 *CONSO TOKENS — {jour}*\n"
                f"Total jour : {tot_e + tot_s:,} tok ({tot_e:,} in / {tot_s:,} out) · {tot_a} appels\n"
                f"Ventilé par fonction ({100 * base / ((tot_e + tot_s) or 1):.0f}% du jour attribué) :\n\n"
                + "\n".join(lignes)).replace(",", " ")
    except Exception as e:
        return f"🧮 rapport indisponible ({str(e)[:60]})"
