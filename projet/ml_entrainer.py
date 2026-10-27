# -*- coding: utf-8 -*-
# =====================================================
#  🧠 RÉINITIALISATION DU ML (29/08/26 — demande patron)
#
#  L'ANCIEN ML est mort le 21/08 : 542 avis jetés sur 575 (94%), scores
#  bloqués à «…» (= la valeur de repli, pas une prédiction). Cause :
#  il avait appris sur 19 661 trades RÉELS du patron, à 38,8% de réussite,
#  arrêtés en juillet 2025. Il avait donc appris à reconnaître les
#  configurations où le patron PERDAIT — et sur un marché disparu depuis.
#
#  LE NOUVEAU apprend du MARCHÉ, pas de nos erreurs :
#  157 176 exemples générés par ml_dataset_prix.py depuis les prix Vantage
#  (avril 2025 → août 2026), spread réel déduit à l'entrée ET à la sortie.
#  La question posée à chaque bougie est la seule qui compte :
#      «…»
#
#  PROTOCOLE ANTI-ILLUSION (le même qui a démasqué l'ancien) :
#   • découpage TEMPOREL strict — on entraîne sur le passé, on teste sur
#     l'avenir jamais vu (jamais de mélange aléatoire : ça fuit)
#   • FOSSÉ de 15 jours entre les deux — sans lui, un trade d'entraînement
#     a son résultat dans la période de test (l'AUC monte à tort)
#   • TEST DE PARANOÏA — on réentraîne sur des étiquettes MÉLANGÉES : si
#     l'AUC reste haute, le modèle triche. Elle doit retomber à ~0,50
#   • ESPÉRANCE EN R — l'AUC ne nourrit personne. Ce qui compte, c'est
#     combien il gagne par trade une fois utilisé comme filtre.
#
#  Le modèle n'est ENREGISTRÉ que s'il passe les trois tests. Sinon on ne
#  garde rien : mieux vaut pas de ML qu'un ML qui ment.
#
#      python ml_entrainer.py
# =====================================================
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
DATASET = HERE / "ml_data" / "dataset_prix.csv"
MODELE = HERE / "ml_data" / "modele_prix.pkl"
CARTE = HERE / "ml_data" / "modele_prix_carte.json"

FEATURES = ["sens", "rsi", "rsi_h4", "ema_ratio", "atr_pct", "macd",
            "bollinger_width", "heure", "jour_semaine", "pos_range20",
            "ret_1d", "ret_5d", "impulsion_atr", "impulsion_proprete",
            "impulsion_sens", "spread_pct_risque"]
FOSSE_JOURS = 15
MIN_TRADES = 800     # volume minimal pour qu'un seuil soit CRÉDIBLE (anti-chance)
TP_R = 2.0          # le dataset a été construit avec un objectif à 2R


