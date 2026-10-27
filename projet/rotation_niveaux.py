# -*- coding: utf-8 -*-
# =====================================================
#  🔄 ROTATION SUR NIVEAUX — encaisser vite, revenir plus fort (02/09/26)
#
#  LE PATRON :
#    «…
#      …»
#    «…»
#    «…»
#
#  LE PRINCIPE :
#    1. une position atteint +40 pips  →  on ENCAISSE (on ne rend rien)
#    2. son prix d'entrée reste ARMÉ comme un piège
#    3. le prix y revient ET les conditions tiennent  →  on REPREND, ×2
#    4. on recommence — c'est la rotation
#
#  POURQUOI DOUBLER SE DÉFEND ICI (et pas ailleurs) :
#  On ne double pas après une PERTE — ça c'est la martingale, et ça ruine.
#  On double après un GAIN, sur un niveau qui vient de PROUVER qu'il paie.
#  On renforce ce qui a marché, on n'essaie pas de rattraper ce qui a raté.
#
#  ⚠️ CE QUI EMPÊCHE L'EMBALLEMENT :
#  Doubler sans limite donne 0.01 → 0.02 → 0.04 → 0.08… et un seul retour
#  de marché efface toute la série. Trois garde-fous :
#    • MAX_REPRISES = 3 : après, le niveau est retiré (pas de 4e doublement)
#    • le lot est PLAFONNÉ par ce que le capital autorise (budget_risque)
#    • une reprise PERDANTE désarme le niveau immédiatement — on n'insiste pas
#
#  ⛔ Et surtout : ce module N'A PAS ÉTÉ MESURÉ en backtest. C'est une
#  mécanique de gestion, pas un signal. Elle s'appuie sur des détecteurs déjà
#  mesurés (impulsion, chasseur) — mais la rotation elle-même reste à valider
#  sur les faits. Le carnet de bord la jugera.
# =====================================================
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FICHIER = HERE / "rotation_niveaux.json"

ENCAISSE_A_PIPS = 40      # on prend le gain à partir d'ici (demande patron)
MAGIC = 999111            # 🖐️ 07/09 : celui de L'ŒIL. Sans lui, MT5 posait magic 0 —
                          # les reprises se faisaient passer pour des trades du patron.
MULT_REPRISE    = 2.0     # ×2 à chaque retour sur le niveau (demande patron)
MAX_REPRISES    = 0       # version publique : 0 = reprises ×2 COUPÉES (non mesurées, hors enveloppe commune) — 3 chez l'auteur : 0.01→0.02→0.04→0.08 STOP
TOLERANCE_PIPS  = 8       # «…» = à ce nombre de pips près
VALIDITE_H      = 6       # un niveau armé expire au bout de 6 h
COOLDOWN_S      = 300     # jamais deux reprises à moins de 5 min d'écart

# Là où la rotation a le droit de vivre : les marchés mesurés rentables.
MARCHES = ("XAUUSD+", "NAS100", "CL-OIL")


def _pip(sym):
    s = sym.upper()
    if "XAU" in s:
        return 0.1
    if s in ("NAS100", "SP500", "BTCUSD", "ETHUSD"):
        return 1.0
    if "JPY" in s or "XAG" in s or "OIL" in s:
        return 0.01
    return 0.0001


def _lire():
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return []


