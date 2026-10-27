# -*- coding: utf-8 -*-
# =====================================================
#  👁️ ŒIL 5 — LE BLOC DEVISES. L'USDJPY+ suit les autres.
#
#  ── POURQUOI CET ŒIL EXISTE ────────────────────────────────────────────
#  Le patron, 13/09 : le bloc devises est le seul que son compte puisse
#  trader à pleine capacité. Les chiffres lui donnent raison :
#      indices   6 à X € le signal      métaux   37 à X €
#      crypto   25 à X €                DEVISES  2,5 à X €
#  Sur X €, un signal devises coûte 1 % du capital. Un signal or en coûte 12.
#
#  ── CE QUE LA MESURE A TROUVÉ (carte du 13/09, 240 sens testés) ────────
#  L'USDJPY+ est la cible la plus suiviste du bloc : 9 des 25 meilleures
#  transmissions pointent dessus. Les meilleures sources, par taux de passage
#  au protocole complet (le hasard en donnerait ~6 %) :
#
#      AUDJPY+  → USDJPY+   23,9 %   +109,0 R   X €
#      CADJPY+  → USDJPY+   18,1 %    +73,2 R  X €
#      CHFJPY+  → USDJPY+   12,7 %   +153,0 R   X €
#      EURGBP+  → USDJPY+   12,5 %    +87,6 R  X €   ← sans yen
#      USDX     → USDJPY+   11,1 %    +53,9 R   X €   ← sans yen
#
#  ── L'OBJECTION MÉCANIQUE, ET POURQUOI ELLE TOMBE ──────────────────────
#  CHFJPY, AUDJPY, CADJPY partagent la jambe yen avec USDJPY+. Leur
#  «…» pouvait n'être qu'une décomposition du même mouvement.
#  Mais l'EURGBP+ (12,5 %) et l'USDX (11,1 %), qui n'ont pas de yen dedans,
#  passent aussi bien que les croisées. Ce n'est donc pas mécanique.
#
#  ── SA FAIBLESSE, DITE FRANCHEMENT ─────────────────────────────────────
#      œil 1 (crypto → NAS100)   50 % de passage   =  8× le bruit
#      œil 5 (devises)         12-24 %             =  2 à 4× le bruit
#  C'est le plus faible des cinq détecteurs. D'où sa construction :
#  IL EXIGE UN ACCORD ENTRE PLUSIEURS SOURCES, dont au moins une SANS yen.
#  Un signal isolé ne suffit pas ici — il suffisait pour l'œil 1, pas pour lui.
#  Le plateau confirme aussi qu'il faut un GROS mouvement : à seuil 1,5 ATR
#  ça perd (−4,0 R puis −26,9 R), à 2,0-3,0 ça passe.
# =====================================================
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from base import Oeil, Rapport, marche_frais

# source : (fenêtre, seuil ATR, contient du yen ?) — réglages mesurés
SOURCES = {
    "AUDJPY+": (3, 2.5, True),
    "CHFJPY+": (2, 2.0, True),
    "CADJPY+": (2, 2.5, True),
    "EURGBP+": (5, 3.0, False),
    "USDX":    (5, 3.0, False),
}
CIBLE = "USDJPY+"
TIMEFRAME = "H1"
SL_ATR = 2.0
TP_R = (2.0, 3.0, 4.0)
MIN_BARRES = 300

# ── la règle propre à cet œil : il n'a pas le droit de parler seul ──────
MIN_SOURCES_ACCORD = 2      # au moins deux sources dans le même sens
EXIGER_UNE_SANS_YEN = True  # dont au moins une qui ne partage pas la jambe yen


