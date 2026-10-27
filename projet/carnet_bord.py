# -*- coding: utf-8 -*-
# =====================================================
#  📓 CARNET DE BORD — la mémoire courte du trader (02/09/26)
#
#  LE PATRON : «…
#  …».
#
#  Ce qui manquait pour ça n'était pas un modèle de plus. C'était la chose
#  la plus banale chez un humain : SE SOUVENIR DE SA SEMAINE.
#  Aujourd'hui, quand un trade se ferme, personne ne se demande pourquoi.
#  Le lendemain le bot repart de zéro. Un trader, lui, se dit «…
#  …» — sans qu'on lui code une
#  règle pour ça. Il l'a juste VÉCU et il s'en souvient.
#
#  ⚠️ CE N'EST PAS DU ML, ET C'EST VOLONTAIRE.
#  On a appris à nos dépens (21/08) qu'entraîner un modèle sur les trades
#  passés du patron — 38,8% de réussite — apprend à REPRODUIRE les pertes.
#  Ici on ne fabrique aucun modèle : on pose des faits récents sous les yeux
#  du cerveau au moment où il décide. La différence est capitale : un modèle
#  généralise le passé et l'impose ; un carnet rappelle et laisse juger.
#
#  Deux usages :
#     enregistrer(mt5)  → à chaque cycle, ramasse les trades qui viennent
#                         de se fermer et note leur contexte
#     contexte(mt5)     → le bloc que le cerveau lit avant de décider
# =====================================================
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CARNET = HERE / "carnet_bord.jsonl"
VU = HERE / "carnet_vu.json"

FENETRE_JOURS = 7        # la mémoire est COURTE, comme celle d'un humain
MIN_CAS = 3              # en dessous, on ne tire aucune conclusion


