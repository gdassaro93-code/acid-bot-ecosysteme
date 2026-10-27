# -*- coding: utf-8 -*-
# =====================================================
#  🛡️ ŒIL 6 — LE RISQUE. Le seul qui ait un droit de veto.
#
#  Il ne regarde pas le marché. IL REGARDE LES CINQ AUTRES.
#
#  ── POURQUOI IL EXISTE, mesuré le 13/09 ────────────────────────────────
#  Corrélation des rendements horaires sur 12 673 bougies communes :
#
#        NAS100 / SP500     +0,95      le même risque
#        BTCUSD / ETHUSD    +0,83      le même risque
#        XAUUSD+/ XAGUSD    +0,77      le même risque
#        EURUSD+/ USDX      −0,95      le même risque, à l'envers
#        NAS100 / BTCUSD    +0,46      à moitié lié
#
#  Les huit marchés de l'écosystème ne sont pas huit marchés : ce sont QUATRE
#  BLOCS. Et le montage à six yeux crée mécaniquement le problème :
#      œil 1 (crypto→NAS100)  prend du NAS100
#      œil 3 (range d'ouv.)   son meilleur marché est SP500
#      œil 4 (choc volat.)    tire surtout sur les indices
#  Trois yeux peuvent ouvrir LA MÊME POSITION sous trois noms différents. Le
#  patron croirait avoir trois signaux indépendants ; il aurait une exposition
#  en triple, et trois fois la perte si ça se retourne.
#
#  ── CE QUE LA DIVERSIFICATION VAUT VRAIMENT ────────────────────────────
#  Mesuré en phase 4 du banc, sur la cassure du range d'ouverture tenue sur
#  six marchés en même temps :
#      somme des drawdowns individuels :X €
#      drawdown de la courbe combinée  :X €   →  divisé par 2,07
#  C'est le seul repas gratuit trouvé de toute la nuit. Mais il n'existe QUE
#  si les positions sont réellement décorrélées. D'où cet œil.
#
#  ── LA MAIN DU PATRON ──────────────────────────────────────────────────
#  Ses positions (magic 0) COMPTENT dans l'exposition — elles risquent de
#  l'argent réel. Mais elles ne sont JAMAIS fermées, réduites ni déplacées.
#  Règle constante depuis le début : rien ne touche à sa main.
#  Concrètement : s'il est déjà chargé en actions, l'œil 6 refuse aux AUTRES
#  yeux d'en rajouter. Il protège son exposition, il ne la corrige pas.
# =====================================================
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from base import Oeil, BLOCS, BLOCS_LIES, bloc_de, tous_les_rapports, RAPPORTS

# ── LES PLAFONDS. Discutables, mais explicites — et jamais modifiés seuls. ──
MAX_BLOCS_OUVERTS = 3          # au-delà, on ne diversifie plus, on s'éparpille
MAX_LIGNES_PAR_BLOC = 2        # deux lignes sur le même bloc, c'est déjà double
RISQUE_MAX_PCT = 6.0           # % du capital exposé, tous blocs confondus
RISQUE_MAX_BLOC_PCT = 2.5      # % sur un seul bloc
LIEN_COMPTE_POUR = 0.5         # un bloc lié à 0,46 compte pour une demi-ligne