class OeilDevises(Oeil):
    NOM = "oeil5_devises"
    LIBELLE = "👁️ 5 · devises → USDJPY+"
    MARCHES = list(SOURCES) + [CIBLE]
    REFERENCE = {"wr": 28.0, "r_par_signal": 0.30, "signaux_jour": 0.25,
                 "risque_signal_eur": 5.30,
                 "force": "faible — 2 à 4× le bruit (l'œil 1 est à 8×)",
                 "source": "carte des devises 13/09 · 240 sens testés · "
                           "plateau 16/117 (13,7 % contre 6 % de hasard) · "
                           "objection mécanique levée par EURGBP+ et USDX"}
    OBSERVATION = True

    def __init__(self):
        super().__init__()
        self._derniere = None

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
        if not marche_frais(mt5, CIBLE, 30.0):
            return []
        cible = self._serie(mt5, CIBLE)
        if cible is None:
            return []
        t_cible = int(cible["T"][-1])
        if self._derniere == t_cible:
            return []

        avis = []
        for sym, (n, k, a_du_yen) in SOURCES.items():
            if not marche_frais(mt5, sym, 30.0):
                continue
            src = self._serie(mt5, sym)
            if src is None:
                continue
            comm, ia, _ = np.intersect1d(src["T"], cible["T"], return_indices=True)
            if len(comm) < n + 5:
                continue
            C = src["C"][ia]; A = src["A"][ia]
            if A[-1] <= 0 or abs(int(comm[-1]) - t_cible) > 7200:
                continue
            mv = (C[-1] - C[-1 - n]) / A[-1]
            if abs(mv) < k:
                continue
            avis.append({"source": sym, "mouvement": float(mv),
                         "sens": 1 if mv > 0 else -1, "yen": a_du_yen,
                         "seuil": k, "fenetre": n})

        if len(avis) < MIN_SOURCES_ACCORD:
            return []

        # il faut un accord franc : on regarde le sens majoritaire
        pour = [a for a in avis if a["sens"] > 0]
        contre = [a for a in avis if a["sens"] < 0]
        camp = pour if len(pour) >= len(contre) else contre
        if len(camp) < MIN_SOURCES_ACCORD:
            return []
        if len(pour) and len(contre):
            # les sources se contredisent : le dollar-yen n'est pas lisible
            return []
        if EXIGER_UNE_SANS_YEN and not any(not a["yen"] for a in camp):
            # que des croisées yen : on ne peut pas distinguer l'avance du
            # simple partage de la jambe yen. On s'abstient.
            return []

        self._derniere = t_cible
        sens = "BUY" if camp[0]["sens"] > 0 else "SELL"
        ampleur = float(np.mean([abs(a["mouvement"]) for a in camp]))
        seuil_moy = float(np.mean([a["seuil"] for a in camp]))
        force = min(1.0, (ampleur - seuil_moy) / max(seuil_moy, 1e-9))
        # 🔒 plafond de confiance volontairement BAS : c'est le plus faible
        # des détecteurs, il n'a pas le droit de se présenter comme le plus sûr.
        confiance = 52.0 + 16.0 * force + 4.0 * (len(camp) - MIN_SOURCES_ACCORD)

        detail = " · ".join(f"{a['source']} {a['mouvement']:+.1f} ATR"
                            for a in camp)
        return [Rapport(
            oeil=self.NOM, symbole=CIBLE, sens=sens,
            confiance=min(74.0, confiance), sl_atr=SL_ATR, tp_r=TP_R,
            raison=(f"{len(camp)} sources d'accord ({detail}) — l'USDJPY+ suit. "
                    f"Détecteur faible : accord obligatoire, dont une source "
                    f"sans yen."),
            sources=[a["source"] for a in camp],
            n_accord=len(camp), ampleur=round(ampleur, 2),
            timeframe=TIMEFRAME)]


def main():
    import logging
    import MetaTrader5 as mt5
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("oeil5")
    if not mt5.initialize():
        log.error("MT5 injoignable : %s", mt5.last_error())
        return
    o = OeilDevises()
    log.info("%s démarré · %s · référence %s%% · %s sources minimum%s",
             o.LIBELLE, TIMEFRAME, o.REFERENCE["wr"], MIN_SOURCES_ACCORD,
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