def _lus() -> set:
    try:
        return set(json.loads(VU.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _marquer(tickets: set):
    try:
        garde = sorted(tickets)[-4000:]      # on ne garde pas l'infini
        VU.write_text(json.dumps(garde), encoding="utf-8")
    except Exception:
        pass


def _tendance_h1(mt5, sym, ts) -> str:
    """Le marché montait ou descendait au moment du trade ?"""
    try:
        r = mt5.copy_rates_from(sym, mt5.TIMEFRAME_H1, ts, 30)
        if r is None or len(r) < 25:
            return "?"
        c = [float(x["close"]) for x in r]
        return "hausse" if c[-1] > c[-25] else "baisse"
    except Exception:
        return "?"


def enregistrer(mt5) -> int:
    """Ramasse les trades fermés depuis le dernier passage. Retourne le nombre noté."""
    try:
        deb = datetime.now() - timedelta(days=2)
        deals = mt5.history_deals_get(deb, datetime.now() + timedelta(hours=4)) or []
    except Exception:
        return 0
    vus = _lus()
    nouveaux = 0
    lignes = []
    for d in deals:
        if d.entry != 1:                     # 1 = sortie de position
            continue
        cle = str(d.ticket)
        if cle in vus:
            continue
        vus.add(cle)
        pnl = d.profit + d.swap + d.commission      # le résultat NET, frais compris
        qui = {999111: "OEIL", 0: "patron", 777777: "MAMMOUTH",
               777999: "MAMMOUTH"}.get(d.magic,
                                       "ACID_IA" if str(d.magic).startswith("2026") else str(d.magic))
        t = datetime.fromtimestamp(d.time)
        lignes.append({
            "ts": int(d.time), "date": t.strftime("%Y-%m-%d %H:%M"), "heure": t.hour,
            "symbole": d.symbol, "sens": "BUY" if d.type == 1 else "SELL",
            "volume": d.volume, "pnl": round(pnl, 2), "qui": qui,
            "tendance": _tendance_h1(mt5, d.symbol, t),
            "commentaire": (d.comment or "")[:40],
        })
        nouveaux += 1
    if lignes:
        try:
            with open(CARNET, "a", encoding="utf-8") as f:
                for l in lignes:
                    f.write(json.dumps(l, ensure_ascii=False) + "\n")
        except Exception:
            pass
        _marquer(vus)
    return nouveaux


def _recents():
    limite = time.time() - FENETRE_JOURS * 86400
    out = []
    try:
        for ligne in CARNET.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ligne)
                if d.get("ts", 0) >= limite:
                    out.append(d)
            except Exception:
                pass
    except Exception:
        pass
    return sorted(out, key=lambda x: x["ts"])


def contexte(mt5=None) -> str:
    """Le bloc que le cerveau lit AVANT de décider. Des faits vécus, pas des règles."""
    r = _recents()
    if len(r) < MIN_CAS:
        return ("📓 CARNET DE BORD : pas encore assez de trades fermés cette semaine "
                "pour en tirer quoi que ce soit. Je note au fur et à mesure.")
    total = sum(x["pnl"] for x in r)
    gagnes = sum(1 for x in r if x["pnl"] > 0)
    lignes = [f"📓 CARNET DE BORD — ce que TU as vécu ces {FENETRE_JOURS} derniers jours "
              f"(ce ne sont pas des règles, ce sont des FAITS : sers-t'en pour juger, "
              f"pas pour obéir aveuglément).",
              f"Bilan : {len(r)} trades fermés, {gagnes} gagnants "
              f"({100 * gagnes / len(r):.0f}%), {total:+.2f}€ au total."]

    # ── ce qui marche et ce qui rate, par symbole ET par sens ──
    par = {}
    for x in r:
        k = (x["symbole"], x["sens"])
        e = par.setdefault(k, [0, 0.0, 0])
        e[0] += 1
        e[1] += x["pnl"]
        e[2] += 1 if x["pnl"] > 0 else 0
    forts = [(k, v) for k, v in par.items() if v[0] >= MIN_CAS]
    if forts:
        forts.sort(key=lambda z: z[1][1])
        pires = [f"{k[0]} {k[1]} ({v[0]} fois, {v[1]:+.2f}€)"
                 for k, v in forts if v[1] < 0][:3]
        bons = [f"{k[0]} {k[1]} ({v[0]} fois, {v[1]:+.2f}€)"
                for k, v in reversed(forts) if v[1] > 0][:3]
        if pires:
            lignes.append("🔴 Ce qui t'a COÛTÉ : " + " · ".join(pires)
                          + " — demande-toi si ça vaut le coup de recommencer.")
        if bons:
            lignes.append("🟢 Ce qui t'a RAPPORTÉ : " + " · ".join(bons))

    # ── les heures qui saignent ──
    heures = {}
    for x in r:
        e = heures.setdefault(x["heure"], [0, 0.0])
        e[0] += 1
        e[1] += x["pnl"]
    mauvaises = [f"{h}h ({v[0]} trades, {v[1]:+.2f}€)"
                 for h, v in sorted(heures.items()) if v[0] >= MIN_CAS and v[1] < -1]
    if mauvaises:
        lignes.append("⏰ Heures où ça part mal : " + " · ".join(mauvaises[:4]))

    # ── trader contre la tendance, ça donne quoi chez nous ? ──
    contre = [x for x in r if (x["sens"] == "BUY" and x["tendance"] == "baisse")
              or (x["sens"] == "SELL" and x["tendance"] == "hausse")]
    avec = [x for x in r if x not in contre and x["tendance"] != "?"]
    if len(contre) >= MIN_CAS and len(avec) >= MIN_CAS:
        pc = sum(x["pnl"] for x in contre)
        pa = sum(x["pnl"] for x in avec)
        lignes.append(f"🌊 Dans le sens de la tendance H1 : {len(avec)} trades, {pa:+.2f}€. "
                      f"À contre-courant : {len(contre)} trades, {pc:+.2f}€.")

    # ── la série en cours : es-tu en train de t'enfoncer ? ──
    serie = 0
    for x in reversed(r):
        if x["pnl"] < 0:
            serie += 1
        else:
            break
    if serie >= 3:
        lignes.append(f"🥊 ATTENTION : {serie} pertes D'AFFILÉE, la dernière il y a "
                      f"{(time.time() - r[-1]['ts']) / 3600:.0f} h. Quand ça s'enchaîne, "
                      f"le marché a changé ou le réglage ne colle plus — un humain "
                      f"lèverait le pied et regarderait avant de re-tirer.")

    # ── les 5 derniers, en clair ──
    lignes.append("Les 5 derniers : " + " | ".join(
        f"{x['symbole']} {x['sens']} {x['pnl']:+.2f}€" for x in r[-5:]))
    return "\n".join(lignes)


if __name__ == "__main__":
    import MetaTrader5 as mt5
    mt5.initialize()
    n = enregistrer(mt5)
    print(f"({n} nouveau(x) trade(s) noté(s))\n")
    print(contexte(mt5))
    mt5.shutdown()
