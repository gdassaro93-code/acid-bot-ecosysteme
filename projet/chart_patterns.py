# -*- coding: utf-8 -*-
# =====================================================
#  📐 CHART PATTERNS — les cheat sheets encodées en dur
#  Bougies japonaises + figures classiques, détection
#  mathématique déterministe (0 token IA). Utilisé par
#  L'ŒIL toutes les 15 min sur les bougies M15 réelles.
# =====================================================


def _bougie(o, h, l, c):
    corps = abs(c - o)
    total = max(h - l, 1e-12)
    return {"o": o, "h": h, "l": l, "c": c, "corps": corps, "total": total,
            "haut": h - max(o, c), "bas": min(o, c) - l,
            "vert": c > o, "rouge": c < o}


def _tendance(closes, n=8):
    """Tendance courte avant la figure (pour situer marteau vs pendu, etc.)."""
    if len(closes) < n + 1:
        return 0
    delta = closes[-1] - closes[-n]
    seuil = abs(closes[-n]) * 0.0008
    return 1 if delta > seuil else (-1 if delta < -seuil else 0)


def detecter_bougies(rates):
    """Figures de bougies sur les 3 dernières bougies CLÔTURÉES.
    rates: liste de dicts/records avec open/high/low/close (>=12 bougies).
    Retourne [{nom, sens, force(1-3)}]."""
    if rates is None or len(rates) < 12:
        return []
    o = [float(r["open"]) for r in rates]
    h = [float(r["high"]) for r in rates]
    l = [float(r["low"]) for r in rates]
    c = [float(r["close"]) for r in rates]
    # on travaille sur les bougies clôturées : la dernière (en cours) est exclue
    b1 = _bougie(o[-4], h[-4], l[-4], c[-4])   # antépénultième
    b2 = _bougie(o[-3], h[-3], l[-3], c[-3])   # avant-dernière
    b3 = _bougie(o[-2], h[-2], l[-2], c[-2])   # dernière clôturée
    trend = _tendance(c[:-1])
    out = []

    def add(nom, sens, force):
        out.append({"nom": nom, "sens": sens, "force": force})

    # --- une bougie (sur b3) ---
    if b3["corps"] <= 0.1 * b3["total"]:
        add("Doji (indécision)", "neutre", 1)
    if b3["bas"] >= 2 * b3["corps"] and b3["haut"] <= 0.35 * max(b3["corps"], 1e-12):
        if trend < 0:
            add("Marteau", "haussier", 2)
        elif trend > 0:
            add("Pendu", "baissier", 2)
    if b3["haut"] >= 2 * b3["corps"] and b3["bas"] <= 0.35 * max(b3["corps"], 1e-12):
        if trend > 0:
            add("Étoile filante", "baissier", 2)
        elif trend < 0:
            add("Marteau inversé", "haussier", 1)
    if b3["corps"] >= 0.9 * b3["total"] and b3["total"] > 0:
        add("Marubozu " + ("haussier" if b3["vert"] else "baissier"),
            "haussier" if b3["vert"] else "baissier", 2)

    # --- deux bougies (b2 -> b3) ---
    if b2["rouge"] and b3["vert"] and b3["o"] <= b2["c"] and b3["c"] >= b2["o"] and b3["corps"] > b2["corps"]:
        add("Avalement haussier", "haussier", 3)
    if b2["vert"] and b3["rouge"] and b3["o"] >= b2["c"] and b3["c"] <= b2["o"] and b3["corps"] > b2["corps"]:
        add("Avalement baissier", "baissier", 3)
    if b2["corps"] > 0 and b3["corps"] < 0.6 * b2["corps"] \
            and max(b3["o"], b3["c"]) <= max(b2["o"], b2["c"]) \
            and min(b3["o"], b3["c"]) >= min(b2["o"], b2["c"]):
        if b2["rouge"] and b3["vert"]:
            add("Harami haussier", "haussier", 1)
        if b2["vert"] and b3["rouge"]:
            add("Harami baissier", "baissier", 1)
    if abs(b2["l"] - b3["l"]) <= 0.0006 * b3["c"] and b2["rouge"] and b3["vert"] and trend < 0:
        add("Pinces de plancher (tweezer bottom)", "haussier", 2)
    if abs(b2["h"] - b3["h"]) <= 0.0006 * b3["c"] and b2["vert"] and b3["rouge"] and trend > 0:
        add("Pinces de sommet (tweezer top)", "baissier", 2)

    # --- trois bougies (b1 -> b2 -> b3) ---
    if b1["rouge"] and b1["corps"] > 0.5 * b1["total"] \
            and b2["corps"] < 0.4 * b1["corps"] \
            and b3["vert"] and b3["c"] > (b1["o"] + b1["c"]) / 2:
        add("Étoile du matin", "haussier", 3)
    if b1["vert"] and b1["corps"] > 0.5 * b1["total"] \
            and b2["corps"] < 0.4 * b1["corps"] \
            and b3["rouge"] and b3["c"] < (b1["o"] + b1["c"]) / 2:
        add("Étoile du soir", "baissier", 3)
    if all(x["vert"] for x in (b1, b2, b3)) and b2["c"] > b1["c"] and b3["c"] > b2["c"] \
            and min(x["corps"] / x["total"] for x in (b1, b2, b3)) > 0.5:
        add("Trois soldats blancs", "haussier", 3)
    if all(x["rouge"] for x in (b1, b2, b3)) and b2["c"] < b1["c"] and b3["c"] < b2["c"] \
            and min(x["corps"] / x["total"] for x in (b1, b2, b3)) > 0.5:
        add("Trois corbeaux noirs", "baissier", 3)

    return out


