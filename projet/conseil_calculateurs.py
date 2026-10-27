# -*- coding: utf-8 -*-
"""
🧮 LE CONSEIL DES CALCULATEURS — deux équipes de quatre  (10/10/2026)

LE PATRON, mot pour mot :
  «…
    …
    …
    …
    …
    …
    …
    …»
  «…
    …»
  «…
    …»

L'ORGANISATION
  ÉQUIPE A — ASTRA   (GPT)       4 mathématiciens
  ÉQUIPE B — GROK    (grok-4.7)  4 mathématiciens

  Quatre copies du même modèle avec le même prompt rendraient quatre fois la
  même réponse. Chaque équipe est donc composée de quatre SPÉCIALITÉS qui
  travaillent le même dossier sous des angles différents, puis un cinquième
  passage — le porte-parole — fond leurs quatre notes en UN SEUL avis. Le
  patron lit deux avis, jamais huit.

  Ils voient : les prix réels du compte (MT5), les positions ouvertes, le
  capital, le calendrier économique, et ils peuvent CHERCHER SUR INTERNET
  (recherche en direct, sans clé API) ce dont ils ont besoin.

DEUX USAGES
  1. LA PAROLE   — «…» → une réponse.
  2. LES SIGNAUX — chaque délibération peut produire un ordre exécutable,
     écrit dans conseil_signaux.json. Le cerveau l'exécute sur la seule
     approbation du conseil (ordre explicite du patron).

    python conseil_calculateurs.py                      délibération sur les 4 marchés
    python conseil_calculateurs.py A "ton avis sur l'or ?"   une équipe, une question
    python conseil_calculateurs.py B "le dollar va où ?"
    python conseil_calculateurs.py duel "on achète quoi ?"   les deux équipes
"""
import concurrent.futures as _cf
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

API = "https://api.mammouth.ai/v1/chat/completions"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
SIGNAUX = HERE / "conseil_signaux.json"
JOURNAL = HERE / "conseil_journal.jsonl"
MARCHES = ("XAUUSD+", "NAS100", "CL-OIL", "BTCUSD")

# ── LA MENTALITÉ, IDENTIQUE POUR LES HUIT ───────────────────────────────
# LE PATRON : «…
# …
# …».
# Les quatre membres d'une équipe reçoivent donc le MÊME esprit et le MÊME
# dossier, et travaillent séparément sans se voir. Ce qui les rend utiles à
# quatre plutôt qu'à un : quand quatre calculs indépendants tombent sur la même
# conclusion, elle est solide ; quand ils divergent, le marché n'est pas lisible
# et le porte-parole le dit au lieu de trancher au hasard. C'est un VOTE.
MENTALITE = (
    "Tu es un super calculateur professionnel, du genre que les grandes maisons "
    "emploient pour décider où placer l'argent. Ta mentalité, invariable :\n"
    "- TU PENSES EN MATHÉMATIQUES. Espérance, probabilité, ratio gain/risque, "
    "taille de position. Un avis sans chiffre n'est pas un avis.\n"
    "- TU PENSES EN LOGIQUE. Chaque conclusion découle d'un fait présent dans "
    "les données. Tu ne combles jamais un trou par une impression.\n"
    "- TU ES PATIENT. Le meilleur calcul conclut souvent qu'il n'y a rien à "
    "faire maintenant. Ne rien faire est une décision professionnelle, pas un "
    "échec : tu attends le mouvement lisible plutôt que de forcer.\n"
    "- TU CHERCHES LE MOUVEMENT REPRODUCTIBLE. Pas le coup de chance : le "
    "schéma qu'on peut rejouer, avec son entrée, son point d'invalidation et sa "
    "cible, tous les trois justifiés par un chiffre."
)
NB_MEMBRES = 4

