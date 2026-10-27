# -*- coding: utf-8 -*-
# =====================================================
#  👁️ LA BASE COMMUNE DES YEUX — le contrat que tous respectent
#
#  Décidé avec le patron le 13/09/2026 :
#    «…
#      …
#      …
#      …
#      …»
#    «…
#      …
#      …»
#
#  POURQUOI CETTE ARCHITECTURE, et ce n'est pas une préférence de style :
#  L'ŒIL actuel fait 8 900 lignes. Le 04/09, une variable mal placée dans
#  execute() a bloqué TOUTES ses ouvertures pendant six heures sans que rien
#  ne le signale. Un œil de 200 lignes qui ne fait qu'une chose, on peut le
#  mesurer, le débrancher et le remplacer seul.
#
#  ── LA RÈGLE QUI COMPTE LE PLUS ─────────────────────────────────────────
#  UN ŒIL NE MODIFIE JAMAIS SES PROPRES SEUILS.
#  Il observe, il journalise, il compare sa forme du moment à sa référence de
#  backtest, et il RAPPORTE. Le cerveau (ou le patron) décide.
#
#  Le précédent qui impose cette règle : le 08/09, L'ŒIL a bougé son scoremin
#  cinq fois dans la journée — 8,5 puis 8 puis 8 puis 7 puis 7 — parce qu'il
#  n'avait aucun retour sur l'effet de son propre réglage. Il tournait le
#  bouton à l'aveugle. Un œil qui s'auto-règle dérive ; un œil qui se mesure
#  apprend.
#
#  ── CE QU'EST UNE RÉFÉRENCE ─────────────────────────────────────────────
#  Chaque œil arrive avec des chiffres de backtest, obtenus sous le protocole
#  vérifié dans la nuit du 12 au 13/09 : spread aux deux bouts, plancher du
#  broker, entrée à l'ouverture suivante, UNE POSITION À LA FOIS, réglage et
#  validation positifs, miroir perdant, décalage d'une bougie non destructeur.
#  Ce moteur a été validé deux fois : à l'épreuve du miroir (original + miroir
#  = les frais) et à l'épreuve du hasard (16 000 entrées tirées au sort :
#  −0,108 R par trade, symétrique).
#  Sa forme du moment se juge CONTRE CETTE RÉFÉRENCE, pas dans l'absolu.
# =====================================================
import json
import sys as _sys
import time
import datetime as dt
from pathlib import Path

# 🚷 30/09 — MT5 NE DOIT JAMAIS ÊTRE RESSUSCITÉ PAR UN ŒIL.
# LE PATRON : «…
# …». Les six yeux tournent en permanence et appellent chacun
# mt5.initialize(), qui DÉMARRE le terminal quand il est fermé. Il suffisait
# donc qu'un œil fasse son tour de veille pour que MT5 revienne dans la
# seconde. base.py est importé par les six : une ligne ici les couvre tous.
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import mt5_garde          # noqa: F401  (l'import POSE la garde, idempotent)
except Exception as _e:
    print(f"⚠️ garde MT5 non posée : {_e}")

RACINE = Path(__file__).resolve().parent
PROJET = RACINE.parent
JOURNAUX = RACINE / "journaux"
RAPPORTS = RACINE / "rapports"
JOURNAUX.mkdir(parents=True, exist_ok=True)
RAPPORTS.mkdir(parents=True, exist_ok=True)

# Les quatre blocs de risque, MESURÉS le 13/09 sur 12 673 bougies H1 communes.
# Deux marchés du même bloc, c'est UNE SEULE exposition sous deux noms.
#     NAS100/SP500 +0,95 · BTCUSD/ETHUSD +0,83 · or/argent +0,77
#     EURUSD+/USDX −0,95 (même risque, inversé)
# C'est l'œil 6 qui s'en sert pour son droit de veto.
BLOCS = {
    "actions": ["NAS100", "SP500", "US500", "US100", "DE40", "UK100"],
    "crypto":  ["BTCUSD", "ETHUSD", "BTCEUR", "ETHEUR", "SOLUSD", "XRPUSD"],
    "metaux":  ["XAUUSD+", "XAGUSD", "XAUUSD", "XPTUSD", "XPDUSD"],
    "devises": ["EURUSD+", "GBPUSD+", "USDJPY+", "USDCHF+", "USDCAD+",
                "AUDUSD+", "NZDUSD+", "EURJPY+", "EURGBP+", "EURCHF+",
                "GBPJPY+", "AUDJPY+", "CADJPY+", "CHFJPY+", "USDX"],
    "energie": ["CL-OIL", "UKOUSD", "USOUSD", "NGAS"],
}
# actions et crypto sont liés à +0,46 : à moitié le même risque.
BLOCS_LIES = [("actions", "crypto", 0.46)]