def detecter_figures(rates):
    """Figures de graphique sur ~60 bougies : double top/bottom, cassures.
    Retourne [{nom, sens, force}]."""
    if rates is None or len(rates) < 40:
        return []
    h = [float(r["high"]) for r in rates][:-1]
    l = [float(r["low"]) for r in rates][:-1]
    c = [float(r["close"]) for r in rates]
    prix = c[-1]
    out = []

    # sommets/creux locaux (pivots 2-2) sur les 45 dernières clôturées
    hs, ls = h[-45:], l[-45:]
    pivots_h = [(i, hs[i]) for i in range(2, len(hs) - 2)
                if hs[i] == max(hs[i - 2:i + 3])]
    pivots_l = [(i, ls[i]) for i in range(2, len(ls) - 2)
                if ls[i] == min(ls[i - 2:i + 3])]

    # Double sommet : 2 pivots hauts proches (0.2%) séparés d'au moins 5 bougies,
    # prix repassé sous le creux intermédiaire (ligne de cou)
    if len(pivots_h) >= 2:
        (i1, p1), (i2, p2) = pivots_h[-2], pivots_h[-1]
        if i2 - i1 >= 5 and abs(p1 - p2) <= 0.002 * p2:
            cou = min(ls[i1:i2 + 1]) if i2 > i1 else min(ls)
            if prix < cou:
                out.append({"nom": "Double sommet cassé (ligne de cou)", "sens": "baissier", "force": 3})
            elif prix < max(p1, p2):
                out.append({"nom": "Double sommet en formation", "sens": "baissier", "force": 1})
    # Double creux
    if len(pivots_l) >= 2:
        (i1, p1), (i2, p2) = pivots_l[-2], pivots_l[-1]
        if i2 - i1 >= 5 and abs(p1 - p2) <= 0.002 * p2:
            cou = max(hs[i1:i2 + 1]) if i2 > i1 else max(hs)
            if prix > cou:
                out.append({"nom": "Double creux cassé (ligne de cou)", "sens": "haussier", "force": 3})
            elif prix > min(p1, p2):
                out.append({"nom": "Double creux en formation", "sens": "haussier", "force": 1})

    # Cassure de range 20 bougies
    if prix > max(h[-21:-1]):
        out.append({"nom": "Cassure haussière (plus haut 20 bougies)", "sens": "haussier", "force": 2})
    if prix < min(l[-21:-1]):
        out.append({"nom": "Cassure baissière (plus bas 20 bougies)", "sens": "baissier", "force": 2})

    return out


