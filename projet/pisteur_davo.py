# -*- coding: utf-8 -*-
"""
🦅 LE PISTEUR DAVO  (28/09/2026)

LE PATRON, mot pour mot :
  «…
    …
    …»
  «…
    …»
  «…
    …»
  «…»
  «…
    …»
  «…
    …»
  «…»

CE QU'ON GARDE DE DAVO, ET CE QU'ON JETTE
  ON GARDE  : ses CIBLES et son SENS. C'est ce à quoi le patron fait confiance —
              «…».
  ON JETTE  : son STOP. Le patron ne lui fait pas confiance («…
              …»). Le stop est le NÔTRE : la distance qui coûte exactement
              la part de mise allouée, pas un pip de plus.
  ON IGNORE : son prix d'entrée. On entre AU MARCHÉ quand l'écart à une cible
              entre dans la fenêtre — inutile d'attendre son point d'entrée.

L'ESCALIER, TEL QU'IL LE DÉCRIT
  DAVO donne TP1, TP2, TP3. Chaque cible mérite SA position, déclenchée quand le
  prix arrive à ECART_MAX_USD d'elle. Comme les cibles sont à des distances
  différentes, elles se déclenchent l'une après l'autre au fil du mouvement —
  c'est un escalier, pas une rafale. La QUATRIÈME vise 10 $ au-delà de la
  dernière cible : c'est le bonus si ça dépasse.

LA FENÊTRE, EN DOLLARS
  Ses «…» valent 20 à 50 $ sur l'or (1 pip = 0,10 $). Son exemple
  chiffré — cible 4205 alors qu'on est à 4255 — fait pile 50 $. La fenêtre est
  donc [ECART_MIN_USD ; ECART_MAX_USD] = [20 ; 50] $ : en dessous il ne reste
  plus assez à prendre, au-dessus le prix n'est pas encore en approche.

LE RISQUE, ET LE CHOIX QUI LUI REVIENT
  Il a autorisé X € de stop pour UNE position. Quatre positions font X €,
  soit une grosse part d'un petit compte — et sa limite de perte journalière est de
 X €. On ne peut pas avoir les deux. Le module plafonne donc l'ESCALIER
  ENTIER à PERTE_MAX_PANIER_EUR et répartit la mise entre les positions
  réellement ouvertes. Mettre PERTE_MAX_PANIER_EUR = 200 rend à chaque position
  ses X € pleins : c'est un chiffre, il est ici, il se change en une seconde.

CE QUE ÇA CASSE, ET POURQUOI C'EST ASSUMÉ
  0.05 lot dépasse la loi des 0.02, et la mise dépasse le plafond de 2,5 % par
  trade. Le patron l'a autorisé pour CE module et pour lui seul. D'où ce fichier
  séparé : mesurable à part (commentaire IA_DAVO, ligne dédiée dans les leçons
  chiffrées du cerveau) et coupable d'un seul booléen.

    python pisteur_davo.py              # ce qu'il ferait MAINTENANT (n'ouvre rien)
    python pisteur_davo.py --histoire   # ce qu'il aurait vu sur une semaine
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# ── Les réglages. Tout est ici, rien n'est en dur dans le code. ───────────
ACTIF            = False    # version publique : coupé (lot fixe 0.05, hors budget commun) — False = il regarde et note, il n'ouvre rien
CANAUX_DAVO      = ("DAVO",)
MARCHES_OK       = ("XAUUSD+",)   # l'or et rien d'autre (ordre du patron)
LOT              = 0.05
ECART_MIN_USD    = 20.0     # patron 28/09 : «…»
ECART_MAX_USD    = 30.0     # «…» — on démarre serré, on élargira
BONUS_USD        = 10.0     # la 4e position «…»
PERTE_MAX_EUR    = 10.0     # patron 28/09 : «…»
PERTE_MAX_PANIER_EUR = 40.0   # 4 marches ×X € — l'escalier entier reste sous sa limite du jour
MAX_POSITIONS    = 4        # TP1 + TP2 + TP3 + la quatrième
FRAICHEUR_H      = 48.0     # «…»
MEME_CIBLE_H     = 12.0     # on ne rejoue pas la même cible avant ce délai
EQUITY_MINI      = 300.0    # en dessous, 0.05 lot n'a plus rien à faire ici
NEWS_FENETRE_MIN = 20.0     # pas d'entrée dans cette fenêtre autour d'une news HIGH
MAGIC            = 999111   # celui du CERVEAU : ses protections gèrent les positions
COMMENT          = "IA_DAVO"

CALENDRIER = Path(__import__("portabilite").mql5_files() or HERE) / "acid_calendrier_histo.csv"
# (version publique : le calendrier est trouvé par portabilite.py, plus de chemin gravé en dur)

_deja = {}          # (symbole, cible) -> ts du dernier passage à l'acte


def _vrai_symbole(mt5, sym):
    """Le nom coté chez le broker : DAVO écrit «…», Vantage dit «…»."""
    for c in (sym, sym + "+", sym.rstrip("+#"), sym.rstrip("+#") + "+"):
        i = mt5.symbol_info(c)
        if i and getattr(i, "trade_mode", 0) == mt5.SYMBOL_TRADE_MODE_FULL:
            return c
    return None


def _euros(mt5, sym, sens, depart, arrivee, lot=LOT):
    """Ce que vaut un trajet de prix, en euros — demandé au broker, pas estimé."""
    ot = mt5.ORDER_TYPE_BUY if sens == "BUY" else mt5.ORDER_TYPE_SELL
    v = mt5.order_calc_profit(ot, sym, lot, depart, arrivee)
    return float(v) if v is not None else 0.0


def stop_pour(mt5, sym, sens, prix, mise, lot=LOT):
    """La distance de stop qui coûte EXACTEMENT `mise` euros au lot donné.
    C'est notre stop, pas celui de DAVO : le patron n'y croit pas."""
    ref = max(abs(prix) * 0.001, 1e-9)
    par_unite = abs(_euros(mt5, sym, sens, prix,
                           prix + (ref if sens == "BUY" else -ref), lot)) / ref
    if par_unite <= 0:
        return None, 0.0
    d = mise / par_unite
    return ((prix - d) if sens == "BUY" else (prix + d)), d


def news_proche():
    """Une news HAUTE importance dans les minutes qui viennent ? (quoi, souci)
    🛡️ Ce module envoie ses ordres EN DIRECT : il ne passe par aucun veto du
    cerveau. Un 0.05 lot sur l'or trente secondes avant un FOMC, c'est exactement
    la perte que le patron refuse. On lit le même calendrier que l'EA. Si le
    fichier est illisible on laisse passer, mais on le DIT : un garde-fou muet
    ne vaut rien (leçon du 28/09 — cf. les 25 028 échecs silencieux)."""
    try:
        lignes = CALENDRIER.read_text(encoding="cp1252", errors="replace").splitlines()
    except Exception as e:
        return None, f"calendrier illisible ({e}) — je tire quand même"
    now = time.time()
    for l in lignes:
        p = l.split("|")
        if len(p) >= 4 and p[2] == "HIGH":
            try:
                quand = int(p[0])
            except ValueError:
                continue
            if abs(quand - now) <= NEWS_FENETRE_MIN * 60:
                return f"{p[3][:40]} dans {(quand - now) / 60:+.0f} min", None
    return None, None


def occasions(mt5, heures=FRAICHEUR_H):
    """Les marches de l'escalier à poser MAINTENANT.
    Ne lit que l'archive et les prix : n'ouvre rien, ne modifie rien."""
    import canaux_signaux as CS
    out = []
    for m in CS.signaux_recents(heures=heures):
        canal = str(m.get("canal") or m.get("source") or "")
        if not any(d in canal.upper() for d in CANAUX_DAVO):
            continue
        s = m.get("signal") or {}
        sym_brut, sens = s.get("symbol"), s.get("sens")
        cibles = [float(t) for t in (s.get("tps") or ([s.get("tp")] if s.get("tp") else [])) if t]
        if not sym_brut or sens not in ("BUY", "SELL") or not cibles:
            continue
        sym = _vrai_symbole(mt5, sym_brut)
        if not sym or sym not in MARCHES_OK:
            continue
        t = mt5.symbol_info_tick(sym)
        if not t:
            continue
        prix = t.ask if sens == "BUY" else t.bid
        signe = 1.0 if sens == "BUY" else -1.0
        cibles = sorted(set(cibles), key=lambda x: (x - prix) * signe)
        # 🪜 la 4e marche : 10 $ au-delà de la cible la plus lointaine
        derniere = cibles[-1]
        marches = [(f"TP{k+1}", c) for k, c in enumerate(cibles)]
        marches.append(("bonus", derniere + signe * BONUS_USD))
        for nom, cible in marches:
            ecart = (cible - prix) * signe
            if not (ECART_MIN_USD <= ecart <= ECART_MAX_USD):
                continue                    # pas encore en approche, ou déjà trop tard
            cle = (sym, round(cible, 5))
            if time.time() - _deja.get(cle, 0) < MEME_CIBLE_H * 3600:
                continue
            out.append(dict(sym=sym, sens=sens, prix=prix, cible=cible, marche=nom,
                            ecart=ecart, gain=_euros(mt5, sym, sens, prix, cible),
                            age_h=(time.time() - m["ts"]) / 3600, cle=cle))
    return out


def _ouvertes(mt5):
    return [p for p in (mt5.positions_get() or [])
            if p.magic == MAGIC and COMMENT in str(p.comment)]


def _garde_fous(mt5):
    """Ce qui empêche de tirer, même sur une belle marche. «…» :
    il a autorisé une mise qui dépasse volontairement le plafond commun, ça ne
    veut pas dire sans limite.
      1. la journée : sa limite de perte quotidienne est de X €. On ne lance pas
         un escalier par-dessus une journée déjà bien rouge.
      2. le capital : 0.05 lot sur un petit compte, c'est un tiers du compte par
         trade. Sous EQUITY_MINI, ce module se tait.
      3. les news : le seul veto du cerveau qu'on lui rend."""
    a = mt5.account_info()
    if not a:
        return "compte illisible", None
    if a.equity < EQUITY_MINI:
        return f"capital {a.equity:.0f} € sous le minimum de {EQUITY_MINI:.0f} €", None
    try:
        import datetime as _dt
        import budget_risque as B
        plafond = float(getattr(B, "PERTE_JOUR_MAX_EUR", 0.0) or 0.0)
        if plafond > 0:
            debut = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            jour = sum(d.profit + d.swap + d.commission
                       for d in (mt5.history_deals_get(debut, _dt.datetime.now()) or []))
            if jour <= -plafond * 0.5:
                return (f"journée déjà à {jour:+.2f} € (limite {plafond:.0f} €)"), None
    except Exception:
        pass
    quoi, souci = news_proche()
    if quoi:
        return f"news haute importance : {quoi}", None
    return None, souci


