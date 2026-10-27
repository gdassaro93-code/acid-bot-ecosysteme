# -*- coding: utf-8 -*-
# =====================================================
#  👁️ ŒIL 4 — LE CHOC DE VOLATILITÉ
#
#  Une bougie dont l'amplitude écrase la normale, c'est l'empreinte d'un
#  événement. On suit le sens du choc.
#
#  ── POURQUOI «…» ET PAS LE CALENDRIER ──────────────────────
#  Le paquet Python de MT5 n'expose AUCUNE fonction calendrier — seul un EA
#  peut lire le calendrier économique du terminal, et il n'en donne que le
#  futur proche, pas l'historique. Impossible donc de backtester «…
#  …». On teste donc ce que l'événement LAISSE SUR LE GRAPHIQUE :
#  une amplitude anormale. C'est mesurable sur des années.
#
#  ── CE QUI LE JUSTIFIE (banc du 13/09, phase événementielle) ───────────
#      choc(seuil 3,5 ATR, continuation) · stop 3 ATR · échelle 2-3-4
#      validation +500,1 R · 29,5 % de réussite · 1 432 trades
#      miroir −836,3 R  ·  décalage +623,4 R  ·  7 marchés des deux côtés
#  8 configurations retenues au protocole complet sur 96 testées. Le seuil
#  voisin (2,5 ATR) passe aussi : +385,8 R. C'est un plateau, pas un pic.
#
#  On a aussi testé, dans la même passe : le pic de volume, le premier
#  vendredi du mois (NFP) et l'effet jour du mois. Le choc d'amplitude est
#  le seul des quatre à tenir.
#
#  ── SON PROBLÈME, ET IL EST SÉRIEUX ────────────────────────────────────
#      risque par signal :X €  →  une grosse part d'un petit compte
#  Un choc de volatilité a par construction une grande amplitude, donc un
#  stop large, donc un ticket cher. C'est structurel : on ne peut pas le
#  réduire sans dénaturer la figure, et le lot dynamique n'y peut rien (on
#  ne descend pas sous le lot minimum du broker).
#  → cet œil est d'abord un GUETTEUR. Il signale les chocs sur tous les
#    marchés, il chiffre le coût réel, et il dit lui-même quand c'est
#    inabordable. Au cerveau et à l'œil 6 de trancher.
# =====================================================
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from base import Oeil, Rapport, marche_frais

MARCHES_SUIVIS = ["NAS100", "SP500", "XAUUSD+", "BTCUSD", "ETHUSD",
                  "EURUSD+", "USDJPY+", "XAGUSD"]
TIMEFRAME = "H1"
SEUIL_ATR = 3.5           # mesuré ; 2,5 passe aussi (+385,8 R)
SL_ATR = 3.0
TP_R = (2.0, 3.0, 4.0)
MIN_BARRES = 300
RISQUE_CHER_EUR = 15.0


class OeilChoc(Oeil):
    NOM = "oeil4_choc"
    LIBELLE = "👁️ 4 · choc de volatilité"
    MARCHES = MARCHES_SUIVIS
    REFERENCE = {"wr": 29.5, "r_par_signal": 0.35, "signaux_jour": 0.5,
                 "risque_signal_eur": 57.95,
                 "force": "solide en R, mais cher pour un petit compte",
                 "source": "banc 13/09 phase événementielle · 8 retenues sur 96 · "
                           "miroir −836 R · décalage +623 R · seuil voisin 2,5 "
                           "passe aussi"}
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
            if not marche_frais(mt5, sym, 30.0):
                continue
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, tf, 0, MIN_BARRES)
            if r is None or len(r) < 40:
                continue
            r = r[:-1]                          # la bougie DOIT être clôturée
            T = r["time"].astype(np.int64)
            O = r["open"].astype(float); H = r["high"].astype(float)
            L = r["low"].astype(float); C = r["close"].astype(float)
            A = self._atr(H, L, C)

            t = int(T[-1])
            if self._fait.get(sym) == t:
                continue
            # l'ATR se mesure AVANT le choc, sinon le choc gonfle sa propre
            # référence et le seuil devient inatteignable.
            a = float(A[-2]) if len(A) > 1 else float(A[-1])
            if a <= 0:
                continue
            amplitude = float(H[-1] - L[-1])
            if amplitude < SEUIL_ATR * a:
                continue
            corps = float(C[-1] - O[-1])
            if abs(corps) < 0.35 * amplitude:
                continue                        # grande mèche, pas de direction
            sens = "BUY" if corps > 0 else "SELL"

            distance = SL_ATR * a
            cout = self._cout(mt5, sym, distance) * len(TP_R)
            avert = ""
            if cout > RISQUE_CHER_EUR:
                avert = (f" ⚠️ {cout:.0f} € de risque les 3 jambes au lot mini — "
                         f"inabordable sous {cout * 8:.0f} € de capital")

            force = min(1.0, (amplitude / a - SEUIL_ATR) / SEUIL_ATR)
            out.append(Rapport(
                oeil=self.NOM, symbole=sym, sens=sens,
                confiance=60.0 + 18.0 * force, sl_atr=SL_ATR, tp_r=TP_R,
                raison=(f"choc de volatilité : bougie {TIMEFRAME} de "
                        f"{amplitude / a:.1f} ATR (seuil {SEUIL_ATR}), corps "
                        f"{abs(corps) / amplitude * 100:.0f}% — on suit le "
                        f"sens du choc{avert}"),
                amplitude_atr=round(amplitude / a, 2),
                cout_estime_eur=round(cout, 2), timeframe=TIMEFRAME))
            self._fait[sym] = t
        return out


def main():
    import logging
    import MetaTrader5 as mt5
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("oeil4")
    if not mt5.initialize():
        log.error("MT5 injoignable : %s", mt5.last_error())
        return
    o = OeilChoc()
    log.info("%s démarré · %s · seuil %s ATR · référence %s%%%s",
             o.LIBELLE, TIMEFRAME, SEUIL_ATR, o.REFERENCE["wr"],
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
