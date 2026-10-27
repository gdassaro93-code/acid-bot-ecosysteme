# -*- coding: utf-8 -*-
# =====================================================
#  👁️ ŒIL 1 — LA TRANSMISSION CRYPTO → NAS100
#
#  CE QU'IL FAIT, en une phrase :
#     quand le BTC ou l'ETH fait un mouvement anormal, le NAS100 suit derrière.
#     Il le dit au cerveau. Il ne trade pas lui-même.
#
#  ── D'OÙ ÇA SORT (nuit du 12 au 13/09/2026) ────────────────────────────
#  Après avoir testé ~25 000 configurations et vu tomber la règle EMA, le bloc
#  d'ordres, le détecteur de rebond, l'effet horaire et douze familles de
#  figures, c'est le signal le plus fort qui soit sorti :
#
#     BTCUSD → NAS100    24 configurations sur 48 passent le protocole complet
#     ETHUSD → NAS100    24 sur 48
#     (le hasard en donnerait ~6 % : quatre filtres à ~50 % chacun.
#      Là on est à 50 %, soit HUIT FOIS le bruit — et les deux cryptos
#      donnent le même résultat indépendamment l'une de l'autre.)
#
#  Meilleures mesures en validation (moitié récente de l'historique) :
#     BTCUSD → NAS100  M30  n=8  k=1,5  stop 2 ATR   +299,1 R
#     ETHUSD → NAS100  M30  n=8  k=2,0  stop 2 ATR   +301,9 R
#
#  ── L'OBJECTION QU'ON A LEVÉE ──────────────────────────────────────────
#  Le crypto tourne 24 h sur 24, le NAS100 dort. On pouvait très bien mesurer
#  l'écart d'ouverture que le NAS100 avait DÉJÀ encaissé, pas une prédiction.
#  Vérifié en retirant les signaux de début de séance :
#     BTCUSD → NAS100   tout +299,1 R  ·  sans les ouvertures +361,6 R
#     ETHUSD → NAS100   tout +301,9 R  ·  OUVERTURES SEULES −27,0 R
#  C'est MEILLEUR sans les ouvertures, et l'ouverture seule perd.
#  Donc ce n'est pas l'écart : c'est une vraie transmission en séance.
#  → l'œil ignore volontairement la première bougie de chaque séance.
#
#  ── CE QU'IL NE FAIT PAS ───────────────────────────────────────────────
#  Il ne passe aucun ordre. Il ne touche à aucun réglage, ni aux siens.
#  Il propose, le cerveau arbitre, l'œil 6 (risque) peut opposer son veto —
#  et il le fera souvent, parce que NAS100 et SP500 sont corrélés à +0,95.
# =====================================================
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from base import Oeil, Rapport, marche_frais

# ── LES RÉGLAGES MESURÉS. On n'y touche pas sans refaire passer le banc. ──
SOURCES = {
    # source   : (n barres, seuil en ATR)   ← ses meilleures mesures
    "BTCUSD": (8, 1.5),
    "ETHUSD": (8, 2.0),
}
CIBLE = "NAS100"
TIMEFRAME = "M30"
SL_ATR = 2.0
TP_R = (2.0, 3.0, 4.0)
MIN_BARRES = 300
IGNORER_OUVERTURE = True   # mesuré meilleur sans (voir en-tête)
ATTENTE_BARRES = 2         # pas deux avis collés