JOURS_FORME = 30        # la fenêtre glissante sur laquelle un œil se juge
MINI_POUR_CONCLURE = 8  # en dessous, on n'ose aucun verdict sur la forme
HORIZON_MIN = 3 * 24 * 60   # un signal non tranché en 3 jours est valorisé au marché
_TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


# ══ 17/09 — LE JEU «…» ══════════════════════════════════════
# LE DÉFAUT : en observation, un signal est noté «…», et
# resoudre() ne traitait QUE les signaux retenus, en cherchant un vrai trade
# chez le broker. Un œil en observation ne pouvait donc JAMAIS avoir un seul
# résultat : «…», pour toujours, et le feu vert
# «…» était impossible à donner.
# Pire, pour un signal retenu, on prenait N'IMPORTE QUEL trade du même marché
# dans les 3 jours — celui d'un autre bot compris.
# LE CORRECTIF : chaque signal est joué contre les VRAIS prix, avec la règle de
# son propre banc (stop sl_atr × ATR de son timeframe, 3 jambes aux objectifs
# tp_r), bougie M1 par bougie M1, spread payé, stop avant objectif dans une
# même bougie. Une seule position virtuelle à la fois par marché, comme au banc.

def _utc(t):
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc)


def _decalage_serveur(mt5):
    """Heure du serveur MT5 moins heure réelle (≈ +3 h chez Vantage l'été)."""
    ref = 0
    for sym in ("BTCUSD", "ETHUSD", "EURUSD+"):
        try:
            t = mt5.symbol_info_tick(sym)
            if t and t.time > ref:
                ref = t.time
        except Exception:
            pass
    if ref <= 0:
        return None
    return int(round((ref - time.time()) / 3600.0)) * 3600


def _atr_oeil(H, L, C, n=14):
    """La formule des yeux (_atr : lissage 1/14), dernière valeur."""
    acc = H[0] - L[0]
    for i in range(1, len(C)):
        tr = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
        acc = tr / n + (1 - 1.0 / n) * acc
    return acc


def jouer_pour_de_faux(mt5, d, timeframe, decalage):
    """Rejoue un signal. Renvoie le résultat (dict), ou None s'il n'est pas
    encore tranché (ou si les prix manquent : on réessaiera)."""
    sym = d["symbole"]
    s = 1 if d.get("sens") == "BUY" else -1
    t_srv = int(d["ts"] + decalage)
    tfm = _TF_MIN.get(str(timeframe).upper(), 60)
    tfc = getattr(mt5, "TIMEFRAME_" + str(timeframe).upper(), mt5.TIMEFRAME_H1)
    r = mt5.copy_rates_range(sym, tfc, _utc(t_srv - 300 * tfm * 60), _utc(t_srv))
    if r is None or len(r) < 30:
        return None
    r = r[r["time"] + tfm * 60 <= t_srv]              # bougies CLÔTURÉES au moment du signal
    if len(r) < 30:
        return None
    atr = _atr_oeil([float(x) for x in r["high"]], [float(x) for x in r["low"]],
                    [float(x) for x in r["close"]])
    info = mt5.symbol_info(sym)
    if not info or atr <= 0:
        return None
    maintenant = int(time.time() + decalage)
    fin = t_srv + HORIZON_MIN * 60
    m1 = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, _utc(t_srv), _utc(min(fin, maintenant)))
    if m1 is None or len(m1) == 0:
        return None
    sp0 = (float(m1[0]["spread"]) or float(info.spread or 0)) * info.point
    entree = float(m1[0]["open"]) + (sp0 if s > 0 else 0.0)
    R = float(d.get("sl_atr") or 2.0) * atr
    stop = entree - s * R
    tps = [float(x) for x in (d.get("tp_r") or [2.0, 3.0, 4.0])]
    sorties = [None] * len(tps)
    t_fin = None
    for x in m1:
        sp = (float(x["spread"]) or float(info.spread or 0)) * info.point
        adj = 0.0 if s > 0 else sp
        o, h, lo = float(x["open"]) + adj, float(x["high"]) + adj, float(x["low"]) + adj
        ouverts = [k for k in range(len(tps)) if sorties[k] is None]
        if not ouverts:
            break
        if int(x["time"]) > t_srv and (o - stop) * s <= 0:                  # écart au-delà du stop
            for k in ouverts:
                sorties[k] = o
            t_fin = int(x["time"])
            break
        if ((lo if s > 0 else h) - stop) * s <= 0:                          # stop AVANT objectif
            for k in ouverts:
                sorties[k] = stop
            t_fin = int(x["time"])
            break
        for k in ouverts:
            cible = entree + s * tps[k] * R
            if ((h if s > 0 else lo) - cible) * s >= 0:
                sorties[k] = cible
                t_fin = int(x["time"])
    if any(v is None for v in sorties):
        if maintenant < fin:
            return None                                                     # pas encore tranché
        dernier = m1[-1]
        sp = (float(dernier["spread"]) or float(info.spread or 0)) * info.point
        px = float(dernier["close"]) + (0.0 if s > 0 else sp)
        sorties = [px if v is None else v for v in sorties]
        t_fin = int(dernier["time"])
    try:
        eur_prix = abs(float(mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, info.volume_min,
                                                   entree, entree + R))) / R
    except Exception:
        eur_prix = float("nan")
    r_jambes = [(v - entree) * s / R for v in sorties]
    euros = sum((v - entree) * s for v in sorties) * eur_prix
    return {"euros": round(float(euros), 2), "R": round(sum(r_jambes) / len(r_jambes), 3),
            "gagnant": bool(euros > 0), "virtuel": True, "entree": round(entree, 6),
            "stop": round(stop, 6), "jambes_R": [round(v, 2) for v in r_jambes],
            "fin_serveur": t_fin, "resolu_le": time.time()}