class OeilRisque(Oeil):
    NOM = "oeil6_risque"
    LIBELLE = "🛡️ 6 · risque (veto)"
    MARCHES = []
    REFERENCE = {"wr": 0.0, "r_par_signal": 0.0, "signaux_jour": 0.0,
                 "source": "corrélations mesurées le 13/09 sur 12 673 bougies H1"}
    OBSERVATION = False        # lui n'observe pas : il arbitre dès le premier jour

    # ── l'état réel du compte, blocs compris ─────────────────────────────
    def exposition(self, mt5) -> dict:
        a = mt5.account_info()
        capital = float(a.balance) if a else 0.0
        pos = mt5.positions_get() or []
        blocs = {}
        for p in pos:
            b = bloc_de(p.symbol)
            e = blocs.setdefault(b, {"lignes": 0, "risque": 0.0, "symboles": [],
                                     "a_la_main": 0, "sens": 0})
            e["lignes"] += 1
            e["symboles"].append(p.symbol)
            e["sens"] += 1 if p.type == 0 else -1
            if p.magic == 0:
                e["a_la_main"] += 1
            # le risque réel : la distance au stop, en euros. Sans stop, on
            # compte le flottant courant — c'est le minimum honnête.
            try:
                if p.sl:
                    d = abs(p.price_open - p.sl)
                    pr = mt5.order_calc_profit(
                        mt5.ORDER_TYPE_BUY if p.type == 0 else mt5.ORDER_TYPE_SELL,
                        p.symbol, p.volume, p.price_open,
                        p.price_open + (d if p.type != 0 else -d))
                    e["risque"] += abs(float(pr or 0.0))
                else:
                    e["risque"] += abs(float(p.profit))
            except Exception:
                pass
        total = sum(v["risque"] for v in blocs.values())
        return {"capital": capital, "blocs": blocs, "risque_total": total,
                "risque_pct": (total / capital * 100.0) if capital > 0 else 0.0,
                "n_blocs": len(blocs), "n_positions": len(pos)}

    def _charge_liee(self, blocs: dict, bloc: str) -> float:
        """Combien de lignes pèse déjà ce bloc, en comptant les blocs liés.
        actions et crypto sont corrélés à +0,46 : chacun compte pour moitié
        dans la charge de l'autre."""
        charge = float(blocs.get(bloc, {}).get("lignes", 0))
        for a, b, c in BLOCS_LIES:
            autre = b if a == bloc else (a if b == bloc else None)
            if autre:
                charge += blocs.get(autre, {}).get("lignes", 0) * LIEN_COMPTE_POUR
        return charge

    # ── l'arbitrage : ce que les autres yeux proposent, ce qui passe ─────
    def arbitrer(self, mt5) -> dict:
        exp = self.exposition(mt5)
        blocs = exp["blocs"]
        capital = exp["capital"]

        propositions = []
        for d in tous_les_rapports():
            if d.get("oeil") == self.NOM or d.get("perime"):
                continue
            if not d.get("actif", True):
                continue
            for r in d.get("rapports", []):
                r = dict(r)
                r["_observation"] = d.get("observation", True)
                r["_ref_wr"] = (d.get("reference") or {}).get("wr", 0.0)
                r["_forme"] = (d.get("forme") or {}).get("etat", "inconnu")
                propositions.append(r)

        verdicts = []
        # on traite les meilleures d'abord : forme correcte, puis référence
        propositions.sort(key=lambda r: (r["_forme"] == "en dessous",
                                         -r.get("_ref_wr", 0),
                                         -r.get("confiance", 0)))
        blocs_pris = set(blocs)
        deja_ce_tour = {}

        for r in propositions:
            b = r.get("bloc", "autre")
            motifs = []
            verdict = "PASSE"

            # 1. deux yeux sur le même bloc pendant ce tour : un seul passe
            if b in deja_ce_tour:
                verdict = "VETO"
                motifs.append(f"{deja_ce_tour[b]} a déjà pris le bloc {b} "
                              f"ce tour — même risque sous un autre nom")

            # 2. le bloc est-il déjà chargé ?
            charge = self._charge_liee(blocs, b)
            if verdict == "PASSE" and charge >= MAX_LIGNES_PAR_BLOC:
                verdict = "VETO"
                dont = blocs.get(b, {}).get("a_la_main", 0)
                m = f"bloc {b} déjà chargé ({charge:.1f} ligne(s))"
                if dont:
                    m += f" dont {dont} à ta main — je n'y touche pas, je bloque le reste"
                motifs.append(m)

            # 3. le nombre de blocs simultanés
            if verdict == "PASSE" and b not in blocs_pris \
                    and len(blocs_pris) >= MAX_BLOCS_OUVERTS:
                verdict = "VETO"
                motifs.append(f"{len(blocs_pris)} blocs déjà ouverts "
                              f"(plafond {MAX_BLOCS_OUVERTS}) — au-delà on ne "
                              f"diversifie plus, on s'éparpille")

            # 4. le budget
            if verdict == "PASSE" and capital > 0:
                if exp["risque_pct"] >= RISQUE_MAX_PCT:
                    verdict = "VETO"
                    motifs.append(f"risque total {exp['risque_pct']:.1f}% du "
                                  f"capital (plafond {RISQUE_MAX_PCT}%)")
                else:
                    rb = blocs.get(b, {}).get("risque", 0.0) / capital * 100.0
                    if rb >= RISQUE_MAX_BLOC_PCT:
                        verdict = "REDUIT"
                        motifs.append(f"bloc {b} déjà à {rb:.1f}% du capital "
                                      f"(plafond {RISQUE_MAX_BLOC_PCT}%) — demi-taille")

            # 5. un œil en mauvaise forme passe, mais à taille réduite
            if verdict == "PASSE" and r.get("_forme") == "en dessous":
                verdict = "REDUIT"
                motifs.append(f"{r['oeil']} est sous sa référence en ce moment "
                              f"— demi-taille le temps qu'il revienne")

            # 6. un œil en observation ne trade pas, mais on garde la trace
            if r.get("_observation"):
                motifs.append("œil en observation — avis noté, pas exécuté")

            if verdict in ("PASSE", "REDUIT"):
                deja_ce_tour[b] = r["oeil"]
                blocs_pris.add(b)

            verdicts.append({**r, "verdict": verdict,
                             "taille": 0.5 if verdict == "REDUIT" else
                                       (1.0 if verdict == "PASSE" else 0.0),
                             "motifs": motifs})
        return {"exposition": exp, "verdicts": verdicts}

    def regarder(self, mt5):
        """L'œil 6 ne produit pas de signal : il produit un ARBITRAGE.
        Il publie donc directement, avec sa propre forme de rapport."""
        a = self.arbitrer(mt5)
        exp = a["exposition"]
        d = {"oeil": self.NOM, "libelle": self.LIBELLE, "actif": self.ACTIF,
             "observation": False, "reference": self.REFERENCE,
             "forme": {"etat": "arbitre", "message":
                       f"{exp['n_positions']} position(s) · {exp['n_blocs']} bloc(s) · "
                       f"{exp['risque_pct']:.1f}% du capital exposé"},
             "marches": [], "ts": time.time(),
             "exposition": exp, "verdicts": a["verdicts"], "rapports": []}
        try:
            tmp = self.rapport_f.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1,
                                      default=float), encoding="utf-8")
            tmp.replace(self.rapport_f)
        except Exception:
            pass
        return []

    def resume(self, mt5) -> str:
        """Ce que le cerveau récitera sur Telegram."""
        a = self.arbitrer(mt5)
        exp = a["exposition"]
        L = [f"🛡️ RISQUE — {exp['n_positions']} position(s) sur "
             f"{exp['n_blocs']} bloc(s) · {exp['risque_pct']:.1f}% du capital"]
        for b, v in sorted(exp["blocs"].items(), key=lambda x: -x[1]["risque"]):
            main = f" (dont {v['a_la_main']} à ta main)" if v["a_la_main"] else ""
            sens = "acheteur" if v["sens"] > 0 else ("vendeur" if v["sens"] < 0 else "mixte")
            L.append(f"   {b:8} {v['lignes']} ligne(s) {sens}{main} · "
                     f"{v['risque']:.2f} € en risque")
        pas = [v for v in a["verdicts"] if v["verdict"] != "PASSE"]
        if pas:
            L.append("   refusés ou réduits :")
            for v in pas[:5]:
                L.append(f"     {v['verdict']} {v['symbole']} ({v['oeil']}) — "
                         f"{v['motifs'][0] if v['motifs'] else ''}")
        return "\n".join(L)


def main():
    import logging
    import MetaTrader5 as mt5
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("oeil6")
    if not mt5.initialize():
        log.error("MT5 injoignable : %s", mt5.last_error())
        return
    o = OeilRisque()
    log.info("%s démarré · plafonds : %s blocs, %s lignes/bloc, %s%% du capital",
             o.LIBELLE, MAX_BLOCS_OUVERTS, MAX_LIGNES_PAR_BLOC, RISQUE_MAX_PCT)
    while True:
        try:
            o.regarder(mt5)
            time.sleep(20)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("boucle : %s", e)
            time.sleep(20)
    mt5.shutdown()


if __name__ == "__main__":
    main()