def detecter_smc(rates):
    """🏦 Setups «…» (09/07) : Spring/Upthrust (liquidity sweep)
    + Fair Value Gaps — la partie actionnable du playbook SMC, codée en dur.
    Retourne [{nom, sens, force}]."""
    if rates is None or len(rates) < 40:
        return []
    o = [float(r["open"]) for r in rates][:-1]
    h = [float(r["high"]) for r in rates][:-1]
    l = [float(r["low"]) for r in rates][:-1]
    c = [float(r["close"]) for r in rates][:-1]     # bougies CLÔTURÉES uniquement
    prix = float(rates[-1]["close"])                # prix courant (bougie en cours)
    out = []
    tol = 0.0008 * prix                             # «…» à ~0.08% près

    # --- SPRING / UPTHRUST : mèche qui chasse la liquidité sous un niveau
    #     évident (>=2 touches) puis clôture de l'autre côté ---
    derniere = _bougie(o[-1], h[-1], l[-1], c[-1])
    zone_l, zone_h = l[-32:-2], h[-32:-2]
    if len(zone_l) >= 15:
        support = min(zone_l)
        if sum(1 for x in zone_l if x - support <= tol) >= 2 \
                and derniere["l"] < support - 0.1 * tol and derniere["c"] > support:
            force = 3 if (derniere["vert"] and derniere["corps"] >= 0.5 * derniere["total"]) else 2
            out.append({"nom": "Spring (mèche sous le support, clôture au-dessus)",
                        "sens": "haussier", "force": force})
        resistance = max(zone_h)
        if sum(1 for x in zone_h if resistance - x <= tol) >= 2 \
                and derniere["h"] > resistance + 0.1 * tol and derniere["c"] < resistance:
            force = 3 if (derniere["rouge"] and derniere["corps"] >= 0.5 * derniere["total"]) else 2
            out.append({"nom": "Upthrust (mèche au-dessus de la résistance, clôture en dessous)",
                        "sens": "baissier", "force": force})

    # --- FVG : bougie centrale si violente que les mèches de A et C ne se
    #     touchent pas → trou de valeur, aimant à prix ---
    # FVG haussier le plus récent, non comblé
    for i in range(len(c) - 3, max(len(c) - 23, 0), -1):
        if l[i + 2] > h[i]:
            bas, haut = h[i], l[i + 2]
            if (haut - bas) < 0.0005 * prix:
                continue                                  # trou insignifiant
            if any(l[j] <= bas for j in range(i + 3, len(l))):
                break                                     # déjà comblé → zone morte
            if bas <= prix <= haut:
                out.append({"nom": "Retour dans FVG haussier (zone aimant)",
                            "sens": "haussier", "force": 3})
            elif prix > haut:
                out.append({"nom": "FVG haussier ouvert en dessous (aimant)",
                            "sens": "haussier", "force": 1})
            break
    # FVG baissier le plus récent, non comblé
    for i in range(len(c) - 3, max(len(c) - 23, 0), -1):
        if h[i + 2] < l[i]:
            bas, haut = h[i + 2], l[i]
            if (haut - bas) < 0.0005 * prix:
                continue
            if any(h[j] >= haut for j in range(i + 3, len(h))):
                break
            if bas <= prix <= haut:
                out.append({"nom": "Retour dans FVG baissier (zone aimant)",
                            "sens": "baissier", "force": 3})
            elif prix < bas:
                out.append({"nom": "FVG baissier ouvert au-dessus (aimant)",
                            "sens": "baissier", "force": 1})
            break

    return out


def _atr(h, l, c, n=14):
    if len(c) < n + 2:
        return 0.0
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
           for i in range(1, len(c))]
    return sum(trs[-n:]) / n