EQUIPES = {
    "A": {"nom": "ASTRA", "emoji": "🅰️", "modele": "gpt-5.2",
          "porte_parole": "gpt-5.2",
          "ame": "Tu fais partie d'ASTRA, un cabinet de calcul réputé pour sa "
                 "rigueur froide. Chez ASTRA on ne parle jamais sans chiffre."},
    "B": {"nom": "GROK", "emoji": "🅱️", "modele": "grok-4.7",
          "porte_parole": "grok-4.7",
          "ame": "Tu fais partie de GROK, un cabinet de calcul réputé pour voir "
                 "ce que les autres ratent. Chez GROK on ose la lecture à "
                 "contre-courant, mais on la prouve."},
}

CADRE = (
    "CONTEXTE DE LA MISSION. Tu travailles pour un trader particulier, sur un "
    "compte réel de taille modeste. Il trade quatre marchés : l'or (XAUUSD+), "
    "le NAS100, le pétrole (CL-OIL) et le BTCUSD. Son objectif est d'environ "
    "10 € de gain par trade au lot minimum. Il ne veut pas de théorie : il veut "
    "savoir OÙ INVESTIR MAINTENANT et COMMENT capturer un mouvement de façon "
    "logique et reproductible.\n"
    "RÈGLES ABSOLUES : tu ne parles que de ce que les données montrent ; si tu "
    "ne sais pas, tu dis que tu ne sais pas ; tu n'inventes jamais un chiffre. "
    "Réponds en français, court et dense."
)


# ══ OUTILS ═══════════════════════════════════════════════════════════════
def _cle():
    src = (HERE / "secrets_acid.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^\s*MAMMOUTH_API_KEY\s*=\s*["\']([^"\']+)', src, re.M)
    return m.group(1) if m else ""


def _ask(modele, messages, max_tokens=900, essais=3):
    """Un appel au modèle. L'en-tête navigateur est OBLIGATOIRE : sans lui,
    Cloudflare répond «…» avant même d'atteindre mammouth."""
    h = {"Authorization": f"Bearer {_cle()}", "Content-Type": "application/json",
         "Accept": "application/json", "User-Agent": UA}
    body = json.dumps({"model": modele, "max_tokens": max_tokens,
                       "messages": messages}).encode()
    for k in range(essais):
        try:
            with urllib.request.urlopen(urllib.request.Request(API, data=body, headers=h),
                                        timeout=120) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if e.code == 429 and "budget" in txt.lower():
                return f"[{modele} indisponible : budget du compte épuisé]"
            if k + 1 < essais:
                time.sleep(2.5 * (k + 1))
                continue
            return f"[{modele} indisponible : HTTP {e.code}]"
        except Exception as e:
            if k + 1 < essais:
                time.sleep(2.0)
                continue
            return f"[{modele} indisponible : {type(e).__name__}]"
    return f"[{modele} muet]"


def recherche_web(question, n=4):
    """L'accès internet du conseil. Pas de clé, pas d'abonnement."""
    try:
        q = urllib.parse.quote(question)
        req = urllib.request.Request(f"https://html.duckduckgo.com/html/?q={q}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        brut = re.findall(r'result__a[^>]*>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a>',
                          html, re.S)[:n]
        out = []
        for t, s in brut:
            t = re.sub(r"<[^>]+>", "", t).strip()
            s = re.sub(r"<[^>]+>", "", s).strip()
            out.append(f"- {t} : {s[:220]}")
        return "\n".join(out) or "(aucun résultat)"
    except Exception as e:
        return f"(recherche indisponible : {type(e).__name__})"


