# -*- coding: utf-8 -*-
# =====================================================
#  ⚖️ L'ARBITRE — quand les détecteurs se contredisent (02/09/26)
#
#  LE PATRON : «…».
#
#  Constat du 02/09, en direct sur le marché :
#     XAUUSD : impulsion dit BUY   ·  chasseur dit SELL
#     CL-OIL : impulsion dit SELL  ·  chasseur dit BUY
#  Deux avis opposés sur le même actif. Le cerveau reçoit ça et ne tire pas —
#  exactement la paralysie qu'on avait déjà eue le 06/08 avec les figures
#  chartistes qui s'auto-contredisaient d'un timeframe à l'autre.
#
#  LA RÈGLE D'ARBITRAGE : ce n'est ni le plus récent ni le plus bruyant qui
#  gagne, c'est CELUI QUI A RAPPORTÉ LE PLUS SUR CE MARCHÉ-LÀ. Chaque
#  détecteur a un poids par marché, tiré des backtests (spread réel inclus,
#  vérifiés sur les deux moitiés de l'historique) — pas de nos impressions.
#
#  Et quand ils sont D'ACCORD, l'arbitre le dit fort : deux détecteurs
#  indépendants qui pointent le même trade, c'est UN setup confirmé deux
#  fois — pas deux setups à prendre en double.
# =====================================================

# Edge MESURÉ par trade (R total ÷ nombre de trades du backtest).
# C'est ça qui fait le poids : un détecteur qui gagne 0,35R par trade a plus
# voix au chapitre qu'un autre à 0,12R — sur CE marché, pas dans l'absolu.
POIDS = {
    ("impulsion", "XAUUSD+"): (0.121, "+35,7R sur 295 trades"),
    ("impulsion", "NAS100"):  (0.138, "+41,4R sur 301 trades"),
    ("chasseur",  "XAUUSD+"): (0.145, "+35,0R sur 241 trades"),
    ("chasseur",  "CL-OIL"):  (0.353, "+18,0R sur 51 trades"),
    ("dollar",    "NAS100"):  (0.123, "+31,6R sur 256 trades"),
    ("dollar",    "XAGUSD"):  (0.060, "+30,3R mais instable"),
    ("ml",        "*"):       (0.030, "consultatif — ML v2 : validation ANNULÉE le 16/09 (fuite du futur) → ne vote plus"),
}
DEFAUT = (0.020, "non mesuré sur ce marché — voix faible")


def _poids(detecteur, symbole):
    if (detecteur, symbole) in POIDS:
        return POIDS[(detecteur, symbole)]
    if (detecteur, "*") in POIDS:
        return POIDS[(detecteur, "*")]
    return DEFAUT


def arbitrer(avis: dict) -> dict:
    """avis : {symbole: [(detecteur, sens), ...]}
    Retourne {symbole: {sens, force, accord, detail}} — un seul verdict par marché."""
    verdicts = {}
    for sym, liste in (avis or {}).items():
        if not liste:
            continue
        camp = {"BUY": 0.0, "SELL": 0.0}
        detail = []
        for det, sens in liste:
            p, note = _poids(det, sym)
            if sens in camp:
                camp[sens] += p
            detail.append((det, sens, p, note))
        gagnant = "BUY" if camp["BUY"] > camp["SELL"] else "SELL"
        ecart = abs(camp["BUY"] - camp["SELL"])
        total = camp["BUY"] + camp["SELL"] or 1e-9
        sens_uniques = {s for _, s in liste}
        verdicts[sym] = {
            "sens": gagnant if ecart > 0 else None,
            "force": round(ecart / total, 2),      # 1.0 = unanime, 0 = parfaitement partagé
            "accord": len(sens_uniques) == 1 and len(liste) > 1,
            "conflit": len(sens_uniques) > 1,
            "nb": len(liste),
            "detail": detail,
        }
    return verdicts