def _ecrire(d):
    """08/09 — DÉDOUBLONNAGE À LA SOURCE. Sans lui le fichier grossissait sans fin :
    9 258 entrées pour 824 niveaux réels (91 % de doublons), 3 Mo, et le cerveau
    recevait tout ça à chaque appel — 150 000 tokens par tour, 93 % de la facture.
    Un niveau = (symbole, prix arrondi, sens). Le plus RÉCENT gagne, et on garde
    aussi le compteur de reprises le plus élevé (ne jamais perdre une reprise déjà
    faite : c'est ce qui protège d'un empilement)."""
    try:
        vus = {}
        for x in (d or []):
            cle = (x.get("symbole"), round(float(x.get("prix", 0)), 2), x.get("sens"))
            anc = vus.get(cle)
            if anc is None:
                vus[cle] = x
            else:
                garde = x if x.get("expire", 0) >= anc.get("expire", 0) else anc
                garde["reprises"] = max(int(anc.get("reprises", 0)), int(x.get("reprises", 0)))
                vus[cle] = garde
        d = sorted(vus.values(), key=lambda x: x.get("expire", 0), reverse=True)[:200]
    except Exception:
        pass
    try:
        FICHIER.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def encaisser(mt5, log=None) -> int:
    """Étape 1-2 : les positions bien en profit sont encaissées, et leur
    niveau d'entrée est ARMÉ pour une reprise. Retourne le nombre encaissé."""
    niveaux = _lire()
    armes = {(n["symbole"], round(n["prix"], 5)) for n in niveaux}
    pris = 0
    for p in (mt5.positions_get() or []):
        try:
            # 🖐️ 07/09 — JAMAIS LES TRADES DU PATRON. Cette fonction encaissait à
            # +40 pips SANS regarder le magic : sur l'or (pip 0,1) ça fait 4 $, donc
            # tout trade à la main un peu gagnant se faisait solder par le bot.
            # «…» — c'était ça, la cause.
            if p.magic == 0:
                continue
            if p.symbol not in MARCHES:
                continue
            if "HEDGE" in (p.comment or "") or "ROTATION" in (p.comment or ""):
                continue
            tick = mt5.symbol_info_tick(p.symbol)
            info = mt5.symbol_info(p.symbol)
            if not tick or not info:
                continue
            pip = _pip(p.symbol)
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            cur = tick.bid if is_buy else tick.ask
            gain_pips = ((cur - p.price_open) if is_buy else (p.price_open - cur)) / pip
            if gain_pips < ENCAISSE_A_PIPS:
                continue

            r = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                "volume": p.volume, "position": p.ticket,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "price": cur, "deviation": 20, "magic": p.magic,
                "comment": "ROTATION_encaisse",
            })
            if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
                continue
            pris += 1
            cle = (p.symbol, round(p.price_open, 5))
            if cle not in armes:
                niveaux.append({
                    "symbole": p.symbol, "prix": p.price_open,
                    "sens": "BUY" if is_buy else "SELL",
                    "lot_base": p.volume, "sl": p.sl, "tp": p.tp,
                    "reprises": 0, "expire": time.time() + VALIDITE_H * 3600,
                    "dernier": 0.0, "gain_encaisse": round(gain_pips),
                })
                armes.add(cle)
            if log:
                log.info(f"🔄 ENCAISSÉ {p.symbol} {'BUY' if is_buy else 'SELL'} "
                         f"à +{gain_pips:.0f} pips ({p.profit:+.2f}€). Niveau "
                         f"{p.price_open} ARMÉ — j'y reviens ×{MULT_REPRISE:g} "
                         f"si le prix repasse.")
        except Exception as e:
            if log:
                log.debug(f"rotation encaisse {getattr(p, 'symbol', '?')} : {e}")
    if pris:
        _ecrire(niveaux)
    return pris


