# -*- coding: utf-8 -*-
# =====================================================
#  👁️ ŒIL 3 — LA CASSURE DU RANGE D'OUVERTURE
#
#  On note le haut et le bas des N premières bougies de la séance. Quand le
#  prix casse d'un côté, on le dit au cerveau. Le stop va de l'autre côté du
#  range — sous la structure, pas à une distance arbitraire.
#
#  ── CE QUI LE JUSTIFIE (banc du 13/09) ─────────────────────────────────
#  Seule rescapée des cinq filtres sur 660 configurations de quinze familles
#  de figures (canaux, triangles, points de croisement, Fibonacci, pivots,
#  gaps, chiffres ronds, z-score, compression…) :
#      range_ouv(8 bougies) · stop sous la structure · échelle 2-3-4
#      validation +675,3 R sur 7 marchés
#      miroir −12 779,3 R   ← le sens inverse se fait massacrer
#      décalage +413,6 R    ← tient en entrant une bougie plus tard
#
#  ── L'ÉPREUVE DU PLATEAU ───────────────────────────────────────────────
#      2 bougies  −353,6 R · décalage −3414,3   ✗
#      3 bougies    +1,9 R · décalage −2083,4   ✗
#      4 bougies  +751,3 R · décalage −1042,1   ✗  ← le meilleur chiffre BRUT,
#                                                     et il échoue au décalage.
#                                                     Sans ce filtre je l'aurais
#                                                     vendu au patron.
#      6 bougies  +592,1 R · décalage   +84,7   ✓
#      8 bougies  +673,7 R · décalage  +474,5   ✓
#     12 bougies  +390,6 R · décalage  +615,0   ✓
#  Trois réglages voisins qui tiennent : c'est un plateau, pas un pic.
#
#  ── LE MARCHÉ QU'ON RETIENT, ET POURQUOI CE N'EST PAS LE PLUS RENTABLE ──
#  En euros au lot minimum, sur la moitié récente :
#      XAUUSD+ H1   X €  MAIS X € de risque par signal · DD X €
#      NAS100  H1   X €              X €
#      SP500   M30    X €               X € · DD X € · les 2 moitiés +
#  Sur X € de capital, l'or demande 12 % par signal : inapplicable, et aucun
#  lot dynamique n'y change quoi que ce soit (on ne descend pas sous le lot
#  minimum du broker). SP500 M30 est le seul à la fois propre ET payable.
#  → l'œil surveille les deux, mais il le DIT quand un signal est trop cher.
# =====================================================
import sys
import time
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from base import Oeil, Rapport, marche_frais

# 25/09 — SP500 sort (hors des 4 marchés du patron :X € = 6,1× ATR H1).
# Le pétrole n'entre PAS malgré la restriction aux 4 : mesuré ce jour sur la
# cassure de range M30, il perd dans les 3 fenêtres de test et dans les 2
# moitiés d'historique (X €, X €, X €, jamais positif) — c'est le seul
# résultat STABLE de la journée. Les 3 autres tiennent.
MARCHES_SUIVIS = ["XAUUSD+", "NAS100", "BTCUSD"]
TIMEFRAME = "M30"
BARRES_RANGE = 8          # plateau confirmé sur 6, 8 et 12
MARGE_STRUCT_ATR = 0.25   # le stop se pose un quart d'ATR au-delà du range
TP_R = (2.0, 3.0, 4.0)
MIN_BARRES = 400
RISQUE_CHER_EUR = 15.0    # au-delà, on prévient le cerveau