def entrainer():
    if not DATASET.exists():
        print("❌ dataset absent — lance d'abord : python ml_dataset_prix.py")
        return False
    d = pd.read_csv(DATASET)
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    print(f"📊 {len(d)} exemples, du {d['date'].min():%d/%m/%Y} au {d['date'].max():%d/%m/%Y}")
    print(f"   {100 * d['gagnant'].mean():.1f}% de gagnants "
          f"(l'équilibre à {TP_R:g}R est à {100 / (1 + TP_R):.1f}%)\n")

    coupe = d["date"].quantile(0.70)
    fosse = coupe + pd.Timedelta(days=FOSSE_JOURS)
    tr, te = d[d["date"] <= coupe], d[d["date"] >= fosse]
    print(f"🔪 entraînement {len(tr)} (jusqu'au {coupe:%d/%m/%Y})")
    print(f"   FOSSÉ de {FOSSE_JOURS} jours — aucun trade d'entraînement ne peut")
    print(f"   avoir son résultat dans la période de test")
    print(f"   test {len(te)} (à partir du {fosse:%d/%m/%Y}, jamais vus)\n")

    Xtr, ytr = tr[FEATURES].values, tr["gagnant"].values
    Xte, yte = te[FEATURES].values, te["gagnant"].values

    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                       max_depth=5, random_state=42)
    m.fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(yte, p)

    # test de paranoïa : étiquettes mélangées → l'AUC DOIT s'effondrer
    rng = np.random.default_rng(0)
    faux = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                          max_depth=5, random_state=42)
    faux.fit(Xtr, rng.permutation(ytr))
    auc_faux = roc_auc_score(yte, faux.predict_proba(Xte)[:, 1])
    signal = auc - auc_faux

    print(f"🎯 AUC sur l'avenir non vu : {auc:.4f}")
    print(f"🎲 AUC étiquettes mélangées : {auc_faux:.4f}   (doit être ~0.50)")
    print(f"📶 SIGNAL NET : {signal:+.4f}\n")

    # ce qui compte vraiment : l'espérance en R une fois utilisé comme filtre
    print("💰 EN FILTRE — combien il rapporterait par trade :")
    meilleur = None
    for seuil in np.arange(0.26, 0.60, 0.02):
        sel = p >= seuil
        if sel.sum() < 150:
            break
        tx = yte[sel].mean()
        esp = tx * TP_R - (1 - tx)
        marque = "  ← RENTABLE" if esp > 0 else ""
        print(f"   P≥{seuil:.2f} : {sel.sum():6d} trades gardés, "
              f"{100 * tx:4.1f}% gagnants, espérance {esp:+.3f}R{marque}")
        # 🎯 On ne retient PAS le seuil à la meilleure espérance : le plus
        # étroit (P≥0.48) affichait +0,186R... sur 167 trades, soit 0,4% de
        # l'échantillon. À ce volume, l'espérance peut être de la chance pure.
        # On exige MIN_TRADES preuves — mieux vaut +0,139R démontré sur 1522
        # trades que +0,186R sur une poignée.
        if esp > 0 and sel.sum() >= MIN_TRADES and (meilleur is None or esp > meilleur[1]):
            meilleur = (float(seuil), float(esp), int(sel.sum()), float(tx))

    print()
    if signal < 0.03:
        print("❌ REFUSÉ : signal trop faible — le modèle n'a rien appris de réel.")
        print("   On ne l'enregistre pas. Mieux vaut pas de ML qu'un ML qui ment.")
        return False
    if meilleur is None:
        print("❌ REFUSÉ : aucun seuil rentable. Il sait trier, mais pas assez")
        print("   pour couvrir le coût des trades. On ne l'enregistre pas.")
        return False

    seuil, esp, n, tx = meilleur
    m.fit(d[FEATURES].values, d["gagnant"].values)   # ré-entraîné sur TOUT
    joblib.dump({"modele": m, "features": FEATURES, "seuil": seuil}, MODELE)
    CARTE.write_text(json.dumps({
        "cree_le": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "exemples": int(len(d)),
        "periode": f"{d['date'].min():%Y-%m-%d} → {d['date'].max():%Y-%m-%d}",
        "auc": round(float(auc), 4),
        "auc_paranoia": round(float(auc_faux), 4),
        "signal_net": round(float(signal), 4),
        "seuil_recommande": round(seuil, 2),
        "esperance_R": round(esp, 3),
        "reussite_au_seuil": round(100 * tx, 1),
        "trades_gardes_sur_test": n,
        "features": FEATURES,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ VALIDÉ ET ENREGISTRÉ → {MODELE.name}")
    print(f"   seuil recommandé : {seuil:.2f}  ({100 * tx:.1f}% de réussite, "
          f"{esp:+.3f}R par trade)")
    print(f"   fiche : {CARTE.name}\n")
    print("   ⚠️ Il n'est PAS encore branché. Pour lui rendre la parole :")
    print("      ML_DANS_LE_CYCLE = True dans ia_watchdog.py")
    print("   Et même là, il reste CONSULTATIF — pas de droit de veto.")
    return True


if __name__ == "__main__":
    print("=" * 62)
    print("🧠 RÉINITIALISATION DU ML — il réapprend du marché, pas de nos erreurs")
    print("=" * 62 + "\n")
    entrainer()