def detecter_impulsion(rates):
    """🚀 IMPULSION — mandat patron 07/08 («…»).

    Ce que le patron trace à la règle sur son graphique : un déplacement
    FRANC, PROPRE et DIRECTIONNEL. Les figures classiques (double sommet,
    FVG…) décrivent un état qui peut traîner 3 jours ; l'impulsion, elle,
    est datée — on sait quand elle a commencé et si elle est encore vivante.

    Sortie (au plus 1 impulsion, la plus significative) :
      nom, sens, force 3-5, age (bougies depuis la fin du mouvement),
      ampleur_atr, proprete (0-1), retrace (0-1), etat :
        'en cours'  → ça part maintenant, on saute dedans
        'repli'     → ça respire, on attend la reprise (le VRAI point d'entrée)
        'reprise'   → le repli est fini et ça repart : SIGNAL D'ENTRÉE
        'morte'     → retracée à >78%, le mouvement est annulé
    """
    if rates is None or len(rates) < 30:
        return []
    o = [float(r["open"]) for r in rates][:-1]
    h = [float(r["high"]) for r in rates][:-1]
    l = [float(r["low"]) for r in rates][:-1]
    c = [float(r["close"]) for r in rates][:-1]     # clôturées uniquement
    prix = float(rates[-1]["close"])
    atr = _atr(h, l, c)
    if atr <= 0:
        return []

    best = None
    N = len(c)
    # fenêtres de 3 à 7 bougies, démarrant jusqu'à 8 bougies dans le passé
    for age in range(0, 9):
        fin = N - 1 - age
        if fin < 10:
            break
        for taille in range(3, 8):
            deb = fin - taille + 1
            if deb < 1:
                continue
            net = c[fin] - o[deb]
            if net == 0:
                continue
            sens = 1 if net > 0 else -1
            haut, bas = max(h[deb:fin + 1]), min(l[deb:fin + 1])
            etendue = max(haut - bas, 1e-12)
            ampleur = abs(net) / atr
            proprete = abs(net) / etendue          # 1.0 = ligne droite, 0.3 = bruit
            meme_sens = sum(1 for i in range(deb, fin + 1)
                            if (c[i] - o[i]) * sens > 0) / taille
            # la clôture finit-elle bien au bout du mouvement ?
            fin_nette = (c[fin] - bas) / etendue if sens > 0 else (haut - c[fin]) / etendue

            if ampleur < 1.5 or proprete < 0.55 or meme_sens < 0.6 or fin_nette < 0.6:
                continue
            score = ampleur * proprete * meme_sens
            if best is None or score > best["score"]:
                best = {"score": score, "sens": sens, "age": age, "taille": taille,
                        "ampleur": ampleur, "proprete": proprete,
                        "haut": haut, "bas": bas, "net": abs(net),
                        "extreme": haut if sens > 0 else bas}
    if best is None:
        return []

    s = best["sens"]
    mot = "haussière" if s > 0 else "baissière"
    sens_txt = "haussier" if s > 0 else "baissier"
    # retracement depuis l'extrême atteint par l'impulsion
    retrace = ((best["extreme"] - prix) if s > 0 else (prix - best["extreme"])) / max(best["net"], 1e-12)
    retrace = max(0.0, retrace)

    if retrace > 0.78:
        return [{"nom": f"Impulsion {mot} ANNULÉE (retracée {retrace * 100:.0f}%)",
                 "sens": "neutre", "force": 1, "age": best["age"], "etat": "morte",
                 "ampleur_atr": round(best["ampleur"], 2), "retrace": round(retrace, 2),
                 "proprete": round(best["proprete"], 2)}]

    force = 3
    if best["ampleur"] >= 2.5 and best["proprete"] >= 0.7:
        force = 4
    if best["ampleur"] >= 4.0 and best["proprete"] >= 0.75:
        force = 5

    # dernière bougie clôturée : repart-elle dans le sens de l'impulsion ?
    repart = (c[-1] - o[-1]) * s > 0 and abs(c[-1] - o[-1]) >= 0.25 * atr

    if best["age"] == 0 and retrace < 0.20:
        etat, nom = "en cours", f"IMPULSION {mot} en cours"
    elif 0.20 <= retrace <= 0.62 and repart:
        etat, nom = "reprise", f"REPRISE après repli d'impulsion {mot}"
        force = min(5, force + 1)          # c'est LE point d'entrée : on le majore
    elif 0.15 <= retrace <= 0.70:
        etat, nom = "repli", f"Impulsion {mot} en repli ({retrace * 100:.0f}%) — guetter la reprise"
    else:
        etat, nom = "en cours", f"IMPULSION {mot} (poussée en cours)"

    return [{"nom": f"{nom} [{best['ampleur']:.1f}xATR]", "sens": sens_txt, "force": force,
             "age": best["age"], "etat": etat,
             "ampleur_atr": round(best["ampleur"], 2), "retrace": round(retrace, 2),
             "proprete": round(best["proprete"], 2),
             "zone_reprise": round((best["extreme"] - s * 0.5 * best["net"]), 6)}]


def scanner(rates):
    """Scan complet : impulsion + bougies + figures + smart money.
    L'impulsion passe DEVANT (elle est datée, les autres décrivent un état)."""
    res = detecter_impulsion(rates) + detecter_bougies(rates) \
        + detecter_figures(rates) + detecter_smc(rates)
    for f in res:
        f.setdefault("age", 0)
    return sorted(res, key=lambda x: (-x["force"], x.get("age", 0)))


if __name__ == "__main__":
    import io, sys
    import MetaTrader5 as mt5
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    mt5.initialize()
    for sym in ["EURUSD#", "GOLD#", "BTCUSD#", "SILVER#", "US500Cash#"]:
        mt5.symbol_select(sym, True)
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 60)
        figs = scanner(r) if r is not None else []
        txt = " · ".join(f"{f['nom']} [{f['sens']} F{f['force']}]" for f in figs) or "rien"
        print(f"{sym}: {txt}")