def contexte(avis: dict) -> str:
    """Le bloc que le cerveau lit : UN verdict par marché, plus d'avis opposés."""
    v = arbitrer(avis)
    if not v:
        return ""
    lignes = ["⚖️ ARBITRAGE DES DÉTECTEURS — un seul verdict par marché.",
              "Quand deux détecteurs s'opposent, celui qui a le meilleur résultat "
              "MESURÉ sur ce marché l'emporte (leur poids vient des backtests, "
              "pas de leur ordre d'arrivée). Ne prends PAS deux positions parce "
              "que deux détecteurs parlent : c'est le même trade."]
    for sym, d in sorted(v.items(), key=lambda x: -x[1]["force"]):
        src = ", ".join(f"{det}({sens})" for det, sens, _, _ in d["detail"])
        if d["accord"]:
            lignes.append(f"  ⭐ {sym} → {d['sens']} — {d['nb']} détecteurs D'ACCORD "
                          f"({src}). Setup confirmé plusieurs fois : c'est le plus "
                          f"solide qu'on ait, mais ça reste UNE position.")
        elif d["conflit"]:
            pour = [x for x in d["detail"] if x[1] == d["sens"]]
            contre = [x for x in d["detail"] if x[1] != d["sens"]]
            lignes.append(
                f"  ⚔️ {sym} → {d['sens']} l'emporte (netteté {d['force']:.0%}). "
                f"POUR : {', '.join(f'{a}[{n}]' for a, _, _, n in pour)} — "
                f"CONTRE : {', '.join(f'{a}[{n}]' for a, _, _, n in contre)}. "
                f"Si la netteté est faible (<30%), c'est que le marché est "
                f"ambigu : mieux vaut ne rien faire que trancher à pile ou face.")
        else:
            det, sens, _, note = d["detail"][0]
            lignes.append(f"     {sym} → {sens} — {det} seul ({note})")
    return "\n".join(lignes)


def collecter(mt5, chart_patterns, symboles) -> dict:
    """Ramasse l'avis de chaque détecteur. Aucun n'écrase l'autre : ils
    déposent tous leur bulletin, l'arbitrage se fait après."""
    avis = {}
    def ajoute(sym, det, sens):
        avis.setdefault(sym, []).append((det, sens))

    for sym in list(symboles)[:10]:
        try:
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 120)
            if r is None or len(r) < 60:
                continue
            imp = chart_patterns.detecter_impulsion(r)
            if imp and imp[0]["etat"] != "morte" and imp[0]["force"] >= 4:
                ajoute(sym, "impulsion", "BUY" if imp[0]["sens"] == "haussier" else "SELL")
        except Exception:
            pass
    try:
        import signal_dollar
        for o in signal_dollar.lire():
            ajoute(o["symbol"], "dollar", o["sens"])
    except Exception:
        pass
    try:
        import chasseur_tendance
        for o in chasseur_tendance.lire():
            ajoute(o["symbol"], "chasseur", o["sens"])
    except Exception:
        pass
    try:
        # 🧠 16/09 — le ML du serveur 8001, en une seule requête pour tous les
        # marchés. Et le sens VOTÉ est le plus probable des deux : avant, la
        # boucle testait BUY puis SELL et s'arrêtait au premier «…»,
        # donc un BUY limite passait devant un SELL franc (biais acheteur).
        import ml_client
        for sym, a in ml_client.avis_lot(list(symboles)[:8]).items():
            if a.get("favorable") and a.get("sens") in ("BUY", "SELL"):
                ajoute(sym, "ml", a["sens"])
    except Exception:
        pass
    return avis


if __name__ == "__main__":
    import MetaTrader5 as mt5
    import chart_patterns as cp
    mt5.initialize()
    a = collecter(mt5, cp, ["XAUUSD+", "NAS100", "BTCUSD", "CL-OIL", "EURUSD+", "XAGUSD"])
    print(contexte(a) or "(aucun détecteur n'a de signal)")
    mt5.shutdown()
