# -*- coding: utf-8 -*-
"""
🧮➜📈 L'EXÉCUTEUR DU CONSEIL  (10/10/2026)

LE PATRON : «…
…
…»

Donc ici : AUCUN filtre de confiance, AUCUN avis du ML, AUCUN plan du jour à
respecter, AUCUN juge supplémentaire. Les quatre calculateurs de l'équipe ont
délibéré, le porte-parole a tranché, le trade passe. Le stop et la cible sont
CEUX QUE L'ÉQUIPE A CALCULÉS — on ne les retouche pas, sinon son chiffre ne
veut plus rien dire.

Ce qui reste, et qui n'est pas une approbation mais de la plomberie :
  · la taille (2 × le lot minimum du broker — l'équipe raisonne au lot mini) ;
  · la cohérence (un stop du mauvais côté du prix serait refusé par le broker) ;
  · la fraîcheur (un signal de plus de 30 min ne parle plus du marché actuel) ;
  · deux trades du conseil ouverts au maximum, pour qu'une erreur reste une
    erreur et pas une série.

Fichier séparé exprès : ACTIF = False le coupe entièrement sans toucher au
reste de l'écosystème, et son journal dit toujours ce qu'il a fait.

    python conseil_executeur.py          montre ce qu'il ferait, n'exécute rien
    python conseil_executeur.py --go     exécute les signaux en attente
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ACTIF = False   # version publique : exécution automatique du conseil coupée (elle contourne le budget de risque) - True pour réactiver
SIGNAUX = HERE / "conseil_signaux.json"
EXECUTES = HERE / "conseil_executes.json"
LOT_MULT = 2           # l'équipe raisonne au lot minimum ; on double, pas plus
FRAICHEUR_MIN = 30     # au-delà, le signal ne parle plus du marché actuel
MAX_OUVERTES = 2       # deux trades du conseil en même temps, pas davantage
MAGIC = 999111
PREFIXE = "IA_CONSEIL"


def _charger(f, defaut):
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else defaut
    except Exception:
        return defaut


def candidats(mt5):
    """Les signaux du conseil qui méritent d'être passés maintenant."""
    sigs = _charger(SIGNAUX, [])
    faits = _charger(EXECUTES, [])
    deja = {f.get("cle") for f in faits}
    ouvertes = [p for p in (mt5.positions_get() or []) if PREFIXE in str(p.comment)]
    out = []
    for s in sigs:
        cle = f"{s.get('equipe')}|{s.get('marche')}|{s.get('sens')}|{s.get('quand')}"
        if cle in deja:
            continue
        if time.time() - float(s.get("ts", 0)) > FRAICHEUR_MIN * 60:
            continue
        sym, sens = s.get("marche"), s.get("sens")
        i, t = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
        if not i or not t or sens not in ("BUY", "SELL"):
            continue
        prix = t.ask if sens == "BUY" else t.bid
        dg = i.digits or 5
        try:
            sl, tp = round(float(s.get("stop")), dg), round(float(s.get("objectif")), dg)
        except (TypeError, ValueError):
            out.append((s, cle, None, "stop ou objectif illisible"))
            continue
        bon = (sl < prix < tp) if sens == "BUY" else (tp < prix < sl)
        if not bon:
            out.append((s, cle, None, f"stop {sl} / objectif {tp} incohérents avec le prix {prix}"))
            continue
        lot = round((i.volume_min or 0.01) * LOT_MULT, 2)
        ot = mt5.ORDER_TYPE_BUY if sens == "BUY" else mt5.ORDER_TYPE_SELL
        rq = abs(float(mt5.order_calc_profit(ot, sym, lot, prix, sl) or 0))
        gn = abs(float(mt5.order_calc_profit(ot, sym, lot, prix, tp) or 0))
        out.append((s, cle, dict(sym=sym, sens=sens, lot=lot, prix=prix, sl=sl, tp=tp,
                                 risque=rq, gain=gn, places=MAX_OUVERTES - len(ouvertes)), None))
    return out


def cycle(mt5, journal=None, pour_de_vrai=True):
    """À appeler dans la boucle du CERVEAU. Rend les textes à annoncer."""
    msgs = []
    if not ACTIF:
        return msgs
    faits = _charger(EXECUTES, [])
    restant = MAX_OUVERTES - len([p for p in (mt5.positions_get() or [])
                                  if PREFIXE in str(p.comment)])
    for s, cle, plan, souci in candidats(mt5):
        if souci:
            msgs.append(f"🧮 signal {s.get('equipe')} ignoré : {souci}")
            faits.append({"cle": cle, "ignore": souci})
            continue
        if restant <= 0:
            msgs.append(f"🧮 signal {s.get('equipe')} laissé : déjà {MAX_OUVERTES} "
                        f"trades du conseil ouverts")
            continue
        if not pour_de_vrai:
            msgs.append(f"🧮 (simulation) {plan['sens']} {plan['sym']} {plan['lot']} — "
                        f"risque {plan['risque']:.2f} € · objectif {plan['gain']:.2f} €")
            continue
        r = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": plan["sym"], "volume": plan["lot"],
            "type": mt5.ORDER_TYPE_BUY if plan["sens"] == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": plan["prix"], "sl": plan["sl"], "tp": plan["tp"], "deviation": 30,
            "magic": MAGIC, "comment": f"{PREFIXE}_{str(s.get('equipe', ''))[:4]}",
            "type_filling": mt5.ORDER_FILLING_IOC})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            restant -= 1
            msgs.append(f"🧮 CONSEIL {s.get('equipe')} — {plan['sens']} {plan['sym']} "
                        f"{plan['lot']} exécuté · stop {plan['sl']} ({plan['risque']:.2f} €) · "
                        f"objectif {plan['tp']} ({plan['gain']:.2f} €) · confiance "
                        f"{s.get('confiance')}% · « {str(s.get('raison', ''))[:90]} »")
            faits.append({"cle": cle, "quand": dt.datetime.now().isoformat(timespec="seconds"),
                          "ticket": getattr(r, "order", 0),
                          "risque": round(plan["risque"], 2), "objectif": round(plan["gain"], 2),
                          **{k: s.get(k) for k in ("equipe", "marche", "sens", "confiance", "raison")}})
        else:
            msgs.append(f"🧮 signal {s.get('equipe')} refusé par le broker : "
                        f"{getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}")
            faits.append({"cle": cle, "refus": getattr(r, "retcode", "?")})
    try:
        EXECUTES.write_text(json.dumps(faits[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    if journal:
        for m in msgs:
            journal(m)
    return msgs


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import MetaTrader5 as mt5
    import mt5_garde  # noqa: F401  (MT5 ne sera jamais ressuscité)
    if not mt5.initialize():
        raise SystemExit("MT5 fermé — ouvre-le, cet exécuteur ne le lance jamais.")
    vrai = "--go" in sys.argv
    print(f"🧮➜📈 EXÉCUTEUR DU CONSEIL — {'EXÉCUTION RÉELLE' if vrai else 'simulation (rien ne part)'}\n")
    out = cycle(mt5, pour_de_vrai=vrai)
    print("\n".join("   " + m for m in out) if out else "   (aucun signal du conseil en attente)")
    mt5.shutdown()