def armer_apres_be(mt5, log=None) -> int:
    """🎯 02/09 (patron : «…
    …
    …»).

    Un BE qui saute, ce n'est pas un échec : c'est un trade qui était bon, sorti
    à zéro par le stop remonté. Le setup, lui, tient peut-être toujours. On arme
    donc DEUX niveaux :
       • le point d'entrée d'origine (si le prix y repasse)
       • un niveau MEILLEUR, un demi-ATR plus bas (pour un achat) — la reprise
         «…» que demande le patron
    Aucun des deux ne se déclenche sans la validation des détecteurs.
    """
    try:
        from datetime import datetime, timedelta
        deals = mt5.history_deals_get(datetime.now() - timedelta(hours=3),
                                      datetime.now() + timedelta(hours=4)) or []
    except Exception:
        return 0
    entrees = {}
    for d in deals:
        if d.entry == 0:
            entrees.setdefault(d.position_id, d)
    niveaux = _lire()
    # 🐛 08/09 — LA BOUCLE DE SPAM. La clé se calculait ici sur 5 décimales à
    # partir du prix BRUT (4403.92571…) alors que le niveau était STOCKÉ arrondi
    # aux digits du symbole (4403.93). Les deux ne se rencontraient jamais : le
    # niveau «…» était ré-armé À CHAQUE CYCLE, soit toutes les 15 s,
    # depuis des heures — 9 lignes identiques en boucle dans le journal (630 Ko)
    # et un fichier d'état plafonné en permanence à 200 entrées.
    # On prend désormais EXACTEMENT la clé de _ecrire() : (symbole, prix à 2
    # décimales, sens).
    deja = {(n["symbole"], round(float(n.get("prix", 0)), 2), n.get("sens"))
            for n in niveaux}
    armes = 0
    for d in deals:
        try:
            if d.entry != 1 or d.symbol not in MARCHES:
                continue
            e = entrees.get(d.position_id)
            if not e:
                continue
            # 🖐️ 08/09 au soir — LA MAIN DU PATRON N'EST PAS UN SIGNAL.
            # encaisser() filtrait magic 0 depuis le 07/09, pas celle-ci : elle
            # lisait TOUS les deals clôturés. Résultat ce soir : ses ferraillages
            # sur l'or (39 trades, dont une dizaine entre X € et X €) armaient
            # des niveaux que le bot pouvait reprendre tout seul. Il n'a rien
            # demandé de tel, et le journal lui affichait «…»
            # sur SES trades — de quoi croire qu'on y touchait.
            if getattr(e, "magic", 0) == 0 and getattr(d, "magic", 0) == 0:
                continue
            pnl = d.profit + d.swap + d.commission
            # 🔍 signature d'un BE : sortie quasi nulle (entre X € et X €).
            # Une vraie perte est plus franche, un vrai TP aussi.
            if not (-0.5 <= pnl <= 2.0):
                continue
            info = mt5.symbol_info(d.symbol)
            r = mt5.copy_rates_from_pos(d.symbol, mt5.TIMEFRAME_H1, 0, 20)
            if not info or r is None or len(r) < 15:
                continue
            atr = sum(float(x["high"]) - float(x["low"]) for x in r[-14:]) / 14
            pip = _pip(d.symbol)
            is_buy = e.type == 0
            sens = "BUY" if is_buy else "SELL"
            # niveau 1 : le point d'entrée d'origine
            # niveau 2 : un demi-ATR MIEUX placé (plus bas si on achète)
            for prix, quoi in ((e.price, "point d'entrée d'origine"),
                               (e.price - (atr * 0.5 if is_buy else -atr * 0.5),
                                "un demi-ATR plus bas" if is_buy else "un demi-ATR plus haut")):
                prix = round(prix, info.digits)      # on arrondit AVANT de comparer
                cle = (d.symbol, round(prix, 2), sens)
                if cle in deja:
                    continue
                deja.add(cle)
                niveaux.append({
                    "symbole": d.symbol, "prix": prix,
                    "sens": sens, "lot_base": e.volume,
                    "sl": prix - (1 if is_buy else -1) * 1.5 * atr,
                    "tp": prix + (1 if is_buy else -1) * 3.0 * atr,
                    "reprises": 0,
                    # 24 h et non 6 : sur l'or en H1, un retour au point d'entrée
                    # prend souvent une nuit entière. 6 h effaçait le niveau
                    # avant même que le prix ait eu le temps de revenir.
                    "expire": time.time() + 24 * 3600,
                    # tolérance = un quart d'ATR (≈45 pips sur l'or) et non 8 :
                    # «…» ne veut pas dire
                    # au centime près, sinon on ne reprend jamais rien.
                    "tol": max(TOLERANCE_PIPS, round(atr * 0.25 / pip)),
                    "mult": 1.0,          # ⛔ pas de martingale sur une reprise BE
                    "dernier": 0.0, "gain_encaisse": 0, "origine": "BE",
                })
                armes += 1
                if log:
                    log.info(f"🎯 BE touché sur {d.symbol} {sens} ({pnl:+.2f}€) — "
                             f"niveau armé à {prix:.{info.digits}f} ({quoi}). "
                             f"J'y reviens SI les convictions tiennent.")
        except Exception as ex:
            if log:
                log.debug(f"armer_apres_be : {ex}")
    if armes:
        _ecrire(niveaux)
    return armes