def dossier_marche():
    """Ce que le conseil a sous les yeux : les prix RÉELS du compte."""
    lignes = []
    try:
        import MetaTrader5 as mt5
        import mt5_garde  # noqa: F401  (l'import pose la garde : MT5 jamais ressuscite)
        if not mt5.initialize():
            return "(MetaTrader fermé : le conseil travaille sans les prix du compte)"
        a = mt5.account_info()
        if a:
            lignes.append(f"COMPTE : {a.balance:.2f} € de solde, {a.equity:.2f} € d'équité.")
        pos = mt5.positions_get() or []
        lignes.append(f"POSITIONS OUVERTES : {len(pos)}" +
                      ("".join(f"\n  - {p.symbol} {'achat' if p.type == 0 else 'vente'} "
                               f"{p.volume} lot, {p.profit:+.2f} €" for p in pos) if pos else " (aucune)"))
        lignes.append("\nMARCHÉS (données réelles du broker, maintenant) :")
        for s in MARCHES:
            t = mt5.symbol_info_tick(s)
            r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 1, 60)
            if not t or r is None or len(r) < 30:
                continue
            H = [float(x["high"]) for x in r]; L = [float(x["low"]) for x in r]
            C = [float(x["close"]) for x in r]
            atr = sum(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
                      for i in range(1, len(r))) / (len(r) - 1)
            d = [C[i] - C[i - 1] for i in range(1, len(C))][-14:]
            g = sum(x for x in d if x > 0) / 14
            p = -sum(x for x in d if x < 0) / 14
            rsi = 100 - 100 / (1 + g / p) if p else 100
            j24 = (C[-1] / C[-24] - 1) * 100 if len(C) > 24 else 0
            i = mt5.symbol_info(s)
            euros_atr = abs(float(mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY, s, i.volume_min, C[-1], C[-1] + atr) or 0))
            lignes.append(
                f"  {s} : prix {t.bid}, ATR H1 {atr:.2f} (= {euros_atr:.2f} € au lot "
                f"minimum {i.volume_min}), RSI H1 {rsi:.0f}, variation 24 h {j24:+.2f} %, "
                f"spread {(t.ask - t.bid):.5f}")
        mt5.shutdown()
    except Exception as e:
        lignes.append(f"(données de marché partielles : {type(e).__name__})")
    return "\n".join(lignes)


def _calendrier():
    f = Path(__import__("portabilite").mql5_files() or HERE) / "acid_calendrier_histo.csv"
    # (version publique : le calendrier est trouvé par portabilite.py, plus de chemin gravé en dur)
    try:
        now = time.time()
        out = []
        for l in f.read_text(encoding="cp1252", errors="replace").splitlines():
            p = l.split("|")
            if len(p) >= 4 and p[2] == "HIGH":
                try:
                    q = int(p[0])
                except ValueError:
                    continue
                if 0 < q - now < 12 * 3600:
                    out.append(f"  - {p[3][:60]} dans {(q - now) / 3600:.1f} h")
        return "\n".join(out[:6]) or "  (aucune annonce majeure dans les 12 h)"
    except Exception:
        return "  (calendrier indisponible)"


# ══ LA DÉLIBÉRATION ══════════════════════════════════════════════════════
def _membre(equipe, numero, consigne, question, dossier, web, cal):
    """Un calculateur. Les quatre de l'équipe reçoivent EXACTEMENT le même
    esprit et le même dossier — c'est voulu : leur accord vaut preuve, leur
    désaccord vaut avertissement."""
    nom = f"calculateur {numero}"
    # 🩹 10/10 — les quatre appels partaient à la même milliseconde et deux se
    # faisaient refuser pour limite de débit : l'équipe rendait un vote à 2/4
    # sans que personne ne le sache. On les décale d'une seconde chacun.
    time.sleep(1.2 * (numero - 1))
    sys_msg = f"{EQUIPES[equipe]['ame']}\n\n{MENTALITE}\n\n{CADRE}"
    user = (f"QUESTION POSÉE : {question}\n\n"
            f"=== DONNÉES DU COMPTE ET DES MARCHÉS ===\n{dossier}\n\n"
            f"=== ANNONCES ÉCONOMIQUES À VENIR ===\n{cal}\n\n"
            f"=== CE QUE DIT INTERNET À L'INSTANT ===\n{web}\n\n"
            f"{consigne}")
    return nom, _ask(EQUIPES[equipe]["modele"],
                     [{"role": "system", "content": sys_msg},
                      {"role": "user", "content": user}], max_tokens=700)