def marche_frais(mt5, symbole: str, retard_max_min: float = 15.0) -> bool:
    """Le marché cote-t-il ENCORE ? Ajouté le 13/09 après un essai à sec un
    dimanche : l'œil 3 a sorti quatre signaux sur SP500, NAS100, l'or et le
    BTC en lisant des bougies de vendredi soir. Un œil qui parle d'un marché
    fermé fait perdre de l'argent le lundi à l'ouverture.

    On compare l'heure du dernier tick à l'heure du serveur, pas à celle du PC :
    l'écart mesuré entre les deux est de trois heures sur cette machine."""
    try:
        t = mt5.symbol_info_tick(symbole)
        if not t or not t.time:
            return False
        # l'heure serveur se déduit du tick le plus récent de TOUS les symboles
        # suivis ; ici on se contente de vérifier que ce symbole-ci n'est pas
        # en retard sur l'horloge du terminal.
        ref = 0
        for s in ("BTCUSD", "ETHUSD", "EURUSD+", symbole):
            try:
                x = mt5.symbol_info_tick(s)
                if x and x.time > ref:
                    ref = x.time
            except Exception:
                pass
        if ref <= 0:
            return False
        return (ref - t.time) <= retard_max_min * 60
    except Exception:
        return False


def bloc_de(symbole: str) -> str:
    s = (symbole or "").upper()
    for nom, membres in BLOCS.items():
        for m in membres:
            if s == m.upper() or s.startswith(m.upper().rstrip("+")):
                return nom
    return "autre"


class Rapport(dict):
    """Ce qu'un œil envoie au cerveau. Ce n'est PAS un ordre : c'est un avis.
    Le cerveau arbitre, l'œil 6 peut opposer son veto, et le patron tranche."""

    def __init__(self, oeil, symbole, sens, confiance, raison,
                 sl_atr=2.0, tp_r=(2.0, 3.0, 4.0), duree_max_min=None, **extra):
        super().__init__(
            oeil=oeil, symbole=symbole, sens=sens.upper(),
            bloc=bloc_de(symbole), confiance=float(confiance),
            raison=raison, sl_atr=float(sl_atr), tp_r=list(tp_r),
            duree_max_min=duree_max_min, ts=time.time(),
            horodatage=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **extra)