def reprendre(mt5, valider=None, log=None) -> int:
    """Étape 3-4 : le prix est-il revenu sur un niveau armé ? Si oui et si les
    conditions tiennent, on remet — au DOUBLE du lot précédent.

    valider(symbole, sens) -> bool : la vérification des conditions, fournie
    par L'ŒIL (les détecteurs). Sans elle, on ne reprend PAS : hors de
    question de rentrer juste parce que le prix est revenu."""
    niveaux = _lire()
    if not niveaux:
        return 0
    maintenant = time.time()
    gardes, repris = [], 0
    for n in niveaux:
        try:
            if maintenant > n["expire"]:
                if log:
                    log.info(f"🔄 niveau {n['symbole']} @{n['prix']} expiré "
                             f"({VALIDITE_H} h) — désarmé")
                continue
            if n["reprises"] >= MAX_REPRISES:
                if log:
                    log.info(f"🔄 niveau {n['symbole']} @{n['prix']} : "
                             f"{MAX_REPRISES} reprises faites, on s'arrête là "
                             f"(pas de 4e doublement)")
                continue
            gardes.append(n)
            if maintenant - n["dernier"] < COOLDOWN_S:
                continue

            tick = mt5.symbol_info_tick(n["symbole"])
            info = mt5.symbol_info(n["symbole"])
            if not tick or not info:
                continue
            pip = _pip(n["symbole"])
            is_buy = n["sens"] == "BUY"
            cur = tick.ask if is_buy else tick.bid
            if abs(cur - n["prix"]) > n.get("tol", TOLERANCE_PIPS) * pip:
                continue                      # pas encore revenu

            # déjà une position dessus ? on n'empile pas
            if [p for p in (mt5.positions_get(symbol=n["symbole"]) or [])
                    if p.magic and "ROTATION" in (p.comment or "")]:
                continue

            # ⚖️ les conditions tiennent-elles TOUJOURS ?
            if valider is None or not valider(n["symbole"], n["sens"]):
                n["dernier"] = maintenant
                if log:
                    log.info(f"🔄 {n['symbole']} revenu à {n['prix']} mais les "
                             f"conditions ne tiennent plus — je ne reprends pas")
                continue

            # 📈 LE DOUBLEMENT, borné par ce que le capital autorise
            # 🎯 02/09 : un niveau armé APRÈS UN BE se reprend à l'identique.
            # Le ×2 est réservé à la rotation «…
            # …» ; reprendre un trade sorti à zéro n'est pas une martingale,
            # c'est la MÊME conviction qu'on rejoue au même prix.
            _mult = n.get("mult", MULT_REPRISE)
            lot = n["lot_base"] * (_mult ** (n["reprises"] + 1))
            try:
                import budget_risque
                _, table = budget_risque.lots_autorises(mt5, symboles=[n["symbole"]])
                maxi = table.get(n["symbole"], 0.0)
                if maxi and lot > maxi:
                    if log:
                        log.info(f"🔄 {n['symbole']} : doublement ramené de "
                                 f"{lot:.2f} à {maxi:.2f} — le capital ne suit pas")
                    lot = maxi
            except Exception:
                pass
            pas = info.volume_step or 0.01
            lot = max(info.volume_min or 0.01, int(lot / pas) * pas)

            r = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": n["symbole"],
                "volume": lot,
                "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                "price": cur, "sl": n["sl"], "tp": n["tp"],
                "deviation": 20, "magic": MAGIC, "comment": "ROTATION_reprise",
            })
            n["dernier"] = maintenant
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                n["reprises"] += 1
                repris += 1
                if log:
                    log.info(f"🔄 REPRISE {n['symbole']} {n['sens']} au niveau "
                             f"{n['prix']} — lot {lot:g} (×{MULT_REPRISE:g}, "
                             f"reprise {n['reprises']}/{MAX_REPRISES})")
        except Exception as e:
            if log:
                log.debug(f"rotation reprise : {e}")
    _ecrire(gardes)
    return repris


def contexte() -> str:
    """Ce que le cerveau doit savoir des niveaux en attente."""
    n = [x for x in _lire() if time.time() < x.get("expire", 0)]
    if not n:
        return ""
    # 08/09 : on RÉSUME. Avant, cette boucle écrivait une ligne par niveau — des
    # milliers — directement dans le prompt du cerveau.
    n = sorted(n, key=lambda x: x.get("expire", 0), reverse=True)
    total = len(n)
    lignes = [f"🔄 NIVEAUX ARMÉS : {total} en attente d'un retour du prix"
              + (" (les 8 plus récents ci-dessous)" if total > 8 else "") + " :"]
    for x in n[:8]:
        lignes.append(f"  {x['symbole']} {x['sens']} @ {x['prix']} — "
                      f"encaissé à +{x.get('gain_encaisse', '?')} pips, "
                      f"{x['reprises']}/{MAX_REPRISES} reprises faites, "
                      f"prochaine à ×{MULT_REPRISE ** (x['reprises'] + 1):g} du lot de départ")
    lignes.append("Si le prix y revient et que tes juges tiennent, on remet — "
                  "sinon on laisse expirer. On ne rentre JAMAIS juste parce que "
                  "le prix est revenu.")
    return "\n".join(lignes)
