# -*- coding: utf-8 -*-
# =====================================================
#  👁️ ŒIL 2 — LA TRANSMISSION MÉTAUX → EURUSD+
#
#  Quand l'or ou l'argent fait un GROS mouvement, l'EURUSD+ suit.
#
#  ── CE QUI LE JUSTIFIE (banc du 13/09) ─────────────────────────────────
#  Point de départ : XAUUSD+ → EURUSD+, H1, n=3 bougies, seuil 2,5 ATR,
#  stop 2 ATR, échelle 2-3-4.
#      réglage +115,4 R · validation +147,4 R (327 trades, 29 %)
#      miroir −199,2 R · décalage +90,7 R · X € · drawdown X €
#
#  ── L'ÉPREUVE DU PLATEAU, celle qui compte ─────────────────────────────
#  Un pic isolé entouré d'effondrements = hasard. Ici, 380 réglages voisins
#  testés, 40 passent (10,5 % contre ~6 % de hasard), ET la structure est
#  LOGIQUE — c'est ça qui convainc :
#
#      H1  n=3  seuil 1,5 ATR  →  −633 R    ✗ les petits mouvements ne disent rien
#      H1  n=3  seuil 2,0 ATR  →  −336 R    ✗
#      H1  n=3  seuil 2,5 ATR  →  +147 R    ✓ il faut un GROS mouvement
#      H1  n=3  seuil 3,0 ATR  →  +136 R    ✓
#  et ça tient ensuite sur n = 2, 3, 5, 8, 13, en H1 comme en H4.
#
#  ── LA CORROBORATION ───────────────────────────────────────────────────
#  Sept sources testées vers EURUSD+ :
#      XAUUSD+  4/48 passent   +147,4 R
#      XAGUSD   2/48 passent    +32,1 R   ← même réglage exact
#      BTCUSD 0/48 · ETHUSD 0/48 · SP500 0/48 · NAS100 0/48 · USDX 0/48
#  Les DEUX métaux précieux marchent, aucun autre actif ne marche. Deux
#  instruments apparentés qui donnent le même résultat, ce n'est pas du bruit :
#  un gros mouvement sur les métaux, c'est un mouvement du dollar, et l'euro
#  suit. L'absence de l'USDX s'explique — l'indice dollar et l'EURUSD sont
#  quasiment le même instrument, il n'y a aucun décalage à exploiter.
#
#  ── ET SURTOUT : c'est le seul qui soit DONNÉ ──────────────────────────
#      risque par signal :X €   →  une petite part du compte
#  L'œil 1 coûte X €, l'œil 4 coûte X €. Celui-ci, le compte le porte sans
#  transpirer. C'est le premier qu'on pourra lâcher en réel.
# =====================================================
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from base import Oeil, Rapport, marche_frais

SOURCES = {
    "XAUUSD+": (3, 2.5),      # (fenêtre en bougies, seuil en ATR) — mesurés
    "XAGUSD":  (3, 2.5),
}
CIBLE = "EURUSD+"
TIMEFRAME = "H1"
SL_ATR = 2.0
TP_R = (2.0, 3.0, 4.0)
MIN_BARRES = 300


class OeilMetaux(Oeil):
    NOM = "oeil2_metaux"
    LIBELLE = "👁️ 2 · métaux → EURUSD+"
    MARCHES = list(SOURCES) + [CIBLE]
    REFERENCE = {"wr": 29.0, "r_par_signal": 0.45, "signaux_jour": 0.35,
                 "risque_signal_eur": 4.37,
                 "source": "banc 13/09 · plateau confirmé sur n=2,3,5,8,13 et "
                           "H1/H4 · corroboré par l'argent · miroir perdant"}
    OBSERVATION = True

    def __init__(self):
        super().__init__()
        self._derniere = {}

    def _atr(self, H, L, C, n=14):
        tr = np.maximum(H[1:] - L[1:],
                        np.maximum(np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])))
        o = np.empty(len(C)); o[0] = tr[0] if len(tr) else 0.0
        acc, a = o[0], 1.0 / n
        for i in range(1, len(C)):
            acc = a * tr[i - 1] + (1 - a) * acc
            o[i] = acc
        return o

    def _serie(self, mt5, sym):
        tf = getattr(mt5, "TIMEFRAME_" + TIMEFRAME)
        mt5.symbol_select(sym, True)
        r = mt5.copy_rates_from_pos(sym, tf, 0, MIN_BARRES)
        if r is None or len(r) < 40:
            return None
        r = r[:-1]
        H = r["high"].astype(float); L = r["low"].astype(float)
        C = r["close"].astype(float)
        return dict(T=r["time"].astype(np.int64), H=H, L=L, C=C,
                    A=self._atr(H, L, C))

    def regarder(self, mt5):
        # 🕒 la cible doit coter ; sinon aucun avis n'a de sens.
        if not marche_frais(mt5, CIBLE, 30.0):
            return []
        cible = self._serie(mt5, CIBLE)
        if cible is None:
            return []
        t_cible = int(cible["T"][-1])
        out = []
        for sym, (n, k) in SOURCES.items():
            if self._derniere.get(sym) == t_cible:
                continue
            if not marche_frais(mt5, sym, 30.0):
                continue
            src = self._serie(mt5, sym)
            if src is None:
                continue
            comm, ia, _ = np.intersect1d(src["T"], cible["T"], return_indices=True)
            if len(comm) < n + 5:
                continue
            C = src["C"][ia]; A = src["A"][ia]
            if A[-1] <= 0:
                continue
            mouvement = (C[-1] - C[-1 - n]) / A[-1]
            if abs(mouvement) < k:
                continue
            if abs(int(comm[-1]) - t_cible) > 7200:
                continue
            sens = "BUY" if mouvement > 0 else "SELL"
            force = min(1.0, (abs(mouvement) - k) / max(k, 1e-9))
            r = Rapport(
                oeil=self.NOM, symbole=CIBLE, sens=sens,
                confiance=58.0 + 22.0 * force, sl_atr=SL_ATR, tp_r=TP_R,
                raison=(f"{sym} {mouvement:+.2f} ATR sur {n} bougies {TIMEFRAME} "
                        f"(seuil {k}) — l'euro suit le mouvement du dollar"),
                source=sym, mouvement=round(float(mouvement), 2), seuil=k,
                fenetre=n, timeframe=TIMEFRAME)
            out.append(r)
            self._derniere[sym] = t_cible

        # or et argent sont corrélés à +0,77 : deux avis identiques, c'est UN avis
        if len(out) > 1:
            if all(r["sens"] == out[0]["sens"] for r in out):
                meilleur = max(out, key=lambda r: abs(r["mouvement"]))
                meilleur["raison"] += " · les deux métaux dans le même sens"
                meilleur["confiance"] = min(85.0, meilleur["confiance"] + 6.0)
                out = [meilleur]
            else:
                return []      # ils se contredisent : le dollar n'est pas lisible
        return out


def main():
    import logging
    import MetaTrader5 as mt5
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("oeil2")
    if not mt5.initialize():
        log.error("MT5 injoignable : %s", mt5.last_error())
        return
    o = OeilMetaux()
    log.info("%s démarré · %s · référence %s%% · risque %s €/signal%s",
             o.LIBELLE, TIMEFRAME, o.REFERENCE["wr"],
             o.REFERENCE["risque_signal_eur"],
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