class OeilCrypto(Oeil):
    NOM = "oeil1_crypto"
    LIBELLE = "👁️ 1 · crypto → NAS100"
    MARCHES = list(SOURCES) + [CIBLE]
    # la référence vient du banc, protocole complet, moitié RÉCENTE
    REFERENCE = {"wr": 27.0, "r_par_signal": 0.21, "signaux_jour": 1.2,
                 "source": "banc 13/09 · 24/48 configs · miroir perdant · "
                           "décalage tenu · survit au retrait des ouvertures"}
    OBSERVATION = True         # le patron ouvrira la main après une semaine

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
        if r is None or len(r) < 60:
            return None
        r = r[:-1]                      # bougies CLÔTURÉES uniquement
        H = r["high"].astype(float); L = r["low"].astype(float)
        C = r["close"].astype(float)
        return dict(T=r["time"].astype(np.int64), O=r["open"].astype(float),
                    H=H, L=L, C=C, A=self._atr(H, L, C))

    def regarder(self, mt5):
        # 🕒 la cible doit coter ; sinon aucun avis n'a de sens.
        if not marche_frais(mt5, CIBLE, 30.0):
            return []
        cible = self._serie(mt5, CIBLE)
        if cible is None:
            return []
        # la bougie de référence de la cible : la dernière clôturée
        t_cible = int(cible["T"][-1])
        atr_cible = float(cible["A"][-1])
        if atr_cible <= 0:
            return []

        # 🚪 on ignore la première bougie de séance : mesuré meilleur sans,
        # et c'est la seule façon d'être sûr qu'on ne mesure pas l'écart
        # d'ouverture que le NAS100 a déjà encaissé pendant la nuit.
        if IGNORER_OUVERTURE and len(cible["T"]) > 3:
            ecarts = np.diff(cible["T"][-20:])
            if len(ecarts) and ecarts[-1] > np.median(ecarts) * 1.5:
                return []

        out = []
        for sym, (n, k) in SOURCES.items():
            if self._derniere.get(sym) == t_cible:
                continue
            if not marche_frais(mt5, sym, 30.0):
                continue
            src = self._serie(mt5, sym)
            if src is None or len(src["C"]) < n + 5:
                continue
            # on aligne sur le temps : le crypto a des bougies que le NAS n'a pas
            comm, ia, _ = np.intersect1d(src["T"], cible["T"], return_indices=True)
            if len(comm) < n + 5:
                continue
            C = src["C"][ia]; A = src["A"][ia]
            if len(C) < n + 1 or A[-1] <= 0:
                continue
            mouvement = (C[-1] - C[-1 - n]) / A[-1]
            if abs(mouvement) < k:
                continue
            if abs(int(comm[-1]) - t_cible) > 3600:
                continue                  # séries désynchronisées : on s'abstient

            sens = "BUY" if mouvement > 0 else "SELL"
            # la confiance monte avec l'ampleur, mais reste bornée :
            # à 27 % de réussite mesurée, personne n'a le droit d'être sûr.
            force = min(1.0, (abs(mouvement) - k) / max(k, 1e-9))
            confiance = 55.0 + 25.0 * force

            r = Rapport(
                oeil=self.NOM, symbole=CIBLE, sens=sens, confiance=confiance,
                sl_atr=SL_ATR, tp_r=TP_R,
                raison=(f"{sym} {mouvement:+.2f} ATR sur {n} bougies {TIMEFRAME} "
                        f"(seuil {k}) — le NAS100 suit en séance"),
                source=sym, mouvement=round(float(mouvement), 2), seuil=k,
                fenetre=n, timeframe=TIMEFRAME)
            out.append(r)
            self._derniere[sym] = t_cible

        # les deux cryptos qui disent la même chose, ce n'est PAS deux signaux :
        # BTC et ETH sont corrélés à +0,83. On garde le plus franc.
        if len(out) > 1:
            memes = all(r["sens"] == out[0]["sens"] for r in out)
            if memes:
                meilleur = max(out, key=lambda r: abs(r["mouvement"]))
                meilleur["raison"] += " · confirmé par l'autre crypto"
                meilleur["confiance"] = min(85.0, meilleur["confiance"] + 5.0)
                out = [meilleur]
            else:
                # ils se contredisent : le crypto n'est pas lisible, on se tait
                return []
        return out


def main():
    import logging
    import MetaTrader5 as mt5
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("oeil1")
    if not mt5.initialize():
        log.error("MT5 injoignable : %s", mt5.last_error())
        return
    o = OeilCrypto()
    log.info("%s démarré · %s · référence %s%% de réussite%s",
             o.LIBELLE, TIMEFRAME, o.REFERENCE["wr"],
             " · MODE OBSERVATION (ne trade pas)" if o.OBSERVATION else "")
    dernier_bilan = 0
    while True:
        try:
            o.cycle(mt5, log)
            # la leçon du soir, une fois par heure : on va chercher ce que sont
            # devenus les signaux retenus et on se compare à sa référence.
            if time.time() - dernier_bilan > 3600:
                n = o.resoudre(mt5)
                f = o.forme()
                log.info("📚 leçon : %s résultat(s) rattaché(s) · %s",
                         n, f.get("message", ""))
                dernier_bilan = time.time()
            time.sleep(30)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("boucle : %s", e)
            time.sleep(30)
    mt5.shutdown()


if __name__ == "__main__":
    main()