def mise_par_position(mt5):
    """La part du panier allouée à la prochaine position. L'escalier entier ne
    dépasse jamais PERTE_MAX_PANIER_EUR, quoi qu'il arrive."""
    deja = len(_ouvertes(mt5))
    restant = MAX_POSITIONS - deja
    if restant <= 0:
        return 0.0
    part = min(PERTE_MAX_EUR, PERTE_MAX_PANIER_EUR / MAX_POSITIONS)
    return part


def tirer(mt5, o, mise):
    i = mt5.symbol_info(o["sym"])
    sl, dist = stop_pour(mt5, o["sym"], o["sens"], o["prix"], mise)
    if sl is None:
        return False, "impossible de calculer le stop"
    dg = i.digits or 5
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": o["sym"], "volume": LOT,
        "type": mt5.ORDER_TYPE_BUY if o["sens"] == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": o["prix"], "sl": round(sl, dg), "tp": round(o["cible"], dg),
        "deviation": 30, "magic": MAGIC, "comment": f"{COMMENT}_{o['marche']}",
        "type_filling": mt5.ORDER_FILLING_IOC})
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        _deja[o["cle"]] = time.time()
        return True, (f"🦅 DAVO {o['marche']} — {o['sens']} {o['sym']} {LOT} vers "
                      f"{round(o['cible'], dg)} (à {o['ecart']:.1f} $) : {o['gain']:.0f} € visés "
                      f"pour {mise:.0f} € risqués, stop {round(sl, dg)}")
    return False, f"refus broker {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}"


