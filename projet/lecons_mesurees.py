# -*- coding: utf-8 -*-
"""
📊 LES LEÇONS QUE LE CERVEAU S'ÉCRIT TOUT SEUL  (28/09/2026)

LE PATRON : «…
…
…».

CE QUI MANQUAIT, ET QUI EXPLIQUE TOUT
Le prompt de décision du cerveau contient 25 blocs (plan, figures, dollar,
carnet d'ordres, yeux, tableau, COT…). Aucun ne lui dit CE QUE SES PROPRES
DÉCISIONS ONT DONNÉ. Il ouvrait donc chaque cycle avec la même ignorance que la
veille. Les leçons existantes (acid_lecons.txt) n'étaient injectées que dans le
chat Telegram et dans la validation des charts de l'EA — jamais dans la tête qui
décide.

CE QUE FAIT CE MODULE
Il lit l'historique RÉEL du compte et en tire des phrases courtes, chiffrées,
dans la langue du bot. Aucune IA n'intervient : c'est de l'arithmétique sur ses
propres trades. Donc ça ne peut pas halluciner, ça ne coûte aucun token à
produire, et ça se met à jour tout seul à chaque trade qui se ferme.

Exemple de ce qu'il produit :
    PLAN du jour : 46 trades, X €/trade, 83 % gagnants  → ton meilleur geste
    IA_OEIL      : 31 trades, X €/trade, 48 % gagnants  → n'ouvre pas sans raison

    python lecons_mesurees.py        # pour voir ce que le cerveau lira
"""
import collections
import datetime as dt

MAGIC_OEIL = 999111
JOURS = 30
MINI = 8            # en dessous, on ne conclut rien et on le dit


def _nom_module(commentaire: str) -> str:
    c = (commentaire or "").strip()
    if "CLUSTER" in c:
        return "PANIER"
    if "PLAN" in c:
        return "PLAN du jour"
    if "pending" in c.lower():
        return "PIÈGE en attente"
    if "RETOUR" in c:
        return "RETOUR moyenne"
    if "RECUP" in c:
        return "RÉCUP"
    if "DAVO" in c:
        return "PISTEUR DAVO"
    if "CONV" in c:
        return "CONVICTION"
    if c.endswith("_R"):
        return "RAFALE"
    if c.startswith("IA_OEIL"):
        return "INSTINCT (sans plan)"
    return c or "?"


def _trades(mt5, jours=JOURS, magic=MAGIC_OEIL):
    deals = mt5.history_deals_get(dt.datetime.now() - dt.timedelta(days=jours),
                                  dt.datetime.now() + dt.timedelta(days=1)) or []
    par = collections.defaultdict(list)
    for d in deals:
        if d.type in (0, 1):
            par[d.position_id].append(d)
    out = []
    for v in par.values():
        e = next((x for x in v if x.entry == 0), None)
        sorties = [x for x in v if x.entry != 0]
        if not e or not sorties or (magic is not None and e.magic != magic):
            continue
        out.append(dict(module=_nom_module(e.comment), marche=e.symbol,
                        sens="achat" if e.type == 0 else "vente",
                        heure=dt.datetime.fromtimestamp(e.time, dt.timezone.utc).hour,
                        minutes=(max(x.time for x in sorties) - e.time) / 60,
                        euros=sum(x.profit + x.swap + x.commission for x in v)))
    return out


def _ligne(nom, v):
    n = len(v)
    tot = sum(x["euros"] for x in v)
    moy = tot / n
    wr = 100.0 * sum(1 for x in v if x["euros"] > 0) / n
    return n, tot, moy, wr, f"{nom} : {n} trades, {moy:+.2f} €/trade, {wr:.0f} % gagnants"


def texte(mt5, jours=JOURS) -> str:
    """Le bloc à injecter dans le prompt. Court exprès : il est lu à chaque cycle."""
    try:
        t = _trades(mt5, jours)
    except Exception as e:
        return f"(mesures indisponibles : {e})"
    if len(t) < MINI:
        return (f"Tu n'as que {len(t)} trades clos sur {jours} jours : trop peu pour "
                f"en tirer une règle. N'invente pas de conclusion là-dessus.")
    lignes = [f"Sur {jours} jours, {len(t)} de tes trades se sont fermés. "
              f"Total : {sum(x['euros'] for x in t):+.2f} €. Voilà ce que TES décisions ont donné "
              f"— ce sont des faits, pas des avis :", "", "PAR MODULE :"]
    par = collections.defaultdict(list)
    for x in t:
        par[x["module"]].append(x)
    classe = sorted(par.items(), key=lambda kv: -sum(y["euros"] for y in kv[1]))
    bons, mauvais = [], []
    for nom, v in classe:
        n, tot, moy, wr, txt = _ligne(nom, v)
        if n < MINI:
            lignes.append(f"  {txt}  (peu de trades : ne conclus rien)")
            continue
        lignes.append(f"  {txt}  → total {tot:+.2f} €")
        (bons if moy > 0 else mauvais).append((nom, moy, n))
    par_m = collections.defaultdict(list)
    for x in t:
        par_m[x["marche"]].append(x)
    forts = [(m, *_ligne(m, v)[:4]) for m, v in par_m.items() if len(v) >= MINI]
    if forts:
        lignes += ["", "PAR MARCHÉ :"]
        for m, n, tot, moy, wr in sorted(forts, key=lambda z: -z[2]):
            lignes.append(f"  {m} : {n} trades, {moy:+.2f} €/trade, {wr:.0f} % gagnants, total {tot:+.2f} €")
    court = [x["euros"] for x in t if x["minutes"] < 15]
    long_ = [x["euros"] for x in t if x["minutes"] >= 60]
    if len(court) >= MINI and len(long_) >= MINI:
        lignes += ["", f"DURÉE : sous 15 min → {sum(court)/len(court):+.2f} €/trade ({len(court)} trades) · "
                       f"au-delà d'1 h → {sum(long_)/len(long_):+.2f} €/trade ({len(long_)} trades)"]
    lignes += ["", "CE QUE TU EN FAIS, MAINTENANT :"]
    for nom, moy, n in sorted(bons, key=lambda z: -z[1])[:3]:
        lignes.append(f"  ✅ {nom} te rapporte {moy:+.2f} € par trade sur {n} trades : c'est là que tu dois insister.")
    for nom, moy, n in sorted(mauvais, key=lambda z: z[1])[:3]:
        lignes.append(f"  ⛔ {nom} te coûte {moy:.2f} € par trade sur {n} trades : n'ouvre pas comme ça sans "
                      f"une raison que tu peux écrire noir sur blanc.")
    if not mauvais:
        lignes.append("  Aucun module n'est perdant en ce moment : garde ce rythme.")
    return "\n".join(lignes)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import MetaTrader5 as mt5
    import mt5_garde          # noqa: F401 — MT5 ne sera jamais ressuscité
    if not mt5.initialize():
        raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
    print(texte(mt5))
    mt5.shutdown()