class Oeil:
    """À hériter. Un œil = une idée, mesurée, et rien d'autre.

    À définir dans la classe fille :
        NOM         identifiant court, sert de nom de fichier
        LIBELLE     ce que le patron lira
        REFERENCE   les chiffres du backtest : wr, r_par_signal, signaux_jour
        MARCHES     ce qu'il surveille
        regarder(mt5) -> list[Rapport]
    """
    NOM = "sans_nom"
    LIBELLE = "œil sans nom"
    REFERENCE = {"wr": 0.0, "r_par_signal": 0.0, "signaux_jour": 0.0}
    MARCHES: list = []
    ACTIF = True
    OBSERVATION = True      # 🔒 par défaut il REGARDE sans trader.
    #                         Le patron ouvre la main œil par œil, après une
    #                         semaine de rapports. «…
    #                         …» — rien ne coûte tant qu'on
    #                         n'a pas vu ce qu'ils auraient fait.

    def __init__(self):
        self.journal_f = JOURNAUX / f"{self.NOM}.jsonl"
        self.rapport_f = RAPPORTS / f"{self.NOM}.json"

    # ── le journal : tout ce qu'il a vu, pour pouvoir se juger plus tard ──
    def noter(self, rapport: Rapport, retenu: bool, motif: str = ""):
        ligne = dict(rapport)
        ligne["retenu"] = bool(retenu)
        ligne["motif"] = motif
        ligne["resultat"] = None        # rempli plus tard par resoudre()
        try:
            with open(self.journal_f, "a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def lire_journal(self, jours=JOURS_FORME) -> list:
        limite = time.time() - jours * 86400
        out = []
        try:
            for l in open(self.journal_f, encoding="utf-8"):
                try:
                    d = json.loads(l)
                except Exception:
                    continue
                if d.get("ts", 0) >= limite:
                    out.append(d)
        except FileNotFoundError:
            pass
        return out

    def resoudre(self, mt5):
        """La leçon du soir : chaque signal est rejoué contre les VRAIS prix,
        avec la règle de son banc (voir jouer_pour_de_faux). Un chiffre constaté,
        pas une opinion — et possible dès l'observation, sans risquer un euro."""
        try:
            lignes = []
            for l in open(self.journal_f, encoding="utf-8"):
                try:
                    lignes.append(json.loads(l))
                except Exception:
                    pass
        except FileNotFoundError:
            return 0
        decalage = _decalage_serveur(mt5)
        if decalage is None:
            return 0
        import sys as _s
        tf = getattr(_s.modules.get(self.__class__.__module__), "TIMEFRAME", "H1")
        # une seule position virtuelle à la fois par marché, dans l'ordre du temps
        occupe = {}
        for d in lignes:
            res = d.get("resultat") or {}
            if res.get("fin_serveur"):
                occupe[d["symbole"]] = max(occupe.get(d["symbole"], 0), int(res["fin_serveur"]))
        bloque = set()
        n = 0
        for d in sorted(lignes, key=lambda x: x.get("ts", 0)):
            if d.get("resultat") is not None or time.time() - d.get("ts", 0) < 600:
                continue
            sym = d.get("symbole")
            if sym in bloque:
                continue
            if int(d["ts"] + decalage) < occupe.get(sym, 0):
                d["resultat"] = {"ignore": "position virtuelle déjà ouverte sur ce marché",
                                 "resolu_le": time.time()}
                n += 1
                continue
            try:
                res = jouer_pour_de_faux(mt5, d, d.get("timeframe") or tf, decalage)
            except Exception:
                res = None
            if res is None:
                bloque.add(sym)          # pas encore tranché : les suivants attendent
                continue
            d["resultat"] = res
            occupe[sym] = int(res["fin_serveur"] or 0)
            n += 1
        if n:
            try:
                tmp = self.journal_f.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for d in lignes:
                        f.write(json.dumps(d, ensure_ascii=False) + "\n")
                tmp.replace(self.journal_f)
            except Exception:
                pass
        return n

    # ── la forme du moment, CONTRE la référence de backtest ──────────────
    def forme(self) -> dict:
        j = self.lire_journal()
        # 🩹 17/09 : les signaux d'OBSERVATION comptent aussi (joués pour de faux)
        resolus = [d for d in j if (d.get("resultat") or {}).get("euros") is not None]
        jours = max(1.0, JOURS_FORME)
        sig_jour = len(j) / jours
        if len(resolus) < MINI_POUR_CONCLURE:
            return {"etat": "trop tot", "n": len(resolus),
                    "euros": round(sum(d["resultat"]["euros"] for d in resolus), 2),
                    "signaux_jour": round(sig_jour, 2),
                    "message": f"{len(resolus)} résultat(s) connus sur "
                               f"{JOURS_FORME} j — pas de quoi conclure"}
        wr = sum(1 for d in resolus if d["resultat"]["gagnant"]) / len(resolus) * 100
        euros = sum(d["resultat"]["euros"] for d in resolus)
        ref = self.REFERENCE.get("wr", 0.0)
        ecart = wr - ref
        # le verdict est mécanique, pas interprété
        if ecart < -8:
            etat = "en dessous"
            msg = (f"{wr:.0f}% de réussite contre {ref:.0f}% de référence "
                   f"({ecart:+.0f} pts) — réduis-moi")
        elif ecart > 8:
            etat = "au dessus"
            msg = f"{wr:.0f}% contre {ref:.0f}% de référence ({ecart:+.0f} pts)"
        else:
            etat = "dans sa norme"
            msg = f"{wr:.0f}% contre {ref:.0f}% de référence — conforme"
        return {"etat": etat, "n": len(resolus), "wr": round(wr, 1),
                "reference_wr": ref, "ecart": round(ecart, 1),
                "euros": round(euros, 2), "signaux_jour": round(sig_jour, 2),
                "reference_signaux_jour": self.REFERENCE.get("signaux_jour", 0),
                "message": msg}

    # ── ce que le cerveau vient lire ─────────────────────────────────────
    def publier(self, rapports: list):
        d = {"oeil": self.NOM, "libelle": self.LIBELLE,
             "actif": self.ACTIF, "observation": self.OBSERVATION,
             "reference": self.REFERENCE, "forme": self.forme(),
             "marches": self.MARCHES, "ts": time.time(),
             "horodatage": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "rapports": [dict(r) for r in rapports]}
        try:
            tmp = self.rapport_f.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.rapport_f)
        except Exception:
            pass
        return d

    def regarder(self, mt5) -> list:
        raise NotImplementedError

    # ── la boucle : c'est tout ce qu'un œil fait de sa vie ────────────────
    def _poser_fiche(self, rapports):
        """📋 16/09 — CHAQUE ŒIL LAISSE SA FICHE SUR LE TABLEAU.

        Idée du patron : «…
        …»

        Ce qu'un œil sait et que personne d'autre ne sait : ce qu'il vient de
        voir, à quel point il y croit, et si sa forme du moment s'éloigne de
        ce que le banc avait mesuré. C'est tout ce qu'on met — un lecteur qui
        n'agit pas sur une valeur n'a pas besoin de la lire.

        Jamais d'exception vers l'appelant : le tableau est un confort, pas un
        organe vital. Un œil ne s'arrête pas parce qu'un disque est plein."""
        try:
            # 🩹 16/09 — UN ŒIL N'A QUE yeux/ DANS SON CHEMIN.
            # Python met le dossier du SCRIPT en tete de sys.path, pas le
            # dossier courant : lance comme «…», un œil
            # voit yeux/ et rien d'autre. Resultat mesure : «…
            # …», avale par le except, et aucune fiche pendant 20 min
            # sans le moindre message. On ajoute le dossier parent.
            import sys as _s
            _parent = str(Path(__file__).resolve().parent.parent)
            if _parent not in _s.path:
                _s.path.append(_parent)
            import tableau
        except Exception:
            return
        try:
            f = self.forme() or {}
            faits = dict(
                observation=self.OBSERVATION,
                marches=",".join(self.MARCHES),
                signaux=len(rapports),
                wr_reference=self.REFERENCE.get("wr"),
                wr_reel=f.get("wr"),
                trades_mesures=f.get("n"),
                derive=f.get("derive"),
            )
            if rapports:
                r = max(rapports, key=lambda x: x.get("confiance", 0))
                faits.update(dernier=r["symbole"], sens=r["sens"],
                             confiance=round(float(r.get("confiance", 0)), 1))
            tableau.ecrire(self.NOM.split("_")[0], **faits)
        except Exception:
            pass

    def cycle(self, mt5, log=None):
        if not self.ACTIF:
            return []
        try:
            rapports = self.regarder(mt5) or []
        except Exception as e:
            if log:
                log.error("%s : %s", self.NOM, e)
            return []
        for r in rapports:
            self.noter(r, retenu=not self.OBSERVATION,
                       motif="observation" if self.OBSERVATION else "")
        self.publier(rapports)
        self._poser_fiche(rapports)
        if rapports and log:
            for r in rapports:
                log.info("👁️ %s : %s %s (%.0f%%) — %s", self.NOM, r["sens"],
                         r["symbole"], r["confiance"], r["raison"])
        return rapports


def tous_les_rapports() -> list:
    """Ce que le cerveau lit : l'avis courant de chaque œil.
    Un rapport de plus de 10 minutes est considéré périmé — un œil muet ou
    planté ne doit pas continuer à peser sur les décisions."""
    out = []
    for f in sorted(RAPPORTS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        d["perime"] = (time.time() - d.get("ts", 0)) > 600
        out.append(d)
    return out