def deliberer(equipe, question, avec_signal=True, dossier=None, web=None):
    """Les 4 mathématiciens travaillent, le porte-parole rend UN avis."""
    e = EQUIPES[equipe]
    dossier = dossier if dossier is not None else dossier_marche()
    web = web if web is not None else recherche_web(f"{question} marché or NAS100 pétrole bitcoin actualité")
    cal = _calendrier()
    consigne = ("Fais ton calcul seul, en 7 lignes maximum. Donne tes chiffres : "
                "ce qu'on risque, ce qu'on vise, a quel prix on entre, a quel prix "
                "on a tort. Termine par une ligne « VERDICT : » suivie de ton avis "
                "en une phrase — et si le calcul dit d'attendre, dis d'attendre.")
    notes = []
    with _cf.ThreadPoolExecutor(max_workers=NB_MEMBRES) as ex:
        futs = [ex.submit(_membre, equipe, i + 1, consigne, question, dossier, web, cal)
                for i in range(NB_MEMBRES)]
        for f in _cf.as_completed(futs):
            try:
                notes.append(f.result())
            except Exception as ex2:
                notes.append(("?", f"[erreur : {ex2}]"))
    notes.sort(key=lambda n: n[0])
    corps = "\n\n".join(f"### {n}\n{t}" for n, t in notes)
    # combien ont VRAIMENT répondu : un calculateur muet ne doit pas être compté
    # comme un avis contraire. Le porte-parole doit le savoir pour que son vote
    # veuille dire quelque chose.
    repondu = sum(1 for _, t in notes if not t.lstrip().startswith("["))
    etat = (f"{repondu}/{NB_MEMBRES} de tes calculateurs ont rendu une note"
            + ("" if repondu == NB_MEMBRES else
               f" — les {NB_MEMBRES - repondu} autres n'ont pas répondu (panne, pas"
               " désaccord : ne les compte PAS comme des avis contraires)"))

    sys_pp = (f"Tu es le PORTE-PAROLE de l'équipe {e['nom']}. Tes quatre "
              f"calculateurs ont travaillé SÉPARÉMENT sur le même dossier, sans "
              f"se voir. Ton travail : rendre UN SEUL avis au patron.\n"
              f"LA RÈGLE DU VOTE : ce sur quoi les quatre tombent d'accord est "
              f"SOLIDE — dis-le avec force. Ce sur quoi ils divergent veut dire "
              f"que le marché n'est pas lisible — dis-le franchement au lieu de "
              f"trancher au hasard. Ne répète jamais quatre fois la même chose.\n"
              f"Tu parles au patron directement, en français.\n\n{MENTALITE}\n\n{CADRE}")
    demande = (
        f"QUESTION DU PATRON : {question}\n\n"
        f"ÉTAT DE L'ÉQUIPE : {etat}.\n\n"
        f"=== LES NOTES DE TON ÉQUIPE ===\n{corps}\n\n"
        "Rends :\n"
        "1. L'AVIS DE L'ÉQUIPE — 8 lignes maximum, au patron, sans détour.\n"
        "2. LE VOTE — combien de tes quatre calculateurs sont d'accord, et sur quoi "
        "ils divergent le cas échéant (une ligne, par exemple « 4/4 unanimes »).\n")
    if avec_signal:
        demande += (
            "3. Un bloc JSON sur UNE ligne, exactement ce format, rien autour :\n"
            '{"signal": true|false, "marche": "XAUUSD+|NAS100|CL-OIL|BTCUSD", '
            '"sens": "BUY|SELL", "confiance": 0-100, "entree": 0, '
            '"stop": <prix>, "objectif": <prix>, "raison": "<une phrase>"}\n'
            "Mets \"signal\": false si rien ne mérite un trade MAINTENANT. "
            "N'invente jamais un prix : le stop et l'objectif doivent venir des "
            "données réelles ci-dessus. \"entree\": 0 veut dire au prix du marché.")
    avis = _ask(e["porte_parole"], [{"role": "system", "content": sys_pp},
                                    {"role": "user", "content": demande}], max_tokens=1100)
    sig = None
    m = re.search(r'\{[^{}]*"signal"[^{}]*\}', avis)
    if m:
        try:
            sig = json.loads(m.group(0))
            avis = avis.replace(m.group(0), "").rstrip()
        except Exception:
            sig = None
    return {"equipe": equipe, "nom": e["nom"], "emoji": e["emoji"],
            "question": question, "notes": notes, "avis": avis.strip(),
            "signal": sig, "quand": dt.datetime.now().isoformat(timespec="seconds")}