def cycle(mt5, journal=None):
    """À appeler dans la boucle du CERVEAU. Rend les textes à annoncer."""
    msgs = []
    occ = occasions(mt5)
    if not ACTIF:
        for o in occ:
            msgs.append(f"👁️ DAVO {o['marche']} (observation) {o['sens']} {o['sym']} vers "
                        f"{o['cible']} à {o['ecart']:.1f} $ — rien pris")
    else:
        stop, avertissement = _garde_fous(mt5)
        if avertissement:
            msgs.append(f"⚠️ pisteur DAVO : {avertissement}")
        if stop:
            if occ:
                msgs.append(f"🦅 DAVO : {len(occ)} marche(s) laissée(s) — {stop}")
        else:
            for o in occ:
                mise = mise_par_position(mt5)
                if mise <= 0:
                    msgs.append(f"🦅 DAVO {o['marche']} laissée : escalier déjà complet "
                                f"({MAX_POSITIONS} positions)")
                    continue
                ok, txt = tirer(mt5, o, mise)
                msgs.append(txt if ok else f"🦅 DAVO {o['marche']} non prise : {txt}")
    if journal:
        for m in msgs:
            journal(m)
    return msgs


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import MetaTrader5 as mt5
    import mt5_garde          # noqa: F401 — MT5 ne sera jamais ressuscité
    if not mt5.initialize():
        raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
    heures = 24 * 7 if "--histoire" in sys.argv else FRAICHEUR_H
    occ = occasions(mt5, heures=heures)
    part = min(PERTE_MAX_EUR, PERTE_MAX_PANIER_EUR / MAX_POSITIONS)
    print(f"🦅 PISTEUR DAVO — {len(occ)} marche(s) prête(s) sur {heures:.0f} h")
    print(f"   fenêtre {ECART_MIN_USD:.0f}–{ECART_MAX_USD:.0f} $ d'une cible · {LOT} lot · "
          f"{part:.0f} € par position · escalier plafonné à {PERTE_MAX_PANIER_EUR:.0f} € · or uniquement")
    a = mt5.account_info()
    if a:
        print(f"   compte {a.equity:.0f} € · l'escalier complet risquerait "
              f"{PERTE_MAX_PANIER_EUR:.0f} € = {100 * PERTE_MAX_PANIER_EUR / a.equity:.1f} % du compte\n")
    for o in occ:
        i = mt5.symbol_info(o["sym"])
        sl, d = stop_pour(mt5, o["sym"], o["sens"], o["prix"], part)
        print(f"   {o['marche']:<6}{o['sens']:<5}{o['sym']:<9} prix {round(o['prix'], i.digits):<10}"
              f"→ {round(o['cible'], i.digits):<10} (écart {o['ecart']:>5.1f} $) · "
              f"{o['gain']:>5.0f} € visés pour {part:.0f} € · stop {round(sl, i.digits)} · "
              f"signal vieux de {o['age_h']:.0f} h")
    if not occ:
        print("   (aucune cible DAVO dans la fenêtre en ce moment)")
    mt5.shutdown()
