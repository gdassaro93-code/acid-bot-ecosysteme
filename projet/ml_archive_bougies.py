import io,sys; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8")
# ============================================================================
# 🕯️📦 ML ARCHIVE BOUGIES — Téléchargement + archivage historique XM (MT5)
# ============================================================================
# Objectif : sauvegarder TOUT l'historique de bougies disponible chez XM pour
# chaque symbole utilisé par les vrais trades VTMarkets (ml_data/trades_reels.csv).
#
# Pourquoi c'est une ASSURANCE : la fenêtre "Max bars" du terminal (100 000)
# efface progressivement le M15 le plus ancien. Chaque exécution ré-archive
# ce qui est encore disponible → on fige l'historique sur disque.
#
# Sortie : C:/AcidBot/BOT COMPLETO/ml_data/candles/{SYMBOLE}_{TF}.csv.gz
#   (le "#" des symboles XM est retiré du nom de fichier, "/" impossible ici)
# ============================================================================

import os
import time
import pandas as pd
import MetaTrader5 as mt5

# 📂 Dossiers
DOSSIER_ML      = r"C:/AcidBot/BOT COMPLETO/ml_data"
DOSSIER_CANDLES = os.path.join(DOSSIER_ML, "candles")
os.makedirs(DOSSIER_CANDLES, exist_ok=True)

# 🗺️ Correspondance symboles VTMarkets → XM (validée trade par trade en amont)
SYMBOL_MAP_VTM_XM = {
    # --- cas particuliers ---
    "xauusd": "GOLD#",     "cl": "OILCash#",      "usousd": "OILCash#",
    "dj30.": "US30Cash#",  "dax40.": "GER40Cash#", "nas100.": "US100Cash#",
    "fra40.": "FRA40Cash#","dogusd": "DOGEUSD#",  "mtcusd": "MATICUSD#",
    "atmusd": "ATOMUSD#",  "amd": "AdvMicroDev",  "nvidia": "Nvidia",
    # --- règle générale : MAJUSCULES + suffixe # ---
    "btcusd": "BTCUSD#",   "gbpjpy": "GBPJPY#",   "eurusd": "EURUSD#",
    "usdchf": "USDCHF#",   "gbpusd": "GBPUSD#",   "gbpchf": "GBPCHF#",
    "eurjpy": "EURJPY#",   "ethusd": "ETHUSD#",   "eurgbp": "EURGBP#",
    "solusd": "SOLUSD#",   "ltcusd": "LTCUSD#",   "adausd": "ADAUSD#",
    "cadjpy": "CADJPY#",   "etheur": "ETHEUR#",   "euraud": "EURAUD#",
    "btceur": "BTCEUR#",   "audchf": "AUDCHF#",   "eurcad": "EURCAD#",
    "audusd": "AUDUSD#",   "xrpusd": "XRPUSD#",   "axsusd": "AXSUSD#",
    "gbpaud": "GBPAUD#",   "nzdusd": "NZDUSD#",   "nzdchf": "NZDCHF#",
    "audnzd": "AUDNZD#",   "chfjpy": "CHFJPY#",   "gbpnzd": "GBPNZD#",
    "fetusd": "FETUSD#",   "usdjpy": "USDJPY#",
}
# ⛔ Exclus (pas d'équivalent XM ou paire inversée) : usdx., xauaud, bnbusd,
#    xagaud, ethbch, btceth — 9 trades au total.

# ⏱️ Timeframes à archiver
TIMEFRAMES = {
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

MAX_BARRES = 99_999  # ⚠️ demander 100 000 pile → erreur MT5 "Invalid params" (limite stricte)


def telecharger(symbole_xm: str, tf_nom: str, tf_mt5) -> pd.DataFrame:
    """📥 Récupère le maximum de bougies disponibles pour un symbole/timeframe."""
    rates = mt5.copy_rates_from_pos(symbole_xm, tf_mt5, 0, MAX_BARRES)
    if rates is None or len(rates) == 0:
        # 🔁 Plan B : plage explicite 2009 → maintenant
        from datetime import datetime, timedelta
        rates = mt5.copy_rates_range(symbole_xm, tf_mt5,
                                     datetime(2009, 1, 1),
                                     datetime.now() + timedelta(days=2))
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    # 🕐 Heure serveur broker (EET) — identique au bot (get_rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def main():
    if not mt5.initialize():
        print(f"❌ mt5.initialize() a échoué : {mt5.last_error()}")
        sys.exit(1)
    info = mt5.terminal_info()
    print(f"✅ MT5 connecté : {info.name if info else '?'}")

    symboles_xm = sorted(set(SYMBOL_MAP_VTM_XM.values()))
    rapport = []

    for sym in symboles_xm:
        # 👁️ Rendre le symbole visible dans le Market Watch (sinon pas de data)
        if not mt5.symbol_select(sym, True):
            print(f"⚠️ symbol_select a échoué pour {sym} : {mt5.last_error()}")
        time.sleep(0.1)

        for tf_nom, tf_mt5 in TIMEFRAMES.items():
            df = telecharger(sym, tf_nom, tf_mt5)
            nom_fichier = f"{sym.replace('#','')}_{tf_nom}.csv.gz"
            chemin = os.path.join(DOSSIER_CANDLES, nom_fichier)
            if df.empty:
                print(f"   ❌ {sym} {tf_nom} : AUCUNE donnée")
                rapport.append((sym, tf_nom, 0, "", ""))
                continue
            df.to_csv(chemin, index=False, compression="gzip")
            debut, fin = df["time"].iloc[0], df["time"].iloc[-1]
            print(f"   💾 {sym:12s} {tf_nom:3s} : {len(df):6d} barres  {debut} → {fin}")
            rapport.append((sym, tf_nom, len(df), str(debut), str(fin)))

    mt5.shutdown()

    # 🧾 Récapitulatif archivage (utilisé aussi comme trace écrite)
    rec = pd.DataFrame(rapport, columns=["symbole_xm", "tf", "n_barres", "debut", "fin"])
    rec.to_csv(os.path.join(DOSSIER_CANDLES, "_recap_archivage.csv"), index=False)
    print(f"\n📦 Archivage terminé : {len(rec)} fichiers dans {DOSSIER_CANDLES}")


if __name__ == "__main__":
    main()