def consulter(question, equipes=("A", "B"), avec_signal=True):
    """Les deux équipes sur la même question, avec le même dossier."""
    d = dossier_marche()
    w = recherche_web(f"{question} or NAS100 pétrole bitcoin marché actualité")
    out = []
    with _cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(deliberer, e, question, avec_signal, d, w): e for e in equipes}
        for f in _cf.as_completed(futs):
            try:
                out.append(f.result())
            except Exception as ex2:
                out.append({"equipe": futs[f], "nom": EQUIPES[futs[f]]["nom"],
                            "emoji": EQUIPES[futs[f]]["emoji"], "question": question,
                            "notes": [], "avis": f"[délibération impossible : {ex2}]",
                            "signal": None, "quand": dt.datetime.now().isoformat()})
    out.sort(key=lambda r: r["equipe"])
    _journaliser(out)
    _ecrire_signaux(out)
    return out


def _journaliser(resultats):
    try:
        with open(JOURNAL, "a", encoding="utf-8") as f:
            for r in resultats:
                f.write(json.dumps({k: v for k, v in r.items() if k != "notes"},
                                   ensure_ascii=False) + "\n")
    except Exception:
        pass


def _ecrire_signaux(resultats):
    """Ce que le cerveau exécutera. Le patron : «…
    …»."""
    sigs = []
    for r in resultats:
        s = r.get("signal")
        if s and s.get("signal") and s.get("marche") in MARCHES and s.get("sens") in ("BUY", "SELL"):
            s = dict(s)
            s["equipe"] = r["nom"]
            s["quand"] = r["quand"]
            s["ts"] = time.time()
            sigs.append(s)
    try:
        SIGNAUX.write_text(json.dumps(sigs, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return sigs


def texte(r):
    """Mise en forme pour le Centre et pour Telegram."""
    t = [f"{r['emoji']} ÉQUIPE {r['nom']} — {r['quand'][11:16]}", "", r["avis"]]
    s = r.get("signal")
    if s and s.get("signal"):
        t += ["", f"📍 SIGNAL : {s.get('sens')} {s.get('marche')} · confiance "
                  f"{s.get('confiance')}% · stop {s.get('stop')} · objectif {s.get('objectif')}",
              f"   « {s.get('raison', '')} »"]
    elif s is not None:
        t += ["", "📍 Aucun trade ne mérite d'être pris maintenant."]
    return "\n".join(t)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args and args[0].upper() in ("A", "B"):
        eq = args[0].upper()
        q = " ".join(args[1:]) or "Où faut-il investir maintenant, et comment capturer le mouvement ?"
        print(f"🧮 consultation de l'équipe {EQUIPES[eq]['nom']}…\n")
        r = deliberer(eq, q)
        _journaliser([r]); _ecrire_signaux([r])
        print(texte(r))
    else:
        q = (" ".join(args[1:]) if args and args[0] == "duel" else " ".join(args)) or \
            "Où faut-il investir maintenant sur l'or, le NAS100, le pétrole ou le BTC, et comment capturer ce mouvement de façon logique ?"
        print(f"🧮 LE CONSEIL DÉLIBÈRE — 8 mathématiciens, 2 équipes\n   question : {q}\n")
        t0 = time.time()
        for r in consulter(q):
            print(texte(r))
            print("\n" + "─" * 78 + "\n")
        print(f"   délibération en {time.time() - t0:.0f} s · signaux : {SIGNAUX.name}")