class OeilRange(Oeil):
    NOM = "oeil3_range"
    LIBELLE = "👁️ 3 · cassure du range d'ouverture"
    MARCHES = MARCHES_SUIVIS
    REFERENCE = {"wr": 29.0, "r_par_signal": 0.35, "signaux_jour": 0.8,
                 "risque_signal_eur": 6.48,
                 "source": "banc 13/09 · seule rescapée sur 660 configs · "
                           "plateau 6/8/12 bougies · miroir −12 779 R"}
    OBSERVATION = True

    def __init__(self):
        super().__init__()
        self._fait = {}

    def _atr(self, H, L, C, n=14):
        tr = np.maximum(H[1:] - L[1:],
                        np.maximum(np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])))
        o = np.empty(len(C)); o[0] = tr[0] if len(tr) else 0.0
        acc, a = o[0], 1.0 / n
        for i in range(1, len(C)):
            acc = a * tr[i - 1] + (1 - a) * acc
            o[i] = acc
        return o

    def _cout(self, mt5, sym, distance):
        """Ce que coûte réellement une jambe au lot minimum, en euros."""
        try:
            i = mt5.symbol_info(sym)
            p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, i.volume_min,
                                      i.ask, i.ask + distance)
            return abs(float(p or 0.0))
        except Exception:
            return 0.0

    def regarder(self, mt5):
        tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME)
        out = []
        for sym in MARCHES_SUIVIS:
            mt5.symbol_select(sym, True)
            # 🕒 un œil ne parle JAMAIS d'un marché qui ne cote plus.
            if not marche_frais(mt5, sym, 30.0):
                continue
            r = mt5.copy_rates_from_pos(sym, tf, 0, MIN_BARRES)
            if r is None or len(r) < 60:
                continue
            r = r[:-1]                            # bougies clôturées
            T = r["time"].astype(np.int64)
            O = r["open"].astype(float); H = r["high"].astype(float)
            L = r["low"].astype(float); C = r["close"].astype(float)
            A = self._atr(H, L, C)

            jours = (T // 86400).astype(np.int64)
            chg = np.where(np.diff(jours) != 0)[0] + 1
            if len(chg) < 2:
                continue
            d0 = int(chg[-1])                     # début de la séance en cours
            if len(C) - d0 <= BARRES_RANGE:
                continue                          # le range n'est pas encore formé
            jour = int(jours[-1])
            if self._fait.get(sym) == jour:
                continue                          # une cassure par séance, pas plus

            haut = float(H[d0:d0 + BARRES_RANGE].max())
            bas = float(L[d0:d0 + BARRES_RANGE].min())
            a = float(A[-1])
            if a <= 0 or haut <= bas:
                continue
            dernier = float(C[-1])

            if dernier > haut:
                sens, struct = "BUY", bas
            elif dernier < bas:
                sens, struct = "SELL", haut
            else:
                continue

            distance = abs(dernier - struct) + MARGE_STRUCT_ATR * a
            cout = self._cout(mt5, sym, distance) * len(TP_R)
            largeur_atr = (haut - bas) / a

            # un range anormalement large donne un stop inatteignable : on passe
            if largeur_atr > 6.0:
                continue

            avert = ""
            if cout > RISQUE_CHER_EUR:
                avert = (f" ⚠️ {cout:.0f} € de risque les 3 jambes au lot mini — "
                         f"trop cher pour un petit compte")

            r_ = Rapport(
                oeil=self.NOM, symbole=sym, sens=sens,
                confiance=62.0 + min(18.0, largeur_atr * 4.0),
                sl_atr=round(distance / a, 2), tp_r=TP_R,
                raison=(f"cassure du range d'ouverture {TIMEFRAME} "
                        f"({BARRES_RANGE} bougies : {bas:.2f}–{haut:.2f}, "
                        f"{largeur_atr:.1f} ATR de large) — stop de l'autre "
                        f"côté du range{avert}"),
                range_haut=round(haut, 5), range_bas=round(bas, 5),
                structure=round(struct, 5), cout_estime_eur=round(cout, 2),
                timeframe=TIMEFRAME)
            out.append(r_)
            self._fait[sym] = jour
        return out


def main():
    import logging
    import MetaTrader5 as mt5
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("oeil3")
    if not mt5.initialize():
        log.error("MT5 injoignable : %s", mt5.last_error())
        return
    o = OeilRange()
    log.info("%s démarré · %s · range %s bougies · référence %s%%%s",
             o.LIBELLE, TIMEFRAME, BARRES_RANGE, o.REFERENCE["wr"],
             " · OBSERVATION" if o.OBSERVATION else "")
    dernier = 0
    while True:
        try:
            o.cycle(mt5, log)
            if time.time() - dernier > 3600:
                n = o.resoudre(mt5)
                log.info("📚 leçon : %s résultat(s) · %s", n,
                         o.forme().get("message", ""))
                dernier = time.time()
            time.sleep(30)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("boucle : %s", e)
            time.sleep(30)
    mt5.shutdown()


if __name__ == "__main__":
    main()
