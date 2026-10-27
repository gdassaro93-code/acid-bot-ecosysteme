//+------------------------------------------------------------------+
//|                    ACID IA V1                        |
//|              Scalp + Swing + Pending + Hedge + ML                |
//|                                                                  |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "ACID IA V1 — Multi-Mode Trading Engine"

#include <Trade\Trade.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

CTrade        trade;
CSymbolInfo   symInfo;
CPositionInfo posInfo;
COrderInfo    ordInfo;

//+------------------------------------------------------------------+
//  Fix 01/10 — erreur 10030 "Unsupported filling mode" (multi-symbole :
//  CL-OIL, NAS100...). Certains symboles declarent mal leur filling, donc
//  on ESSAIE les modes (FOK -> IOC -> RETURN) et on garde celui qui passe,
//  a l'OUVERTURE comme a la FERMETURE. Bulletproof, independant des flags.
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING g_fillTry[3] = {ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN};

bool ClosePos(const ulong ticket)
{
   for(int i = 0; i < 3; i++)
   {
      trade.SetTypeFilling(g_fillTry[i]);
      if(trade.PositionClose(ticket)) return true;
      if(trade.ResultRetcode() != TRADE_RETCODE_INVALID_FILL) break;
   }
   return false;
}
bool ClosePosPartial(const ulong ticket, const double vol)
{
   for(int i = 0; i < 3; i++)
   {
      trade.SetTypeFilling(g_fillTry[i]);
      if(trade.PositionClosePartial(ticket, vol)) return true;
      if(trade.ResultRetcode() != TRADE_RETCODE_INVALID_FILL) break;
   }
   return false;
}
bool BuyFix(double vol, string sym = NULL, double price = 0, double sl = 0, double tp = 0, string cm = "")
{
   for(int i = 0; i < 3; i++)
   {
      trade.SetTypeFilling(g_fillTry[i]);
      if(trade.Buy(vol, sym, price, sl, tp, cm)) return true;
      if(trade.ResultRetcode() != TRADE_RETCODE_INVALID_FILL) break;
   }
   return false;
}
bool SellFix(double vol, string sym = NULL, double price = 0, double sl = 0, double tp = 0, string cm = "")
{
   for(int i = 0; i < 3; i++)
   {
      trade.SetTypeFilling(g_fillTry[i]);
      if(trade.Sell(vol, sym, price, sl, tp, cm)) return true;
      if(trade.ResultRetcode() != TRADE_RETCODE_INVALID_FILL) break;
   }
   return false;
}

//+------------------------------------------------------------------+
//  ENUMS
//+------------------------------------------------------------------+
enum ENUM_BOT_MODE
{
   MODE_SCALP   = 0,  // Scalp uniquement
   MODE_SWING   = 1,  // Swing uniquement
   MODE_HYBRID  = 2   // Les deux selon contexte
};

enum ENUM_RISK_LEVEL
{
   RISK_SAFE       = 0,  // Prudent  (0.5%)
   RISK_NORMAL     = 1,  // Normal   (1%)
   RISK_AGGRESSIVE = 2   // Agressif (2%)
};

enum ENUM_REGIME
{
   REG_DEAD    = 0,  // Marché mort
   REG_RANGE   = 1,  // Range
   REG_TREND   = 2,  // Tendance claire
   REG_VIOLENT = 3   // Volatilité extrême
};

enum ENUM_BIAS
{
   BIAS_NONE = 0,
   BIAS_BUY  = 1,
   BIAS_SELL = 2
};

enum ENUM_ASSET
{
   ASSET_GOLD  = 0,
   ASSET_BTC   = 1,
   ASSET_FOREX = 2,
   ASSET_OIL   = 3,
   ASSET_OTHER = 4
};
enum ENUM_ASSET_OVERRIDE
{
   ASSET_AUTO    = 0,  // Auto-detect (defaut)
   ASSET_GOLD_M  = 1,  // Gold / XAUUSD
   ASSET_BTC_M   = 2,  // Bitcoin / BTCUSD
   ASSET_OIL_M   = 3,  // Oil / WTI
   ASSET_FOREX_M = 4,  // Forex
};
//+------------------------------------------------------------------+
//  INPUTS — GLOBAL
//+------------------------------------------------------------------+
input string      GRP_GLOBAL        = "========= GLOBAL =========";
input ulong       MagicNumber       = 20260613;
input bool        TradingEnabled    = false;   // version publique : passe a true en connaissance de cause (voir README.txt)
input ENUM_BOT_MODE   BotMode       = MODE_HYBRID;
input ENUM_RISK_LEVEL RiskLevel     = RISK_NORMAL;
input string      TelegramToken     = "A_REMPLIR_TELEGRAM_BOT_TOKEN";           // Token bot Telegram
input string      TelegramChatID    = "0";           // Chat ID Telegram
input bool        SendTelegram      = false;       // Telegram géré par L'ŒIL (ia_watchdog.py) — plus de notifs de l'EA
input ENUM_ASSET_OVERRIDE AssetOverride = ASSET_AUTO; // Selectionner actif manuellement

input string GRP_ACIDBOT = "========= ACIDBOT BRIDGE =========";
input bool   AcidBotEnabled     = true;
// 🌉 Pont v2 : chemins EN DUR dans la sandbox MQL5\Files (acidbot_commands.txt
// / acidbot_feedback.txt) — les inputs de chemin ont été RETIRÉS (audit 13/07) :
// la sandbox refusait C:\MT5_Bridge en silence, ils ne servaient à rien.
//+------------------------------------------------------------------+
//  INPUTS — RISK MANAGEMENT
//+------------------------------------------------------------------+
input string      GRP_RISK          = "========= RISK =========";
// ⚠️ DEUX ÉTAGES (audit 13/07) : CalcLot dimensionne avec le % ci-dessous,
// puis SecureLot RE-CAPE au SET|RISK de L'ŒIL (défaut 1%) — AGGRESSIVE 2%
// est donc inerte tant que set_risk n'est pas monté. Règles d'acier priment.
input double      RiskPctSafe       = 0.5;          // % SAFE (final capé par SET|RISK)
input double      RiskPctNormal     = 1.0;          // % NORMAL (= defaut SET|RISK) - version publique : reglage de base 1 %
input double      RiskPctAggressive = 2.0;          // % AGGRESSIVE (inerte si SET|RISK<2)
input double      MaxDailyLossPct   = 5.0;          // Perte max journaliere % (0 = desactive) - version publique : 5 %
input double      MaxDailyLossEur   = 0.0;          // Plafond journalier en euros (0 = desactive : seul le % ci-dessus s'applique)
input double      KillSwitchOwnPct  = 15.0;         // dernier rempart : % de perte sur les PROPRES positions de l'EA (version publique : 15 %)
input double      MaxDrawdownPct    = 15.0;         // Drawdown max %
input int         MaxPositions      = 6;            // Positions simultanées max (3→6 le 12/07, pilotable SET|MAXPOS)
input int         MaxTradesPerDay   = 100;          // Plafond d'ENTREES/jour/chart (0 = illimite) — patron 24/07 (100 x 7 charts = 700 max), pilotable SET|MAXDAY
input double      MaxSpreadPips     = 20.0;         // Spread max autorisé (pips)
input double      MinMarginPct      = 200.0;        // Marge libre min %

//+------------------------------------------------------------------+
//  INPUTS — SCALP
//+------------------------------------------------------------------+
input string      GRP_SCALP         = "========= SCALP =========";
input bool        ScalpEnabled      = true;
input ENUM_TIMEFRAMES ScalpTF       = PERIOD_M5;    // Timeframe scalp
input int         Scalp_EMA_Fast    = 8;            // EMA rapide
input int         Scalp_EMA_Slow    = 21;           // EMA lente
input int         Scalp_RSI_Period  = 14;           // RSI période
input double      Scalp_RSI_OB      = 70.0;         // RSI surachat
input double      Scalp_RSI_OS      = 30.0;         // RSI survente
input int         Scalp_ATR_Period  = 14;           // ATR période
input double      Scalp_SL_ATR      = 3.0;          // SL = X * ATR — 08/09 : 2.0 -> 3.0
                                                    // (patron : «…»).
                                                    // A 2 ATR le stop etait dans le bruit : 9 sorties
                                                    // en moins de 5 min le 08/09, toutes au stop.
input double      Scalp_TP_ATR      = 3.0;          // TP = X * ATR
input int         Scalp_ScoreMin    = 6;            // Score min pour entrer (0-10)
input double      Scalp_MaxBougiePct= 60.0;         // 🎯 08/09 (patron : «…
                                                    // …») : on n'entre PAS si le prix a
                                                    // déjà parcouru plus de X % de la bougie en cours
                                                    // dans notre sens. 100 = filtre désactivé.
input int         Scalp_CooldownMin = 15;           // 🧘 08/09 (patron : «…») :
                                                    // temps de repos entre 2 scalps sur CE chart.
                                                    // Avant : AUCUN — une entrée par bougie M5, soit
                                                    // 12/heure/chart. Mesuré le 08/09 : 18 trades pour
                                                    // 4 gagnants, 9 sortis en moins de 5 minutes.
                                                    // MOM a 30 min, le rebond 20 : lui n'avait rien.
input int         Scalp_MaxPerDay   = 10;           // 🎯 25/07 patron : 10 scalps/jour MAX — il choisit ses meilleures balles

//+------------------------------------------------------------------+
//  INPUTS — SWING
//+------------------------------------------------------------------+
input string      GRP_SWING         = "========= SWING =========";
input bool        SwingEnabled      = true;
input ENUM_TIMEFRAMES SwingTF       = PERIOD_H4;    // Timeframe swing
input ENUM_TIMEFRAMES SwingConfirmTF= PERIOD_D1;    // TF confirmation swing
input int         Swing_EMA_Fast    = 21;           // EMA rapide swing
input int         Swing_EMA_Slow    = 55;           // EMA lente swing
input int         Swing_EMA_Trend   = 200;          // EMA tendance
input int         Swing_RSI_Period  = 14;
input double      Swing_RSI_OB      = 65.0;
input double      Swing_RSI_OS      = 35.0;
input int         Swing_ATR_Period  = 14;
input double      Swing_SL_ATR      = 2.8;
input double      Swing_TP_ATR      = 5.0;          // RR minimum 1:2.5
input int         Swing_ScoreMin    = 7;
input int         Swing_MaxDays     = 15;           // Max jours en position swing

//+------------------------------------------------------------------+
//  INPUTS — PENDING ORDERS
//+------------------------------------------------------------------+
input string      GRP_PENDING       = "========= PENDING ORDERS =========";
input bool        PendingEnabled    = true;
input double      BuyLimit_Offset   = 30.0;         // Pips sous le prix pour Buy Limit
input double      SellLimit_Offset  = 30.0;         // Pips au-dessus pour Sell Limit
input double      BuyStop_Offset    = 20.0;         // Pips au-dessus pour Buy Stop
input double      SellStop_Offset   = 20.0;         // Pips sous pour Sell Stop
input int         Pending_Expiry_H  = 24;           // Expiration pending (heures)
input bool        AutoOverbid       = true;         // Surenchère auto sur pending
input double      OverbidPips       = 2.0;          // Pips de surenchère

//+------------------------------------------------------------------+
//  INPUTS — HEDGE
//+------------------------------------------------------------------+
input string      GRP_HEDGE         = "========= HEDGE =========";
input bool        HedgeEnabled      = true;
input double      HedgeTriggerPips  = 50.0;         // Perte en pips pour déclencher hedge
input double      HedgeRatio        = 1.0;          // Ratio hedge (1.0 = 100%)
input double      HedgeClosePips    = 30.0;         // Profit pour fermer hedge

//+------------------------------------------------------------------+
//  INPUTS — TRAILING + BREAKEVEN
//+------------------------------------------------------------------+
input string      GRP_TRAIL         = "========= TRAILING & BE =========";
input bool        UseBreakEven      = true;
input double      BreakEvenPips     = 120.0;        // 30→120 le 02/09 : voir la note ci-dessous
input double      LockBEPips        = 50.0;         // 🔒 +X pips -> SL a l'ENTREE (securise, jamais reperdre un gagnant)
input double      LockBEPart        = 0.50;         // 🔒 part du palier 1 REELLEMENT verrouillee (0 = l'ancien SL a l'entree)
input double      LockProfitAt      = 100.0;        // 🔒 +X pips -> on VERROUILLE du profit
input double      LockProfitGive    = 50.0;         // 🔒 ...SL bloque a +Y pips (on banque)
input double      StallMinATR       = 1.2;          // 🍒 profit mini (x ATR) avant de banquer sur essoufflement
input double      StallGiveFrac     = 0.35;         // 🍒 retombe de X% du sommet + bougie contre = on encaisse (le X du haut)
input int         PG_TempsMortMin   = 10;            // ⏱️ TEMPS MORT : coupe une position qui STAGNE depuis X min sans progresser (0 = off)
input double      PG_TempsMortATR   = 0.5;          // ⏱️ ...seuil de «…» : n'a pas gagne plus de X x ATR depuis son sommet
input bool        UseTrailing       = true;
input double      TrailStartPips    = 150.0;        // 45→150 le 02/09
// 🩹 02/09 — CE QUI COUPAIT LES GAGNANTS (backtest du patron sur l'or, 1 semaine) :
//     position gagnante moyenne : X €    position perdante moyenne : X €
//     facteur de profit 0,42 · X € sur X € · drawdown 91,70%
// Les gains faisaient LA MOITIÉ des pertes. Cause : le BE mordait à 30 pips
// et le trailing démarrait à 45 en suivant de 16 — alors que l'ATR H1 de l'or
// fait ~190 pips. Un trail de 16 pips sur un marché qui respire à 190, c'est
// un étranglement : on sortait au premier hoquet, la course partait sans nous.
// Mesure du 06/08 sur le même sujet : TP sec +101R · avec BE -206R · trail -119R.
// Le patron : «…». C'était encore du BE.
input double      TrailStepPips     = 60.0;         // 16→60 : le stop respire au lieu d'étrangler

input string      GRP_LADDER        = "========= ECHELLE DE SORTIE (patron 21/07) =========";
input bool        LadderEnabled     = false;        // 02/09 : COUPÉ — c'était le 3e couteau (partiel tous les 100 pips)
input double      LadderPartialPips = 100.0;        // TP partiel a chaque palier de X pips (par SYMBOLE via preset)
input double      LadderReentryPips = 500.0;        // a X pips : cloture + reprise meme sens (BTC preset : 5000)
input double      LadderPartialFrac = 0.5;          // fraction fermee a chaque palier

input string      GRP_REBOUND       = "========= REBOUND SNIPER (patron 24/07) =========";
input string      GRP_MOM           = "========= MOMENTUM CAPTURE (patron 25/07) =========";
input bool        MOM_Enabled       = true;         // entree AUTO sur impulsion (grosse bougie alignée) — capte les mouvements entiers
input ENUM_TIMEFRAMES MOM_TF        = PERIOD_H1;    // TF de détection de l'impulsion — M15→H1 le 02/09
// 🕯️ 02/09 (patron : «…»).
// CheckMomentum FAISAIT déjà exactement ça — entrée à la clôture d'une grosse
// bougie alignée — mais en M15. Mesure sur 2000 bougies, spread réel :
//     XAUUSD  M15 : +3R  et INSTABLE (+26 puis -23 sur les deux moitiés)
//     XAUUSD  H1  : +25R et SOLIDE   (+4  puis +21)
//     NAS100  M15 : -34R          H1 : 0R (plat — rien à y prendre)
// Le H1 multiplie le résultat par 8 sur l'or ET le stabilise. Même leçon que
// le détecteur d'impulsion de L'ŒIL le 06/08 : M15 -40R contre H1 +101R.
// Le M15 donne plus de signaux, mais ce sont des signaux de bruit.
input double      MOM_ImpulseATR    = 1.1;          // corps de bougie >= X * ATR = vraie impulsion
input double      MOM_CloseFrac     = 0.70;         // clôture dans les X% haut/bas de la bougie (force du move)
input int         MOM_ADXMin        = 20;           // ADX mini (une tendance qui prend vraiment)
input int         MOM_RSIguard      = 78;           // n'achète pas si RSI > X (ni ne vend si < 100-X) : pas de sommet parabolique
input int         MOM_CooldownMin   = 30;           // 1 capture max / sens / X min
input double      MOM_SL_ATR        = 1.8;          // SL LARGE (laisse rider, FlowRider prend le relais)
input double      MOM_TP_ATR        = 4.0;          // TP loin (on vise la bougie entière, pas 10 pips)

input bool        RB_Enabled        = true;         // entree AUTO sur rebond de niveau (support/resistance)
input ENUM_TIMEFRAMES RB_TF         = PERIOD_M15;   // TF de detection des niveaux et du signal
input int         RB_LookBack       = 96;           // barres analysees (96 x M15 = 24 h de structure)
input int         RB_PivotSpan      = 2;            // force des pivots (3 = extreme sur 7 barres)
input int         RB_MinTouches     = 1;            // 25/07 patron : 1 touche = niveau valide, entree DES le 2e rebond (avant 2 = entree au 3e)
input double      RB_TolATR         = 0.60;         // largeur de la zone autour du niveau (x ATR)
input double      RB_WickFrac       = 0.25;         // meche de rejet minimum (fraction de la bougie)
input double      RB_PadATR         = 0.60;         // marge du SL au-dela du niveau (x ATR)
input double      RB_TP_ATR         = 2.2;          // TP par defaut (x ATR) si aucun niveau oppose utile
input int         RB_CooldownMin    = 20;           // delai mini entre 2 rebonds du meme sens (min)
input bool        RB_DrawLevels     = true;         // dessiner les niveaux detectes sur le chart

input string      GRP_VISION        = "========= ACID VISION — SMC integre (patron 24/07) =========";
input bool        ShowVision        = true;         // dessine Order Blocks + FVG + lignes cles (remplace 4 indicateurs Market)
input bool        Vis_OrderBlocks   = true;         // zones d'ordres institutionnels (ICT)
input bool        Vis_FVG           = true;         // Fair Value Gaps (desequilibres 3 bougies)
input bool        Vis_Lines         = true;         // lignes cles : PDH/PDL/cloture/open du jour + ronds psycho
input bool        Vis_Fibo          = true;         // echelle Fibonacci auto sur le dernier swing (remplace Free Auto Fibonacci)
input int         Vis_LookBack      = 120;          // bougies analysees (OB + FVG + swing du Fibo)
input int         Vis_MaxZones      = 6;            // nb max de zones OB / FVG affichees
input double      Vis_MaxDistATR    = 8.0;          // n'affiche un niveau que s'il est a moins de X ATR du prix (0 = tout)

input string      GRP_EPUIS         = "========= EPUISEMENT / BOUT DE MECHE (patron 27/07) =========";
input bool        EP_Enabled        = true;         // autorise un rebond CONTRE le rail sur capitulation reelle
input double      EP_RSI            = 30.0;         // RSI <= X (achat) ou >= 100-X (vente) : extreme reel
input double      EP_WickFrac       = 0.50;         // meche de rejet mini (fraction de la bougie)
input double      EP_SL_ATR         = 0.9;          // SL SERRE sous la meche (x ATR) — c'est un pari de retournement
input double      EP_LotFrac        = 0.5;          // lot REDUIT (fraction du lot normal)

input string      GRP_PLAN          = "========= PLAN DU JOUR (patron 27/07) =========";
input double      PlanBonusScore    = 1.0;          // bonus/malus de score quand l'EA va dans le sens (ou contre) le plan de L'OEIL

input string      GRP_REPRISE       = "========= REPRISE APRES COUPE MANUELLE (patron 27/07) =========";
input bool        RepriseEnabled    = true;         // si TU coupes a la main un trade ou l'EA croyait fort -> il le reprend
input double      RepriseMinScore   = 7.0;          // conviction mini a l'ouverture (score/12) pour meriter une reprise
input int         RepriseMaxParJour = 3;            // plafond de reprises par jour (anti-boucle)

input string      GRP_OBJ           = "========= LIGNES D'OBJECTIFS (patron 24/07) =========";
input bool        ShowObjectives    = true;         // dessiner Entree/SL/TP1/TP2/TP3 des positions & plans en cours
input color       ObjBuyColor       = clrLimeGreen; // couleur des TP quand on est ACHETEUR
input color       ObjSellColor      = clrTomato;    // couleur des TP quand on est VENDEUR

//+------------------------------------------------------------------+
//  INPUTS — ML BONUS
//+------------------------------------------------------------------+
input string      GRP_ML            = "========= ML ENGINE =========";
input bool        MLEnabled         = true;
input double      MLBonusMax        = 2.0;          // Bonus ML LOCAL (stats maison 30j) — se CUMULE avec le bonus serveur
input double      ML_WinRateWeight  = 0.5;          // Poids winrate dans ML
input double      ML_RRWeight       = 0.5;          // Poids RR dans ML

input string SignalServerURL = "http://127.0.0.1:5001/signal";
input string MLServerURL     = "http://127.0.0.1:8001/predict";
input bool   UseSignalServer = true;
input bool   UseMLServer     = true;

input string GRP_MLSERVER_LIVE       = "========= ML SERVER LIVE (seuil confiance) =========";
input bool   MLServerBlockOpposite   = false;  // 24/07 patron : trades 2 sens autorises (martingale) — le ML ne bloque plus l'oppose
input bool   MLServerBlockHold       = false;  // 25/07 : le ML ne VETO plus (il conseille via bonus) — fin de la paralysie   // Scalp: bloquer si ML = HOLD/NEUTRAL (Swing reste tolerant)
input double MLMinConfidence         = 0.53;   // 25/07 FIX : le ML recalibre sort 0.54-0.62, 0.65 bloquait TOUT   // Confiance ML min pour valider l'entree (le serveur ne descend jamais sous 0.65 en BUY/SELL)
input double MLServerScoreBonusMax   = 2.0;    // Bonus ML SERVEUR (8001) — se CUMULE avec le bonus local (jusqu à +4)
input int    MLServerTimeoutMs       = 2000;   // Timeout WebRequest vers le serveur ML (ms)

input string GRP_SYNC_PY = "========= SYNC BOT PYTHON (Mammouth V7) =========";
input bool   UsePartialTP        = false;   // 02/09 : COUPÉ — le patron veut des positions ENTIÈRES
// 🎯 02/09 (patron, rappel d'une consigne déjà donnée le 22/07) :
// «…
//   …».
// Le partiel laissait un demi-lot orphelin avec un TP mal placé et brouillait
// le suivi. La bonne méthode est celle de L'ŒIL depuis le 22/07 : on ouvre
// 3 positions entières (une par palier TP1/TP2/TP3), et chacune se ferme
// À SON palier. Même effet qu'un partiel, mais lisible et propre.
input double PartialTPPct        = 50.0;    // % du volume ferme au TP1 (PARTIAL_TP_PCT Python)
input bool   NoWeekendTrading    = true;    // 📅 samedi/dimanche : analyse seulement, pas d'entree (12/07)
input bool   UseCrashCatcher     = true;    // Suspendre les entrees apres un mouvement brutal
input int    CrashPauseSec       = 300;     // Duree de pause apres crash (CrashCatcher Python)
input bool   UseAIValidation     = true;    // ON (13/07): l'IA du chart VIT — consultée dès qu'un setup approche du seuil (pré-filtre anti-429 ; conseil ±score, ne bloque JAMAIS)
// 🧠 IA de CE chart (12/07) : chaque graphique choisit son cerveau — il
// discute avec L'ŒIL. Défaut gemini (rapide, discipliné) ; mistral (le
// gagnant de l'Arène en génération), gpt, ou claude sonnet dispo aussi.
enum ENUM_SONNET_AI { AI_GEMINI, AI_MISTRAL, AI_GPT, AI_CLAUDE };
input ENUM_SONNET_AI SonnetAIModel = AI_MISTRAL;  // IA du chart — défaut MISTRAL (04/08 patron : plus jamais gemini sur ré-attache). Identifiant "Sonnet" GARDÉ pour ne pas effacer le choix sauvegardé par chart
input bool   AICanTrade          = true;    // ⚡ ON (13/07 patron): l'IA est LIBRE sur son chart — pendings/close (toujours via SecureLot + règles d'acier). L'ŒIL corrige APRÈS si danger.
input string AIValidationURL     = "http://127.0.0.1:8060/api/ai/validate"; // L'ŒIL (ia_watchdog.py) — cerveau unique, marche sans dashboard
input int    AITimeoutMs         = 10000;   // Timeout WebRequest validation IA (ms)
// 🖼️ INDICATEURS DU CHART (13/07, demande patron) : l'EA lit ce que TES
// indicateurs DESSINENT (objets) — peu importe la marque ou les réglages.
// Chaque famille se coupe ici OU à distance par L'ŒIL (set_chart*) s'il
// constate qu'elle raconte n'importe quoi. Poids modestes : conseillers.
input bool   Use_ChartIndicators = true;    // interrupteur général du bloc
input bool   Use_ChartTrendLines = true;    // lignes (TrendLine PRO + tes tracés)
input bool   Use_ChartArrows     = true;    // flèches BUY/SELL (ex. Boom & Crash smasher)
input bool   Use_ChartFibo       = true;    // niveaux Fibonacci auto (confluence)
input bool   Use_ChartZones      = true;    // rectangles/zones (ex. Fair Value Gaps)
input bool   UseErrorMemory      = true;    // Journal d'erreurs: MQL5\Files\acid_error_memory.csv

input string GRP_PENDING_SAFE = "========= PENDINGS SECURISES =========";
input double Pending_MinSLPips  = 8.0;    // SL plancher (pips) du sizing de TOUS les trades — scalp/swing/pending (fix 07/07)
input double OverbidMinDistPips = 10.0;   // l'overbid ne rapproche jamais un pending a moins de X pips du marche
input int    MaxPendingPerSide  = 1;      // max de pendings par direction BUY/SELL (fini les triplets)
input int    Pending_CooldownMin = 20;    // 🧊 16/09 : pas de pending dans un sens < X min après la sortie d'un pending de ce sens (0 = off, SET|PENDCOOL)
input bool   PendingNeedML      = true;   // ne poser un pending que si le ML confirme la direction
input double PendingMinScore    = 6.0;    // score technique minimum du cote du biais pour poser un pending

input string GRP_TIME_BE = "========= BE TEMPOREL =========";
input bool   TimeBE_Enabled     = true;   // BE base sur le temps : verrouille les trades gagnants
input int    TimeBE_AfterSec    = 300;    // age minimum de la position (secondes)
input int    TimeBE_PositiveSec = 180;     // duree minimale en profit continu (secondes)
input double TimeBE_LockPips    = 40.0;   // 3→40 le 02/09 : on ne bride plus un trade pour 3 pips
// 🩹 02/09 — LE VERROU QUI EMPÊCHAIT D'AVANCER (patron : «…
// …
// …»).
// À +3 pips, le moindre bruit de marché sortait la position : on encaissait
// des clopinettes et le vrai mouvement partait sans nous. C'est le même
// break-even précoce qu'on a MESURÉ le 06/08 : TP sec +101R, avec BE à 1R
// -206R. Le stop ne bouge donc plus avant 40 pips acquis.

//+------------------------------------------------------------------+
//  🧼 URLClean (24/07) — un preset .set corrompu (fins de ligne \r\r\n,
//  bug du generateur du 21/07) injectait un \r INVISIBLE au bout des URLs
//  serveur -> WebRequest 400 sur News ET ML pendant 3 jours ("srv=off",
//  l'EA tradait au score technique seul). On purge TOUT blanc parasite
//  de TOUTE URL avant chaque appel : plus jamais tuable par un preset.
//+------------------------------------------------------------------+
string URLClean(string u)
{
   StringReplace(u, "\r", "");
   StringReplace(u, "\n", "");
   StringReplace(u, "\t", "");
   StringTrimLeft(u);
   StringTrimRight(u);
   return u;
}

//+------------------------------------------------------------------+
//  SIGNAL SERVER — Récupère le signal news depuis le serveur Python
//+------------------------------------------------------------------+
string GetNewsSignalEA()
{
   if(!UseSignalServer) return "safe";

   static datetime lastCall = 0;
   static string   cached   = "safe";

   // Cache : 1 appel max toutes les 60 secondes
   if(TimeCurrent() - lastCall < 60) return cached;
   lastCall = TimeCurrent();

   // Détection du symbole
   string sym = _Symbol;
   if(StringFind(sym,"XAU")>=0 || StringFind(sym,"GOLD")>=0) sym="XAUUSD";
   if(StringFind(sym,"BTC")>=0) sym="BTCUSD";

   // Préparation des tableaux WebRequest
   char   data[];      // corps vide pour un GET
   char   result[];    // réponse brute
   string headers = ""; // headers requête
   string resultHeaders; // headers réponse

   // Appel HTTP
 int code = WebRequest("GET", URLClean(SignalServerURL) + "?symbol=" + sym,
                         headers, 5000, data, result, resultHeaders);

   Print("Code HTTP : ", code);  // 200 = OK

   // Échec de la requête → on garde le cache (URL non autorisée ou serveur éteint)
   if(code != 200)
   {
      Print("❌ Échec WebRequest. Erreur : ", GetLastError());
      cached = "safe";
      return cached;
   }

   // Conversion réponse en string
   string t = CharArrayToString(result);
   Print("✅ Réponse serveur : ", t);  // affiche ce que Python renvoie

   // Parsing du signal
   if(StringFind(t,"crucial")  > -1) cached = "crucial";
   else if(StringFind(t,"high_vol") > -1) cached = "high_vol";
   else if(StringFind(t,"news_now") > -1) cached = "news_now";
   else cached = "safe";

   return cached;
}

//+------------------------------------------------------------------+
//  JSON MINI-PARSER (extraction de champs plats, sans dependance externe)
//+------------------------------------------------------------------+
string JsonGetStr(string json, string key)
{
   string pat = "\"" + key + "\":\"";
   int p = StringFind(json, pat);
   if(p < 0) return "";
   p += StringLen(pat);
   int q = StringFind(json, "\"", p);
   if(q < 0) return "";
   return StringSubstr(json, p, q - p);
}

double JsonGetNum(string json, string key)
{
   string pat = "\"" + key + "\":";
   int p = StringFind(json, pat);
   if(p < 0) return 0.0;
   p += StringLen(pat);
   int len = StringLen(json);
   while(p < len && StringGetCharacter(json, p) == ' ') p++;
   int q = p;
   while(q < len)
   {
      ushort c = StringGetCharacter(json, q);
      if((c >= '0' && c <= '9') || c == '-' || c == '.' || c == 'e' || c == 'E' || c == '+') q++;
      else break;
   }
   return StringToDouble(StringSubstr(json, p, q - p));
}

//+------------------------------------------------------------------+
//  ML SERVER — Prediction reelle (port 8001) avec seuil de confiance
//+------------------------------------------------------------------+
bool GetMLPrediction(string symbol, double rsi, double emaRatio, double atr,
                      double macd, double bbWidth, double newsScore,
                      string &predOut, double &confOut)
{
   predOut = "NEUTRAL";
   confOut = 0.5;
   if(!UseMLServer) return false;

   double rsiC  = MathMax(0.0, MathMin(100.0, rsi));
   double emaC  = MathMax(0.5, MathMin(1.5, emaRatio));
   double atrC  = MathMax(0.0, atr);
   double newsC = MathMax(0.0, MathMin(100.0, newsScore));

   // '#' est un delimiteur de fragment en URL : il tronquerait la query string
   // (symboles broker type GOLD#, BTCUSD#, OILCash#) — on le retire avant l'appel
   string symClean = symbol;
   StringReplace(symClean, "#", "");

   string url = URLClean(MLServerURL)
              + "?symbol="          + symClean
              + "&rsi="             + DoubleToString(rsiC, 2)
              + "&ema_ratio="       + DoubleToString(emaC, 4)
              + "&atr="             + DoubleToString(atrC, 5)
              + "&macd="            + DoubleToString(macd, 5)
              + "&bollinger_width=" + DoubleToString(bbWidth, 5)
              + "&news_score="      + DoubleToString(newsC, 1);

   char   data[];
   char   result[];
   string headers = "";
   string resultHeaders;

   ResetLastError();
   int code = WebRequest("GET", url, headers, MLServerTimeoutMs, data, result, resultHeaders);

   if(code != 200)
   {
      Print("⚠️ ML server injoignable (code=", code, ", err=", GetLastError(), ") — score technique seul");
      return false;
   }

   string body = CharArrayToString(result);
   string pred = JsonGetStr(body, "prediction");
   if(pred != "") predOut = pred;
   confOut = JsonGetNum(body, "confidence");
   return true;
}

//+------------------------------------------------------------------+
//  SYNC BOT PYTHON (Mammouth V7) — partial TP, crash catcher,
//  validation IA et journal d'erreurs : memes regles que
//  BOT_MAMMOUTH_COMPLETE_V7.py, ajoutees sans toucher a l'existant.
//+------------------------------------------------------------------+
ulong    g_PartialDone[];           // tickets deja fermes partiellement
double   g_CrashLastPrice  = 0.0;
datetime g_CrashLastCheck  = 0;
datetime g_CrashPauseUntil = 0;
bool     g_OeilPause       = false; // pause des OUVERTURES demandee par L'ŒIL

void LogErrorMemory(string source, string msg)
{
   if(!UseErrorMemory) return;
   int fh = FileOpen("acid_error_memory.csv", FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI, ';');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   FileWrite(fh, TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS), source, msg);
   FileClose(fh);
}

bool IsPartialDone(ulong ticket)
{
   for(int i = 0; i < ArraySize(g_PartialDone); i++)
      if(g_PartialDone[i] == ticket) return true;
   return false;
}

void MarkPartialDone(ulong ticket)
{
   int n = ArraySize(g_PartialDone);
   ArrayResize(g_PartialDone, n + 1);
   g_PartialDone[n] = ticket;
}

// Ferme PartialTPPct % du volume quand le prix atteint TP1 = mi-chemin du TP
// (regle PARTIAL_TP_PCT=0.5 + tp1 du bot Python). Jamais les hedges (pas de TP).
void ManagePartialTP()
{
   if(!UsePartialTP) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(IsPartialDone(ticket)) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "HEDGE") >= 0) continue;

      double tp = PositionGetDouble(POSITION_TP);
      if(tp <= 0) continue;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      long   type = PositionGetInteger(POSITION_TYPE);
      double cur  = (type == POSITION_TYPE_BUY)
                    ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                    : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double tp1  = open + (tp - open) * 0.5;
      bool   hit  = (type == POSITION_TYPE_BUY) ? (cur >= tp1) : (cur <= tp1);
      if(!hit) continue;

      double vol     = PositionGetDouble(POSITION_VOLUME);
      double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      double closeV  = MathFloor(vol * (PartialTPPct / 100.0) / lotStep) * lotStep;
      if(closeV < minLot || (vol - closeV) < minLot) { MarkPartialDone(ticket); continue; }

      double posProfit = PositionGetDouble(POSITION_PROFIT);
      if(ClosePosPartial(ticket, closeV))
      {
         MarkPartialDone(ticket);
         double closedProfit = (vol > 0) ? posProfit * (closeV / vol) : 0.0;
         SendTelegramMsg(StringFormat("💰 TP PARTIEL | %s | Profit : %+.2f %s",
                                       _Symbol, closedProfit, AccountInfoString(ACCOUNT_CURRENCY)));
      }
      else
         LogErrorMemory("PartialTP", StringFormat("echec ticket %I64u ret=%d", ticket, (int)trade.ResultRetcode()));
   }
}

// Seuils de crash par symbole — memes valeurs que CrashCatcher du bot Python
double CrashThreshold()
{
   if(StringFind(_Symbol, "BTC") >= 0)     return 300.0;
   if(StringFind(_Symbol, "ETHUSD") >= 0)  return 10.0;   // ETH ~1800$
   if(StringFind(_Symbol, "XAU") >= 0 || StringFind(_Symbol, "GOLD") >= 0) return 10.0;
   if(StringFind(_Symbol, "SILVER") >= 0 || StringFind(_Symbol, "XAG") >= 0) return 0.80; // argent ~60$ (0.25 = faux krachs)
   if(StringFind(_Symbol, "US500") >= 0)   return 25.0;   // S&P 500 ~7500 pts
   if(StringFind(_Symbol, "Crypto") >= 0)  return 50.0;   // Crypto_10 ~12750 pts
   if(StringFind(_Symbol, "OIL") >= 0)     return 2.0;
   if(StringFind(_Symbol, "JPY") >= 0)     return 0.5;
   return 50.0 * g_PipSize;             // defaut forex: 50 pips
}

// Mouvement brutal entre deux checks (~30 s) => pause des ENTREES pendant
// CrashPauseSec (la gestion des positions ouvertes continue, comme en Python).
void CheckCrashCatcher()
{
   if(!UseCrashCatcher) return;
   datetime now = TimeCurrent();
   if(now - g_CrashLastCheck < 30) return;
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(g_CrashLastPrice > 0.0 && MathAbs(price - g_CrashLastPrice) >= CrashThreshold())
   {
      bool alreadyPaused = (now < g_CrashPauseUntil);
      g_CrashPauseUntil = now + CrashPauseSec;
      if(!alreadyPaused)
      {
         string msg = StringFormat("⚡ CRASH detecte sur %s (%.5f -> %.5f) — entrees suspendues %d s",
                                    _Symbol, g_CrashLastPrice, price, CrashPauseSec);
         Print(msg);
         SendTelegramMsg(msg);
         LogErrorMemory("CrashCatcher", msg);
      }
   }
   g_CrashLastPrice = price;
   g_CrashLastCheck = now;
}

// Validation IA finale via le dashboard local (Claude, meme cle que le bot
// Python) — equivalent de MammouthAI.analyze_trade : TRADE/SKIP + confiance.
// 🤬 CONSEIL de l'IA intérieure (12/07 — demande patron : «…
// …»).
// Renvoie un AJUSTEMENT de score (jamais un blocage) :
//   TRADE fort → petit bonus | SKIP fort → malus modéré (max -1.5, ne
//   paralyse qu'un setup déjà limite) | IA injoignable → 0 (neutre).
// Le score TECHNIQUE reste le patron ; l'IA ne fait que pencher la marge.
// 💓 BATTEMENT DE CŒUR (12/07) : toutes les 10 min, l'EA écrit dans SON
// journal une ligne «…» avec son modèle IA. L'ŒIL lit le journal
// (sans whitelist) → sait quels charts sont ACTIFS et avec quelle IA,
// donc ils apparaissent dans le chat de groupe MÊME sans trader (week-end).
void SendHeartbeat()
{
   PublishCalendar();   // 📅 08/09 : les serveurs Python n'ont pas accès au calendrier MT5

   // Appelé par OnTimer (temps réel) → marche MÊME marché fermé (week-end),
   // contrairement à OnTick qui ne se déclenche que sur un tick de prix.
   // 👁️ (13/07) : annonce aussi les RÉGLAGES EFFECTIFS du chart (cascade
   // preset SYM+TF > SYM > global > input) — L'ŒIL les lit dans le journal
   // (sans whitelist) et peut donc auditer/optimiser les presets lui-même.
   // 👁️ 04/09 — LA VUE (patron : «…
   // …»). Jusqu'ici ce chart calculait RSI, ADX, tendance
   // et rail pour son dashboard… et ne les envoyait à PERSONNE. Le heartbeat
   // ne remontait que les réglages. On ajoute ce que le chart VOIT, dans un
   // bloc «…» placé AVANT «…» pour ne pas casser le parseur de L'ŒIL
   // (il capture cfg jusqu'en fin de ligne).
   double vRsiB[]; ArraySetAsSeries(vRsiB, true);
   double vRsi = (h_ScalpRSI != INVALID_HANDLE && CopyBuffer(h_ScalpRSI, 0, 0, 1, vRsiB) > 0) ? vRsiB[0] : 0;
   double vAtrB[]; ArraySetAsSeries(vAtrB, true);
   double vAtr = (h_ScalpATR != INVALID_HANDLE && CopyBuffer(h_ScalpATR, 0, 0, 1, vAtrB) > 0) ? vAtrB[0] : 0;
   double vAdx = BrainADX();
   double vRail = 0; int vDir = BrainSuperTrend(vRail);
   Print("💓 alive | model=", AcidAIName(),
         " | aival=", (SEC_Ov("AIVAL", UseAIValidation ? 1 : 0) >= 0.5) ? "on" : "off",
         " | libre=", AIFree() ? "oui" : "non",
         " | vue rsi=", DoubleToString(vRsi, 0),
         " adx=", DoubleToString(vAdx, 0),
         " trend=", (vDir == 1 ? "HAUT" : vDir == -1 ? "BAS" : "NEUTRE"),
         " rail=", DoubleToString(vRail, _Digits),
         " atr=", DoubleToString(vAtr, _Digits),
         " prix=", DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_BID), _Digits),
         " pos=", IntegerToString(CountPositions()),
         " | cfg maxlot=", DoubleToString(SEC_MaxLot(), 2),
         " risk=", DoubleToString(SEC_RiskPct(), 1),
         " slatr=", DoubleToString(SEC_Ov("SLATR", Scalp_SL_ATR), 1),
         " tpatr=", DoubleToString(SEC_Ov("TPATR", Scalp_TP_ATR), 1),
         " bepips=", DoubleToString(SEC_Ov("BEPIPS", BreakEvenPips), 0),
         " trailstart=", DoubleToString(SEC_Ov("TRAILSTART", TrailStartPips), 0),
         " trailstep=", DoubleToString(SEC_Ov("TRAILSTEP", TrailStepPips), 0),
         " scoremin=", DoubleToString(SEC_Ov("SCOREMIN", Scalp_ScoreMin), 1),
         " maxpos=", DoubleToString(SEC_Ov("MAXPOS", MaxPositions), 0),
         " maxcluster=", DoubleToString(SEC_Ov("MAXCLUSTER", 6), 0),
         " newsmin=", DoubleToString(SEC_Ov("NEWSMIN", 15), 0),
         " recovery=", SEC_Recovery() ? "1" : "0",
         " scalp=", (SEC_Ov("SCALP", 1) >= 0.5) ? "1" : "0",
         " pending=", (SEC_Ov("PENDING", 1) >= 0.5) ? "1" : "0",
         " pguard=", (SEC_Ov("PGUARD", 1) >= 0.5) ? "1" : "0",
         " cotveto=", (SEC_Ov("COTVETO", 1) >= 0.5) ? "1" : "0",
         " chartind=", (SEC_Ov("CHARTIND", Use_ChartIndicators ? 1 : 0) >= 0.5) ? "1" : "0",
         " chlines=", ChartIndOn("CHARTLINES", Use_ChartTrendLines) ? "1" : "0",
         " charrows=", ChartIndOn("CHARTARROWS", Use_ChartArrows) ? "1" : "0",
         " chfibo=", ChartIndOn("CHARTFIBO", Use_ChartFibo) ? "1" : "0",
         " chzones=", ChartIndOn("CHARTZONES", Use_ChartZones) ? "1" : "0");
}

// 📅 Week-end : samedi/dimanche = pas de NOUVELLE entrée (la gestion des
// positions ouvertes et les CLOSE continuent normalement).
bool WeekendBlock()
{
   if(!NoWeekendTrading) return false;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   return (dt.day_of_week == 0 || dt.day_of_week == 6);   // 0 = dimanche, 6 = samedi
}

string AcidAIName()
{
   // 🎛️ set_model (13/07, demande patron «…») : L'ŒIL change
   // l'IA du chart à distance — 0=gemini 1=mistral 2=gpt 3=claude, global
   // (SET|MODEL|n) ou par chart (SETSYM). Sans override : l'input du chart.
   int m = (int)MathRound(SEC_Ov("MODEL", (double)SonnetAIModel));
   switch((ENUM_SONNET_AI)m)
   {
      case AI_MISTRAL: return "mistral";
      case AI_GPT:     return "gpt";
      case AI_CLAUDE:  return "claude";
      default:         return "gemini";
   }
}

// ⚡ Liberté d'action de l'IA du chart — pilotable à distance par L'ŒIL
// (SET|CANTRADE|0/1), sinon l'input AICanTrade du chart fait foi.
bool AIFree()
{
   return SEC_Ov("CANTRADE", AICanTrade ? 1 : 0) >= 0.5;
}

// ⚡ L'IA agit (via les RÈGLES D'ACIER : SecureLot + quotas). Elle anticipe
// les ZONES : BUYLIMIT/SELLLIMIT (retour sur support/résistance), BUYSTOP/
// SELLSTOP (cassure), CLOSE (sortie de danger). Garde-fou anti-prix-fantôme.
void ExecuteAIOrder(string ord, double oprice)
{
   if(!AIFree()) return;

   if(ord == "CLOSE")
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
         if(posInfo.SelectByIndex(i) && posInfo.Symbol() == _Symbol
            && posInfo.Magic() == MagicNumber)
            ClosePos(posInfo.Ticket());
      Print("⚡ IA : fermeture des positions ACID IA sur ", _Symbol);
      return;
   }

   // ⚡ MÊME POUVOIR QUE L'ŒIL, borné à SON chart (13/07 patron) : entrée
   // IMMÉDIATE au marché quand l'opportunité est là — mêmes règles d'acier
   // (veto COT natif, SecureLot, quota de positions, week-end).
   if(ord == "BUY" || ord == "SELL")
   {
      if(WeekendBlock()) return;
      if(CountPositions() >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
      if(DailyCapReached()) return;
      bool buy = (ord == "BUY");
      if(CotBlocks(buy)) { Print("🐋 Veto COT — ordre IA ", ord, " bloqué"); return; }
      double atrM[1];
      if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrM) < 1 || atrM[0] <= 0) return;
      double px   = buy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double slDm = SEC_Ov("SLATR", Scalp_SL_ATR) * atrM[0], tpDm = SEC_Ov("TPATR", Scalp_TP_ATR) * atrM[0];
      double slM  = NormalizeDouble(buy ? px - slDm : px + slDm, g_Digits);
      double tpM  = NormalizeDouble(buy ? px + tpDm : px - tpDm, g_Digits);
      double lotM = SecureLot(_Symbol, CalcLot(slDm / g_PipSize), slDm);
      if(lotM <= 0) { Print("⚡ IA ", ord, " refusé : lot hors règles d'acier"); return; }
      bool okM = buy ? BuyFix(lotM, _Symbol, 0, slM, tpM, "AI_MARKET")
                     : SellFix(lotM, _Symbol, 0, slM, tpM, "AI_MARKET");
      Print(okM ? "⚡ IA : " + ord + " marché exécuté (" + DoubleToString(lotM, 2) + " lots)"
                : "⚡ IA " + ord + " échec ret=" + IntegerToString((int)trade.ResultRetcode()));
      return;
   }

   bool isPend = (ord == "BUYLIMIT" || ord == "SELLLIMIT" || ord == "BUYSTOP" || ord == "SELLSTOP");
   if(!isPend || oprice <= 0) return;
   if(WeekendBlock()) return;                            // 📅 pas de nouveau pending IA le week-end
   if(CountPending() > 0) return;                       // 1 pending IA à la fois par chart
   if(CountPositions() >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
   if(DailyCapReached()) return;

   double atrB[1];
   if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrB) < 1 || atrB[0] <= 0) return;
   double atr = atrB[0];
   bool   wantBuy = (ord == "BUYLIMIT" || ord == "BUYSTOP");
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double maxDist = 5.0 * atr;

   // 🛡️ chaque type doit être du BON côté du marché et à distance raisonnable
   bool bon = false;
   if(ord == "BUYLIMIT")  bon = (oprice < ask && oprice > ask - maxDist);  // achat sur repli
   if(ord == "SELLLIMIT") bon = (oprice > bid && oprice < bid + maxDist);  // vente sur rebond
   if(ord == "BUYSTOP")   bon = (oprice > ask && oprice < ask + maxDist);  // achat sur cassure haute
   if(ord == "SELLSTOP")  bon = (oprice < bid && oprice > bid - maxDist);  // vente sur rupture basse
   if(!bon) { Print("⚡ IA ", ord, " rejeté : prix ", oprice, " aberrant vs marché"); return; }

   double slD = SEC_Ov("SLATR", Scalp_SL_ATR) * atr, tpD = SEC_Ov("TPATR", Scalp_TP_ATR) * atr;
   double sl  = wantBuy ? oprice - slD : oprice + slD;
   double tp  = wantBuy ? oprice + tpD : oprice - tpD;
   double lot = SecureLot(_Symbol, CalcLot(slD / g_PipSize), slD);   // 🛡️ règles d'acier
   if(lot <= 0) { Print("⚡ IA ", ord, " refusé : lot hors règles d'acier"); return; }
   oprice = NormalizeDouble(oprice, g_Digits);
   sl = NormalizeDouble(sl, g_Digits); tp = NormalizeDouble(tp, g_Digits);

   bool ok = false;
   if(ord == "BUYLIMIT")  ok = trade.BuyLimit(lot, oprice, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "AI_ZONE");
   if(ord == "SELLLIMIT") ok = trade.SellLimit(lot, oprice, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "AI_ZONE");
   if(ord == "BUYSTOP")   ok = trade.BuyStop(lot, oprice, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "AI_ZONE");
   if(ord == "SELLSTOP")  ok = trade.SellStop(lot, oprice, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "AI_ZONE");
   Print(ok ? "⚡ IA : " + ord + " posé @ " + DoubleToString(oprice, g_Digits)
            : "⚡ IA " + ord + " échec ret=" + IntegerToString((int)trade.ResultRetcode()));
}

double GetAIAdvice(bool isBuy, string kind, double score, double rsi,
                   string mlSignal, double mlConf)
{
   if(SEC_Ov("AIVAL", UseAIValidation ? 1 : 0) < 0.5) return 0.0;

   string sym = _Symbol;
   StringReplace(sym, "#", "%23");
   string url = URLClean(AIValidationURL)
              + "?symbol=" + sym + "&dir=" + (isBuy ? "BUY" : "SELL")
              + "&kind="   + kind + "&score=" + DoubleToString(score, 1)
              + "&rsi="    + DoubleToString(rsi, 1) + "&ml=" + mlSignal
              + "&mlconf=" + DoubleToString(mlConf, 2)
              + "&model="  + AcidAIName()
              + "&tf="     + StringSubstr(EnumToString((ENUM_TIMEFRAMES)Period()), 7)  // "PERIOD_M5" -> "M5"
              + "&price="  + DoubleToString(isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                                  : SymbolInfoDouble(_Symbol, SYMBOL_BID), g_Digits)
              + "&cantrade=" + (AIFree() ? "1" : "0");

   char data[], result[]; string resultHeaders;
   ResetLastError();
   int code = WebRequest("GET", url, "", AITimeoutMs, data, result, resultHeaders);
   if(code != 200) return 0.0;   // 🔋 injoignable = NEUTRE, l'ACID IA trade seule (jamais bloqué)

   string body   = CharArrayToString(result);
   string action = JsonGetStr(body, "action");
   double conf   = JsonGetNum(body, "confidence") / 100.0;

   // ⚡ ordre optionnel de l'IA (exécuté SEULEMENT si AICanTrade, via SecureLot)
   string ord = JsonGetStr(body, "order");
   if(AIFree() && ord != "" && ord != "NONE")
      ExecuteAIOrder(ord, JsonGetNum(body, "oprice"));

   if(action == "TRADE")
   {
      Print("🤬 conseil IA (", AcidAIName(), ") : GO ", kind, " (", DoubleToString(conf*100,0), "%) — ", JsonGetStr(body, "reason"));
      return 0.75 * conf;         // petit coup de pouce
   }
   Print("🤬 conseil IA (", AcidAIName(), ") : MOF ", kind, " (", DoubleToString(conf*100,0), "%) — ", JsonGetStr(body, "reason"));
   return -1.5 * conf;            // malus modéré : ne tue qu'un setup déjà faible
}

// 📶 MACD SIGNAL ALERT (12/07, demande patron) : croisement FRAIS de la
// ligne MACD à travers sa signal sur la dernière bougie clôturée = le
// trigger que l'indicateur «…» affiche. +1 haussier /
// -1 baissier / 0. (Distinct du MACD de position déjà dans le score.)
int MacdSignalAlert(int handle)
{
   double m[], s[];
   ArraySetAsSeries(m, true); ArraySetAsSeries(s, true);
   if(CopyBuffer(handle, 0, 0, 3, m) < 3 || CopyBuffer(handle, 1, 0, 3, s) < 3) return 0;
   if(m[2] <= s[2] && m[1] > s[1]) return 1;    // cross haussier tout frais
   if(m[2] >= s[2] && m[1] < s[1]) return -1;   // cross baissier tout frais
   return 0;
}

// ---- BE TEMPOREL : suivi du temps passe en profit par ticket ----
ulong    g_TBE_Tickets[];
datetime g_TBE_Since[];

int TBE_Find(ulong tk)
{
   for(int i = 0; i < ArraySize(g_TBE_Tickets); i++)
      if(g_TBE_Tickets[i] == tk) return i;
   return -1;
}

void TBE_Set(ulong tk)
{
   if(TBE_Find(tk) >= 0) return;
   int n = ArraySize(g_TBE_Tickets);
   ArrayResize(g_TBE_Tickets, n + 1);
   ArrayResize(g_TBE_Since,   n + 1);
   g_TBE_Tickets[n] = tk;
   g_TBE_Since[n]   = TimeCurrent();
}

void TBE_Clear(ulong tk)
{
   int i = TBE_Find(tk);
   if(i < 0) return;
   int last = ArraySize(g_TBE_Tickets) - 1;
   g_TBE_Tickets[i] = g_TBE_Tickets[last];
   g_TBE_Since[i]   = g_TBE_Since[last];
   ArrayResize(g_TBE_Tickets, last);
   ArrayResize(g_TBE_Since,   last);
}

// BE TEMPOREL (demande du 06/07) : une position agee d'au moins
// TimeBE_AfterSec ET en profit continu depuis TimeBE_PositiveSec voit son
// SL verrouille a entree +/- TimeBE_LockPips -> sortie en benefice garantie,
// meme si le seuil classique en pips (BreakEvenPips) n'est jamais atteint.
// Le compteur "en profit" repart de zero si la position repasse negative.
void ManageTimeBE()
{
   if(!TimeBE_Enabled) return;
   datetime now = TimeCurrent();
   // 🔧 FIX audit 03/08 : ATR courant pour un verrou proportionnel (avant, le lock
   // fixe de +3 pips = le spread, écrasait les gagnants avant qu'ils ne bougent).
   double _tbeAtr = 0; double _tbeA[1];
   if(CopyBuffer(h_ScalpATR, 0, 0, 1, _tbeA) > 0) _tbeAtr = _tbeA[0];
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "HEDGE") >= 0) continue;
      // 🔧 FIX audit 03/08 : le BE temporel ne s'applique QU'AU SCALP. Les moteurs
      // STRUCTURE/SWING doivent courir (patron : «…»).
      if(StringFind(PositionGetString(POSITION_COMMENT), "SCALP") < 0) continue;

      double profit = PositionGetDouble(POSITION_PROFIT);
      if(profit <= 0) { TBE_Clear(ticket); continue; }
      TBE_Set(ticket);

      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(now - opened < TimeBE_AfterSec) continue;
      int idx = TBE_Find(ticket);
      if(idx < 0 || now - g_TBE_Since[idx] < TimeBE_PositiveSec) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      long   type  = PositionGetInteger(POSITION_TYPE);
      double lock  = MathMax(TimeBE_LockPips * g_PipSize, 0.25 * _tbeAtr);
      double stopsDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;

      if(type == POSITION_TYPE_BUY)
      {
         double target = NormalizeDouble(entry + lock, g_Digits);
         double bidNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(sl >= target) continue;                  // deja verrouille
         if(bidNow - target <= stopsDist) continue;  // marche trop proche du SL vise
         if(trade.PositionModify(ticket, target, tp))
         {
            Print("🔒 BE temporel #", ticket, " : SL verrouille a ", DoubleToString(target, g_Digits));
            SendTelegramMsg(StringFormat("🔒 BE TEMPOREL | %s | sortie en benef assuree (SL %s)",
                                          _Symbol, DoubleToString(target, g_Digits)));
         }
      }
      else
      {
         double target = NormalizeDouble(entry - lock, g_Digits);
         double askNow = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(sl > 0 && sl <= target) continue;
         if(target - askNow <= stopsDist) continue;
         if(trade.PositionModify(ticket, target, tp))
         {
            Print("🔒 BE temporel #", ticket, " : SL verrouille a ", DoubleToString(target, g_Digits));
            SendTelegramMsg(StringFormat("🔒 BE TEMPOREL | %s | sortie en benef assuree (SL %s)",
                                          _Symbol, DoubleToString(target, g_Digits)));
         }
      }
   }
}

// Nombre de pendings deja poses d'un cote (BUY = limit+stop achat, SELL = vente)
int CountPendingSide(bool buySide)
{
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!ordInfo.SelectByIndex(i)) continue;
      if(ordInfo.Symbol() != _Symbol || ordInfo.Magic() != MagicNumber) continue;
      ENUM_ORDER_TYPE t = ordInfo.OrderType();
      bool isBuy = (t == ORDER_TYPE_BUY_LIMIT || t == ORDER_TYPE_BUY_STOP);
      if(isBuy == buySide) n++;
   }
   // 🩹 16/09 — LES POSITIONS NÉES D'UN PENDING COMPTENT AUSSI.
   // Avant : seuls les ordres EN ATTENTE étaient comptés. Un SellLimit exécuté
   // devenait une position, le compteur retombait à 0, et un nouveau SellLimit
   // partait à la bougie suivante. Le 16/09 sur l'or : 2 SellLimit gagnants,
   // puis 4 de plus posés PENDANT qu'ils étaient ouverts, au fond d'une baisse
   // de 12 $ : X € pour X €. «…» ne tenait pas.
   for(int j = PositionsTotal() - 1; j >= 0; j--)
   {
      if(!posInfo.SelectByIndex(j)) continue;
      if(posInfo.Symbol() != _Symbol || posInfo.Magic() != MagicNumber) continue;
      if(StringFind(posInfo.Comment(), "PENDING") != 0) continue;
      bool isBuyPos = (posInfo.PositionType() == POSITION_TYPE_BUY);
      if(isBuyPos == buySide) n++;
   }
   return n;
}

//+------------------------------------------------------------------+
//  🧊 16/09 — PAS DE RÉ-ENTRÉE PENDING JUSTE APRÈS UNE SORTIE
//  Mesuré sur 4 jours, 36 pendings : ré-entrée même sens < 20 min
//  = 18 % de gagnants et X €/trade, contre 36 % et X € pour une
//  première entrée. Juste après un gain : 3 trades, 0 gagnant, X €.
//  Vrai si un pending de CE sens, sur CE symbole, est sorti il y a moins de
//  Pending_CooldownMin minutes. Lu dans l'historique, pas en mémoire : un
//  rechargement de l'EA ne remet pas le compteur à zéro.
//+------------------------------------------------------------------+
bool PendingCooldownActive(bool buySide)
{
   int mins = (int)SEC_Ov("PENDCOOL", Pending_CooldownMin);
   if(mins <= 0) return false;
   datetime now = TimeCurrent();
   // 🩹 16/09 (relecture) : 30 jours pour retrouver l'ENTRÉE (une position pending
   // gardée plus de 24 h — un week-end — n'était plus reconnue et la pause sautait),
   // et +60 s en borne haute comme RecentLoss : une sortie horodatée une seconde
   // après TimeCurrent() tombait hors de la sélection.
   if(!HistorySelect(now - 30 * 86400, now + 60)) return false;
   int total = HistoryDealsTotal();

   // 1. les positions nées d'un pending : leur deal d'ENTRÉE est commenté PENDING
   ulong nees[];
   int nn = 0;
   for(int i = 0; i < total; i++)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != MagicNumber) continue;
      if(StringFind(HistoryDealGetString(d, DEAL_COMMENT), "PENDING") != 0) continue;
      ArrayResize(nees, nn + 1);
      nees[nn++] = (ulong)HistoryDealGetInteger(d, DEAL_POSITION_ID);
   }
   if(nn == 0) return false;

   // 2. l'une d'elles, dans CE sens, est-elle sortie depuis moins de X minutes ?
   for(int i = total - 1; i >= 0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;
      datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
      if(t < now - mins * 60) continue;
      ulong pid = (ulong)HistoryDealGetInteger(d, DEAL_POSITION_ID);
      bool nee = false;
      for(int j = 0; j < nn; j++) if(nees[j] == pid) { nee = true; break; }
      if(!nee) continue;
      // un deal de sortie SELL ferme un ACHAT ; un deal BUY ferme une VENTE
      bool fermaitAchat = (HistoryDealGetInteger(d, DEAL_TYPE) == DEAL_TYPE_SELL);
      if(fermaitAchat != buySide) continue;
      static datetime _logCool = 0;
      if(TimeCurrent() - _logCool >= 300)
      {
         _logCool = TimeCurrent();
         Print("🧊 Pending ", buySide ? "BUY" : "SELL", " bloqué : un pending de ce sens est sorti il y a ",
               (int)((now - t) / 60), " min (pause ", mins, " min)");
      }
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//  INPUTS — NEWS FILTER
//+------------------------------------------------------------------+
input string      GRP_NEWS          = "========= NEWS FILTER =========";
input bool        NewsFilterEnabled = true;         // Filtre calendrier MT5 natif — fenêtre ±X min pilotée par SET|NEWSMIN (défaut 15, 0=off) [FIX audit 03/08 : activé, fail-open si calendrier indispo]

//+------------------------------------------------------------------+
//  INPUTS — SESSIONS
//+------------------------------------------------------------------+
input string      GRP_SESSIONS      = "========= SESSIONS =========";
input bool        LondonEnabled     = true;
input bool        NewYorkEnabled    = true;
input bool        AsiaEnabled       = false;
input int         LondonOpen        = 8;            // Heure ouverture London (UTC)
input int         LondonClose       = 17;
input int         NewYorkOpen       = 13;           // Heure ouverture NY (UTC)
input int         NewYorkClose      = 22;
input int         AsiaOpen          = 0;
input int         AsiaClose         = 8;

//+------------------------------------------------------------------+
//  INPUTS — AFFICHAGE
//+------------------------------------------------------------------+
input string      GRP_DISPLAY       = "========= DISPLAY =========";
input bool        ShowDashboard     = true;
input color       ClrBull           = clrLime;
input color       ClrBear           = clrRed;
input color       ClrNeutral        = clrGray;
input int         DashOpacite       = 70;           // 🪟 opacite du cadre 0-255 (0 = totalement transparent, 255 = plein) — patron 31/07
input int         DashX             = 20;
input int         DashY             = 30;
input double      ChartMargeDroite  = 12.0;         // 🖼️ marge droite du chart en % (patron 03/08 : compacter le vide à droite, 10-50 ; 0 = ne pas toucher)

//+------------------------------------------------------------------+
//  VARIABLES GLOBALES — HANDLES INDICATEURS SCALP
//+------------------------------------------------------------------+
int h_ScalpEMAFast   = INVALID_HANDLE;
int h_ScalpEMASlow   = INVALID_HANDLE;
int h_ScalpRSI       = INVALID_HANDLE;
int h_ScalpATR       = INVALID_HANDLE;
int h_ScalpMACD      = INVALID_HANDLE;
int h_ScalpBB        = INVALID_HANDLE;  // Bollinger Bands
int h_ScalpADX       = INVALID_HANDLE;  // 🧠 v2 : force de tendance sur le TF d'entrée

//+------------------------------------------------------------------+
//  VARIABLES GLOBALES — HANDLES INDICATEURS SWING
//+------------------------------------------------------------------+
int h_SwingEMAFast   = INVALID_HANDLE;
int h_SwingEMASlow   = INVALID_HANDLE;
int h_SwingEMATrend  = INVALID_HANDLE;
int h_SwingRSI       = INVALID_HANDLE;
int h_SwingATR       = INVALID_HANDLE;
int h_SwingMACD      = INVALID_HANDLE;
int h_SwingStoch     = INVALID_HANDLE;  // Stochastique
int h_SwingADX       = INVALID_HANDLE;  // ADX tendance

//+------------------------------------------------------------------+
//  VARIABLES GLOBALES — HANDLES CONFIRMATION TF SUPERIEUR
//+------------------------------------------------------------------+
int h_ConfirmEMA50   = INVALID_HANDLE;
int h_ConfirmEMA200  = INVALID_HANDLE;
int h_ConfirmRSI     = INVALID_HANDLE;

//+------------------------------------------------------------------+
//  VARIABLES GLOBALES — ETAT BOT
//+------------------------------------------------------------------+
ENUM_REGIME   g_Regime        = REG_DEAD;
ENUM_BIAS     g_Bias          = BIAS_NONE;
ENUM_ASSET    g_AssetType     = ASSET_OTHER;

double        g_PipSize       = 0.0001;
double        g_PipValue      = 0.0;
double        g_AccountBalance = 0.0;
double        g_DailyStartBal  = 0.0;
double        g_DailyLoss      = 0.0;
double        g_PeakBalance    = 0.0;
double        g_DrawdownPct    = 0.0;

datetime      g_LastScalpTime  = 0;
datetime      g_LastSwingTime  = 0;
datetime      g_LastPendingTime= 0;
datetime      g_DayStart       = 0;
datetime      g_LastRecoveryBar = 0;

bool          g_DailyLimitHit  = false;
bool          g_DDLimitHit     = false;
bool          g_NewsBlocked    = false;

int           g_TotalTrades    = 0;
string        g_LastSignalTxt  = "";
bool          g_EpuisementNow  = false;   // 💥 le tir en cours est un pari d'epuisement     // 🗣️ derniere action, affichee sur le chart (patron 24/07)

//+------------------------------------------------------------------+
//  🎨 CONFIG D'AFFICHAGE pilotee par le Centre (onglet Visualisation,
//  24/07). L'EA lit Files\acid_display.cfg (key=valeur) et applique a
//  CHAUD : couleurs du panneau et de Vision + quelles infos montrer +
//  taille de police. Absent = valeurs par defaut (rien ne casse).
//+------------------------------------------------------------------+
color    Cfg_Title=clrGold, Cfg_IA=clrDeepSkyBlue, Cfg_Text=clrSilver, Cfg_TP=clrGold, Cfg_Sig=clrLightGreen;
color    Cfg_OBbull=clrTeal, Cfg_OBbear=clrMaroon, Cfg_FVG=clrDarkSlateGray, Cfg_Lines=clrGoldenrod, Cfg_Fibo=clrMediumPurple;
color    Cfg_ArrowBuy=clrLime, Cfg_ArrowSell=clrRed, Cfg_ObjEntry=clrGold, Cfg_ObjSL=clrTomato, Cfg_ObjTP=clrLimeGreen, Cfg_ObjPend=clrDodgerBlue;
int      Cfg_Font=11;
bool     Cfg_RSI=true, Cfg_ADX=true, Cfg_ATR=true, Cfg_Spread=true, Cfg_Regime=true, Cfg_Pos=true, Cfg_LastSig=true;
datetime g_CfgCheck=0;

color CfgColor(string rgb, color def)
{
   string p[];
   if(StringSplit(rgb, ',', p) == 3)
      return (color)((int)StringToInteger(p[0]) | ((int)StringToInteger(p[1])<<8) | ((int)StringToInteger(p[2])<<16));
   return def;
}
void LoadDisplayCfg()
{
   int h = FileOpen("acid_display.cfg", FILE_READ|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      int eq = StringFind(ln, "=");
      if(eq < 1) continue;
      string k = ln; string v = ln;
      k = StringSubstr(ln, 0, eq); v = StringSubstr(ln, eq+1);
      StringTrimLeft(k); StringTrimRight(k); StringTrimLeft(v); StringTrimRight(v);
      if(k=="font")        Cfg_Font   = (int)StringToInteger(v);
      else if(k=="title")  Cfg_Title  = CfgColor(v, Cfg_Title);
      else if(k=="ia")     Cfg_IA     = CfgColor(v, Cfg_IA);
      else if(k=="text")   Cfg_Text   = CfgColor(v, Cfg_Text);
      else if(k=="tp")     Cfg_TP     = CfgColor(v, Cfg_TP);
      else if(k=="sig")    Cfg_Sig    = CfgColor(v, Cfg_Sig);
      else if(k=="obbull") Cfg_OBbull = CfgColor(v, Cfg_OBbull);
      else if(k=="obbear") Cfg_OBbear = CfgColor(v, Cfg_OBbear);
      else if(k=="fvg")    Cfg_FVG    = CfgColor(v, Cfg_FVG);
      else if(k=="lines")  Cfg_Lines  = CfgColor(v, Cfg_Lines);
      else if(k=="fibo")   Cfg_Fibo   = CfgColor(v, Cfg_Fibo);
      else if(k=="arrbuy") Cfg_ArrowBuy = CfgColor(v, Cfg_ArrowBuy);
      else if(k=="arrsell")Cfg_ArrowSell= CfgColor(v, Cfg_ArrowSell);
      else if(k=="objentry")Cfg_ObjEntry= CfgColor(v, Cfg_ObjEntry);
      else if(k=="objsl")  Cfg_ObjSL  = CfgColor(v, Cfg_ObjSL);
      else if(k=="objtp")  Cfg_ObjTP  = CfgColor(v, Cfg_ObjTP);
      else if(k=="objpend")Cfg_ObjPend= CfgColor(v, Cfg_ObjPend);
      else if(k=="rsi")    Cfg_RSI    = (v=="1");
      else if(k=="adx")    Cfg_ADX    = (v=="1");
      else if(k=="atr")    Cfg_ATR    = (v=="1");
      else if(k=="spread") Cfg_Spread = (v=="1");
      else if(k=="regime") Cfg_Regime = (v=="1");
      else if(k=="pos")    Cfg_Pos    = (v=="1");
      else if(k=="lastsig")Cfg_LastSig= (v=="1");
   }
   FileClose(h);
}

//+------------------------------------------------------------------+
//  🎯 Fleche de signal sur le graphique (patron 24/07 : «…
//  …»). Chaque entree laisse une fleche + une pastille.
//+------------------------------------------------------------------+
void SignalArrow(bool isBuy, double price, string kind)
{
   string nm = "ACID_SIG_" + (string)(long)TimeCurrent() + "_" + kind;
   datetime t = iTime(_Symbol, PERIOD_M1, 0);
   if(ObjectCreate(0, nm, isBuy ? OBJ_ARROW_BUY : OBJ_ARROW_SELL, 0, t, price))
   {
      ObjectSetInteger(0, nm, OBJPROP_COLOR, isBuy ? Cfg_ArrowBuy : Cfg_ArrowSell);
      ObjectSetInteger(0, nm, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetString (0, nm, OBJPROP_TOOLTIP, kind + " " + (isBuy ? "BUY" : "SELL"));
   }
   string tx = nm + "_t";
   if(ObjectCreate(0, tx, OBJ_TEXT, 0, t, price))
   {
      ObjectSetString (0, tx, OBJPROP_TEXT, " " + kind);
      ObjectSetInteger(0, tx, OBJPROP_COLOR, isBuy ? Cfg_ArrowBuy : Cfg_ArrowSell);
      ObjectSetInteger(0, tx, OBJPROP_FONTSIZE, 11);
      ObjectSetInteger(0, tx, OBJPROP_ANCHOR, isBuy ? ANCHOR_LEFT_UPPER : ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0, tx, OBJPROP_SELECTABLE, false);
   }
}
int           g_WinTrades      = 0;
int           g_LoseTrades     = 0;
double        g_TotalProfit    = 0.0;
double        g_WinRate        = 0.0;
double        g_AvgRR          = 0.0;

// ML memory arrays
double        g_MLScores[];
double        g_MLResults[];
int           g_MLCount        = 0;

// Hedge tracking
ulong         g_HedgeTickets[];

//+------------------------------------------------------------------+
//  CONSTANTES CALCULÉES À L'INIT
//+------------------------------------------------------------------+
double        g_MinLot         = 0.01;
double        g_MaxLot         = 100.0;
double        g_LotStep        = 0.01;
int           g_Digits         = 5;
double        g_Point          = 0.00001;
string        g_Symbol         = "";

//+------------------------------------------------------------------+
//  DETECT ASSET TYPE
//+------------------------------------------------------------------+
ENUM_ASSET DetectAsset()
{
   // ---- Override manuel prioritaire ----
   if(AssetOverride == ASSET_GOLD_M)  { Print("Asset FORCE : GOLD");  return ASSET_GOLD;  }
   if(AssetOverride == ASSET_BTC_M)   { Print("Asset FORCE : BTC");   return ASSET_BTC;   }
   if(AssetOverride == ASSET_OIL_M)   { Print("Asset FORCE : OIL");   return ASSET_OIL;   }
   if(AssetOverride == ASSET_FOREX_M) { Print("Asset FORCE : FOREX"); return ASSET_FOREX; }

   // ---- Auto-detect si ASSET_AUTO ----
   string sym = _Symbol;
   StringToUpper(sym);

   // Gold
   if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0)
   {
      Print("Asset detecte : ASSET_GOLD");
      return ASSET_GOLD;
   }

   // Bitcoin
   if(StringFind(sym, "BTC") >= 0 || StringFind(sym, "BITCOIN") >= 0)
   {
      Print("Asset detecte : ASSET_BTC");
      return ASSET_BTC;
   }

   // Oil
   if(StringFind(sym, "OIL")  >= 0 || StringFind(sym, "WTI")  >= 0 ||
      StringFind(sym, "BRENT")>= 0 || StringFind(sym, "USOIL")>= 0)
   {
      Print("Asset detecte : ASSET_OIL");
      return ASSET_OIL;
   }

   // Forex par defaut
   Print("Asset detecte : ASSET_FOREX");
   return ASSET_FOREX;
}

//+------------------------------------------------------------------+
//  DETECT REGIME DE MARCHE
//+------------------------------------------------------------------+
ENUM_REGIME DetectRegime()
{
   double atr[];
   ArraySetAsSeries(atr,true);
   if(CopyBuffer(h_ScalpATR,0,0,20,atr)<20) return REG_DEAD;

   double atrNow  = atr[0];
   double atrAvg  = 0;
   for(int i=1;i<20;i++) atrAvg += atr[i];
   atrAvg /= 19.0;

   double ratio = (atrAvg > 0) ? atrNow / atrAvg : 1.0;

   // ADX pour tendance
   double adxVal[];
   ArraySetAsSeries(adxVal,true);
   bool hasTrend = false;
   if(CopyBuffer(h_SwingADX,0,0,3,adxVal)>=3)
      hasTrend = (adxVal[0] > 25.0);

   if(ratio > 2.5)                    return REG_VIOLENT;
   if(hasTrend && ratio >= 0.8)       return REG_TREND;
   if(!hasTrend && ratio < 1.5)       return REG_RANGE;
   return REG_DEAD;
}

//+------------------------------------------------------------------+
//  DETECT BIAS DIRECTIONNEL
//+------------------------------------------------------------------+
ENUM_BIAS DetectBias()
{
   double emaFast[], emaSlow[], emaTrend[];
   ArraySetAsSeries(emaFast,true);
   ArraySetAsSeries(emaSlow,true);
   ArraySetAsSeries(emaTrend,true);

   if(CopyBuffer(h_SwingEMAFast, 0,0,3,emaFast) <3) return BIAS_NONE;
   if(CopyBuffer(h_SwingEMASlow, 0,0,3,emaSlow) <3) return BIAS_NONE;
   if(CopyBuffer(h_SwingEMATrend,0,0,3,emaTrend)<3) return BIAS_NONE;

   double price = SymbolInfoDouble(_Symbol,SYMBOL_BID);

   bool bullAlign = (emaFast[0] > emaSlow[0]) &&
                    (emaSlow[0] > emaTrend[0]) &&
                    (price > emaTrend[0]);

   bool bearAlign = (emaFast[0] < emaSlow[0]) &&
                    (emaSlow[0] < emaTrend[0]) &&
                    (price < emaTrend[0]);

   if(bullAlign) return BIAS_BUY;
   if(bearAlign) return BIAS_SELL;
   return BIAS_NONE;
}

//+------------------------------------------------------------------+
//  ML BONUS — basé sur historique des trades
//+------------------------------------------------------------------+
double GetMLBonus()
{
   if(!MLEnabled || g_MLCount < 10) return 0.0;

   // Winrate component
   double wrScore = (g_WinRate - 50.0) / 50.0;   // -1.0 à +1.0
   wrScore = MathMax(-1.0, MathMin(1.0, wrScore));

   // RR component
   double rrScore = (g_AvgRR - 1.0) / 2.0;       // normalise autour de RR=1
   rrScore = MathMax(-1.0, MathMin(1.0, rrScore));

   double bonus = (wrScore * ML_WinRateWeight + rrScore * ML_RRWeight) * MLBonusMax;
   return MathMax(-MLBonusMax, MathMin(MLBonusMax, bonus));
}

//+------------------------------------------------------------------+
//  SCORE ENGINE — SCALP (0 à 10 + bonus ML)
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//  🧠 SUPER-CERVEAU v2 (12/07) — 5 sens supplémentaires :
//  ADX scalp, VWAP session, squeeze Bollinger, SuperTrend, SMC natif
//  (FVG + Spring portés de chart_patterns.py). But : agressif POUR DE
//  BONNES RAISONS — plus de chemins vers le seuil quand tout s'aligne,
//  des malus quand on nage contre le flux.
//+------------------------------------------------------------------+
double BrainADX()
{
   double b[1];
   if(h_ScalpADX == INVALID_HANDLE || CopyBuffer(h_ScalpADX, 0, 0, 1, b) < 1) return 0;
   return b[0];
}

// VWAP de session : le prix «…» des institutionnels depuis minuit serveur
double BrainVWAP()
{
   datetime day0 = iTime(_Symbol, PERIOD_D1, 0);
   MqlRates r[];
   int n = CopyRates(_Symbol, ScalpTF, day0, TimeCurrent(), r);
   if(n < 3) return 0;
   double pv = 0, vol = 0;
   for(int i = 0; i < n; i++)
   {
      double typ = (r[i].high + r[i].low + r[i].close) / 3.0;
      pv  += typ * (double)r[i].tick_volume;
      vol += (double)r[i].tick_volume;
   }
   return vol > 0 ? pv / vol : 0;
}

// Squeeze : bandes de Bollinger compressées (< 60% de leur largeur moyenne
// sur 50 barres) = le ressort se bande, cassure imminente
bool BrainSqueeze()
{
   double up[], lo[];
   ArraySetAsSeries(up, true);
   ArraySetAsSeries(lo, true);
   if(CopyBuffer(h_ScalpBB, 1, 0, 52, up) < 52 || CopyBuffer(h_ScalpBB, 2, 0, 52, lo) < 52)
      return false;
   double now = up[0] - lo[0], avg = 0;
   for(int i = 1; i <= 50; i++) avg += (up[i] - lo[i]);
   avg /= 50.0;
   return (avg > 0 && now < 0.6 * avg);
}

// 🌊 08/09 (patron) : rail RESSERRÉ à 1,5 ATR et FlowRider déclenché dès ADX 18.
// Le SL colle davantage au mouvement : on garde plus de gain, on sort plus tôt
// si ça se retourne. Effet de bord ASSUMÉ : le rail sert aussi de garde-fou
// «…» à l'entrée — plus serré, il change d'avis plus vite.
input double      ST_MULT           = 1.5;          // largeur du rail SuperTrend (x ATR)
input double      FR_ADX_MIN        = 18.0;         // force minimum pour que FlowRider prenne la main
// SuperTrend (10, xST_MULT ATR) : +1 rail haussier / -1 baissier ; 'line' = le rail
// (sert aussi de SL de trailing intelligent au FlowRider)
int BrainSuperTrend(double &line)
{
   static datetime lastBar = 0;
   static int      lastDir = 0;
   static double   lastLine = 0;
   datetime cur = iTime(_Symbol, ScalpTF, 0);
   if(cur == lastBar && lastDir != 0) { line = lastLine; return lastDir; }
   MqlRates r[];
   double atrB[];
   ArraySetAsSeries(r, true);
   ArraySetAsSeries(atrB, true);
   int n = CopyRates(_Symbol, ScalpTF, 0, 120, r);
   if(n < 60 || CopyBuffer(h_ScalpATR, 0, 0, n, atrB) < 60) { line = 0; return 0; }
   int dir = 1;
   double ub = 0, lb = 0, st = 0;
   for(int i = n - 2; i >= 1; i--)              // du passé vers la dernière clôturée
   {
      double mid = (r[i].high + r[i].low) / 2.0, a = atrB[i] * ST_MULT;
      double bu = mid + a, bl = mid - a;
      if(i == n - 2) { ub = bu; lb = bl; st = bl; dir = 1; continue; }
      lb = (bl > lb || r[i + 1].close < lb) ? bl : lb;
      ub = (bu < ub || r[i + 1].close > ub) ? bu : ub;
      if(dir == 1 && r[i].close < lb)      { dir = -1; st = ub; }
      else if(dir == -1 && r[i].close > ub){ dir = 1;  st = lb; }
      else st = (dir == 1) ? lb : ub;
   }
   lastBar = cur; lastDir = dir; lastLine = st;
   line = st;
   return dir;
}

// Spring/Upthrust : mèche qui chasse la liquidité sous un niveau touché >=2x
// puis clôture de l'autre côté (+1 haussier / -1 baissier / 0)
int BrainSpring()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, ScalpTF, 0, 40, r);
   if(n < 38) return 0;
   double tol = 0.0008 * r[1].close;
   double support = DBL_MAX, resistance = 0;
   int tS = 0, tR = 0;
   for(int i = 3; i <= 32; i++) { if(r[i].low  < support)    support    = r[i].low; }
   for(int i = 3; i <= 32; i++) { if(r[i].high > resistance) resistance = r[i].high; }
   for(int i = 3; i <= 32; i++)
   {
      if(r[i].low - support <= tol)     tS++;
      if(resistance - r[i].high <= tol) tR++;
   }
   double corps = MathAbs(r[1].close - r[1].open), total = MathMax(r[1].high - r[1].low, g_Point);
   if(tS >= 2 && r[1].low < support - 0.1 * tol && r[1].close > support
      && r[1].close > r[1].open && corps >= 0.4 * total) return 1;
   if(tR >= 2 && r[1].high > resistance + 0.1 * tol && r[1].close < resistance
      && r[1].close < r[1].open && corps >= 0.4 * total) return -1;
   return 0;
}

// FVG le plus récent NON comblé : +1 haussier / -1 baissier, inside=prix dedans
int BrainFVG(bool &inside)
{
   inside = false;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, ScalpTF, 0, 30, r);
   if(n < 26) return 0;
   double px = r[0].close;
   for(int i = 3; i <= 22; i++)     // A=r[i+2] B=r[i+1] C=r[i] (série inversée)
   {
      if(r[i].low > r[i + 2].high)                       // FVG haussier
      {
         double bas = r[i + 2].high, haut = r[i].low;
         if(haut - bas < 0.0005 * px) continue;
         bool comble = false;
         for(int j = i - 1; j >= 1; j--) if(r[j].low <= bas) { comble = true; break; }
         if(comble) break;
         inside = (px >= bas && px <= haut);
         return 1;
      }
      if(r[i].high < r[i + 2].low)                       // FVG baissier
      {
         double bas = r[i].high, haut = r[i + 2].low;
         if(haut - bas < 0.0005 * px) continue;
         bool comble = false;
         for(int j = i - 1; j >= 1; j--) if(r[j].high >= haut) { comble = true; break; }
         if(comble) break;
         inside = (px >= bas && px <= haut);
         return -1;
      }
   }
   return 0;
}

//+------------------------------------------------------------------+
//  🧠 SUPER-CERVEAU v3 (12/07) — R:R adaptatif, corrélation, news réel,
//  journal d'auto-apprentissage. Tout piloté par SEC_Ov (pas d'inputs
//  fantômes) : SET|MAXCLUSTER|3, SET|NEWSMIN|15, SET|JOURNAL|1.
//+------------------------------------------------------------------+

// R:R ADAPTATIF : en vraie tendance (ADX fort / REG_TREND) on laisse
// courir le TP (×1.4) ; en range/mou on resserre (TP ×0.7, SL ×0.9)
// pour prendre vite avant que ça retourne.
void AdaptiveRR(double baseSL, double baseTP, double &slM, double &tpM)
{
   slM = baseSL; tpM = baseTP;
   double adx = BrainADX();
   if(g_Regime == REG_TREND || adx >= 28)       tpM = baseTP * 1.4;
   else if(g_Regime == REG_RANGE || (adx > 0 && adx < 18)) { tpM = baseTP * 0.7; slM = baseSL * 0.9; }
}

// CLUSTER de corrélation d'un symbole (0=FX 1=métaux 2=crypto 3=indices 4=oil)
int AssetCluster(string sym)
{
   string s = sym; StringToUpper(s);
   if(StringFind(s,"XAU")>=0||StringFind(s,"GOLD")>=0||StringFind(s,"XAG")>=0||StringFind(s,"SILVER")>=0) return 1;
   if(StringFind(s,"BTC")>=0||StringFind(s,"ETH")>=0||StringFind(s,"LTC")>=0||StringFind(s,"XRP")>=0||
      StringFind(s,"SOL")>=0||StringFind(s,"ADA")>=0||StringFind(s,"DOG")>=0||StringFind(s,"CRYPTO")>=0||
      StringFind(s,"BNB")>=0||StringFind(s,"MATIC")>=0||StringFind(s,"ATOM")>=0) return 2;
   if(StringFind(s,"US500")>=0||StringFind(s,"US100")>=0||StringFind(s,"US30")>=0||StringFind(s,"NAS")>=0||
      StringFind(s,"GER40")>=0||StringFind(s,"DAX")>=0||StringFind(s,"FRA40")>=0||StringFind(s,"SPX")>=0) return 3;
   if(StringFind(s,"OIL")>=0||StringFind(s,"WTI")>=0||StringFind(s,"USO")>=0||StringFind(s,"BRENT")>=0) return 4;
   return 0;
}

// Compte les positions de la FAMILLE ACID IA (magics 2026xxxx) du MÊME cluster
// et du MÊME sens que _Symbol — pour ne pas empiler 5 paris identiques.
int CountClusterAcid(bool isBuy)
{
   int clu = AssetCluster(_Symbol), n = 0;
   for(int i=0; i<PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      long mg = posInfo.Magic();
      if(mg < 20260000 || mg > 20269999) continue;          // famille ACID IA
      if(AssetCluster(posInfo.Symbol()) != clu) continue;
      bool posBuy = (posInfo.PositionType() == POSITION_TYPE_BUY);
      if(posBuy == isBuy) n++;
   }
   return n;
}

// JOURNAL d'auto-apprentissage : 1 ligne CSV par trade ouvert, avec tous
// les indicateurs à l'entrée → carburant du futur ML V3 (vraies décisions
// live). Fichier MQL5\Files\acid_trade_journal.csv.
void JournalTrade(string kind, bool isBuy, double lot, double entry, double sl, double tp,
                  double score, double rsi, double atr, double emaR, double macd,
                  string mlSig, double mlConf)
{
   if(SEC_Ov("JOURNAL", 1) < 0.5) return;
   double stLine = 0; int stDir = BrainSuperTrend(stLine);
   int h = FileOpen("acid_trade_journal.csv", FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h == INVALID_HANDLE) return;
   if(FileSize(h) == 0)
      FileWriteString(h, "time,symbol,dir,kind,lot,entry,sl,tp,score,rsi,atr,ema_ratio,macd,adx,supertrend,regime,bias,ml,mlconf\r\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, StringFormat("%s,%s,%s,%s,%.2f,%.5f,%.5f,%.5f,%.2f,%.1f,%.6f,%.5f,%.5f,%.1f,%d,%d,%d,%s,%.2f\r\n",
      TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS), _Symbol, isBuy?"BUY":"SELL", kind,
      lot, entry, sl, tp, score, rsi, atr, emaR, macd, BrainADX(), stDir, g_Regime, g_Bias, mlSig, mlConf));
   FileClose(h);
}

//+------------------------------------------------------------------+
//  📏 BRAIN LINES (12/07) — demande patron : «…
//  …». Lit les LIGNES du chart (les tiennes, TrendLine
//  PRO, n'importe quel indicateur qui trace) : OBJ_HLINE + OBJ_TREND.
//  +1 = support proche EN DESSOUS (tremplin) ; -1 = résistance proche
//  AU-DESSUS (mur) ; 0 = rien à moins de 0.6 ATR. Cache par bougie.
//+------------------------------------------------------------------+
int BrainLines()
{
   static datetime lastBar = 0;
   static int      lastRes = 0;
   datetime cur = iTime(_Symbol, ScalpTF, 0);
   if(cur == lastBar) return lastRes;
   lastBar = cur; lastRes = 0;
   double atrB[1];
   if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrB) < 1) return 0;
   double atr = atrB[0];
   if(atr <= 0) return 0;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   datetime now = TimeCurrent();
   double best = DBL_MAX;
   int total = ObjectsTotal(0, -1, -1);
   for(int i = 0; i < total; i++)
   {
      string nm = ObjectName(0, i);
      long typ = ObjectGetInteger(0, nm, OBJPROP_TYPE);
      double lvl = 0;
      if(typ == OBJ_HLINE)      lvl = ObjectGetDouble(0, nm, OBJPROP_PRICE);
      else if(typ == OBJ_TREND) lvl = ObjectGetValueByTime(0, nm, now, 0);
      else continue;
      if(lvl <= 0) continue;
      double d = MathAbs(lvl - bid);
      if(d > 0.6 * atr || d >= best) continue;
      best = d;
      lastRes = (lvl < bid) ? 1 : -1;
   }
   return lastRes;
}

// 🖼️ Une famille d'indicateurs du chart est-elle active ? (input du chart
// ET coupable à distance par L'ŒIL : SET/SETSYM CHARTIND, CHARTLINES, …)
bool ChartIndOn(string key, bool inp)
{
   if(SEC_Ov("CHARTIND", Use_ChartIndicators ? 1 : 0) < 0.5) return false;
   return SEC_Ov(key, inp ? 1 : 0) >= 0.5;
}

//+------------------------------------------------------------------+
//  🖼️ BRAIN CHART EXTRAS (13/07) — lit les AUTRES dessins des
//  indicateurs du chart : flèches (signaux), Fibonacci (confluence),
//  rectangles (zones FVG / offre-demande). Une passe par bougie,
//  les DEUX sens calculés d'un coup (cache). Conseiller, pas décideur.
//+------------------------------------------------------------------+
string g_ChartIndNote = "";
double BrainChartExtras(bool isBuy)
{
   static datetime lastBar = 0;
   static double   cBuy = 0, cSell = 0;
   static string   note = "";
   datetime cur = iTime(_Symbol, ScalpTF, 0);
   if(cur != lastBar)
   {
      lastBar = cur; cBuy = 0; cSell = 0; note = "";
      bool useArr = ChartIndOn("CHARTARROWS", Use_ChartArrows);
      bool useFib = ChartIndOn("CHARTFIBO", Use_ChartFibo);
      bool useZon = ChartIndOn("CHARTZONES", Use_ChartZones);
      double atrB[1];
      if((useArr || useFib || useZon)
         && CopyBuffer(h_ScalpATR, 0, 0, 1, atrB) == 1 && atrB[0] > 0)
      {
         double atr = atrB[0];
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         datetime fraiche = iTime(_Symbol, ScalpTF, 3);   // flèche fraîche = ≤ 3 bougies
         int total = ObjectsTotal(0, -1, -1);
         for(int i = 0; i < total; i++)
         {
            string nm = ObjectName(0, i);
            long typ = ObjectGetInteger(0, nm, OBJPROP_TYPE);
            // 🏹 flèches de signal, fraîches uniquement
            if(useArr && (typ == OBJ_ARROW_BUY || typ == OBJ_ARROW_SELL || typ == OBJ_ARROW))
            {
               datetime t = (datetime)ObjectGetInteger(0, nm, OBJPROP_TIME);
               if(t < fraiche) continue;
               int sens = 0;
               if(typ == OBJ_ARROW_BUY) sens = 1;
               else if(typ == OBJ_ARROW_SELL) sens = -1;
               else
               {
                  long code = ObjectGetInteger(0, nm, OBJPROP_ARROWCODE);
                  if(code == 233 || code == 241 || code == 217) sens = 1;
                  else if(code == 234 || code == 242 || code == 218) sens = -1;
                  else continue;   // flèche décorative
               }
               cBuy  += (sens > 0) ?  0.5 : -0.5;
               cSell += (sens > 0) ? -0.5 :  0.5;
               note += (sens > 0) ? "flèche↑ " : "flèche↓ ";
            }
            // 📐 Fibonacci : prix collé à un niveau = confluence (les 2 sens)
            else if(useFib && typ == OBJ_FIBO)
            {
               double p1 = ObjectGetDouble(0, nm, OBJPROP_PRICE, 0);
               double p2 = ObjectGetDouble(0, nm, OBJPROP_PRICE, 1);
               if(p1 <= 0 || p2 <= 0) continue;
               double lv[5] = {0.236, 0.382, 0.5, 0.618, 0.786};
               for(int k = 0; k < 5; k++)
               {
                  double niveau = p2 + (p1 - p2) * lv[k];
                  if(MathAbs(bid - niveau) <= 0.3 * atr)
                  { cBuy += 0.5; cSell += 0.5; note += "fibo "; break; }
               }
            }
            // 🟦 rectangles (FVG / offre-demande) : dedans = réaction attendue
            else if(useZon && typ == OBJ_RECTANGLE)
            {
               double r1 = ObjectGetDouble(0, nm, OBJPROP_PRICE, 0);
               double r2 = ObjectGetDouble(0, nm, OBJPROP_PRICE, 1);
               double hi = MathMax(r1, r2), lo = MathMin(r1, r2);
               if(bid < lo || bid > hi) continue;
               if(hi - lo > 4 * atr) continue;      // fond d'écran décoratif
               if(bid >= (hi + lo) / 2) { cBuy += 1.0; cSell -= 0.5; note += "zone-support "; }
               else                     { cSell += 1.0; cBuy -= 0.5; note += "zone-résistance "; }
            }
         }
         cBuy  = MathMax(-1.5, MathMin(1.5, cBuy));    // conseiller, pas décideur
         cSell = MathMax(-1.5, MathMin(1.5, cSell));
      }
   }
   g_ChartIndNote = note;
   return isBuy ? cBuy : cSell;
}

//+------------------------------------------------------------------+
//  🛡️ NAKED GUARD (12/07) — autonomie sans L'ŒIL : toute position de
//  l'EA sans SL depuis >60 s reçoit un SL natif à 1.5×ATR. (Le filet
//  de L'ŒIL fait pareil, mais l'EA doit savoir se protéger SEUL.)
//+------------------------------------------------------------------+
void NakedGuard()
{
   double atrB[1];
   if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrB) < 1) return;
   double atr = atrB[0];
   if(atr <= 0) return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol || posInfo.Magic() != MagicNumber) continue;
      if(StringFind(posInfo.Comment(), "HEDGE") >= 0) continue;
      if(posInfo.StopLoss() > 0) continue;
      if(TimeCurrent() - (datetime)posInfo.Time() < 60) continue;
      bool isLong = (posInfo.PositionType() == POSITION_TYPE_BUY);
      double ancre = isLong ? MathMin(posInfo.PriceOpen(), bid) : MathMax(posInfo.PriceOpen(), ask);
      double dist  = MathMax(1.5 * atr, (ask - bid) * 2);
      double sl    = NormalizeDouble(isLong ? ancre - dist : ancre + dist, g_Digits);
      if(trade.PositionModify(posInfo.Ticket(), sl, posInfo.TakeProfit()))
         Print("🛡️ NakedGuard : SL de secours natif posé sur #", posInfo.Ticket(), " -> ", sl);
   }
}

//+------------------------------------------------------------------+
//  💎 PROFIT GUARD (12/07) — demande patron : «…
//  …
//  …». Deux réflexes :
//  FLIP  : gain correct + le rail SuperTrend passe CONTRE → on encaisse.
//  GIVEBACK : le trade a atteint >=0.8 ATR puis rend 60 % → on coupe.
//  Ne touche NI les swings (ils respirent) NI le flux FlowRider.
//  Pilotable : SET|PGUARD|0.
//+------------------------------------------------------------------+
ulong    g_PG_Tk[50];
double   g_PG_Pk[50];
datetime g_PG_PkT[50];        // ⏱️ instant du dernier NOUVEAU sommet (temps mort)
int      g_PG_N = 0;

void ProfitGuard()
{
   if(SEC_Ov("PGUARD", 1) < 0.5) return;
   double atrB[1];
   if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrB) < 1) return;
   double atr = atrB[0];
   if(atr <= 0) return;
   double rail = 0;
   int    stDir = BrainSuperTrend(rail);
   double adx   = BrainADX();
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = ask - bid;
   ulong  nT[50]; double nP[50]; datetime nPT[50]; int n = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol || posInfo.Magic() != MagicNumber) continue;
      string cm = posInfo.Comment();
      if(StringFind(cm, "SWING") >= 0 || StringFind(cm, "HEDGE") >= 0) continue;
      bool isLong = (posInfo.PositionType() == POSITION_TYPE_BUY);
      double cur  = isLong ? bid : ask;
      double gain = isLong ? (cur - posInfo.PriceOpen()) : (posInfo.PriceOpen() - cur);
      double peak = gain; datetime peakT = TimeCurrent();
      for(int k = 0; k < g_PG_N; k++)
         if(g_PG_Tk[k] == posInfo.Ticket())
         {
            if(gain > g_PG_Pk[k]) { peak = gain; peakT = TimeCurrent(); }   // nouveau sommet -> on reset le chrono
            else                  { peak = g_PG_Pk[k]; peakT = g_PG_PkT[k]; }
            break;
         }
      if(n < 50) { nT[n] = posInfo.Ticket(); nP[n] = peak; nPT[n] = peakT; n++; }
      // ⏱️ TEMPS MORT (patron 29/07) : une position en profit qui n'a pas fait
      // de NOUVEAU sommet depuis PG_TempsMortMin minutes, et qui a rendu du
      // terrain (peak - gain >= PG_TempsMortATR x ATR), STAGNE : on libere le
      // capital au lieu d'attendre. FlowRider garde la priorite (teste plus bas).
      if(PG_TempsMortMin > 0 && gain > 0
         && (TimeCurrent() - peakT) >= PG_TempsMortMin * 60
         && (peak - gain) >= PG_TempsMortATR * atr)
      {
         bool flowT = (adx >= FR_ADX_MIN && ((isLong && stDir > 0) || (!isLong && stDir < 0)));
         if(!flowT && ClosePos(posInfo.Ticket()))
         {
            Print("⏱ TEMPS MORT : +", DoubleToString(gain / g_PipSize, 1),
                  " pips encaisses (stagne ", PG_TempsMortMin, " min sans avancer) #", posInfo.Ticket());
            continue;
         }
      }
      if(gain <= 0) continue;
      // le flux commande : si FlowRider est aux manettes, on ne coupe pas
      // 08/09 : même seuil que FlowRider (18) — avant, 23 ici et 18 là : entre les
      // deux, ProfitGuard coupait ce que FlowRider voulait laisser courir.
      bool flow = (adx >= FR_ADX_MIN && ((isLong && stDir > 0) || (!isLong && stDir < 0)));
      if(flow) continue;
      // FLIP : gain >= 2 spreads et le rail vient de passer contre nous
      double pgFloor = SEC_Ov("LOCKBE", LockBEPips) * g_PipSize;   // 🚧 plancher : on n'encaisse RIEN sous +50 pips
      if(gain >= MathMax(pgFloor, MathMax(2 * spread, 0.7 * atr)) && ((isLong && stDir < 0) || (!isLong && stDir > 0)))
      {
         if(ClosePos(posInfo.Ticket()))
            Print("💎 ProfitGuard FLIP : +", DoubleToString(gain / g_PipSize, 1),
                  " pips encaissés (rail contre) #", posInfo.Ticket());
         continue;
      }
      // 🍒 ESSOUFFLEMENT (patron 24/07 : «…
      // …» — le X du haut). En BON profit (>= StallMinATR),
      // si le prix retombe de StallGiveFrac du sommet ET qu'une bougie PLEINE
      // se referme CONTRE nous (retournement en haut), on encaisse tout de
      // suite — sans attendre le giveback de 60%. FlowRider garde la priorité
      // (le bloc «…» plus haut protège les vrais runners).
      if(gain >= MathMax(StallMinATR * atr, pgFloor) && peak > gain && (peak - gain) >= StallGiveFrac * peak)
      {
         MqlRates sr[]; ArraySetAsSeries(sr, true);
         if(CopyRates(_Symbol, ScalpTF, 0, 2, sr) >= 2)
         {
            double bd = MathAbs(sr[1].close - sr[1].open);
            double rgb = MathMax(sr[1].high - sr[1].low, g_Point);
            bool   rev = isLong ? (sr[1].close < sr[1].open) : (sr[1].close > sr[1].open);
            if(rev && bd >= 0.5 * rgb)
            {
               if(ClosePos(posInfo.Ticket()))
                  Print("🍒 ESSOUFFLEMENT : +", DoubleToString(gain / g_PipSize, 1),
                        " pips banqués (sommet ", DoubleToString(peak / g_PipSize, 1),
                        ") — bougie de retournement #", posInfo.Ticket());
               continue;
            }
         }
      }

      // GIVEBACK : a atteint >=0.8 ATR puis rendu 60 % du sommet
      if(peak >= MathMax(1.1 * atr, 1.5 * pgFloor) && gain <= 0.45 * peak && gain >= pgFloor)
      {
         if(ClosePos(posInfo.Ticket()))
            Print("💎 ProfitGuard GIVEBACK : +", DoubleToString(gain / g_PipSize, 1),
                  " pips sauvés (sommet ", DoubleToString(peak / g_PipSize, 1), ") #", posInfo.Ticket());
         continue;
      }
   }
   g_PG_N = n;
   for(int k = 0; k < n; k++) { g_PG_Tk[k] = nT[k]; g_PG_Pk[k] = nP[k]; g_PG_PkT[k] = nPT[k]; }
}

//+------------------------------------------------------------------+
//  🌊 FLOW RIDER (12/07) — demande patron : «…
//  …
//  …». Concrètement : ADX >= 23 + SuperTrend aligné
//  avec la position => le SL grimpe sur le RAIL SuperTrend (jamais
//  reculé, jamais collé au prix), et on laisse le mouvement respirer.
//+------------------------------------------------------------------+
void ManageFlowRider()
{
   double rail = 0;
   int stDir = BrainSuperTrend(rail);
   if(stDir == 0 || rail <= 0 || BrainADX() < FR_ADX_MIN) return;   // 08/09 : 23 -> 18, plus sensible
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol || posInfo.Magic() != MagicNumber) continue;
      bool isLong = (posInfo.PositionType() == POSITION_TYPE_BUY);
      if((isLong && stDir < 0) || (!isLong && stDir > 0)) continue;   // pas dans le flux
      double sl = posInfo.StopLoss();
      double newSL = NormalizeDouble(rail, g_Digits);
      if(isLong && newSL < bid - g_Point && (sl == 0 || newSL > sl + g_Point))
      {
         if(trade.PositionModify(posInfo.Ticket(), newSL, posInfo.TakeProfit()))
            Print("🌊 FlowRider : SL sur le rail SuperTrend #", posInfo.Ticket(), " -> ", newSL);
      }
      if(!isLong && newSL > ask + g_Point && (sl == 0 || newSL < sl - g_Point))
      {
         if(trade.PositionModify(posInfo.Ticket(), newSL, posInfo.TakeProfit()))
            Print("🌊 FlowRider : SL sur le rail SuperTrend #", posInfo.Ticket(), " -> ", newSL);
      }
   }
}

//+------------------------------------------------------------------+
//  🏀 REBOUND SNIPER (patron 24/07) — «…
//  …». L'EA lisait des moyennes, il ne VOYAIT pas la
//  structure. Ce module detecte les VRAIS niveaux (pivots regroupes en
//  zones sur RB_TF, touches comptees), puis entre AUTOMATIQUEMENT quand
//  le prix revient sur un niveau et le REJETTE : meche de rejet + cloture
//  du bon cote + RSI qui se retourne. Confluence obligatoire : jamais
//  contre un rail SuperTrend en tendance forte (ADX>=23) ni contre le H1
//  en marche — un rebond contre un train n'est pas un rebond. ML consulte
//  en douceur (ne bloque que si franchement contraire). 100% local, zero
//  appel IA payant. Pilotable a chaud : SET|REBOUND|0 pour couper.
//+------------------------------------------------------------------+
double RB_ATRval()
{
   MqlRates r[]; ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, RB_TF, 0, 17, r) < 17) return 0;
   double s = 0;
   for(int i = 1; i <= 14; i++)
      s += MathMax(r[i].high - r[i].low,
           MathMax(MathAbs(r[i].high - r[i+1].close), MathAbs(r[i].low - r[i+1].close)));
   return s / 14.0;
}

int RB_H1Trend()
{
   static int hF = INVALID_HANDLE, hS = INVALID_HANDLE;
   if(hF == INVALID_HANDLE) hF = iMA(_Symbol, PERIOD_H1, 21, 0, MODE_EMA, PRICE_CLOSE);
   if(hS == INVALID_HANDLE) hS = iMA(_Symbol, PERIOD_H1, 55, 0, MODE_EMA, PRICE_CLOSE);
   if(hF == INVALID_HANDLE || hS == INVALID_HANDLE) return 0;
   double f[1], s[1];
   if(CopyBuffer(hF, 0, 0, 1, f) < 1 || CopyBuffer(hS, 0, 0, 1, s) < 1) return 0;
   return (f[0] > s[0]) ? 1 : ((f[0] < s[0]) ? -1 : 0);
}

// Collecte les niveaux : pivots hauts/bas fusionnes en zones (tol = x ATR),
// chaque re-touche renforce le niveau. Renvoie le nombre de zones.
int RB_CollectLevels(double &lvls[], int &touches[], bool &isSup[], double atrRef)
{
   MqlRates r[]; ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, RB_TF, 0, RB_LookBack, r);
   if(n < RB_PivotSpan * 2 + 10) return 0;
   double tol = RB_TolATR * atrRef;
   int cnt = 0;
   ArrayResize(lvls, 0); ArrayResize(touches, 0); ArrayResize(isSup, 0);
   for(int i = RB_PivotSpan + 1; i < n - RB_PivotSpan; i++)
   {
      bool pH = true, pL = true;
      for(int k = 1; k <= RB_PivotSpan; k++)
      {
         if(r[i].high < r[i-k].high || r[i].high < r[i+k].high) pH = false;
         if(r[i].low  > r[i-k].low  || r[i].low  > r[i+k].low)  pL = false;
         if(!pH && !pL) break;
      }
      if(!pH && !pL) continue;
      // un pivot peut etre les deux (barre dominante) : on traite chaque face
      for(int face = 0; face < 2; face++)
      {
         if(face == 0 && !pL) continue;
         if(face == 1 && !pH) continue;
         double px  = (face == 0) ? r[i].low : r[i].high;
         bool   sup = (face == 0);
         bool merged = false;
         for(int j = 0; j < cnt; j++)
            if(isSup[j] == sup && MathAbs(lvls[j] - px) <= tol)
            {
               lvls[j] = (lvls[j] * touches[j] + px) / (touches[j] + 1);
               touches[j]++;
               merged = true;
               break;
            }
         if(!merged)
         {
            ArrayResize(lvls, cnt + 1); ArrayResize(touches, cnt + 1); ArrayResize(isSup, cnt + 1);
            lvls[cnt] = px; touches[cnt] = 1; isSup[cnt] = sup; cnt++;
         }
      }
   }
   return cnt;
}

// Trace les niveaux valides sur le chart (lecture visuelle du patron)
void RB_Draw(double &lvls[], int &touches[], bool &isSup[], int cnt)
{
   ObjectsDeleteAll(0, "ACID_RB_");
   int drawn = 0;
   for(int j = 0; j < cnt && drawn < 8; j++)
   {
      if(touches[j] < RB_MinTouches) continue;
      string nm = "ACID_RB_" + IntegerToString(j);
      if(ObjectCreate(0, nm, OBJ_HLINE, 0, 0, lvls[j]))
      {
         ObjectSetInteger(0, nm, OBJPROP_COLOR, isSup[j] ? clrSeaGreen : clrFireBrick);
         ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, nm, OBJPROP_WIDTH, touches[j] >= 3 ? 2 : 1);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP,
            StringFormat("ACID niveau %s — %d touches", isSup[j] ? "SUPPORT" : "RESISTANCE", touches[j]));
      }
      drawn++;
   }
}

void OpenReboundTrade(bool isBuy, double niveau, int nTouches, double atr,
                      double &lvls[], int &touches[], bool &isSup[], int cnt)
{
   if(!TradingEnabled) return;
   if(g_DailyLimitHit || g_DDLimitHit) return;
   if(WeekendBlock()) return;
   if(!IsSpreadOK() || !IsMarginOK() || !IsNewsOK() || !IsSessionOK()) return;
   if(CountPositions() >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
   if(DailyCapReached()) return;
   if(CountClusterAcid(isBuy) >= (int)SEC_Ov("MAXCLUSTER", 6)) { Print("🔗 cluster sature — rebond ignore"); return; }
   if(CotBlocks(isBuy)) { Print("🐋 Veto COT — rebond ", isBuy ? "BUY" : "SELL", " bloque"); return; }

   // ⚔️ CONFLUENCE : un rebond contre un train n'est pas un rebond
   double rail = 0; int stDir = BrainSuperTrend(rail);
   double adx = BrainADX();
   if(adx >= 28 && ((isBuy && stDir == -1) || (!isBuy && stDir == 1)))
   {
      // 💥 EXCEPTION EPUISEMENT (patron 27/07 : «…») : on
      // accepte d'aller contre le train UNIQUEMENT sur une vraie capitulation
      // — RSI extreme + grosse meche de rejet + niveau connu (on est deja
      // dedans, appele depuis CheckRebound). Lot reduit, SL serre.
      bool epuise = false;
      if(EP_Enabled)
      {
         double rbe[]; ArraySetAsSeries(rbe, true);
         MqlRates re[]; ArraySetAsSeries(re, true);
         if(h_ScalpRSI != INVALID_HANDLE && CopyBuffer(h_ScalpRSI, 0, 0, 1, rbe) >= 1
            && CopyRates(_Symbol, RB_TF, 0, 2, re) >= 2)
         {
            double rg = MathMax(re[1].high - re[1].low, g_Point);
            double wl = MathMin(re[1].open, re[1].close) - re[1].low;
            double wh = re[1].high - MathMax(re[1].open, re[1].close);
            if(isBuy  && rbe[0] <= EP_RSI          && wl >= EP_WickFrac * rg) epuise = true;
            if(!isBuy && rbe[0] >= 100.0 - EP_RSI  && wh >= EP_WickFrac * rg) epuise = true;
         }
      }
      if(!epuise)
      { Print("🌊 rebond contre rail fort (ADX ", DoubleToString(adx, 0), ") — passe"); return; }
      Print("💥 EPUISEMENT : rebond contre le rail AUTORISE (RSI extreme + meche de rejet) — lot reduit, SL serre");
      g_EpuisementNow = true;
   }
   if(adx >= 26)
   {
      int h1 = RB_H1Trend();
      if((isBuy && h1 == -1) || (!isBuy && h1 == 1))
      { Print("🧭 rebond contre tendance H1 en marche — passe"); return; }
   }

   // 🤖 ML consultatif (features M5 deja calculees par les handles scalp) :
   // ne bloque QUE si franchement contraire — pas de peur inutile.
   string newsSig = GetNewsSignalEA();
   if(newsSig == "crucial") { Print("🔴 NEWS CRUCIAL — pas de rebond"); return; }
   double ns = (newsSig == "high_vol") ? 25.0 : (newsSig == "news_now") ? 40.0 : (newsSig == "safe") ? 60.0 : 50.0;
   double rsiv = 50.0, emaR = 1.0, atr5 = atr, macdv = 0.0, bbw = 0.0;
   double bB[]; ArraySetAsSeries(bB, true);
   if(h_ScalpRSI != INVALID_HANDLE && CopyBuffer(h_ScalpRSI, 0, 0, 2, bB) >= 2) rsiv = bB[0];
   if(h_ScalpATR != INVALID_HANDLE && CopyBuffer(h_ScalpATR, 0, 0, 2, bB) >= 2) atr5 = bB[0];
   if(h_ScalpMACD != INVALID_HANDLE && CopyBuffer(h_ScalpMACD, 0, 0, 1, bB) >= 1) macdv = bB[0];
   double eF[], eS[]; ArraySetAsSeries(eF, true); ArraySetAsSeries(eS, true);
   if(h_ScalpEMAFast != INVALID_HANDLE && h_ScalpEMASlow != INVALID_HANDLE
      && CopyBuffer(h_ScalpEMAFast, 0, 0, 2, eF) >= 2 && CopyBuffer(h_ScalpEMASlow, 0, 0, 2, eS) >= 2
      && eS[0] != 0) emaR = eF[0] / eS[0];
   double bbU[1], bbL[1];
   if(h_ScalpBB != INVALID_HANDLE && CopyBuffer(h_ScalpBB, 1, 0, 1, bbU) >= 1
      && CopyBuffer(h_ScalpBB, 2, 0, 1, bbL) >= 1) bbw = bbU[0] - bbL[0];
   string mlSig = "NEUTRAL"; double mlConf = 0.5;
   if(GetMLPrediction(_Symbol, rsiv, emaR, atr5, macdv, bbw, ns, mlSig, mlConf))
      if(((isBuy && mlSig == "SELL") || (!isBuy && mlSig == "BUY")) && mlConf >= 0.58)
      { Print("🤖 ML franchement contraire (", mlSig, " ", DoubleToString(mlConf, 2), ") — rebond passe"); return; }

   // ⏲️ anti-mitraille : 1 rebond max par sens par RB_CooldownMin
   static datetime lastFireBuy = 0, lastFireSell = 0;
   if(isBuy  && TimeCurrent() - lastFireBuy  < RB_CooldownMin * 60) return;
   if(!isBuy && TimeCurrent() - lastFireSell < RB_CooldownMin * 60) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double price = isBuy ? ask : bid;

   // SL : sous le niveau ET la meche (niveau repris = rebond invalide)
   MqlRates rr[]; ArraySetAsSeries(rr, true);
   if(CopyRates(_Symbol, RB_TF, 0, 2, rr) < 2) return;
   // 💥 pari d'epuisement : SL SERRE sous la meche (on ne paie pas cher pour
   //    tester un retournement) ; sinon marge normale sous le niveau.
   double _pad = g_EpuisementNow ? EP_SL_ATR : RB_PadATR;
   double sl = isBuy ? MathMin(niveau, rr[1].low)  - _pad * atr
                     : MathMax(niveau, rr[1].high) + _pad * atr;

   // TP : vise le prochain niveau OPPOSE s'il tombe bien, sinon RB_TP_ATR x ATR
   double tp = isBuy ? price + RB_TP_ATR * atr : price - RB_TP_ATR * atr;
   double bestDist = DBL_MAX;
   for(int j = 0; j < cnt; j++)
   {
      if(isSup[j] == isBuy || touches[j] < RB_MinTouches) continue;   // camp d'en face seulement
      double dist = isBuy ? lvls[j] - price : price - lvls[j];
      if(dist < 1.0 * atr || dist > RB_TP_ATR * atr) continue;
      if(dist < bestDist) { bestDist = dist; tp = isBuy ? lvls[j] - 0.15 * atr : lvls[j] + 0.15 * atr; }
   }

   sl = NormalizeDouble(sl, g_Digits);
   tp = NormalizeDouble(tp, g_Digits);
   double slPips = MathAbs(price - sl) / g_PipSize;
   double lot = CalcLot(slPips);
   if(g_EpuisementNow) lot = MathMax(g_MinLot, NormalizeDouble(lot * EP_LotFrac, 2));  // 💥 lot reduit
   string comment = g_EpuisementNow ? "EPUISEMENT" : StringFormat("REBOUND|t=%d", nTouches);
   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = isBuy ? BuyFix(lot, _Symbol, price, sl, tp, comment)
                   : SellFix(lot, _Symbol, price, sl, tp, comment);
   if(ok)
   {
      if(isBuy) lastFireBuy = TimeCurrent(); else lastFireSell = TimeCurrent();
      g_TotalTrades++;
      SignalArrow(isBuy, price, g_EpuisementNow ? "EPUISEMENT" : "REBOND");
      g_LastSignalTxt = StringFormat("REBOND %s (%d touches)", isBuy?"BUY":"SELL", nTouches);
      JournalTrade(g_EpuisementNow ? "EPUISEMENT" : "REBOUND", isBuy, lot, price, sl, tp, nTouches, rsiv, atr, emaR, macdv, mlSig, mlConf);
      g_EpuisementNow = false;
      SendTelegramMsg(StringFormat("🏀 REBOND %s %s @ %s — niveau %s (%d touches) | SL %s | TP %s",
         isBuy ? "BUY" : "SELL", _Symbol, DoubleToString(price, g_Digits),
         DoubleToString(niveau, g_Digits), nTouches,
         DoubleToString(sl, g_Digits), DoubleToString(tp, g_Digits)));
   }
}

//+------------------------------------------------------------------+
//  🚀 MOMENTUM CAPTURE (patron 25/07) — «…
//  …». Une IMPULSION forte (gros corps + clôture
//  décidée) alignée avec le rail + le COT + l'ADX qui prend => on entre
//  pour RIDER (SL large, TP loin). FlowRider tient ensuite, l'essoufflement
//  et l'échelle de verrouillage encaissent. Confluence stricte pour ne pas
//  acheter un sommet parabolique (garde RSI). Cooldown anti-mitraille.
//+------------------------------------------------------------------+
double MOM_ATR(ENUM_TIMEFRAMES tf)
{
   MqlRates r[]; ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, tf, 0, 17, r) < 17) return 0;
   double s = 0;
   for(int i = 1; i <= 14; i++)
      s += MathMax(r[i].high - r[i].low,
           MathMax(MathAbs(r[i].high - r[i+1].close), MathAbs(r[i].low - r[i+1].close)));
   return s / 14.0;
}

void OpenMomentumTrade(bool isBuy, double atr)
{
   if(!TradingEnabled || g_DailyLimitHit || g_DDLimitHit) return;
   if(WeekendBlock()) return;
   if(!IsSpreadOK() || !IsMarginOK() || !IsNewsOK() || !IsSessionOK()) return;
   if(CountPositions() >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
   if(DailyCapReached()) return;
   if(CountClusterAcid(isBuy) >= (int)SEC_Ov("MAXCLUSTER", 6)) { Print("🔗 cluster saturé — momentum ignoré"); return; }
   if(CotBlocks(isBuy)) { Print("🐋 Veto COT — momentum ", isBuy?"BUY":"SELL", " bloqué"); return; }
   string ns = GetNewsSignalEA();
   if(ns == "crucial") { Print("🔴 NEWS CRUCIAL — pas de momentum"); return; }
   // pas d'empilement : déjà en position même sens sur ce symbole ?
   for(int i = 0; i < PositionsTotal(); i++)
      if(posInfo.SelectByIndex(i) && posInfo.Symbol() == _Symbol && posInfo.Magic() == MagicNumber
         && ((posInfo.PositionType() == POSITION_TYPE_BUY) == isBuy)) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double price = isBuy ? ask : bid;
   double sl = isBuy ? price - MOM_SL_ATR * atr : price + MOM_SL_ATR * atr;
   double tp = isBuy ? price + MOM_TP_ATR * atr : price - MOM_TP_ATR * atr;
   sl = NormalizeDouble(sl, g_Digits); tp = NormalizeDouble(tp, g_Digits);
   double slPips = MathAbs(price - sl) / g_PipSize;
   double lot = CalcLot(slPips);
   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = isBuy ? BuyFix(lot, _Symbol, price, sl, tp, "MOMENTUM")
                   : SellFix(lot, _Symbol, price, sl, tp, "MOMENTUM");
   if(ok)
   {
      g_TotalTrades++;
      SignalArrow(isBuy, price, "MOMENTUM");
      g_LastSignalTxt = StringFormat("MOMENTUM %s (impulsion)", isBuy ? "BUY" : "SELL");
      JournalTrade("MOMENTUM", isBuy, lot, price, sl, tp, 0, 0, atr, 0, 0, "-", 0);
      SendTelegramMsg(StringFormat("🚀 MOMENTUM %s %s @ %s — grosse bougie alignée | SL %s | TP %s",
         isBuy ? "BUY" : "SELL", _Symbol, DoubleToString(price, g_Digits),
         DoubleToString(sl, g_Digits), DoubleToString(tp, g_Digits)));
   }
}

void CheckMomentum()
{
   if(!MOM_Enabled || SEC_Ov("MOM", 1) < 0.5) return;
   static datetime lastBar = 0;
   datetime cur = iTime(_Symbol, MOM_TF, 0);
   if(cur == lastBar) return;          // 1 examen par bougie MOM_TF CLÔTURÉE
   lastBar = cur;

   double atr = MOM_ATR(MOM_TF);
   if(atr <= 0) return;
   MqlRates r[]; ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, MOM_TF, 0, 3, r) < 3) return;

   double body = MathAbs(r[1].close - r[1].open);
   double rng  = MathMax(r[1].high - r[1].low, g_Point);
   if(body < MOM_ImpulseATR * atr) return;                  // pas une vraie impulsion
   bool isBuy = (r[1].close > r[1].open);
   // clôture décidée (dans le haut/bas de la bougie)
   double closePos = isBuy ? (r[1].close - r[1].low) / rng : (r[1].high - r[1].close) / rng;
   if(closePos < MOM_CloseFrac) return;

   // ⚔️ CONFLUENCE : ADX qui prend + aligné rail + RSI pas déjà extrême
   if(BrainADX() < MOM_ADXMin) return;
   double rail = 0; int stDir = BrainSuperTrend(rail);
   if((isBuy && stDir < 0) || (!isBuy && stDir > 0)) return;   // jamais contre le rail
   double rb[]; ArraySetAsSeries(rb, true);
   if(h_ScalpRSI != INVALID_HANDLE && CopyBuffer(h_ScalpRSI, 0, 0, 1, rb) >= 1)
   {
      if(isBuy  && rb[0] > MOM_RSIguard)         return;   // pas de sommet parabolique
      if(!isBuy && rb[0] < (100 - MOM_RSIguard)) return;
   }
   // ⏲️ cooldown par sens
   static datetime lastBuy = 0, lastSell = 0;
   if(isBuy  && TimeCurrent() - lastBuy  < MOM_CooldownMin * 60) return;
   if(!isBuy && TimeCurrent() - lastSell < MOM_CooldownMin * 60) return;
   OpenMomentumTrade(isBuy, atr);
   if(isBuy) lastBuy = TimeCurrent(); else lastSell = TimeCurrent();
}

void CheckRebound()
{
   if(!RB_Enabled || SEC_Ov("REBOUND", 1) < 0.5) return;
   static datetime lastBar = 0;
   datetime cur = iTime(_Symbol, RB_TF, 0);
   if(cur == lastBar) return;           // 1 examen par bougie RB_TF CLOTUREE
   lastBar = cur;

   double atr = RB_ATRval();
   if(atr <= 0) return;
   double lvls[]; int touches[]; bool isSup[];
   int cnt = RB_CollectLevels(lvls, touches, isSup, atr);
   if(RB_DrawLevels) RB_Draw(lvls, touches, isSup, cnt);
   if(cnt == 0) return;

   MqlRates r[]; ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, RB_TF, 0, 3, r) < 3) return;
   double tol    = RB_TolATR * atr;
   double range  = MathMax(r[1].high - r[1].low, g_Point);
   double wickLo = MathMin(r[1].open, r[1].close) - r[1].low;
   double wickHi = r[1].high - MathMax(r[1].open, r[1].close);

   // RSI RB_TF qui se retourne (pas d'entree sur un couteau qui tombe)
   static int hR = INVALID_HANDLE;
   if(hR == INVALID_HANDLE) hR = iRSI(_Symbol, RB_TF, 14, PRICE_CLOSE);
   bool rsiOKbuy = true, rsiOKsell = true;
   double rb[]; ArraySetAsSeries(rb, true);
   if(hR != INVALID_HANDLE && CopyBuffer(hR, 0, 0, 3, rb) >= 3)
   {
      rsiOKbuy  = (rb[1] < 62.0 && rb[1] >= rb[2]);   // remonte depuis le bas
      rsiOKsell = (rb[1] > 38.0 && rb[1] <= rb[2]);   // redescend depuis le haut
   }

   for(int j = 0; j < cnt; j++)
   {
      if(touches[j] < RB_MinTouches) continue;
      if(isSup[j] && rsiOKbuy                          // SUPPORT -> rebond ACHAT
         && r[1].low   <= lvls[j] + tol * 0.5          // la bougie a touche la zone
         && r[1].low   >= lvls[j] - tol * 1.5          // perce toleree, pas cassee
         && r[1].close >  lvls[j]                      // cloture au-dessus = niveau TENU
         && wickLo     >= RB_WickFrac * range          // meche de rejet
         && r[1].close >= r[1].low + 0.55 * range)     // cloture dans le haut de bougie
      { OpenReboundTrade(true, lvls[j], touches[j], atr, lvls, touches, isSup, cnt); return; }
      if(!isSup[j] && rsiOKsell                        // RESISTANCE -> rebond VENTE
         && r[1].high  >= lvls[j] - tol * 0.5
         && r[1].high  <= lvls[j] + tol * 1.5
         && r[1].close <  lvls[j]
         && wickHi     >= RB_WickFrac * range
         && r[1].close <= r[1].high - 0.55 * range)
      { OpenReboundTrade(false, lvls[j], touches[j], atr, lvls, touches, isSup, cnt); return; }
   }
}


//+------------------------------------------------------------------+
//  📋 PLAN DU JOUR (patron 27/07) — L'OEIL ecrit MQL5\Filescid_plan.txt
//  («…»). L'EA le SUIT AVEC SES REGLES : c'est un
//  BONUS DE SCORE quand il va dans le sens du plan, et un MALUS quand il va
//  contre — jamais un ordre. «…» : il n'entre pas pour le
//  plan, il penche pour lui. Relu 1x/minute.
//+------------------------------------------------------------------+
int PlanBias()
{
   static int    biais = 0;
   static datetime lastRead = 0;
   if(TimeCurrent() - lastRead < 60) return biais;
   lastRead = TimeCurrent();
   biais = 0;
   int h = FileOpen("acid_plan.txt", FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h == INVALID_HANDLE) return 0;
   while(!FileIsEnding(h))
   {
      string l = FileReadString(h);
      string p[];
      if(StringSplit(l, '=', p) < 2) continue;
      if(StringCompare(p[0], _Symbol, false) != 0) continue;
      if(p[1] == "BUY")  biais =  1;
      if(p[1] == "SELL") biais = -1;
      break;
   }
   FileClose(h);
   return biais;
}

double PlanBonus(bool isBuy)
{
   int b = PlanBias();
   if(b == 0) return 0.0;
   bool aligne = (isBuy && b == 1) || (!isBuy && b == -1);
   return aligne ? PlanBonusScore : -PlanBonusScore;   // penche, n'impose pas
}

double CalcScalpScore(bool isBuy)
{
   double score = 0.0;

   // --- EMA alignment ---
   double emaF[], emaS[];
   ArraySetAsSeries(emaF,true);
   ArraySetAsSeries(emaS,true);
   if(CopyBuffer(h_ScalpEMAFast,0,0,3,emaF)<3) return 0;
   if(CopyBuffer(h_ScalpEMASlow,0,0,3,emaS)<3) return 0;

   if(isBuy  && emaF[0] > emaS[0] && emaF[1] > emaS[1]) score += 2.0;
   if(!isBuy && emaF[0] < emaS[0] && emaF[1] < emaS[1]) score += 2.0;

   // Croisement récent EMA (+bonus)
   if(isBuy  && emaF[1] <= emaS[1] && emaF[0] > emaS[0]) score += 1.0;
   if(!isBuy && emaF[1] >= emaS[1] && emaF[0] < emaS[0]) score += 1.0;

   // --- RSI ---
   double rsi[];
   ArraySetAsSeries(rsi,true);
   if(CopyBuffer(h_ScalpRSI,0,0,3,rsi)>=3)
   {
      if(isBuy  && rsi[0] > 45 && rsi[0] < Scalp_RSI_OB) score += 1.5;
      if(!isBuy && rsi[0] < 55 && rsi[0] > Scalp_RSI_OS) score += 1.5;
      // RSI sortie de zone extrême
      if(isBuy  && rsi[1] < Scalp_RSI_OS && rsi[0] > Scalp_RSI_OS) score += 1.0;
      if(!isBuy && rsi[1] > Scalp_RSI_OB && rsi[0] < Scalp_RSI_OB) score += 1.0;
   }

   // --- MACD ---
   double macdMain[], macdSignal[];
   ArraySetAsSeries(macdMain,true);
   ArraySetAsSeries(macdSignal,true);
   if(CopyBuffer(h_ScalpMACD,0,0,3,macdMain)>=3 &&
      CopyBuffer(h_ScalpMACD,1,0,3,macdSignal)>=3)
   {
      if(isBuy  && macdMain[0] > macdSignal[0] && macdMain[0] > 0) score += 1.5;
      if(!isBuy && macdMain[0] < macdSignal[0] && macdMain[0] < 0) score += 1.5;
      // Croisement MACD récent
      if(isBuy  && macdMain[1] <= macdSignal[1] && macdMain[0] > macdSignal[0]) score += 0.5;
      if(!isBuy && macdMain[1] >= macdSignal[1] && macdMain[0] < macdSignal[0]) score += 0.5;
   }

   // --- Bollinger Bands ---
   double bbUpper[], bbLower[], bbMid[];
   ArraySetAsSeries(bbUpper,true);
   ArraySetAsSeries(bbLower,true);
   ArraySetAsSeries(bbMid,true);
   if(CopyBuffer(h_ScalpBB,1,0,3,bbUpper)>=3 &&
      CopyBuffer(h_ScalpBB,2,0,3,bbLower)>=3 &&
      CopyBuffer(h_ScalpBB,0,0,3,bbMid)  >=3)
   {
      double price = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      if(isBuy  && price < bbMid[0])  score += 0.5;
      if(!isBuy && price > bbMid[0])  score += 0.5;
   }

   // --- Regime bonus ---
   if(g_Regime == REG_TREND) score += 0.5;
   if(g_Regime == REG_VIOLENT) score -= 2.0;

   // --- Bias alignment ---
   if(isBuy  && g_Bias == BIAS_BUY)  score += 1.0;
   if(!isBuy && g_Bias == BIAS_SELL) score += 1.0;
   if(isBuy  && g_Bias == BIAS_SELL) score -= 1.5;
   if(!isBuy && g_Bias == BIAS_BUY)  score -= 1.5;

   // --- 🧠 SUPER-CERVEAU v2 : ADX / VWAP / Squeeze / SuperTrend / SMC ---
   double adx = BrainADX();
   if(adx >= 25)                score += 0.75;  // vraie tendance : on peut pousser
   else if(adx > 0 && adx < 18) score -= 0.5;   // marché mou : exiger plus

   double vwap = BrainVWAP();
   double bidV = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(vwap > 0)
   {
      if(isBuy  && bidV > vwap) score += 0.75;  // trader du côté du flux institutionnel
      if(!isBuy && bidV < vwap) score += 0.75;
      if(isBuy  && bidV < vwap) score -= 0.5;
      if(!isBuy && bidV > vwap) score -= 0.5;
   }

   if(BrainSqueeze()) score += 0.5;             // ressort bandé : cassure imminente

   double stLine = 0;
   int stDir = BrainSuperTrend(stLine);
   if((isBuy && stDir > 0) || (!isBuy && stDir < 0)) score += 1.0;
   else if(stDir != 0) score -= 1.0;            // JAMAIS contre le rail

   int spring = BrainSpring();
   if((isBuy && spring > 0) || (!isBuy && spring < 0)) score += 1.5;  // sweep de liquidité

   bool dansFVG = false;
   int fvg = BrainFVG(dansFVG);
   if(dansFVG && ((isBuy && fvg > 0) || (!isBuy && fvg < 0))) score += 1.5;  // zone aimant touchée

   // 📏 lignes du chart (les tiennes + TrendLine PRO) : tremplin ou mur
   int lig = ChartIndOn("CHARTLINES", Use_ChartTrendLines) ? BrainLines() : 0;
   if(lig == 1)  { if(isBuy)  score += 0.75; else score -= 0.5; }   // support sous le nez
   if(lig == -1) { if(!isBuy) score += 0.75; else score -= 0.5; }   // mur au-dessus : on n'achète pas dedans

   // 🖼️ les AUTRES dessins de tes indicateurs (flèches, fibo, zones)
   score += BrainChartExtras(isBuy);

   // 📶 MACD signal alert : croisement frais dans le sens du trade
   int macdAlert = MacdSignalAlert(h_ScalpMACD);
   if((isBuy && macdAlert > 0) || (!isBuy && macdAlert < 0)) score += 1.0;
   else if(macdAlert != 0) score -= 0.5;   // cross frais CONTRE le trade = drapeau rouge

   // --- ML Bonus ---
   score += GetMLBonus();

   return MathMax(0.0, MathMin(12.0, score));
}

//+------------------------------------------------------------------+
//  SCORE ENGINE — SWING (0 à 10 + bonus ML)
//+------------------------------------------------------------------+
double CalcSwingScore(bool isBuy)
{
   double score = 0.0;

   // --- EMA alignment H4 ---
   double emaF[], emaS[], emaT[];
   ArraySetAsSeries(emaF,true);
   ArraySetAsSeries(emaS,true);
   ArraySetAsSeries(emaT,true);
   if(CopyBuffer(h_SwingEMAFast, 0,0,3,emaF)<3) return 0;
   if(CopyBuffer(h_SwingEMASlow, 0,0,3,emaS)<3) return 0;
   if(CopyBuffer(h_SwingEMATrend,0,0,3,emaT)<3) return 0;

   if(isBuy  && emaF[0]>emaS[0] && emaS[0]>emaT[0]) score += 2.5;
   if(!isBuy && emaF[0]<emaS[0] && emaS[0]<emaT[0]) score += 2.5;

   // Croisement EMA Fast/Slow récent
   if(isBuy  && emaF[1]<=emaS[1] && emaF[0]>emaS[0]) score += 1.0;
   if(!isBuy && emaF[1]>=emaS[1] && emaF[0]<emaS[0]) score += 1.0;

   // --- RSI H4 ---
   double rsi[];
   ArraySetAsSeries(rsi,true);
   if(CopyBuffer(h_SwingRSI,0,0,3,rsi)>=3)
   {
      if(isBuy  && rsi[0] > 40 && rsi[0] < Swing_RSI_OB) score += 1.5;
      if(!isBuy && rsi[0] < 60 && rsi[0] > Swing_RSI_OS) score += 1.5;
      if(isBuy  && rsi[1] < Swing_RSI_OS && rsi[0] >= Swing_RSI_OS) score += 1.0;
      if(!isBuy && rsi[1] > Swing_RSI_OB && rsi[0] <= Swing_RSI_OB) score += 1.0;
   }

   // --- ADX tendance ---
   double adx[];
   ArraySetAsSeries(adx,true);
   if(CopyBuffer(h_SwingADX,0,0,3,adx)>=3)
   {
      if(adx[0] > 25) score += 1.0;
      if(adx[0] > 40) score += 0.5;
   }

   // --- MACD H4 ---
   double macdMain[], macdSig[];
   ArraySetAsSeries(macdMain,true);
   ArraySetAsSeries(macdSig,true);
   if(CopyBuffer(h_SwingMACD,0,0,3,macdMain)>=3 &&
      CopyBuffer(h_SwingMACD,1,0,3,macdSig) >=3)
   {
      if(isBuy  && macdMain[0]>macdSig[0] && macdMain[0]>0) score += 1.0;
      if(!isBuy && macdMain[0]<macdSig[0] && macdMain[0]<0) score += 1.0;
   }

   // --- Stochastique ---
   double stochK[], stochD[];
   ArraySetAsSeries(stochK,true);
   ArraySetAsSeries(stochD,true);
   if(CopyBuffer(h_SwingStoch,0,0,3,stochK)>=3 &&
      CopyBuffer(h_SwingStoch,1,0,3,stochD)>=3)
   {
      if(isBuy  && stochK[0]>stochD[0] && stochK[0]<80) score += 0.5;
      if(!isBuy && stochK[0]<stochD[0] && stochK[0]>20) score += 0.5;
   }

   // --- Confirmation D1 ---
   double cfEMA50[], cfEMA200[];
   ArraySetAsSeries(cfEMA50,true);
   ArraySetAsSeries(cfEMA200,true);
   if(CopyBuffer(h_ConfirmEMA50, 0,0,3,cfEMA50) >=3 &&
      CopyBuffer(h_ConfirmEMA200,0,0,3,cfEMA200)>=3)
   {
      if(isBuy  && cfEMA50[0] > cfEMA200[0]) score += 1.0;
      if(!isBuy && cfEMA50[0] < cfEMA200[0]) score += 1.0;
   }

   // --- Regime ---
   if(g_Regime == REG_TREND)   score += 1.0;
   if(g_Regime == REG_VIOLENT) score -= 2.0;
   if(g_Regime == REG_DEAD)    score -= 1.0;

   // --- 🧠 SUPER-CERVEAU v2 (version swing) : flux + rail + zones ---
   double vwapS = BrainVWAP();
   double bidS  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(vwapS > 0)
   {
      if(isBuy  && bidS > vwapS) score += 0.5;
      if(!isBuy && bidS < vwapS) score += 0.5;
   }
   double stLineS = 0;
   int stDirS = BrainSuperTrend(stLineS);
   if((isBuy && stDirS > 0) || (!isBuy && stDirS < 0)) score += 1.0;
   else if(stDirS != 0) score -= 1.0;             // pas de swing contre le rail
   int springS = BrainSpring();
   if((isBuy && springS > 0) || (!isBuy && springS < 0)) score += 1.0;
   bool dansFVGS = false;
   int fvgS = BrainFVG(dansFVGS);
   if(dansFVGS && ((isBuy && fvgS > 0) || (!isBuy && fvgS < 0))) score += 1.0;

   int ligS = ChartIndOn("CHARTLINES", Use_ChartTrendLines) ? BrainLines() : 0;
   if(ligS == 1)  { if(isBuy)  score += 0.5; else score -= 0.5; }
   if(ligS == -1) { if(!isBuy) score += 0.5; else score -= 0.5; }

   score += 0.75 * BrainChartExtras(isBuy);   // 🖼️ dessins du chart (poids réduit en swing)

   int macdAlertS = MacdSignalAlert(h_SwingMACD);
   if((isBuy && macdAlertS > 0) || (!isBuy && macdAlertS < 0)) score += 0.75;
   else if(macdAlertS != 0) score -= 0.5;

   // --- ML Bonus ---
   score += GetMLBonus();

   return MathMax(0.0, MathMin(12.0, score));
}

//+------------------------------------------------------------------+
//  SESSION CHECK
//+------------------------------------------------------------------+
bool IsSessionOK()
{
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   int h = dt.hour;

   bool london  = LondonEnabled  && h >= LondonOpen  && h < LondonClose;
   bool newyork = NewYorkEnabled && h >= NewYorkOpen  && h < NewYorkClose;
   bool asia    = AsiaEnabled    && (h >= AsiaOpen    && h < AsiaClose);

   return (london || newyork || asia);
}

//+------------------------------------------------------------------+
//  SPREAD CHECK
//+------------------------------------------------------------------+
bool IsSpreadOK()
{
   double spread = SymbolInfoInteger(_Symbol,SYMBOL_SPREAD) * g_Point;
   double spreadPips = spread / g_PipSize;
   return (spreadPips <= MaxSpreadPips);
}

//+------------------------------------------------------------------+
//  MARGIN CHECK
//+------------------------------------------------------------------+
bool IsMarginOK()
{
   double margin     = AccountInfoDouble(ACCOUNT_MARGIN);
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin <= 0) return true;
   double pct = (freeMargin / margin) * 100.0;
   return (pct >= MinMarginPct);
}

//+------------------------------------------------------------------+
//  NEWS FILTER (placeholder — peut être connecté à un calendrier)
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//  📅 PUBLICATION DU CALENDRIER (08/09, idée du patron : «…
//  …»)
//  Le paquet Python de MT5 n'expose AUCUNE fonction calendrier — seul un EA
//  peut le lire. Les serveurs devinaient donc les events à partir des titres
//  de presse : un article parlant du FOMC bloquait TOUT le trading, et un
//  «…» a été déclaré un mardi (ML à confiance 0,0 toute la journée).
//  On écrit les events HAUTE importance des prochaines 24 h. Un seul chart
//  écrit par fenêtre de 5 min (verrou par GlobalVariable).
//+------------------------------------------------------------------+
void PublishCalendar()
{
   datetime now = TimeTradeServer();
   if(GlobalVariableGet("ACID_CAL_TS") + 300 > (double)now) return;   // déjà fait
   GlobalVariableSet("ACID_CAL_TS", (double)now);

   MqlCalendarValue vals[];
   int n = CalendarValueHistory(vals, now - 3600, now + 86400);       // -1 h → +24 h
   int h = FileOpen("acid_calendrier.txt", FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   FileWrite(h, "# genere par ACID IA V1 le " + TimeToString(now, TIME_DATE|TIME_SECONDS));
   FileWrite(h, "# horodatage_serveur|devise|importance|nom");
   int ecrits = 0;
   for(int i = 0; i < n; i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(vals[i].event_id, ev)) continue;
      if(ev.importance != CALENDAR_IMPORTANCE_HIGH) continue;
      MqlCalendarCountry pays;
      string dev = "";
      if(CalendarCountryById(ev.country_id, pays)) dev = pays.currency;
      FileWrite(h, (string)(long)vals[i].time + "|" + dev + "|HIGH|" + ev.name);
      ecrits++;
   }
   FileClose(h);
   static datetime _log = 0;
   if(now - _log >= 3600)
   {
      _log = now;
      Print("📅 calendrier publie : ", ecrits, " evenements HAUTE importance sur 24 h");
   }
}

bool IsNewsOK()
{
   if(!NewsFilterEnabled) return true;
   // 🛡️ VRAI filtre news (12/07) : calendrier économique NATIF de MT5.
   // Avant = placeholder qui renvoyait toujours true → le scalp tradait en
   // plein NFP/FOMC/CPI. Maintenant : pas de nouvelle entrée à ± NEWSMIN min
   // d'un event HAUTE importance touchant une des devises du symbole.
   int mins = (int)SEC_Ov("NEWSMIN", 15);
   if(mins <= 0) return true;
   string curBase  = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE);
   string curQuote = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT);
   datetime from = TimeTradeServer() - mins*60;
   datetime to   = TimeTradeServer() + mins*60;
   string devises[2]; devises[0]=curBase; devises[1]=curQuote;
   for(int d=0; d<2; d++)
   {
      if(devises[d]=="") continue;
      MqlCalendarValue vals[];
      int n = CalendarValueHistory(vals, from, to, NULL, devises[d]);
      for(int i=0; i<n; i++)
      {
         MqlCalendarEvent ev;
         if(!CalendarEventById(vals[i].event_id, ev)) continue;
         if(ev.importance == CALENDAR_IMPORTANCE_HIGH)
         {
            // 🤫 05/08 : annonce 1x/5min max (avant : hurlé à CHAQUE tick × 7 charts)
            static datetime _newsLog = 0;
            if(TimeCurrent() - _newsLog >= 300)
            {
               _newsLog = TimeCurrent();
               Print("🔴 NEWS HAUTE IMPORTANCE (", devises[d], ") sous ", mins, " min — entrées bloquées : ", ev.name);
            }
            return false;
         }
      }
   }
   return true;   // échoue OUVERT si le calendrier est vide/indispo (mieux que l'ancien placeholder muet)
}

//+------------------------------------------------------------------+
//  🐋 VETO COT NATIF (12/07) — l'ACID IA ne trade plus CONTRE les
//  institutionnels (le sell-or contre COT = X € historiques).
//  L'ŒIL écrit le biais dans MQL5\Files\acid_cot.txt : «…»
//  par ligne (ex. GOLD#=HAUSSIER=52.5). Pilotable SET|COTVETO|0.
//+------------------------------------------------------------------+
bool CotBlocks(bool isBuy)
{
   if(SEC_Ov("COTVETO", 1) < 0.5) return false;
   // 🔋 autonomie (12/07) : si L'ŒIL est éteint depuis >3 jours, le fichier
   // COT est périmé → on n'applique PAS un biais fossile (fail open).
   long modif = FileGetInteger("acid_cot.txt", FILE_MODIFY_DATE);
   if(modif > 0 && TimeCurrent() - (datetime)modif > 3 * 24 * 3600) return false;
   int h = FileOpen("acid_cot.txt", FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h == INVALID_HANDLE) return false;
   bool block = false;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      string p[];
      if(StringSplit(line, '=', p) < 3) continue;
      if(p[0] != _Symbol) continue;
      double pct = StringToDouble(p[2]);
      if(MathAbs(pct) >= 10)
      {
         if(p[1] == "HAUSSIER" && !isBuy) block = true;   // biais acheteur fort → pas de SELL
         if(p[1] == "BAISSIER" &&  isBuy) block = true;   // biais vendeur fort → pas de BUY
      }
      break;
   }
   FileClose(h);
   return block;
}

//+------------------------------------------------------------------+
//  DAILY DRAWDOWN CHECK
//+------------------------------------------------------------------+
void UpdateDailyDD()
{
   // Reset journalier
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   datetime todayStart = StringToTime(
      StringFormat("%04d.%02d.%02d 00:00", dt.year, dt.mon, dt.day));

   if(g_DayStart != todayStart)
   {
      g_DayStart       = todayStart;
      g_DailyStartBal  = AccountInfoDouble(ACCOUNT_BALANCE);
      g_DailyLoss      = 0.0;
      g_DailyLimitHit  = false;
      // 🔧 FIX audit 03/08 : réarmer le drawdown chaque jour + repartir du solde du
      // jour. Aucun reset n'existait ailleurs → g_DDLimitHit restait true à vie et
      // l'EA était MORT (plus aucune entrée) jusqu'au rechargement manuel du chart.
      g_DDLimitHit     = false;
      g_PeakBalance    = AccountInfoDouble(ACCOUNT_BALANCE);
   }

   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);

   // Perte journalière — 🔧 04/08 (patron «…») : compte les pertes
   // RÉALISÉES (balance), plus le flottant. Le panier assumé de L'ŒIL (risque
   // 10%) verrouillait l'EA en «…» alors que rien n'était perdu.
   // Garde-fou d'URGENCE conservé : équity -25% du départ (vrai crash) → stop.
   g_DailyLoss = g_DailyStartBal - balance;
   double dailyLossPct  = (g_DailyStartBal > 0) ? (g_DailyLoss / g_DailyStartBal) * 100.0 : 0.0;
   double equityLossPct = (g_DailyStartBal > 0) ? ((g_DailyStartBal - equity) / g_DailyStartBal) * 100.0 : 0.0;

   // ═══════════════════════════════════════════════════════════════════
   // 🔓 07/08 — ORDRE PATRON : «…
   // …». DEUX défauts trouvés en mesurant sur le compte réel :
   //
   //  1) Le seuil en % est ABSURDE sur un petit compte : 5% de X € =X €.
   //     L'EA se coupait pour DEUX EUROS. → plancher absolu en euros.
   //
   //  2) LE PLUS GRAVE : equityLossPct utilisait l'équity du COMPTE ENTIER.
   //     Mesure du 07/08 : flottant compte X € dont X € appartenant à
   //     L'ŒIL (magic 999111) et X € à l'EA — qui n'avait AUCUNE position.
   //     → equityLossPct = 56,7% → kill-switch armé → «…
   //     …» sur tous les charts. L'EA se suicidait à cause du
   //     travail d'un AUTRE bot, sans avoir perdu un centime lui-même.
   //     C'est exactement pourquoi les 6 mouvements de la nuit sont passés
   //     sous son nez. → on ne compte plus que SON PROPRE flottant.
   //
   // Le vrai rempart anti-catastrophe (SES pertes à lui) reste armé.
   // ═══════════════════════════════════════════════════════════════════
   double flottantPropre = 0.0;
   for(int _i = PositionsTotal() - 1; _i >= 0; _i--)
   {
      ulong _tk = PositionGetTicket(_i);
      if(_tk <= 0 || !PositionSelectByTicket(_tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)MagicNumber) continue;
      flottantPropre += PositionGetDouble(POSITION_PROFIT)
                      + PositionGetDouble(POSITION_SWAP);
   }
   // équity «…» par l'EA = son solde + SES flottants (les autres bots ne le regardent pas)
   double equityPropre   = balance + flottantPropre;
   double equityLossOwn  = (g_DailyStartBal > 0)
                           ? ((g_DailyStartBal - equityPropre) / g_DailyStartBal) * 100.0 : 0.0;

   // Limite journalière : MaxDailyLossPct = 0 → DÉSACTIVÉE (choix patron).
   // Sinon elle exige AUSSI d'avoir réellement perdu MaxDailyLossEur euros.
   // 💶 25/09 (patron : «…
   // …» — «…»). Le plafond en EUROS suffit désormais
   // à lui seul, et il est pilotable à chaud (SET|DAILYEUR|30). g_DailyLoss est
   // calculé sur le SOLDE DU COMPTE : la limite vaut donc pour les 7 charts
   // ensemble, pas X € par chart comme avant. Le compteur repart chaque matin,
   // et rien n'est fermé : seules les NOUVELLES entrées sont coupées.
   double _dlEur = SEC_Ov("DAILYEUR", MaxDailyLossEur);
   double _dlPct = SEC_Ov("DAILYPCT", MaxDailyLossPct);
   bool limiteJour = (_dlEur > 0.0 && g_DailyLoss >= _dlEur)
                     || (_dlPct > 0.0 && dailyLossPct >= _dlPct);

   if(limiteJour || equityLossOwn >= KillSwitchOwnPct)
   {
      if(!g_DailyLimitHit)
         PrintFormat("🛑 Entrées coupées — perte jour %.2f€ (%.1f%%), flottant PROPRE %.2f€ "
                     "(%.1f%% du solde du jour). Le flottant des autres bots n'entre PAS en compte.",
                     g_DailyLoss, dailyLossPct, flottantPropre, equityLossOwn);
      g_DailyLimitHit = true;
   }

   // Peak balance pour drawdown global
   if(balance > g_PeakBalance) g_PeakBalance = balance;
   // 🔧 FIX audit 03/08 : drawdown mesuré sur la BALANCE réalisée (pas l'equity
   // flottante) — sinon 6 positions momentanément rouges latchaient g_DDLimitHit.
   double dd = (g_PeakBalance > 0)
               ? ((g_PeakBalance - balance) / g_PeakBalance) * 100.0
               : 0.0;
   g_DrawdownPct = dd;
   if(dd >= MaxDrawdownPct) g_DDLimitHit = true;
}

//+------------------------------------------------------------------+
//  PLAFOND JOURNALIER D'ENTREES (patron 24/07) — compte les deals
//  d'ENTREE ouverts aujourd'hui sur CE symbole + CE magic (= ce chart).
//  Empeche l'over-trading : au-dela de MaxTradesPerDay, plus de nouvelle
//  entree du jour (les CLOSE/gestion restent permis). Pilotable SET|MAXDAY.
//+------------------------------------------------------------------+
int ScalpsToday()
{
   datetime jour = (datetime)(TimeCurrent() - (TimeCurrent() % 86400));  // minuit serveur
   if(!HistorySelect(jour, TimeCurrent())) return 0;
   int n = 0, deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
   {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != (long)MagicNumber)  continue;
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol)            continue;
      if(StringFind(HistoryDealGetString(tk, DEAL_COMMENT), "SCALP") < 0) continue;
      n++;
   }
   return n;
}

int TradesToday()
{
   datetime jour = (datetime)(TimeCurrent() - (TimeCurrent() % 86400));  // minuit serveur
   if(!HistorySelect(jour, TimeCurrent())) return 0;
   int n = 0, deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
   {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != (long)MagicNumber)  continue;
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol)            continue;
      n++;
   }
   return n;
}

bool DailyCapReached()
{
   int cap = (int)SEC_Ov("MAXDAY", MaxTradesPerDay);
   if(cap <= 0) return false;                 // 0 = illimite
   if(TradesToday() >= cap)
   {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn > 300)      // 1 log / 5 min max (anti-spam)
      { Print("🛑 Plafond du jour atteint : ", cap, " entrees sur ", _Symbol, " — pas de nouvelle entree."); lastWarn = TimeCurrent(); }
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//  COUNT POSITIONS
//+------------------------------------------------------------------+
int CountPositions(string comment="")
{
   int count = 0;
   for(int i=0;i<PositionsTotal();i++)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Symbol()==_Symbol && posInfo.Magic()==MagicNumber)
         {
            if(comment=="" || StringFind(posInfo.Comment(),comment)>=0)
               count++;
         }
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//  COUNT PENDING ORDERS
//+------------------------------------------------------------------+
int CountPending()
{
   int count = 0;
   for(int i=0;i<OrdersTotal();i++)
   {
      if(ordInfo.SelectByIndex(i))
      {
         if(ordInfo.Symbol()==_Symbol && ordInfo.Magic()==MagicNumber)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//  CALC LOT SIZE
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//  🛡️ RÈGLES D'ACIER NATIVES (09/07) — codées en DUR (pas des inputs :
//  les charts gardent des inputs fantômes après recompilation) et
//  pilotables à distance par L'ŒIL via le pont :
//     SET|MAXLOT|0.01   SET|RISK|1.0   SET|RECOVERY|0
//  Persistance : GlobalVariables du terminal (survivent aux restarts).
//+------------------------------------------------------------------+
// 🎛️ «…» (09/07) : curseur générique piloté par L'ŒIL.
// Si L'ŒIL a réglé la clé (GlobalVariable ACID_SEC_<KEY>), elle PRIME sur
// l'input du chart ; sinon l'input garde la main. Réglable via SET|<KEY>|val.
// 🎯 PRESETS PAR CHART (13/07 patron) : la clé la plus PRÉCISE gagne —
// ACID_SEC_<SYM>_<TF>_<CLÉ> > ACID_SEC_<SYM>_<CLÉ> > ACID_SEC_<CLÉ> > input.
// Posées par L'ŒIL via SETSYM|SYM|TF|CLÉ|VAL (TF="*" = tous les TF du symbole).
double SEC_Ov(string key, double def)
{
   string tf = StringSubstr(EnumToString((ENUM_TIMEFRAMES)Period()), 7);
   string g1 = "ACID_SEC_" + _Symbol + "_" + tf + "_" + key;
   if(GlobalVariableCheck(g1)) return GlobalVariableGet(g1);
   string g2 = "ACID_SEC_" + _Symbol + "_" + key;
   if(GlobalVariableCheck(g2)) return GlobalVariableGet(g2);
   string g = "ACID_SEC_" + key;
   return GlobalVariableCheck(g) ? GlobalVariableGet(g) : def;
}

double SEC_MaxLot()   { return SEC_Ov("MAXLOT", 0.02); }
double SEC_RiskPct()  { return SEC_Ov("RISK", 1.0); }   // version publique : défaut 1 % (2 % chez l'auteur)
// 🪙 MODE PETIT COMPTE (patron 04/08 : «…») :
// plafond DUR de risque pour ACCEPTER le lot MINIMUM quand le risque cible ne le
// finance pas. Sans ça, un compte <X € restait muet sur presque tout.
double SEC_RiskCap()  { return SEC_Ov("RISKCAP", 2.0); }   // version publique : 2 % (8 % chez l'auteur) — au-delà, le lot mini est REFUSÉ à voix haute
bool   SEC_Recovery() { return SEC_Ov("RECOV", 1) > 0.5; }

// 🎛️ Bornes du «…» — chaque curseur est BORNÉ (l'IA règle à sa
// guise, jamais hors règles d'acier). Catalogue UNIQUE pour SET et SETSYM.
bool SetBounds(string k, double &lo, double &hi)
{
   if(k == "MAXLOT")          { lo = 0.01; hi = 0.10; }   // jamais > 0.10 (règle d'acier)
   else if(k == "RISK")       { lo = 0.1;  hi = 50.0; }   // 04/08 : plafond levé (patron décide, jusqu'à 50%)
   else if(k == "RISKCAP")    { lo = 0.5;  hi = 50.0; }   // 🪙 petit compte — pilotable librement (SET|RISKCAP|30 possible)
   else if(k == "RECOVERY")   { lo = 0;    hi = 1;    }
   else if(k == "BEPIPS")     { lo = 1;    hi = 200;  }   // seuil breakeven (pips)
   else if(k == "TRAILSTART") { lo = 1;    hi = 300;  }   // départ trailing (pips)
   else if(k == "TRAILSTEP")  { lo = 1;    hi = 100;  }   // pas du trailing (pips)
   else if(k == "SCOREMIN")   { lo = 0;    hi = 10;   }   // sélectivité des entrées
   else if(k == "MAXPOS")     { lo = 1;    hi = 10;   }   // positions simultanées max
   else if(k == "SCALP")      { lo = 0;    hi = 1;    }   // module scalp on/off
   else if(k == "PENDING")    { lo = 0;    hi = 1;    }   // module pendings on/off
   else if(k == "AIVAL")      { lo = 0;    hi = 1;    }   // validation IA (8060) on/off
   else if(k == "MAXCLUSTER") { lo = 1;    hi = 6;    }   // positions corrélées même sens max
   else if(k == "NEWSMIN")    { lo = 0;    hi = 60;   }   // minutes de blackout news (0=off)
   else if(k == "JOURNAL")    { lo = 0;    hi = 1;    }   // journal d'auto-apprentissage
   else if(k == "COTVETO")    { lo = 0;    hi = 1;    }   // veto COT natif
   else if(k == "PGUARD")     { lo = 0;    hi = 1;    }   // profit guard
   else if(k == "CANTRADE")   { lo = 0;    hi = 1;    }   // liberté d'action de l'IA du chart (13/07)
   else if(k == "SLATR")      { lo = 0.5;  hi = 5.0;  }   // SL scalp = X × ATR (13/07)
   else if(k == "TPATR")      { lo = 0.5;  hi = 8.0;  }   // TP scalp = X × ATR (13/07)
   else if(k == "CHARTIND")   { lo = 0;    hi = 1;    }   // bloc indicateurs du chart (13/07)
   else if(k == "CHARTLINES") { lo = 0;    hi = 1;    }   // famille lignes
   else if(k == "CHARTARROWS"){ lo = 0;    hi = 1;    }   // famille flèches
   else if(k == "CHARTFIBO")  { lo = 0;    hi = 1;    }   // famille Fibonacci
   else if(k == "CHARTZONES") { lo = 0;    hi = 1;    }   // famille zones/rectangles
   else if(k == "MODEL")      { lo = 0;    hi = 3;    }   // IA du chart : 0=gemini 1=mistral 2=gpt 3=claude (13/07)
   else if(k == "PENDCOOL")   { lo = 0;    hi = 240;  }   // 🧊 16/09 pause (min) avant un pending même sens après une sortie
   else if(k == "HEDGE")      { lo = 0;    hi = 1;    }   // 🛡️ 16/09 ouverture de nouveaux hedges (0 = coupée)
   // 🩹 16/09 — CheckRebound et CheckMomentum lisent SEC_Ov("REBOUND") et SEC_Ov("MOM"),
   // et le commentaire promet «…». Mais ces clés manquaient
   // ici : la commande finissait en «…» et le module continuait.
   else if(k == "REBOUND")    { lo = 0;    hi = 1;    }   // module REBOUND on/off
   else if(k == "SWING")      { lo = 0;    hi = 1;    }   // module SWING on/off (24/09)
   else if(k == "DAILYEUR")   { lo = 0;    hi = 500;  }   // 💶 25/09 perte max du jour (€, compte entier)
   else if(k == "DAILYPCT")   { lo = 0;    hi = 50;   }   // ...ou en % du solde du jour (0 = off)
   else if(k == "MOM")        { lo = 0;    hi = 1;    }   // module MOMENTUM on/off
   else if(k == "LOCKBEPART") { lo = 0;    hi = 0.9;  }   // 🔒 14/09 part du palier 1 verrouillée (borne oubliée, ajoutée le 16/09)
   else return false;
   return true;
}

// Applique un réglage (borné) — global si sym=="", sinon preset par chart.
void SetApply(string k, double sv, string sym, string tf)
{
   double lo = 0, hi = 0;
   if(!SetBounds(k, lo, hi)) { Print("⚠️ SET inconnu : ", k); return; }
   sv = MathMax(lo, MathMin(hi, sv));
   string gk = (k == "RECOVERY") ? "RECOV" : k;   // compat SEC_Recovery()
   string prefixe = "";
   if(sym != "")
      prefixe = sym + "_" + ((tf == "" || tf == "*") ? "" : tf + "_");
   GlobalVariableSet("ACID_SEC_" + prefixe + gk, sv);
   Print("🛡️ SET ", (sym == "" ? "" : "[" + sym + ((tf == "" || tf == "*") ? "" : " " + tf) + "] "),
         k, " = ", sv, "  (borné [", lo, " ; ", hi, "])");
}

// Lot sécurisé : cap dur + risque réel (lot × distance SL) <= SEC_RiskPct%
// du solde. Renvoie 0.0 = trade REFUSÉ (on ne gonfle JAMAIS en silence).
double SecureLot(string sym, double lot, double slDist)
{
   // 🪜 PALIERS DE LOTS (patron 05/08, passage au COMPTE RÉEL) :
   //   <X € → 0.01 fixe partout · 200-X € → 0.02 max · >X € → sizing
   //   dynamique, borné par MAXLOT («…»). Central : AUCUN moteur
   //   ne peut contourner ce péage.
   double _balPal = AccountInfoDouble(ACCOUNT_BALANCE);
   double _palier = (_balPal < 200.0) ? 0.01 : ((_balPal < 500.0) ? 0.02 : SEC_MaxLot());
   lot = MathMin(lot, _palier);
   lot = MathMin(lot, SEC_MaxLot());
   double ts  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tv  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double lossPerLot = (slDist > 0 && ts > 0 && tv > 0) ? slDist / ts * tv : 0.0;  // € au SL pour 1.0 lot
   if(lossPerLot > 0)
   {
      double lotMax = bal * SEC_RiskPct() / 100.0 / lossPerLot;   // sizing au risque CIBLE
      if(lot > lotMax) lot = lotMax;
   }
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);  if(step <= 0) step = 0.01;
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);   if(vmin <= 0) vmin = 0.01;
   lot = MathFloor(lot / step) * step;
   if(lot >= vmin) return NormalizeDouble(lot, 2);

   // 🪙 MODE PETIT COMPTE (patron 04/08) : le risque CIBLE ne finance pas le lot
   // mini → on l'ACCEPTE quand même TANT QUE son risque réel reste sous le
   // PLAFOND DUR SEC_RiskCap (défaut 2 % dans cette version). Au-delà (ex : GOLD swing = 0.01 lot ≈
   // 25 % du compte), c'est physiquement trop lourd → on refuse, mais À VOIX
   // HAUTE (jamais muet en silence).
   if(lossPerLot > 0)
   {
      double minRisk = vmin * lossPerLot;              // € risqués au lot minimum
      double cap     = bal * SEC_RiskCap() / 100.0;    // plafond dur en €
      if(minRisk <= cap)
      {
         Print("🪙 PETIT COMPTE ", sym, " : lot mini ", DoubleToString(vmin, 2),
               " accepté (risque ", DoubleToString(minRisk, 2), " € = ",
               DoubleToString(bal > 0 ? minRisk / bal * 100.0 : 0, 1),
               "% ≤ plafond ", DoubleToString(SEC_RiskCap(), 1), "%)");
         return NormalizeDouble(vmin, 2);
      }
      Print("🛡️ LOT REFUSÉ ", sym, " : lot mini risquerait ", DoubleToString(minRisk, 2),
            " € (", DoubleToString(bal > 0 ? minRisk / bal * 100.0 : 0, 1),
            "%) > plafond ", DoubleToString(SEC_RiskCap(), 1), "% — trop lourd pour ",
            DoubleToString(bal, 2), " € (SL ", DoubleToString(slDist, 2), ")");
      return 0.0;
   }
   Print("🛡️ LOT REFUSÉ ", sym, " : sizing impossible (SL/tick invalides)");
   return 0.0;
}

double CalcLot(double slPips)
{
   if(slPips <= 0) return g_MinLot;
   // Fix 07/07 : PLANCHER GLOBAL de sizing — un SL microscopique (ATR de
   // nuit/matin calme) donnait des lots geants (0.28 EURUSD sur un petit compte !).
   // Le lot est desormais calcule comme si le SL faisait au moins
   // Pending_MinSLPips (8 pips), quel que soit le chemin (scalp/swing/pending).
   slPips = MathMax(slPips, Pending_MinSLPips);

   double riskPct = RiskPctNormal;
   if(RiskLevel == RISK_SAFE)       riskPct = RiskPctSafe;
   if(RiskLevel == RISK_AGGRESSIVE) riskPct = RiskPctAggressive;

   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * riskPct / 100.0;

   double tickSize  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0 || tickValue <= 0) return g_MinLot;

   double slMoney   = slPips * g_PipSize;
   double pipValue  = (tickValue / tickSize) * g_PipSize;
   if(pipValue <= 0) return g_MinLot;

   double lot = riskMoney / (slPips * pipValue);
   lot = MathFloor(lot / g_LotStep) * g_LotStep;
   lot = MathMax(g_MinLot, MathMin(g_MaxLot, lot));
   // 🛡️ règle d'acier : cap dur + risque réel <= SEC_RiskPct% — dernier mot
   return SecureLot(_Symbol, lot, slPips * g_PipSize);
}

//+------------------------------------------------------------------+
//  🧊 Mémoire courte anti-mur (patron 25/07) : une perte récente sur ce
//  symbole DANS CE SENS = le marché vient de dire non. On attend X min
//  avant de retenter le même pari (le chop de 14-18h mangeait tout).
//+------------------------------------------------------------------+
bool RecentLoss(bool isBuy, int minutes)
{
   datetime from = TimeCurrent() - minutes * 60;
   if(!HistorySelect(from, TimeCurrent() + 60)) return false;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong tk = HistoryDealGetTicket(i);
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != MagicNumber) continue;
      if(HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetDouble(tk, DEAL_PROFIT) >= 0) continue;
      bool wasBuy = (HistoryDealGetInteger(tk, DEAL_TYPE) == DEAL_TYPE_SELL);   // deal OUT inversé
      if(wasBuy == isBuy) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//  OPEN SCALP TRADE
//+------------------------------------------------------------------+
void OpenScalpTrade(bool isBuy)
{
  // ✅ Anti-spam - 1 check par minute max
   static datetime lastCheck = 0;
   if(TimeCurrent() - lastCheck < 60) return;
   lastCheck = TimeCurrent();
   if(!ScalpEnabled || SEC_Ov("SCALP", 1) < 0.5)   return;   // 🎛️ coupable à distance
   if(WeekendBlock()) return;                                // 📅 pas d'entrée le week-end
   if(!TradingEnabled) return;
   if(g_DailyLimitHit || g_DDLimitHit) return;
   if(!IsSpreadOK())   return;
   if(!IsMarginOK())   return;
   if(!IsNewsOK())     return;
   if(!IsSessionOK())  return;
   // 🧘 08/09 — TEMPS DE REPOS DU SCALP (patron). Le seul moteur qui n'en avait pas.
   static datetime lastScalpFire = 0;
   if(Scalp_CooldownMin > 0 && TimeCurrent() - lastScalpFire < Scalp_CooldownMin * 60)
      return;
   if(CountPositions("SCALP") >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
   if(DailyCapReached()) return;
   // 🔗 filtre corrélation : pas plus de MAXCLUSTER paris ACID IA même sens /
   // même cluster (métaux, crypto, indices…) = fini le risque concentré déguisé.
   if(CountClusterAcid(isBuy) >= (int)SEC_Ov("MAXCLUSTER", 6)) { Print("🔗 cluster saturé — scalp ignoré"); return; }
   if(CotBlocks(isBuy)) { Print("🐋 Veto COT — scalp ", isBuy?"BUY":"SELL", " bloqué"); return; }

   // 🎯 QUALITÉ DES TIRS (patron 25/07, nuit du backtest : «…
   // …») — le backtest GOLD montre : gains 8-11h, hémorragie 14-18h en
   // scalp de range. Le seuil devient ADAPTATIF au contexte :
   //   • RANGE/DEAD : +2 pts exigés (un scalp de chop doit être PARFAIT)
   //   • heures rouges mesurées (14-18h) : +1.5 pt
   //   • perte récente même sens (<30 min) : on ne re-rentre pas dans le mur
   // 🔫 25/07 patron : «…» — chaque balle doit compter.
   if(ScalpsToday() >= (int)SEC_Ov("SCALPMAX", Scalp_MaxPerDay))
   { static datetime lastMsg = 0;
     if(TimeCurrent() - lastMsg > 3600) { Print("🔫 quota scalp du jour atteint (", (int)SEC_Ov("SCALPMAX", Scalp_MaxPerDay), ") — sniper only"); lastMsg = TimeCurrent(); }
     return; }

   double seuilQ = SEC_Ov("SCOREMIN", Scalp_ScoreMin);
   if(g_Regime == REG_RANGE || g_Regime == REG_DEAD) seuilQ += 2.0;
   MqlDateTime dtQ; TimeToStruct(TimeCurrent(), dtQ);
   // ⏰ 25/07 backtest : le scalp GAGNE 8-13h, PERD 14-18h — a chaque run.
   // Fenetre DURE : hors des heures prouvees gagnantes, le scalp ne tire pas
   // (le sniper structure/momentum, lui, reste actif 24h). Pilotable SCALPH1/H2.
   if(dtQ.hour < (int)SEC_Ov("SCALPH1", 8) || dtQ.hour > (int)SEC_Ov("SCALPH2", 13)) return;
   if(RecentLoss(isBuy, (int)SEC_Ov("LOSSCOOL", 30)))
   { Print("🧊 perte récente ", isBuy?"BUY":"SELL", " — on ne re-rentre pas dans le mur"); return; }

   // 🌊 02/09 — LE SCALP NE REME PLUS À CONTRE-COURANT (mandat patron :
   // «…»).
   // Mesure sur 4000 bougies M5 de l'or, spread réel inclus :
   //     sans filtre : 169 tirs, 47,9% gagnants, +33,5R
   //     avec filtre : 104 tirs, 56,7% gagnants, +43,5R  (+25,5 puis +18,0)
   // 40% de tirs en moins pour 30% de résultat en plus : ceux qu'on supprime
   // sont exactement les scalps pris CONTRE la tendance H1.
   // RB_H1Trend() (EMA 21/55 en H1) existait déjà — il n'était pas consulté.
   // Pilotable : SET|SCALPTREND|0 pour revenir au comportement d'avant.
   if(SEC_Ov("SCALPTREND", 1) > 0.5)
   {
      int tH1 = RB_H1Trend();
      if(tH1 != 0 && ((isBuy && tH1 < 0) || (!isBuy && tH1 > 0)))
      {
         static datetime lastTrendMsg = 0;
         if(TimeCurrent() - lastTrendMsg > 1800)
         {
            Print("🌊 scalp ", isBuy ? "BUY" : "SELL", " refusé : la tendance H1 va "
                  "dans l'autre sens — on suit le fil, on ne rame pas contre");
            lastTrendMsg = TimeCurrent();
         }
         return;
      }
   }

   double score = CalcScalpScore(isBuy) + PlanBonus(isBuy);   // 📋 penche vers le plan du jour
   if(score < seuilQ) return;   // 🎛️ sélectivité ADAPTATIVE (base pilotable SCOREMIN)

   // ✅ Indicateurs pour ML
   double rsi_val       = 50.0;
   double ema_ratio_val = 1.0;
if(h_ScalpEMAFast != INVALID_HANDLE && h_ScalpEMASlow != INVALID_HANDLE)
{
   double ef[], es[];
   ArraySetAsSeries(ef, true);
   ArraySetAsSeries(es, true);
   if(CopyBuffer(h_ScalpEMAFast, 0, 0, 3, ef) >= 3 &&
      CopyBuffer(h_ScalpEMASlow, 0, 0, 3, es) >= 3 && es[0] != 0)
      ema_ratio_val = ef[0] / es[0];
}
   double atr_val       = 0.0;

   double rsi_buf[], atr_buf[];
   ArraySetAsSeries(rsi_buf, true);
   ArraySetAsSeries(atr_buf, true);

   if(CopyBuffer(h_ScalpRSI, 0, 0, 3, rsi_buf) < 3) return;
   if(CopyBuffer(h_ScalpATR, 0, 0, 3, atr_buf) < 3) return;

   rsi_val = rsi_buf[0];
   atr_val = atr_buf[0];

   // ✅ News score
   string newsSignal = GetNewsSignalEA();
   double news_score = 50.0;
   if(newsSignal == "crucial")  { Print("🔴 NEWS CRUCIAL — pas de scalp"); return; }
   if(newsSignal == "high_vol") news_score = 25.0;
   if(newsSignal == "news_now") news_score = 40.0;
   if(newsSignal == "safe")     news_score = 60.0;

   // ✅ MACD + largeur Bollinger pour le serveur ML
   double macd_val = 0.0, bb_width_val = 0.0;
   double macdBuf[];
   ArraySetAsSeries(macdBuf, true);
   if(CopyBuffer(h_ScalpMACD, 0, 0, 1, macdBuf) > 0) macd_val = macdBuf[0];
   double bbU[], bbL[];
   ArraySetAsSeries(bbU, true);
   ArraySetAsSeries(bbL, true);
   if(CopyBuffer(h_ScalpBB, 1, 0, 1, bbU) > 0 && CopyBuffer(h_ScalpBB, 2, 0, 1, bbL) > 0)
      bb_width_val = bbU[0] - bbL[0];

   // ✅ ML server reel (port 8001) — seuil de confiance regle via MLMinConfidence
   string mlSignal = "NEUTRAL";
   double mlConf   = 0.5;
   bool   mlOk     = GetMLPrediction(_Symbol, rsi_val, ema_ratio_val, atr_val,
                                      macd_val, bb_width_val, news_score,
                                      mlSignal, mlConf);

   Print(StringFormat("🔍 SCALP %s | RSI=%.1f | EMA_R=%.4f | ATR=%.5f | ML=%s (conf=%.2f, srv=%s)",
         isBuy?"BUY":"SELL", rsi_val, ema_ratio_val, atr_val, mlSignal, mlConf, mlOk?"ok":"off"));

   double mlBonus = 0.0;
   if(mlOk)
   {
      if(MLServerBlockOpposite && mlSignal == "SELL" && isBuy)
      {
         Print("🤖 ML bloque SCALP BUY (ML=SELL, conf=", DoubleToString(mlConf,2), ")");
         return;
      }
      if(MLServerBlockOpposite && mlSignal == "BUY" && !isBuy)
      {
         Print("🤖 ML bloque SCALP SELL (ML=BUY, conf=", DoubleToString(mlConf,2), ")");
         return;
      }
      if(MLServerBlockHold && (mlSignal == "HOLD" || mlSignal == "NEUTRAL"))
      {
         Print("🤖 ML HOLD/NEUTRAL — scalp ignoré");
         return;
      }

      bool aligned  = (isBuy && mlSignal == "BUY") || (!isBuy && mlSignal == "SELL");
      bool mlOppose = (mlSignal == "BUY" || mlSignal == "SELL") && !aligned;
      if(aligned)
         mlBonus = MLServerScoreBonusMax * MathMax(0.0, MathMin(1.0, (mlConf - 0.5) * 2.0));
      // 🔧 FIX audit 03/08 : le veto ML était INVERSÉ — il refusait le trade quand
      // le ML était D'ACCORD (faible conf) et laissait passer quand le ML était
      // CONTRE. Corrigé : ML contre + convaincu = MALUS de score (pas un veto
      // aveugle) ; un ML d'accord peu sûr ne bloque plus un setup technique valide.
      else if(mlOppose && mlConf >= MLMinConfidence)
      {
         mlBonus = -MLServerScoreBonusMax * MathMax(0.0, MathMin(1.0, (mlConf - 0.5) * 2.0));
         Print("🤖 ML CONTRE le SCALP (", mlSignal, " conf ", DoubleToString(mlConf,2), ") → malus ", DoubleToString(mlBonus,2));
      }
   }
   score = MathMax(0.0, MathMin(12.0, score + mlBonus));

   // 🤬 Conseil de l'IA intérieure (ajustement, JAMAIS un blocage)
   // 🚦 pré-filtre (13/07) : on ne dérange l'IA que si le setup technique est
   // déjà à portée du seuil (−2 pts) — les bougies plates ne coûtent plus un
   // appel mammouth (même recette que le bot Python, la clé sature moins).
   if(score >= seuilQ - 2.0)
      score = MathMax(0.0, MathMin(12.0, score + GetAIAdvice(isBuy, "SCALP", score, rsi_val, mlSignal, mlConf)));
   if(score < seuilQ) return;   // re-check après conseil (même seuil ADAPTATIF)

   // ✅ Suite logique existante
   double atr[];
   ArraySetAsSeries(atr,true);
   if(CopyBuffer(h_ScalpATR,0,0,3,atr)<3) return;
   double atrVal = atr[0];

   double ask   = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid   = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   // 🎯 08/09 — ON ENTRE À L'EXTRÉMITÉ, PAS AU MILIEU. Si la bougie en cours a
   // déjà fait l'essentiel du chemin dans notre sens, on paie le sommet : le stop
   // est loin, la cible est proche, et le moindre repli nous sort.
   if(Scalp_MaxBougiePct < 100.0)
   {
      MqlRates bc[]; ArraySetAsSeries(bc, true);
      if(CopyRates(_Symbol, ScalpTF, 0, 1, bc) >= 1)
      {
         double amp = bc[0].high - bc[0].low;
         if(amp > 0)
         {
            double parcouru = isBuy ? (ask - bc[0].low) / amp : (bc[0].high - bid) / amp;
            if(parcouru * 100.0 > Scalp_MaxBougiePct)
            {
               Print("🎯 scalp refusé : la bougie a déjà fait ",
                     DoubleToString(parcouru * 100.0, 0), "% du chemin (max ",
                     DoubleToString(Scalp_MaxBougiePct, 0), "%) — on n'achète pas le sommet");
               return;
            }
         }
      }
   }
   double price = isBuy ? ask : bid;
   double sl,tp;

   // 🎯 R:R adaptatif au régime (12/07)
   double slM, tpM;
   AdaptiveRR(SEC_Ov("SLATR", Scalp_SL_ATR), SEC_Ov("TPATR", Scalp_TP_ATR), slM, tpM);
   // 🔇 GARDE SPREAD (25/07) : si le TP visé ne vaut pas 4× le spread, le
   // broker mange le trade avant nous — c'est du bruit, pas un signal.
   if(atrVal * tpM < SEC_Ov("TPSPREAD", 4.0) * (ask - bid))
   { Print("🔇 scalp refusé : TP ", DoubleToString(atrVal*tpM/g_PipSize,1),
           "p < 4× spread — le broker gagnerait, pas nous"); return; }
   if(isBuy)
   {
      sl = price - atrVal * slM;
      tp = price + atrVal * tpM;
   }
   else
   {
      sl = price + atrVal * slM;
      tp = price - atrVal * tpM;
   }

   sl = NormalizeDouble(sl, g_Digits);
   tp = NormalizeDouble(tp, g_Digits);

   double slPips = MathAbs(price - sl) / g_PipSize;
   double lot    = CalcLot(slPips);

   string comment = StringFormat("SCALP|score=%.1f|ML=%s|%s",
                                  score, mlSignal, isBuy?"BUY":"SELL");
   trade.SetExpertMagicNumber(MagicNumber);

   bool result;
   if(isBuy)  result = BuyFix(lot, _Symbol, price, sl, tp, comment);
   else       result = SellFix(lot, _Symbol, price, sl, tp, comment);

   if(result)
      lastScalpFire = TimeCurrent();   // 🧘 08/09 : le temps de repos démarre au TIR RÉUSSI
   if(result)
   {
      g_LastScalpTime = TimeCurrent();
      g_TotalTrades++;
      SignalArrow(isBuy, price, "SCALP");
      g_LastSignalTxt = StringFormat("SCALP %s (score %.1f)", isBuy?"BUY":"SELL", score);
      JournalTrade("SCALP", isBuy, lot, price, sl, tp, score, rsi_val, atrVal, ema_ratio_val, macd_val, mlSignal, mlConf);
      string msg = StringFormat("🎯 SCALP %s | Lot: %.2f | Score: %.1f | ML: %s | SL: %.5f | TP: %.5f",
                                 isBuy?"BUY":"SELL", lot, score, mlSignal, sl, tp);
      SendTelegramMsg(msg);
   }
}

//+------------------------------------------------------------------+
//  OPEN SWING TRADE
//+------------------------------------------------------------------+
void OpenSwingTrade(bool isBuy)
{
   if(!SwingEnabled)   return;
   if(WeekendBlock())  return;                               // 📅 pas d'entrée le week-end
   if(!TradingEnabled) return;
   if(g_DailyLimitHit || g_DDLimitHit) return;
   if(!IsSpreadOK())   return;
   if(!IsMarginOK())   return;
   if(!IsNewsOK())     return;
   // ✅ Anti-spam (09/07) : 1 tentative par bougie MAX — avant, un swing
   // invalide (lot refusé par les règles d'acier, serveurs 4014…) retentait
   // à CHAQUE tick : des centaines de lignes/minute dans le journal.
   static datetime lastSwingBar = 0;
   datetime curBar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(curBar == lastSwingBar) return;
   lastSwingBar = curBar;
   if(CountPositions("SWING") >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
   if(DailyCapReached()) return;
   if(CountClusterAcid(isBuy) >= (int)SEC_Ov("MAXCLUSTER", 6)) { Print("🔗 cluster saturé — swing ignoré"); return; }
   if(CotBlocks(isBuy)) { Print("🐋 Veto COT — swing ", isBuy?"BUY":"SELL", " bloqué"); return; }

   double score = CalcSwingScore(isBuy);
   if(score < Swing_ScoreMin) return;
// ✅ Indicateurs pour ML
   double rsi_val       = 50.0;
   double ema_ratio_val = 1.0;
if(h_SwingEMAFast != INVALID_HANDLE && h_SwingEMASlow != INVALID_HANDLE)
{
   double ef[], es[];
   ArraySetAsSeries(ef, true);
   ArraySetAsSeries(es, true);
   if(CopyBuffer(h_SwingEMAFast, 0, 0, 3, ef) >= 3 &&
      CopyBuffer(h_SwingEMASlow, 0, 0, 3, es) >= 3 && es[0] != 0)
      ema_ratio_val = ef[0] / es[0];
}
   double atr_val       = 0.0;

   double rsi_buf[], atr_buf[];
   ArraySetAsSeries(rsi_buf, true);
   ArraySetAsSeries(atr_buf, true);

   if(CopyBuffer(h_SwingRSI, 0, 0, 3, rsi_buf) < 3) return;
   if(CopyBuffer(h_SwingATR, 0, 0, 3, atr_buf) < 3) return;

   rsi_val = rsi_buf[0];
   atr_val = atr_buf[0];

   // ✅ News score
   string newsSignal = GetNewsSignalEA();
   double news_score = 50.0;
   if(newsSignal == "crucial")  { Print("🔴 NEWS CRUCIAL — pas de swing"); return; }
   if(newsSignal == "high_vol") news_score = 25.0;
   if(newsSignal == "news_now") news_score = 40.0;
   if(newsSignal == "safe")     news_score = 60.0;

   // ✅ MACD pour le serveur ML (pas de Bollinger sur le TF swing)
   double macd_val = 0.0;
   double macdBuf[];
   ArraySetAsSeries(macdBuf, true);
   if(CopyBuffer(h_SwingMACD, 0, 0, 1, macdBuf) > 0) macd_val = macdBuf[0];

   // ✅ ML server reel (port 8001) — seuil de confiance regle via MLMinConfidence
   string mlSignal = "NEUTRAL";
   double mlConf   = 0.5;
   bool   mlOk     = GetMLPrediction(_Symbol, rsi_val, ema_ratio_val, atr_val,
                                      macd_val, 0.0, news_score,
                                      mlSignal, mlConf);

   Print(StringFormat("🔍 SWING %s | RSI=%.1f | EMA_R=%.4f | ATR=%.5f | ML=%s (conf=%.2f, srv=%s)",
         isBuy?"BUY":"SELL", rsi_val, ema_ratio_val, atr_val, mlSignal, mlConf, mlOk?"ok":"off"));

   // ✅ Filtre ML — swing moins strict (HOLD autorisé)
   double mlBonus = 0.0;
   if(mlOk)
   {
      if(MLServerBlockOpposite && mlSignal == "SELL" && isBuy)
      {
         Print("🤖 ML bloque SWING BUY (ML=SELL, conf=", DoubleToString(mlConf,2), ")");
         return;
      }
      if(MLServerBlockOpposite && mlSignal == "BUY" && !isBuy)
      {
         Print("🤖 ML bloque SWING SELL (ML=BUY, conf=", DoubleToString(mlConf,2), ")");
         return;
      }
      // HOLD/NEUTRAL → swing continue quand même

      bool aligned  = (isBuy && mlSignal == "BUY") || (!isBuy && mlSignal == "SELL");
      bool mlOppose = (mlSignal == "BUY" || mlSignal == "SELL") && !aligned;
      if(aligned)
         mlBonus = MLServerScoreBonusMax * MathMax(0.0, MathMin(1.0, (mlConf - 0.5) * 2.0));
      // 🔧 FIX audit 03/08 : idem scalp — veto ML inversé, corrigé en malus.
      else if(mlOppose && mlConf >= MLMinConfidence)
      {
         mlBonus = -MLServerScoreBonusMax * MathMax(0.0, MathMin(1.0, (mlConf - 0.5) * 2.0));
         Print("🤖 ML CONTRE le SWING (", mlSignal, " conf ", DoubleToString(mlConf,2), ") → malus ", DoubleToString(mlBonus,2));
      }
   }
   score = MathMax(0.0, MathMin(12.0, score + mlBonus));

   // 🤬 Conseil de l'IA intérieure (ajustement, JAMAIS un blocage)
   // 🚦 pré-filtre (13/07) : idem scalp — l'IA n'est consultée qu'à portée du seuil
   if(score >= Swing_ScoreMin - 2.0)
      score = MathMax(0.0, MathMin(12.0, score + GetAIAdvice(isBuy, "SWING", score, rsi_val, mlSignal, mlConf)));
   if(score < Swing_ScoreMin) return;   // re-check après conseil

   // ✅ Suite logique existante
   double atr[];
   ArraySetAsSeries(atr,true);
   if(CopyBuffer(h_SwingATR,0,0,3,atr)<3) return;
   double atrVal = atr[0];

   double ask   = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid   = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double price = isBuy ? ask : bid;
   double sl,tp;

   // 🎯 R:R adaptatif au régime (12/07)
   double slM, tpM;
   AdaptiveRR(Swing_SL_ATR, Swing_TP_ATR, slM, tpM);
   if(isBuy)
   {
      sl = price - atrVal * slM;
      tp = price + atrVal * tpM;
   }
   else
   {
      sl = price + atrVal * slM;
      tp = price - atrVal * tpM;
   }

   sl = NormalizeDouble(sl, g_Digits);
   tp = NormalizeDouble(tp, g_Digits);

   double slPips = MathAbs(price - sl) / g_PipSize;
   double lot    = CalcLot(slPips);

   string comment = StringFormat("SWING|score=%.1f|ML=%s|%s",
                                  score, mlSignal, isBuy?"BUY":"SELL");
   trade.SetExpertMagicNumber(MagicNumber);

   bool result;
   if(isBuy)  result = BuyFix(lot, _Symbol, price, sl, tp, comment);
   else       result = SellFix(lot, _Symbol, price, sl, tp, comment);

   if(result)
   {
      g_LastSwingTime = TimeCurrent();
      g_TotalTrades++;
      SignalArrow(isBuy, price, "SWING");
      g_LastSignalTxt = StringFormat("SWING %s (score %.1f)", isBuy?"BUY":"SELL", score);
      JournalTrade("SWING", isBuy, lot, price, sl, tp, score, rsi_val, atrVal, ema_ratio_val, macd_val, mlSignal, mlConf);
      string msg = StringFormat("📈 SWING %s | Lot: %.2f | Score: %.1f | ML: %s | SL: %.5f | TP: %.5f",
                                 isBuy?"BUY":"SELL", lot, score, mlSignal, sl, tp);
      SendTelegramMsg(msg);
   }
}


//+------------------------------------------------------------------+
//  AUTO OVERBID — rapproche du marché les pending orders non remplis.
//  AutoOverbid/OverbidPips étaient déclarés en input mais jamais utilisés
//  nulle part : un pending order ne bougeait jamais tant qu'il n'était pas
//  rempli ou expiré, quelle que soit la valeur de ces deux paramètres.
//+------------------------------------------------------------------+
void OverbidPendingOrders()
{
   if(!AutoOverbid) return;

   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double step   = OverbidPips * g_PipSize;
   // Distance minimum au marché : l'overbid ne colle plus les pendings au prix
   // (avant: 1 pip -> rafales de fills simultanés la nuit du 06/07)
   double minGap = MathMax(1.0, OverbidMinDistPips) * g_PipSize;

   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      if(!ordInfo.SelectByIndex(i)) continue;
      if(ordInfo.Symbol() != _Symbol)     continue;
      if(ordInfo.Magic()  != MagicNumber) continue;

      ulong           ticket = ordInfo.Ticket();
      ENUM_ORDER_TYPE type   = ordInfo.OrderType();
      double          price  = ordInfo.PriceOpen();
      double          sl     = ordInfo.StopLoss();
      double          tp     = ordInfo.TakeProfit();
      double          newPrice = price;

      if(type == ORDER_TYPE_BUY_LIMIT)
      {
         newPrice = MathMin(price + step, bid - minGap);
         if(newPrice <= price) continue;
      }
      else if(type == ORDER_TYPE_SELL_LIMIT)
      {
         newPrice = MathMax(price - step, ask + minGap);
         if(newPrice >= price) continue;
      }
      else if(type == ORDER_TYPE_BUY_STOP)
      {
         newPrice = MathMax(price - step, ask + minGap);
         if(newPrice >= price) continue;
      }
      else if(type == ORDER_TYPE_SELL_STOP)
      {
         newPrice = MathMin(price + step, bid - minGap);
         if(newPrice <= price) continue;
      }
      else continue;

      newPrice = NormalizeDouble(newPrice, g_Digits);
      double delta = newPrice - price;
      double newSL = (sl > 0) ? NormalizeDouble(sl + delta, g_Digits) : 0.0;
      double newTP = (tp > 0) ? NormalizeDouble(tp + delta, g_Digits) : 0.0;

      if(trade.OrderModify(ticket, newPrice, newSL, newTP,
                            ORDER_TIME_SPECIFIED, ordInfo.TimeExpiration()))
         Print("🔼 Surenchère pending #", ticket, " ", price, " → ", newPrice);
   }
}

//+------------------------------------------------------------------+
//  OPEN PENDING ORDERS
//+------------------------------------------------------------------+
void ManagePendingOrders()
{
   if(!PendingEnabled || SEC_Ov("PENDING", 1) < 0.5) return;   // 🎛️ coupable à distance
   if(WeekendBlock()) return;                                  // 📅 pas de pending le week-end
   if(!TradingEnabled) return;
   if(g_DailyLimitHit || g_DDLimitHit) return;

   OverbidPendingOrders();

   if(CountPending() >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;
   if(DailyCapReached()) return;

   static datetime lastPendingBar = 0;
   datetime currentBar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentBar == lastPendingBar) return;
   lastPendingBar = currentBar;

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED)) return;

   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(h_ScalpATR, 0, 0, 3, atr) < 3) return;
   double atrVal = atr[0];

   // ✅ SECURISATION : un pending n'est pose que si la logique est CONFIRMEE
   // (score technique du cote du biais + accord du serveur ML + pas de news
   // critique). Avant : aucun filtre -> rafales nocturnes du 06/07.
   bool wantBuy = (g_Bias == BIAS_BUY);
   if(g_Bias == BIAS_NONE) return;

   double pScore = CalcScalpScore(wantBuy);
   if(pScore < PendingMinScore)
      return;

   string pNews = GetNewsSignalEA();
   if(pNews == "crucial") return;
   double pNewsScore = (pNews == "high_vol") ? 25.0 : (pNews == "news_now") ? 40.0 : (pNews == "safe") ? 60.0 : 50.0;

   if(PendingNeedML)
   {
      double rsiB[], efB[], esB[], mcdB[];
      double rsi_v = 50.0, ema_r = 1.0, macd_v = 0.0;
      ArraySetAsSeries(rsiB, true); ArraySetAsSeries(efB, true);
      ArraySetAsSeries(esB, true);  ArraySetAsSeries(mcdB, true);
      if(CopyBuffer(h_ScalpRSI, 0, 0, 1, rsiB) > 0) rsi_v = rsiB[0];
      if(CopyBuffer(h_ScalpEMAFast, 0, 0, 1, efB) > 0 &&
         CopyBuffer(h_ScalpEMASlow, 0, 0, 1, esB) > 0 && esB[0] != 0) ema_r = efB[0] / esB[0];
      if(CopyBuffer(h_ScalpMACD, 0, 0, 1, mcdB) > 0) macd_v = mcdB[0];

      string mlPred = "NEUTRAL";
      double mlConf = 0.5;
      bool   mlOk   = GetMLPrediction(_Symbol, rsi_v, ema_r, atrVal, macd_v, 0.0, pNewsScore, mlPred, mlConf);
      if(mlOk)
      {
         bool aligned = (wantBuy && mlPred == "BUY") || (!wantBuy && mlPred == "SELL");
         if(!aligned || mlConf < MLMinConfidence)
         {
            Print("⏸️ Pending refuse: ML=", mlPred, " conf=", DoubleToString(mlConf, 2),
                  " (biais ", wantBuy ? "BUY" : "SELL", ", score ", DoubleToString(pScore, 1), ")");
            return;
         }
      }
   }

   // SL plancher : sizing et stops jamais calcules sur un ATR nocturne
   // microscopique (le ratio TP/SL d'origine est conserve)
   double slDist = MathMax(atrVal * SEC_Ov("SLATR", Scalp_SL_ATR), Pending_MinSLPips * g_PipSize);
   double tpDist = slDist * (SEC_Ov("TPATR", Scalp_TP_ATR) / SEC_Ov("SLATR", Scalp_SL_ATR));

   datetime expiry = TimeCurrent() + Pending_Expiry_H * 3600;

   // Buy Limit
   if(g_Bias == BIAS_BUY && CountPendingSide(true) < MaxPendingPerSide && !PendingCooldownActive(true))
   {
      double blPrice = NormalizeDouble(bid - BuyLimit_Offset * g_PipSize, g_Digits);
      double blSL    = NormalizeDouble(blPrice - slDist, g_Digits);
      double blTP    = NormalizeDouble(blPrice + tpDist, g_Digits);
      double slPips  = slDist / g_PipSize;
      double lot     = CalcLot(slPips);

      trade.SetExpertMagicNumber(MagicNumber);
      if(trade.BuyLimit(lot, blPrice, _Symbol, blSL, blTP,
                        ORDER_TIME_SPECIFIED, expiry, "PENDING|BuyLimit"))
         g_LastPendingTime = TimeCurrent();
   }

   // Sell Limit
   if(g_Bias == BIAS_SELL && CountPendingSide(false) < MaxPendingPerSide && !PendingCooldownActive(false))
   {
      double slPrice = NormalizeDouble(ask + SellLimit_Offset * g_PipSize, g_Digits);
      double slSL    = NormalizeDouble(slPrice + slDist, g_Digits);
      double slTP    = NormalizeDouble(slPrice - tpDist, g_Digits);
      double slPips  = slDist / g_PipSize;
      double lot     = CalcLot(slPips);

      trade.SetExpertMagicNumber(MagicNumber);
      if(trade.SellLimit(lot, slPrice, _Symbol, slSL, slTP,
                         ORDER_TIME_SPECIFIED, expiry, "PENDING|SellLimit"))
         g_LastPendingTime = TimeCurrent();
   }

   // Buy Stop
   if(g_Regime == REG_TREND && g_Bias == BIAS_BUY && CountPendingSide(true) < MaxPendingPerSide && !PendingCooldownActive(true))
   {
      double bsPrice = NormalizeDouble(ask + BuyStop_Offset * g_PipSize, g_Digits);
      double bsSL    = NormalizeDouble(bsPrice - slDist, g_Digits);
      double bsTP    = NormalizeDouble(bsPrice + tpDist, g_Digits);
      double slPips  = slDist / g_PipSize;
      double lot     = CalcLot(slPips);

      trade.SetExpertMagicNumber(MagicNumber);
      trade.BuyStop(lot, bsPrice, _Symbol, bsSL, bsTP,
                    ORDER_TIME_SPECIFIED, expiry, "PENDING|BuyStop");
   }

   // Sell Stop
   if(g_Regime == REG_TREND && g_Bias == BIAS_SELL && CountPendingSide(false) < MaxPendingPerSide && !PendingCooldownActive(false))
   {
      double ssPrice = NormalizeDouble(bid - SellStop_Offset * g_PipSize, g_Digits);
      double ssSL    = NormalizeDouble(ssPrice + slDist, g_Digits);
      double ssTP    = NormalizeDouble(ssPrice - tpDist, g_Digits);
      double slPips  = slDist / g_PipSize;
      double lot     = CalcLot(slPips);

      trade.SetExpertMagicNumber(MagicNumber);
      trade.SellStop(lot, ssPrice, _Symbol, ssSL, ssTP,
                     ORDER_TIME_SPECIFIED, expiry, "PENDING|SellStop");
   }
}


//+------------------------------------------------------------------+
//  TELEGRAM SEND
//+------------------------------------------------------------------+
void SendTelegramMsg(string msg)
{
   if(!SendTelegram || TelegramToken=="" || TelegramChatID=="") return;
   string url = URLClean(StringFormat(
      "https://api.telegram.org/bot%s/sendMessage?chat_id=%s&text=%s",
      TelegramToken, TelegramChatID,
      msg));
   char   data[];
   char   result[];
   string headers;
   int    timeout = 3000;
   WebRequest("GET", url, "", "", timeout, data, 0, result, headers);
}

//+------------------------------------------------------------------+
//  HEDGE ENGINE
//+------------------------------------------------------------------+
void ManageHedge()
{
   if(!HedgeEnabled)   return;
   if(!TradingEnabled) return;
   // 🛡️ 16/09 — INTERRUPTEUR À DISTANCE : SET|HEDGE|0 coupe l'OUVERTURE de
   // nouveaux hedges sur tous les graphiques, sans toucher à leurs réglages.
   // Mesuré du 14 au 16/09, 68 hedges : 70,6 % gagnants, mais X € en
   // moyenne contre X € quand ils perdent (pas de stop) — total X €,
   // négatif sur CL-OIL, XAUUSD+, NAS100, plat sur BTCUSD. Le 16/09 : 4 hedges
   // SELL posés contre 2 BUY d'or qui ont fini à X € chacun, et qui ont
   // perdu X € chacun pendant la hausse.
   // La FERMETURE (CloseHedgeIfProfit) n'est PAS coupée : un hedge déjà ouvert
   // continue de sortir en gain comme avant.
   if(SEC_Ov("HEDGE", 1) < 0.5) return;

   for(int i=0; i<PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol()  != _Symbol)   continue;
      if(posInfo.Magic()   != MagicNumber) continue;

      // Ne pas hedger un hedge
      if(StringFind(posInfo.Comment(),"HEDGE") >= 0) continue;

      double openPrice  = posInfo.PriceOpen();
      double currentBid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double currentAsk = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      bool   isLong     = (posInfo.PositionType() == POSITION_TYPE_BUY);

      double lossPips;
      if(isLong)  lossPips = (openPrice - currentBid) / g_PipSize;
      else        lossPips = (currentAsk - openPrice) / g_PipSize;

      // Déclencher hedge si perte > seuil
      if(lossPips < HedgeTriggerPips) continue;

      // Vérifier si hedge déjà ouvert pour ce ticket
      ulong ticket = posInfo.Ticket();
      bool  alreadyHedged = false;
      for(int h=0; h<ArraySize(g_HedgeTickets); h++)
         if(g_HedgeTickets[h] == ticket) { alreadyHedged = true; break; }
      if(alreadyHedged) continue;

      // Ouvrir position inverse
      double hedgeLot = NormalizeDouble(posInfo.Volume() * HedgeRatio, 2);
      hedgeLot = MathMax(g_MinLot, MathMin(g_MaxLot, hedgeLot));

      string hedgeComment = StringFormat("HEDGE|orig=%llu", ticket);
      bool   hedgeResult  = false;

      trade.SetExpertMagicNumber(MagicNumber);
      if(isLong)
         hedgeResult = SellFix(hedgeLot, _Symbol, currentBid, 0, 0, hedgeComment);
      else
         hedgeResult = BuyFix(hedgeLot, _Symbol, currentAsk, 0, 0, hedgeComment);

      if(hedgeResult)
      {
         int sz = ArraySize(g_HedgeTickets);
         ArrayResize(g_HedgeTickets, sz+1);
         g_HedgeTickets[sz] = ticket;
         SendTelegramMsg(StringFormat(
            "🛡 HEDGE ouvert | Perte: %.1f pips | Lot: %.2f",
            lossPips, hedgeLot));
      }
   }
}

//+------------------------------------------------------------------+
//  CLOSE HEDGE WHEN PROFITABLE
//+------------------------------------------------------------------+
void CloseHedgeIfProfit()
{
   if(!HedgeEnabled) return;

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol)     continue;
      if(posInfo.Magic()  != MagicNumber) continue;
      if(StringFind(posInfo.Comment(),"HEDGE") < 0) continue;

      double openPrice  = posInfo.PriceOpen();
      double currentBid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double currentAsk = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      bool   isLong     = (posInfo.PositionType() == POSITION_TYPE_BUY);

      double profitPips;
      if(isLong)  profitPips = (currentBid - openPrice) / g_PipSize;
      else        profitPips = (openPrice - currentAsk) / g_PipSize;

      if(profitPips >= HedgeClosePips)
      {
         ulong ticket = posInfo.Ticket();
         ClosePos(ticket);
         SendTelegramMsg(StringFormat(
            "✅ HEDGE fermé en profit | +%.1f pips", profitPips));
      }
   }
}

//+------------------------------------------------------------------+
//  RESTORE HEDGE STATE — reconstruit g_HedgeTickets depuis les positions
//  déjà ouvertes au démarrage. g_HedgeTickets ne vit qu'en mémoire et est
//  perdu à chaque redémarrage EA/terminal ; sans ça, ManageHedge() ne
//  détecte plus les hedges déjà ouverts avant le redémarrage et peut en
//  ouvrir un doublon sur la même position perdante.
//+------------------------------------------------------------------+
void RestoreHedgeState()
{
   ArrayResize(g_HedgeTickets, 0);
   for(int i=0; i<PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol)     continue;
      if(posInfo.Magic()  != MagicNumber) continue;

      string comment = posInfo.Comment();
      int p = StringFind(comment, "HEDGE|orig=");
      if(p < 0) continue;

      string tail = StringSubstr(comment, p + StringLen("HEDGE|orig="));
      ulong origTicket = (ulong)StringToInteger(tail);
      if(origTicket == 0) continue;

      int sz = ArraySize(g_HedgeTickets);
      ArrayResize(g_HedgeTickets, sz+1);
      g_HedgeTickets[sz] = origTicket;
   }
   if(ArraySize(g_HedgeTickets) > 0)
      Print("🔁 Hedges restaurés après redémarrage : ", ArraySize(g_HedgeTickets));
}

//+------------------------------------------------------------------+
//  BREAKEVEN
//+------------------------------------------------------------------+
void ManageBreakEven()
{
   if(!UseBreakEven) return;

   // 🔒 ECHELLE DE VERROUILLAGE GARANTIE (patron 24/07 : «…
   // …»). Indépendante des presets (qui pouvaient avoir un
   // BEPIPS aberrant). Deux paliers DURS, en pips REELS (g_PipSize par symbole) :
   //   +LockBEPips (50)  -> SL a +LockBEPart x 50 pips : un gagnant de 50
   //                        pips ne redevient jamais perdant ET ne ressort
   //                        plus a zero. 14/09 : ce palier verrouillait 0,0 —
   //                        le patron voyait X € et encaissait +0,06.
   //                        Banc : verrouiller la moitie bat verrouiller rien
   //                        sur les QUATRE seuils testes (+78/+61/+91/+69 R
   //                        contre +30/+32/-18/-2).
   //   +LockProfitAt (100) -> SL bloque a +LockProfitGive (50) : on BANQUE.
   // Le SL ne recule jamais ; le trail (plus loin) prend le relais au-dessus.
   double beAt   = SEC_Ov("LOCKBE",  LockBEPips);
   double lockAt = SEC_Ov("LOCKAT",  LockProfitAt);
   double give   = SEC_Ov("LOCKGIVE",LockProfitGive);
   double bePart = MathMax(0.0, MathMin(0.9, SEC_Ov("LOCKBEPART", LockBEPart)));

   for(int i=0; i<PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol)     continue;
      if(posInfo.Magic()  != MagicNumber) continue;

      double openPrice  = posInfo.PriceOpen();
      double currentSL  = posInfo.StopLoss();
      double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      bool   isLong = (posInfo.PositionType() == POSITION_TYPE_BUY);
      ulong  ticket = posInfo.Ticket();

      double profitPips = isLong ? (bid - openPrice) / g_PipSize
                                 : (openPrice - ask) / g_PipSize;

      double lockPips;                          // pips AU-DESSUS de l'entree a verrouiller
      if(profitPips >= lockAt)      lockPips = give;   // palier 2 : on banque +give
      else if(profitPips >= beAt)   lockPips = beAt * bePart;  // palier 1 : on verrouille pour de vrai
      else                          continue;          // pas encore assez de profit

      double newSL = NormalizeDouble(openPrice + (isLong ? 1 : -1) * lockPips * g_PipSize, g_Digits);
      // ne JAMAIS reculer le SL (que vers plus de securite)
      if(isLong  && currentSL > 0 && newSL <= currentSL + g_Point) continue;
      if(!isLong && currentSL > 0 && newSL >= currentSL - g_Point) continue;

      if(trade.PositionModify(ticket, newSL, posInfo.TakeProfit()))
      {
         double secured = isLong ? (newSL-openPrice)/g_PipSize : (openPrice-newSL)/g_PipSize;
         SendTelegramMsg(StringFormat("🔒 %s #%llu : +%.0f pips sécurisés (profit +%.0f)",
            profitPips>=lockAt ? "LOCK PROFIT" : "BE", ticket, secured, profitPips));
      }
   }
}

//+------------------------------------------------------------------+
//  ECHELLE DE SORTIE (patron 21/07) : partial par palier + cloture/reprise
//  Valeurs par SYMBOLE via le preset .set. Etat des paliers en GlobalVariable
//  (survit aux redemarrages, propre par ticket).
//+------------------------------------------------------------------+
void ManageLadder()
{
   if(!LadderEnabled) return;
   double partP = SEC_Ov("LADPART",    LadderPartialPips);
   double reenP = SEC_Ov("LADREENTRY", LadderReentryPips);
   if(partP <= 0.0 || reenP <= 0.0) return;

   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol)     continue;
      if(posInfo.Magic()  != MagicNumber) continue;

      bool   isLong = (posInfo.PositionType() == POSITION_TYPE_BUY);
      double open   = posInfo.PriceOpen();
      double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double vol    = posInfo.Volume();
      ulong  ticket = posInfo.Ticket();
      double profitPips = isLong ? (bid - open) / g_PipSize : (open - ask) / g_PipSize;
      if(profitPips <= 0.0) continue;

      string gv = "LAD_" + (string)ticket;

      // ---- REENTRY : cloture totale + reprise directe meme sens ----
      if(profitPips >= reenP)
      {
         double price = isLong ? bid : ask;
         if(ClosePos(ticket))
         {
            if(GlobalVariableCheck(gv)) GlobalVariableDel(gv);
            double dist = partP * g_PipSize;                 // SL = 1 palier
            double sl   = isLong ? price - dist : price + dist;
            double tp   = isLong ? price + reenP * g_PipSize : price - reenP * g_PipSize;
            if(isLong) BuyFix(vol, _Symbol, price, sl, tp, "ACID_ladder_reopen");
            else       SellFix(vol, _Symbol, price, sl, tp, "ACID_ladder_reopen");
         }
         continue;
      }

      // ---- PALIER : TP partiel tous les partP pips ----
      int rung     = (int)MathFloor(profitPips / partP);
      int prevRung = GlobalVariableCheck(gv) ? (int)GlobalVariableGet(gv) : 0;
      if(rung > prevRung)
      {
         double part = NormalizeDouble(vol * LadderPartialFrac, 2);
         double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         if(part >= vmin && (vol - part) >= vmin - 1e-9)
         {
            if(ClosePosPartial(ticket, part))
               GlobalVariableSet(gv, rung);
         }
         else GlobalVariableSet(gv, rung);   // lot trop petit : on marque le palier
      }
   }
}

//+------------------------------------------------------------------+
//  TRAILING STOP
//+------------------------------------------------------------------+
void ManageTrailing()
{
   if(!UseTrailing) return;

   for(int i=0; i<PositionsTotal(); i++)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol)     continue;
      if(posInfo.Magic()  != MagicNumber) continue;

      double openPrice  = posInfo.PriceOpen();
      double currentSL  = posInfo.StopLoss();
      double currentTP  = posInfo.TakeProfit();
      double currentBid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double currentAsk = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      bool   isLong     = (posInfo.PositionType() == POSITION_TYPE_BUY);
      ulong  ticket     = posInfo.Ticket();

      double profitPips;
      double price;
      if(isLong) { profitPips = (currentBid - openPrice) / g_PipSize; price = currentBid; }
      else       { profitPips = (openPrice - currentAsk) / g_PipSize; price = currentAsk; }

      if(profitPips < SEC_Ov("TRAILSTART", TrailStartPips)) continue;   // 🎛️ pilotable

      // 🔧 FIX audit 03/08 : trail indexé sur l'ATR au lieu de 16 pips absolus
      // (0.06×ATR sur BTC → runners étranglés, FlowRider et l'échelle de
      // verrouillage rendus inertes). En plein flux (SuperTrend aligné + ADX≥23)
      // on ÉLARGIT le pas (~3×ATR = la distance du rail) pour laisser courir ;
      // sinon pas normal (≥ TrailStepPips ET ≥ 1.2×ATR). Le SL ne recule jamais.
      double _trAtr = 0; double _trA[1];
      if(CopyBuffer(h_ScalpATR, 0, 0, 1, _trA) > 0) _trAtr = _trA[0];
      double _trRail = 0; int _trDir = BrainSuperTrend(_trRail);
      bool   _inFlux = (BrainADX() >= 23 && ((isLong && _trDir > 0) || (!isLong && _trDir < 0)));
      double _trStep = MathMax(SEC_Ov("TRAILSTEP", TrailStepPips) * g_PipSize, 1.2 * _trAtr);
      if(_inFlux) _trStep = MathMax(_trStep, 3.0 * _trAtr);

      double newSL;
      if(isLong)
      {
         newSL = NormalizeDouble(price - _trStep, g_Digits);
         if(newSL <= currentSL) continue;
      }
      else
      {
         newSL = NormalizeDouble(price + _trStep, g_Digits);
         if(currentSL > 0 && newSL >= currentSL) continue;
      }

      trade.PositionModify(ticket, newSL, currentTP);
   }
}

//+------------------------------------------------------------------+
//  CLOSE SWING TROP VIEILLES
//+------------------------------------------------------------------+
void ManageSwingExpiry()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol)     continue;
      if(posInfo.Magic()  != MagicNumber) continue;
      if(StringFind(posInfo.Comment(),"SWING") < 0) continue;

      datetime openTime = posInfo.Time();
      int daysOpen = (int)((TimeCurrent() - openTime) / 86400);

      if(daysOpen >= Swing_MaxDays)
      {
         ulong ticket = posInfo.Ticket();
         double profit = posInfo.Profit();
         ClosePos(ticket);
         SendTelegramMsg(StringFormat(
            "⏰ SWING expiré après %d jours | P&L: %.2f", daysOpen, profit));
      }
   }
}

//+------------------------------------------------------------------+
//  CHECK TRADE CLOSED — mise à jour stats ML
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//  ✋ REPRISE APRES COUPE MANUELLE (patron 27/07)
//  Si le PATRON ferme a la main une position de CET EA alors qu'elle etait
//  ouverte sur une forte conviction, on la REPREND — mais proprement :
//    • TP = le MEME niveau vise (une cible reste une cible)
//    • SL = RECALCULE sur l'ATR actuel depuis le nouveau prix (patron :
//      «…» — le marche a bouge depuis)
//  MT5 distingue nativement la cause : DEAL_REASON_CLIENT = ta main,
//  DEAL_REASON_EXPERT = l'EA (donc un CLOSEALL de L'OEIL ne se reprend
//  JAMAIS). Garde-fous : score actuel toujours >= a la conviction d'origine,
//  plafond/jour, pas de doublon, et toutes les regles d'acier via les gates.
//+------------------------------------------------------------------+
void CheckManualClose()
{
   if(!RepriseEnabled) return;
   static datetime lastScan = 0;
   static ulong    lastDeal = 0;
   static int      reprisesJour = 0;
   static int      jourCourant = -1;
   MqlDateTime dtj; TimeToStruct(TimeCurrent(), dtj);
   if(dtj.day != jourCourant) { jourCourant = dtj.day; reprisesJour = 0; }
   if(TimeCurrent() - lastScan < 20) return;         // scan toutes les 20 s
   lastScan = TimeCurrent();
   if(reprisesJour >= RepriseMaxParJour) return;
   if(!HistorySelect(TimeCurrent() - 900, TimeCurrent() + 60)) return;

   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong dt = HistoryDealGetTicket(i);
      if(dt == 0 || dt <= lastDeal) continue;
      if(HistoryDealGetString(dt, DEAL_SYMBOL) != _Symbol)                continue;
      if(HistoryDealGetInteger(dt, DEAL_MAGIC)  != (long)MagicNumber)     continue;
      if(HistoryDealGetInteger(dt, DEAL_ENTRY)  != DEAL_ENTRY_OUT)        continue;
      long reason = HistoryDealGetInteger(dt, DEAL_REASON);
      if(reason != DEAL_REASON_CLIENT && reason != DEAL_REASON_MOBILE
         && reason != DEAL_REASON_WEB)                                    continue;  // pas une coupe manuelle
      lastDeal = dt;

      // ---- retrouver l'entree d'origine (sens, TP vise, conviction) ----
      long posid = HistoryDealGetInteger(dt, DEAL_POSITION_ID);
      double tpVise = 0; bool isBuy = false; double score0 = 0; bool trouve = false;
      for(int j = 0; j < HistoryDealsTotal(); j++)
      {
         ulong d0 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(d0, DEAL_POSITION_ID) != posid)  continue;
         if(HistoryDealGetInteger(d0, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
         isBuy  = (HistoryDealGetInteger(d0, DEAL_TYPE) == DEAL_TYPE_BUY);
         string cm = HistoryDealGetString(d0, DEAL_COMMENT);
         int ps = StringFind(cm, "score=");
         if(ps >= 0) score0 = StringToDouble(StringSubstr(cm, ps + 6));
         trouve = true;
         break;
      }
      if(!trouve) continue;
      // le TP visé : on le relit sur la position d'origine si encore connu
      if(PositionSelectByTicket(posid)) tpVise = PositionGetDouble(POSITION_TP);
      if(score0 < RepriseMinScore)
      { Print("✋ coupe manuelle ", _Symbol, " — conviction d'origine ", DoubleToString(score0,1),
              " < ", DoubleToString(RepriseMinScore,1), ", je respecte ta décision"); continue; }

      // ---- la conviction est-elle TOUJOURS la ? ----
      double scoreNow = CalcScalpScore(isBuy);
      if(scoreNow < score0)
      { Print("✋ coupe manuelle ", _Symbol, " — je n'y crois plus autant (", DoubleToString(scoreNow,1),
              " < ", DoubleToString(score0,1), ") : pas de reprise"); continue; }

      // ---- garde-fous d'ouverture (memes regles d'acier que partout) ----
      if(!TradingEnabled || g_DailyLimitHit || g_DDLimitHit) continue;
      if(WeekendBlock() || !IsSpreadOK() || !IsMarginOK() || !IsNewsOK() || !IsSessionOK()) continue;
      if(CountPositions() >= (int)SEC_Ov("MAXPOS", MaxPositions)) continue;
      if(DailyCapReached()) continue;
      if(CotBlocks(isBuy)) continue;
      bool encore = false;                     // deja de retour dans ce sens ?
      for(int k = 0; k < PositionsTotal(); k++)
         if(posInfo.SelectByIndex(k) && posInfo.Symbol() == _Symbol
            && posInfo.Magic() == MagicNumber
            && ((posInfo.PositionType() == POSITION_TYPE_BUY) == isBuy)) { encore = true; break; }
      if(encore) continue;

      // ---- SL RECALCULE (frais), TP = meme cible ----
      double atrB[1];
      if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrB) < 1 || atrB[0] <= 0) continue;
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double px  = isBuy ? ask : bid;
      double sl  = isBuy ? px - SEC_Ov("SLATR", Scalp_SL_ATR) * atrB[0]
                         : px + SEC_Ov("SLATR", Scalp_SL_ATR) * atrB[0];
      double tp  = tpVise;
      bool tpOk = (tp > 0) && (isBuy ? (tp > px + 10 * g_Point) : (tp < px - 10 * g_Point));
      if(!tpOk)   // cible deja atteinte/derriere -> on reprend une cible normale
         tp = isBuy ? px + SEC_Ov("TPATR", Scalp_TP_ATR) * atrB[0]
                    : px - SEC_Ov("TPATR", Scalp_TP_ATR) * atrB[0];
      sl = NormalizeDouble(sl, g_Digits); tp = NormalizeDouble(tp, g_Digits);
      double lot = CalcLot(MathAbs(px - sl) / g_PipSize);
      trade.SetExpertMagicNumber(MagicNumber);
      bool ok = isBuy ? BuyFix(lot, _Symbol, px, sl, tp, "REPRISE")
                      : SellFix(lot, _Symbol, px, sl, tp, "REPRISE");
      if(ok)
      {
         reprisesJour++;
         g_TotalTrades++;
         SignalArrow(isBuy, px, "REPRISE");
         g_LastSignalTxt = StringFormat("REPRISE %s (conviction %.1f)", isBuy ? "BUY" : "SELL", scoreNow);
         SendTelegramMsg(StringFormat("✋ REPRISE %s %s — tu l'as coupé à la main mais j'y crois toujours "
            "(%.1f/12 ≥ %.1f) | TP %s (même cible) | SL %s (recalculé sur l'ATR) | %d/%d aujourd'hui",
            isBuy ? "BUY" : "SELL", _Symbol, scoreNow, score0,
            DoubleToString(tp, g_Digits), DoubleToString(sl, g_Digits), reprisesJour, RepriseMaxParJour));
      }
      break;   // une reprise par scan
   }
}

void CheckTradeClosed()
{
   // Fenêtre glissante de 30 jours plutôt que g_DayStart (remis à zéro
   // chaque jour) : avec un reset quotidien, il fallait 10 trades LE JOUR
   // MÊME pour que GetMLBonus() s'active (g_MLCount>=10) — irréaliste pour
   // un scalp+swing prudent, ce qui rendait le bonus ML adaptatif quasi
   // mort en pratique. Une fenêtre glissante laisse winrate/RR se
   // construire sur plusieurs jours au lieu de repartir de zéro à minuit.
   datetime statsWindowStart = TimeCurrent() - 30*24*3600;
   HistorySelect(statsWindowStart, TimeCurrent());
   int deals = HistoryDealsTotal();

   int    wins      = 0;
   int    losses    = 0;
   double sumRR     = 0.0;
   int    countRR   = 0;
   double sumProfit = 0.0;

   for(int i=0; i<deals; i++)
   {
      ulong dTicket = HistoryDealGetTicket(i);
      if(dTicket == 0) continue;

      long magic = HistoryDealGetInteger(dTicket, DEAL_MAGIC);
      if(magic != (long)MagicNumber) continue;

      long entry = HistoryDealGetInteger(dTicket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT) continue;

      double profit = HistoryDealGetDouble(dTicket, DEAL_PROFIT);
      double swap   = HistoryDealGetDouble(dTicket, DEAL_SWAP);
      double comm   = HistoryDealGetDouble(dTicket, DEAL_COMMISSION);
      double net    = profit + swap + comm;

      if(net > 0) wins++;
      else        losses++;

      sumProfit += net;

      // RR approximé : profit / (balance * riskPct / 100)
      double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
      double riskPct  = (RiskLevel==RISK_SAFE) ? RiskPctSafe :
                        (RiskLevel==RISK_AGGRESSIVE) ? RiskPctAggressive : RiskPctNormal;
      double riskMoney= balance * riskPct / 100.0;
      if(riskMoney > 0)
      {
         sumRR += MathAbs(net) / riskMoney;
         countRR++;
      }
   }

   // Recalculé à chaque appel (jamais accumulé) : l'ancien code faisait
   // g_TotalProfit += net DANS la boucle appelée à chaque tick, donc
   // resommait les mêmes deals encore et encore — un compteur qui n'aurait
   // jamais rien voulu dire s'il avait fini par être affiché quelque part.
   g_TotalProfit = sumProfit;

   int total = wins + losses;
   if(total > 0)
   {
      g_WinTrades  = wins;
      g_LoseTrades = losses;
      g_WinRate    = (double)wins / total * 100.0;
      if(countRR > 0) g_AvgRR = sumRR / countRR;
      g_MLCount    = total;
   }
}

//+------------------------------------------------------------------+
//  👁️ ACID VISION (patron 24/07) — SMC INTEGRE dans l'EA : Order Blocks
//  + Fair Value Gaps + lignes cles, dessines par le bot lui-meme. Le
//  patron peut donc SUPPRIMER 4 indicateurs Market (Order Block Finder,
//  Fair Value Gaps, Important Lines, S/R Finder) : un de moins a charger
//  par chart. Techniques PUBLIQUES, zero licence. 1 redraw / bougie.
//+------------------------------------------------------------------+
// 🔖 (patron 03/08) Étiquette placée au BORD DROIT du chart (dans la marge vide),
// au lieu de coller au prix courant → fini les libellés qui barrent les bougies.
// Le décalage par famille est conservé (escalier : normal 2, SL 7, TP 12) pour
// éviter que les libellés proches se chevauchent. Repli sur l'ancien décalage si
// aucune marge droite n'est visible (chart collé au bord).
datetime _LabelTime(int shift, ENUM_ANCHOR_POINT &anchor)
{
   // 📍 13/09 — LA MÉTHODE D'ACID VISION, portée ici à la demande du patron.
   //
   // L'ANCIENNE (pixels, 04/08) épinglait l'étiquette au bord droit avec
   // ChartXYToTimePrice et ANCHOR_RIGHT_LOWER : le texte partait donc vers la
   // GAUCHE, par-dessus les bougies, et les 17 niveaux de la vision (PDH, PDL,
   // PDC, PIV, R1-R3, S1-S3, Fib 0 à 6) s'entassaient dans la même colonne.
   //
   // ACID Vision, lui, fait ceci — et c'est pour ça qu'il est lisible partout :
   //     ObjectCreate(..., t0 + PeriodSeconds(_Period)*2, price)
   //     OBJPROP_ANCHOR = ANCHOR_LEFT
   // L'étiquette va DANS LA MARGE VIDE à droite de la dernière bougie, le texte
   // part vers la DROITE, et la distance est comptée EN BOUGIES DU GRAPHIQUE
   // COURANT : deux bougies, que le chart soit en M1 ou en H4.
   //
   // On conserve l'escalier par famille (normal 2, SL 7, TP 12) mais converti
   // en bougies, pour que deux familles voisines ne se superposent pas.
   anchor = ANCHOR_LEFT;                    // le texte part vers la DROITE, dans le vide
   // 🪜 14/09 (patron) : «…
   // …».
   // Chaque famille a donc son propre retrait, en BOUGIES du graphique courant.
   int bougies = 2;
   if(shift >= 30)      bougies = 14;       // TP des positions
   else if(shift >= 25) bougies = 12;       // SL des positions
   else if(shift >= 20) bougies = 10;       // entrées / ordres en attente
   else if(shift >= 16) bougies =  8;       // Fibonacci
   else if(shift >= 12) bougies =  6;       // hauts/bas H1
   else if(shift >=  7) bougies =  4;       // lignes du jour (PDH/PDC/PDL)
   datetime t0 = iTime(_Symbol, _Period, 0);
   if(t0 <= 0) t0 = TimeCurrent();
   return t0 + (datetime)(PeriodSeconds(_Period) * bougies);
}

// 📍 Recolle TOUTES les étiquettes ACID au bord droit à CHAQUE tick — exactement
// comme le fait l'indicateur maison du patron (lui se replace en continu, c'est
// pour ça qu'il est toujours bien placé). L'escalier de chaque étiquette est
// mémorisé dans son ZORDER à la création.
void RepositionLabels()
{
   for(int i = ObjectsTotal(0, 0, OBJ_TEXT) - 1; i >= 0; i--)
   {
      string nm = ObjectName(0, i, 0, OBJ_TEXT);
      if(StringFind(nm, "ACID_VIS_") != 0 && StringFind(nm, "ACID_OBJ_") != 0) continue;
      if(StringSubstr(nm, StringLen(nm) - 2) != "_t") continue;    // seulement les étiquettes
      int shift = (int)ObjectGetInteger(0, nm, OBJPROP_ZORDER);    // escalier mémorisé (2/7/12)
      ENUM_ANCHOR_POINT anc;
      datetime t = _LabelTime(shift, anc);
      double   p = ObjectGetDouble(0, nm, OBJPROP_PRICE);
      ObjectMove(0, nm, 0, t, p);
      ObjectSetInteger(0, nm, OBJPROP_ANCHOR, anc);
   }
}

void VBox(string id, datetime t1, double p1, datetime t2, double p2, color clr, string label)
{
   string nm = "ACID_VIS_" + id;
   if(ObjectCreate(0, nm, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
   {
      ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, nm, OBJPROP_FILL, true);
      ObjectSetInteger(0, nm, OBJPROP_BACK, true);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   }
   if(label != "")
   {
      string tx = nm + "_t";
      if(ObjectCreate(0, tx, OBJ_TEXT, 0, t1, p2))
      {
         ObjectSetString(0, tx, OBJPROP_TEXT, label);
         ObjectSetInteger(0, tx, OBJPROP_COLOR, clr);
         ObjectSetInteger(0, tx, OBJPROP_FONTSIZE, 11);
         ObjectSetInteger(0, tx, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0, tx, OBJPROP_SELECTABLE, false);
      }
   }
}
// 📏 14/09 — LE FILTRE DE DISTANCE, copié sur ACID Vision.
// Vision ne trace que 5 ronds CENTRÉS sur le prix (for k=-2..2). L'EA traçait
// R3/S3/PDH/PDL sans condition : hors écran, MT5 plaque leur étiquette contre
// le bord du graphique, et c'est là que tout s'entassait. On ne dessine plus
// ce qui est trop loin pour servir.
bool _ProcheDuPrix(double niveau)
{
   if(Vis_MaxDistATR <= 0) return true;              // filtre désactivé
   double px = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(px <= 0 || niveau <= 0) return true;
   double atrb[]; ArraySetAsSeries(atrb, true);
   double a = (h_ScalpATR != INVALID_HANDLE && CopyBuffer(h_ScalpATR,0,0,1,atrb) > 0) ? atrb[0] : 0;
   if(a <= 0) return true;                           // pas d'ATR : on ne filtre pas
   return MathAbs(niveau - px) <= Vis_MaxDistATR * a;
}

void VLine(string id, double price, color clr, int style, string label, int font=11, int fam=2)
{
   // trop loin du prix = inutile, et ça salit le bord du graphique
   if(!_ProcheDuPrix(price)) { ObjectDelete(0, "ACID_VIS_" + id);
                               ObjectDelete(0, "ACID_VIS_" + id + "_t"); return; }
   string nm = "ACID_VIS_" + id;
   datetime t0 = iTime(_Symbol, PERIOD_M1, 0);
   if(ObjectCreate(0, nm, OBJ_TREND, 0, t0, price, t0 + PeriodSeconds(PERIOD_M1)*10, price))
   {
      ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, nm, OBJPROP_STYLE, style);
      ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, true);
      ObjectSetInteger(0, nm, OBJPROP_BACK, true);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   }
   string tx = nm + "_t";
   ENUM_ANCHOR_POINT _anc;
   datetime tlab = _LabelTime(fam, _anc);   // 🪜 retrait selon la famille
   if(ObjectCreate(0, tx, OBJ_TEXT, 0, tlab, price))
   {
      // 📏 le tiret d'ACID Vision : il relie l'œil à la ligne
      ObjectSetString(0, tx, OBJPROP_TEXT, "-- " + label);
      ObjectSetInteger(0, tx, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, tx, OBJPROP_FONTSIZE, font);
      ObjectSetInteger(0, tx, OBJPROP_ANCHOR, _anc);   // 🔖 au-dessus de la ligne
      ObjectSetInteger(0, tx, OBJPROP_ZORDER, fam);    // 🪜 famille mémorisée pour RepositionLabels
      ObjectSetInteger(0, tx, OBJPROP_SELECTABLE, false);
   }
}
void NettoyageOrphelins()
{
   // 🧹 13/09 — QUATRE FAMILLES N'ÉTAIENT JAMAIS EFFACÉES :
   //   ACID_SEC_ (8 usages) · ACID_DASH_ (5) · ACID_CAL_ (2) · ACID_SIG_ (1)
   // La pire est ACID_SIG_ : ses noms contiennent l'horodatage du signal
   // (ACID_SIG_1785987183_SWIN…), donc chaque signal créait un objet unique
   // qui ne disparaissait jamais. Trouvés empilés par dizaines dans les
   // fichiers .chr du patron.
   // ACID Vision n'a pas ce problème : il fait ObjectsDeleteAll(0, PFX) au
   // début de CHAQUE redessin. On ne peut pas faire pareil ici (l'EA dessine
   // par morceaux à des moments différents), donc on purge les orphelins
   // une fois par bougie, sur critère d'âge.
   static datetime _last = 0;
   datetime b = iTime(_Symbol, _Period, 0);
   if(b == _last) return;
   _last = b;
   datetime limite = TimeCurrent() - 48 * 3600;     // deux jours de mémoire
   for(int i = ObjectsTotal(0, 0, -1) - 1; i >= 0; i--)
   {
      string nm = ObjectName(0, i, 0, -1);
      if(StringFind(nm, "ACID_SIG_") != 0) continue;
      // ACID_SIG_<horodatage>_XXXX : on relit l'horodatage dans le nom
      string reste = StringSubstr(nm, 9);
      int us = StringFind(reste, "_");
      if(us <= 0) continue;
      long ts = StringToInteger(StringSubstr(reste, 0, us));
      if(ts > 0 && (datetime)ts < limite) ObjectDelete(0, nm);
   }
}

void DrawVision()
{
   if(!ShowVision) { ObjectsDeleteAll(0, "ACID_VIS_"); return; }
   static datetime lastBar = 0;
   datetime cur = iTime(_Symbol, _Period, 0);
   if(cur == lastBar) return;      // 1 redraw par bougie (leger)
   lastBar = cur;

   ObjectsDeleteAll(0, "ACID_VIS_");
   double atrb[]; ArraySetAsSeries(atrb, true);
   double a = (h_ScalpATR != INVALID_HANDLE && CopyBuffer(h_ScalpATR,0,0,1,atrb) > 0) ? atrb[0] : 0;
   if(a <= 0) return;
   datetime tNow = iTime(_Symbol, PERIOD_M1, 0);

   MqlRates r[]; ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, _Period, 0, Vis_LookBack + 5, r);
   if(n < 30) return;

   // --- LIGNES CLES : style «…» (Pivots + PDH/PDC/PDL + H1) ---
   if(Vis_Lines)
   {
      double pdh = iHigh(_Symbol,PERIOD_D1,1), pdl = iLow(_Symbol,PERIOD_D1,1), pdc = iClose(_Symbol,PERIOD_D1,1);
      if(pdh>0 && pdl>0 && pdc>0)
      {
         double P = (pdh+pdl+pdc)/3.0, rng = pdh-pdl;
         double R1 = 2*P-pdl,  S1 = 2*P-pdh;
         double R2 = P+rng,    S2 = P-rng;
         double R3 = pdh+2*(P-pdl), S3 = pdl-2*(pdh-P);
         color gr = clrGray;
         VLine("R3",  R3, gr,          STYLE_DASH,    "R3",  11, 2);
         VLine("R2",  R2, gr,          STYLE_DASH,    "R2",  11, 2);
         VLine("R1",  R1, gr,          STYLE_DASH,    "R1",  11, 2);
         VLine("PIV", P,  clrSilver,   STYLE_DASH,    "Pivot", 11, 2);
         VLine("S1",  S1, clrRed,      STYLE_DASHDOT, "S1",  11, 2);
         VLine("S2",  S2, gr,          STYLE_DASH,    "S2",  11, 2);
         VLine("S3",  S3, gr,          STYLE_DASH,    "S3",  11, 2);
         VLine("PDH", pdh, clrLime,      STYLE_DASH, "PDH", 11, 7);   // haut d'hier (vert)
         VLine("PDC", pdc, clrLimeGreen, STYLE_DASH, "PDC", 11, 7);   // cloture d'hier (vert)
         VLine("PDL", pdl, clrRed,       STYLE_DASH, "PDL", 11, 7);   // bas d'hier (rouge)
      }
      double hi1 = iHigh(_Symbol,PERIOD_H1,0), lo1 = iLow(_Symbol,PERIOD_H1,0);   // bougie H1 en cours
      if(hi1>0) VLine("HIH1", hi1, clrWhite, STYLE_DASH, "HI H1", 11, 12);
      if(lo1>0) VLine("LOH1", lo1, clrWhite, STYLE_DASH, "Low H1", 11, 12);
   }

   // --- FAIR VALUE GAPS ---
   if(Vis_FVG)
   {
      int drawn=0;
      for(int i=2;i<n-1 && drawn<Vis_MaxZones;i++)
      {
         if(r[i-1].low > r[i+1].high)
         {
            double bas=r[i+1].high, haut=r[i-1].low;
            if(haut-bas < 0.25*a) continue;
            bool c=false; for(int j=i-1;j>=0;j--) if(r[j].low<=bas){c=true;break;}
            if(c) continue;
            VBox("FVGb"+(string)i, r[i+1].time, bas, tNow, haut, Cfg_FVG, "FVG"); drawn++;
         }
         else if(r[i-1].high < r[i+1].low)
         {
            double bas=r[i-1].high, haut=r[i+1].low;
            if(haut-bas < 0.25*a) continue;
            bool c=false; for(int j=i-1;j>=0;j--) if(r[j].high>=haut){c=true;break;}
            if(c) continue;
            VBox("FVGs"+(string)i, r[i+1].time, bas, tNow, haut, Cfg_FVG, "FVG"); drawn++;
         }
      }
   }

   // --- ORDER BLOCKS (ICT : derniere bougie opposee avant impulsion) ---
   if(Vis_OrderBlocks)
   {
      int drawn=0, IB=3;
      for(int i=IB+1;i<n-1 && drawn<Vis_MaxZones;i++)
      {
         double up = r[i-IB].close - r[i].low;
         if(r[i].close < r[i].open && up >= 1.2*a)
         {
            bool c=false; for(int j=i-1;j>=0;j--) if(r[j].low<=r[i].low){c=true;break;}
            if(!c){ VBox("OBb"+(string)i, r[i].time, r[i].low, tNow, r[i].high, Cfg_OBbull, "OB+"); drawn++; i+=IB; continue; }
         }
         double dn = r[i].high - r[i-IB].close;
         if(r[i].close > r[i].open && dn >= 1.2*a)
         {
            bool c=false; for(int j=i-1;j>=0;j--) if(r[j].high>=r[i].high){c=true;break;}
            if(!c){ VBox("OBs"+(string)i, r[i].time, r[i].low, tNow, r[i].high, Cfg_OBbear, "OB-"); drawn++; i+=IB; continue; }
         }
      }
   }

   // --- ECHELLE FIBONACCI AUTO sur le dernier swing (haut/bas extremes) ---
   if(Vis_Fibo)
   {
      int hi=0, lo=0, m=MathMin(n, Vis_LookBack);
      for(int i=1;i<m;i++){ if(r[i].high>r[hi].high) hi=i; if(r[i].low<r[lo].low) lo=i; }
      double top=r[hi].high, bot=r[lo].low, rng=top-bot;
      if(rng > 0.5*a)   // swing significatif seulement
      {
         bool up = (hi < lo);   // le haut est plus RECENT que le bas => jambe haussiere
         double ratios[] = {0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0};
         int last = ArraySize(ratios) - 1;
         for(int k=0;k<ArraySize(ratios);k++)
         {
            // en jambe haussiere : 0% en haut (recent), retracement vers le bas
            double lvl = up ? top - ratios[k]*rng : bot + ratios[k]*rng;
            color fc = (ratios[k]==0.618 || ratios[k]==0.5) ? clrOrchid : Cfg_Fibo;
            color lc = (k==0||k==last)?clrGray:fc;
            int   st = (ratios[k]==0.618)?STYLE_SOLID:STYLE_DOT;
            if(k==0 || k==last)   // 1re et 7e : inchangees (Fib 0.000 / 1.000 + prix)
               VLine("FIB"+(string)k, lvl, lc, st,
                     StringFormat("Fib %.3f  %s", ratios[k], DoubleToString(lvl,_Digits)), 11, 16);
            else                  // intermediaires : juste le numero + le prix, plus petit
               VLine("FIB"+(string)k, lvl, lc, st,
                     StringFormat("%d  %s", k, DoubleToString(lvl,_Digits)), 9, 16);
         }
      }
   }
}

//+------------------------------------------------------------------+
//  🎯 LIGNES D'OBJECTIFS (patron 24/07) — le bot AFFICHE ses TP/SL/Entree
//  pour toutes les positions ET pendings du symbole (tous magics : donc
//  aussi les trades du plan de L'ŒIL). Les TP dans le meme sens sont
//  numerotes TP1/TP2/TP3 du plus proche au plus lointain — quand le plan
//  ouvre ses 3 jambes, le patron voit ses 3 cibles empilees sur le chart.
//+------------------------------------------------------------------+
void ObjLine(string name, double price, color clr, int style, int width, string label, int shift=2)
{
   string ln = "ACID_OBJ_" + name;
   datetime t0 = iTime(_Symbol, PERIOD_M1, 0);
   datetime t1 = t0 + PeriodSeconds(PERIOD_M1) * 10;
   if(ObjectFind(0, ln) < 0) ObjectCreate(0, ln, OBJ_TREND, 0, t0, price, t1, price);
   ObjectMove(0, ln, 0, t0, price);
   ObjectMove(0, ln, 1, t1, price);
   ObjectSetInteger(0, ln, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, ln, OBJPROP_STYLE, style);
   ObjectSetInteger(0, ln, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, ln, OBJPROP_RAY_RIGHT, true);
   ObjectSetInteger(0, ln, OBJPROP_BACK, true);
   ObjectSetInteger(0, ln, OBJPROP_SELECTABLE, false);
   string tx = ln + "_t";
   // 🔖 decalage en ESCALIER (patron 24/07) : normal=2 bougies, SL=7, TP=12 —
   // chaque famille a sa colonne, plus de chevauchement de libelles.
   ENUM_ANCHOR_POINT _anc;
   datetime tlab = _LabelTime(shift, _anc);   // 🔖 au BORD DROIT, décalé par famille (escalier conservé)
   if(ObjectFind(0, tx) < 0) ObjectCreate(0, tx, OBJ_TEXT, 0, tlab, price);
   ObjectMove(0, tx, 0, tlab, price);
   ObjectSetString(0, tx, OBJPROP_TEXT, "-- " + label);
   ObjectSetInteger(0, tx, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, tx, OBJPROP_FONTSIZE, 11);
   ObjectSetInteger(0, tx, OBJPROP_ANCHOR, _anc);   // 🔖 au-dessus de la ligne
   ObjectSetInteger(0, tx, OBJPROP_ZORDER, shift);  // 📍 escalier mémorisé pour RepositionLabels
   ObjectSetInteger(0, tx, OBJPROP_SELECTABLE, false);
}

void DrawObjectives()
{
   ObjectsDeleteAll(0, "ACID_OBJ_");
   if(!ShowObjectives) return;

   // 1) collecte des TP (positions + pendings du symbole) par sens, pour
   //    les numeroter TP1/TP2/TP3 du plus proche au plus lointain.
   double buyTP[], sellTP[];
   int nB = 0, nS = 0;
   ArrayResize(buyTP, 64); ArrayResize(sellTP, 64);

   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk) || PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double ent = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl  = PositionGetDouble(POSITION_SL);
      double tp  = PositionGetDouble(POSITION_TP);
      string id  = "P" + (string)tk;
      ObjLine(id + "_E", ent, Cfg_ObjEntry, STYLE_SOLID, 1, "Entree " + DoubleToString(ent, _Digits));
      if(sl > 0) ObjLine(id + "_S", sl, Cfg_ObjSL, STYLE_DOT, 1, "SL " + DoubleToString(sl, _Digits), 12);
      if(tp > 0) { if(isBuy && nB < 64) buyTP[nB++] = tp; else if(!isBuy && nS < 64) sellTP[nS++] = tp; }
   }
   for(int i = 0; i < OrdersTotal(); i++)
   {
      ulong tk = OrderGetTicket(i);
      if(!OrderSelect(tk) || OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      long ot = OrderGetInteger(ORDER_TYPE);
      bool isBuy = (ot == ORDER_TYPE_BUY_LIMIT || ot == ORDER_TYPE_BUY_STOP);
      double op = OrderGetDouble(ORDER_PRICE_OPEN);
      double sl = OrderGetDouble(ORDER_SL);
      double tp = OrderGetDouble(ORDER_TP);
      string id = "O" + (string)tk;
      ObjLine(id + "_E", op, Cfg_ObjPend, STYLE_DASHDOT, 1, "P " + DoubleToString(op, _Digits));
      if(sl > 0) ObjLine(id + "_S", sl, Cfg_ObjSL, STYLE_DOT, 1, "SL " + DoubleToString(sl, _Digits), 12);
      if(tp > 0) { if(isBuy && nB < 64) buyTP[nB++] = tp; else if(!isBuy && nS < 64) sellTP[nS++] = tp; }
   }

   // 2) tri croissant / decroissant + numerotation TP1/TP2/TP3...
   ArrayResize(buyTP, nB); ArrayResize(sellTP, nS);
   ArraySort(buyTP);                       // BUY : le plus proche (plus bas) = TP1
   ArraySort(sellTP);                      // SELL : trie croissant...
   for(int k = 0; k < nB; k++)
      ObjLine("TPB" + (string)k, buyTP[k], Cfg_ObjTP, STYLE_DASH, 2,
              "TP" + (string)(k + 1) + " " + DoubleToString(buyTP[k], _Digits), 7);
   for(int k = 0; k < nS; k++)             // ...donc pour SELL on numerote a l'envers (le plus HAUT = TP1)
      ObjLine("TPS" + (string)k, sellTP[k], Cfg_ObjTP, STYLE_DASH, 2,
              "TP" + (string)(nS - k) + " " + DoubleToString(sellTP[k], _Digits), 7);
}

//+------------------------------------------------------------------+
//  DASHBOARD
//+------------------------------------------------------------------+
void DrawDashboard()
{
   if(!ShowDashboard) return;

   // 🖥️ Panneau v3 (24/07, demande patron) : «…
   // …». On garde les 2 lignes du
   // haut (identite + IA), on vire l'argent, on met du live utile (RSI/ADX/
   // ATR/rail), les TP1/TP2/TP3 quand il y en a, et ce que le bot fait. Plus
   // compact (13 px/ligne, largeur 190). Les 2 premieres lignes : intouchees.
   string mdl = AcidAIName();
   StringToUpper(mdl);
   bool aival = (SEC_Ov("AIVAL", UseAIValidation ? 1 : 0) >= 0.5);
   string regime = g_Regime==REG_TREND?"TREND":g_Regime==REG_RANGE?"RANGE":
                   g_Regime==REG_VIOLENT?"VIOLENT":"DEAD";
   string biais  = g_Bias==BIAS_BUY?"BUY":g_Bias==BIAS_SELL?"SELL":"NEUTRE";

   // --- chiffres LIVE qui parlent ---
   double rsiB[], atrB[]; ArraySetAsSeries(rsiB, true); ArraySetAsSeries(atrB, true);
   double rsi = (h_ScalpRSI != INVALID_HANDLE && CopyBuffer(h_ScalpRSI,0,0,1,rsiB) > 0) ? rsiB[0] : 0;
   double atr = (h_ScalpATR != INVALID_HANDLE && CopyBuffer(h_ScalpATR,0,0,1,atrB) > 0) ? atrB[0] : 0;
   double adx = BrainADX();
   double rail = 0; int stDir = BrainSuperTrend(rail);
   string railTxt = (stDir == 1 ? "HAUT" : stDir == -1 ? "BAS" : "-");
   double spread  = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   int    pos     = CountPositions();

   // --- TP1/TP2/TP3 des positions du symbole (le plus proche = TP1) ---
   double tps[]; int nt = 0; ArrayResize(tps, 16);
   for(int i=0;i<PositionsTotal();i++)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk) || PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      double tp = PositionGetDouble(POSITION_TP);
      if(tp>0 && nt<16) tps[nt++]=tp;
   }
   ArrayResize(tps, nt); ArraySort(tps);
   double px = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   // trie par distance au prix pour numeroter TP1/TP2/TP3 du plus proche
   for(int a=0;a<nt;a++) for(int b=a+1;b<nt;b++)
      if(MathAbs(tps[b]-px) < MathAbs(tps[a]-px)){ double t=tps[a]; tps[a]=tps[b]; tps[b]=t; }

   // --- construction des lignes (nombre variable) ---
   // lignes construites selon les TOGGLES du Centre (onglet Visualisation)
   string lines[]; ArrayResize(lines, 32); int L = 0;
   lines[L++] = "ACID IA V1";                                                        // 0 (intouchee)
   lines[L++] = "IA " + mdl + (AIFree()?"  · libre":"  · conseil") + (aival?"  · ON":"  · OFF"); // 1 (intouchee)
   lines[L++] = _Symbol + "  " + StringSubstr(EnumToString((ENUM_TIMEFRAMES)Period()),7);
   if(Cfg_RSI || Cfg_ADX)
      lines[L++] = (Cfg_RSI?StringFormat("RSI %.0f", rsi):"") + (Cfg_RSI&&Cfg_ADX?"   ":"") + (Cfg_ADX?StringFormat("ADX %.0f", adx):"");
   if(Cfg_ATR || Cfg_Spread)
      lines[L++] = (Cfg_ATR?StringFormat("ATR %s", DoubleToString(atr,_Digits)):"") + (Cfg_ATR&&Cfg_Spread?"  ":"") + (Cfg_Spread?StringFormat("spread %.0f", spread):"");
   if(Cfg_Regime)
      lines[L++] = StringFormat("%s  biais %s  rail %s", regime, biais, railTxt);
   if(Cfg_Pos)
      lines[L++] = StringFormat("Pos %d/%d", pos, (int)SEC_Ov("MAXPOS", MaxPositions));
   for(int k=0;k<nt && k<3;k++)
      lines[L++] = StringFormat("TP%d  %s", k+1, DoubleToString(tps[k], _Digits));
   if(Cfg_LastSig && g_LastSignalTxt != "") lines[L++] = "> " + g_LastSignalTxt;
   // ⛔ Alarme limite (04/08 patron) : UNE ligne orange dédiée — avant, l'alarme
   // repeignait TOUT le panneau en orange et on ne lisait plus rien.
   if(g_DailyLimitHit)   lines[L++] = "!! LIMITE PERTE JOUR - entrees OFF";
   else if(g_DDLimitHit) lines[L++] = "!! LIMITE DRAWDOWN - entrees OFF";
   ArrayResize(lines, L);

   const int LH = Cfg_Font + 6;   // hauteur de ligne suit la police (Centre)
   // fond
   string bg = "ACID_DASH_BG";
   if(ObjectFind(0, bg) < 0) ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bg, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, DashX - 8);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, DashY - 6);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE,     215);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE,     L * LH + 12);
   // 🪟 31/07 (patron : «…») :
   // le fond devient semi-transparent (canal alpha) et passe DERRIERE les bougies.
   int _op = (int)MathMax(0, MathMin(255, SEC_Ov("DASHOP", DashOpacite)));
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, (color)((_op << 24) | C'16,20,28'));
   ObjectSetInteger(0, bg, OBJPROP_COLOR,     C'48,56,72');
   ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, bg, OBJPROP_BACK,      true);   // 🪟 derriere les bougies
   ObjectSetInteger(0, bg, OBJPROP_SELECTABLE,false);

   for(int i=0; i<L; i++)
   {
      string objName = "ACID_DASH_" + IntegerToString(i);
      if(ObjectFind(0, objName) < 0) ObjectCreate(0, objName, OBJ_LABEL, 0, 0, 0);
      color clr = Cfg_Text;                                             // corps : couleur Centre
      if(i == 0) clr = Cfg_Title;                                        // titre
      if(i == 1) clr = Cfg_IA;                                           // ligne IA
      if(i == 2) clr = clrWhite;                                         // symbole
      if(StringFind(lines[i], "biais") >= 0)                            // ligne regime/biais
         clr = (g_Bias==BIAS_BUY?ClrBull:g_Bias==BIAS_SELL?ClrBear:ClrNeutral);
      if(StringFind(lines[i], "TP") == 0) clr = Cfg_TP;                  // les TP
      if(StringFind(lines[i], ">")  == 0) clr = Cfg_Sig;                 // ce que le bot fait
      if(StringFind(lines[i], "!!") == 0) clr = clrOrange;               // ⛔ seule la ligne d'alarme est orange
      ObjectSetInteger(0, objName, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, objName, OBJPROP_XDISTANCE, DashX);
      ObjectSetInteger(0, objName, OBJPROP_YDISTANCE, DashY + i * LH);
      ObjectSetString (0, objName, OBJPROP_TEXT,      lines[i]);
      ObjectSetString (0, objName, OBJPROP_FONT,      "Consolas");
      ObjectSetInteger(0, objName, OBJPROP_FONTSIZE,  i == 0 ? Cfg_Font+1 : Cfg_Font);
      ObjectSetInteger(0, objName, OBJPROP_COLOR,     clr);
      ObjectSetInteger(0, objName, OBJPROP_SELECTABLE,false);
   }
   for(int i=L; i<32; i++) ObjectDelete(0, "ACID_DASH_" + IntegerToString(i));  // menage
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//  DELETE DASHBOARD
//+------------------------------------------------------------------+
void DeleteDashboard()
{
   ObjectDelete(0, "ACID_DASH_BG");
   for(int i=0; i<20; i++)
   {
      string objName = "ACID_DASH_" + IntegerToString(i);
      if(ObjectFind(0, objName) >= 0)
         ObjectDelete(0, objName);
   }
}

//+------------------------------------------------------------------+
//  OnInit
//+------------------------------------------------------------------+
int OnInit()
{
   Print("═══════════════════════════════════════");
   Print("  ACID IA V1 — INIT START  ");
   Print("═══════════════════════════════════════");

   g_Symbol = _Symbol;
   g_Digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   g_Point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   // Calcul pip size selon asset
   g_AssetType = DetectAsset();
   switch(g_AssetType)
   {
      case ASSET_GOLD:  g_PipSize = 0.1;    break;
      case ASSET_BTC:   g_PipSize = 1.0;    break;
      case ASSET_OIL:   g_PipSize = 0.01;   break;
      default:
         g_PipSize = (g_Digits == 3 || g_Digits == 5) ? g_Point * 10 : g_Point;
         break;
   }
   // 🩸 05/09 : indices et ETH (digits=2, détectés FOREX) → 1 pip = 1 point, comme les presets et L'ŒIL.
   // Avant : g_Point = 0,01 → toutes les valeurs en pips ×100, MaxSpreadPips jamais satisfait,
   // NAS100/SP500 ne tiraient JAMAIS.
   if(StringFind(_Symbol, "NAS") >= 0 || StringFind(_Symbol, "SP500") >= 0 || StringFind(_Symbol, "US500") >= 0 ||
      StringFind(_Symbol, "US100") >= 0 || StringFind(_Symbol, "ETH") >= 0)
      g_PipSize = 1.0;

   // Lot info
   g_MinLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   g_MaxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   g_LotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   // Init balance
   g_AccountBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_PeakBalance    = g_AccountBalance;

   // 🖼️ (patron 03/08) Compacter la marge droite du chart : moins de vide à
   // droite → les bougies s'étalent (plus de graphique) et les étiquettes de
   // prix se rapprochent, sans coller. Pilotable via ChartMargeDroite (0 = ne
   // pas toucher, laisse le réglage manuel du patron).
   if(ChartMargeDroite > 0)
   {
      ChartSetInteger(0, CHART_SHIFT, true);
      ChartSetDouble (0, CHART_SHIFT_SIZE, MathMax(10.0, MathMin(50.0, ChartMargeDroite)));
   }
   g_DailyStartBal  = g_AccountBalance;
   g_DayStart       = 0;

   // Init arrays
   ArrayResize(g_MLScores,  0);
   ArrayResize(g_MLResults, 0);
   RestoreHedgeState();

   // ---- HANDLES SCALP ----
   h_ScalpEMAFast = iMA(_Symbol, ScalpTF, Scalp_EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_ScalpEMASlow = iMA(_Symbol, ScalpTF, Scalp_EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   h_ScalpRSI     = iRSI(_Symbol, ScalpTF, Scalp_RSI_Period, PRICE_CLOSE);
   h_ScalpATR     = iATR(_Symbol, ScalpTF, Scalp_ATR_Period);
   h_ScalpMACD    = iMACD(_Symbol, ScalpTF, 12, 26, 9, PRICE_CLOSE);
   h_ScalpBB      = iBands(_Symbol, ScalpTF, 20, 0, 2.0, PRICE_CLOSE);
   h_ScalpADX     = iADX(_Symbol, ScalpTF, 14);   // 🧠 v2

   // ---- HANDLES SWING ----
   h_SwingEMAFast  = iMA(_Symbol, SwingTF, Swing_EMA_Fast,  0, MODE_EMA, PRICE_CLOSE);
   h_SwingEMASlow  = iMA(_Symbol, SwingTF, Swing_EMA_Slow,  0, MODE_EMA, PRICE_CLOSE);
   h_SwingEMATrend = iMA(_Symbol, SwingTF, Swing_EMA_Trend, 0, MODE_EMA, PRICE_CLOSE);
   h_SwingRSI      = iRSI(_Symbol, SwingTF, Swing_RSI_Period, PRICE_CLOSE);
   h_SwingATR      = iATR(_Symbol, SwingTF, Swing_ATR_Period);
   h_SwingMACD     = iMACD(_Symbol, SwingTF, 12, 26, 9, PRICE_CLOSE);
   h_SwingStoch    = iStochastic(_Symbol, SwingTF, 5, 3, 3,
                                  MODE_SMA, STO_LOWHIGH);
   h_SwingADX      = iADX(_Symbol, SwingTF, 14);

   // ---- HANDLES CONFIRMATION D1 ----
   h_ConfirmEMA50  = iMA(_Symbol, SwingConfirmTF, 50,  0, MODE_EMA, PRICE_CLOSE);
   h_ConfirmEMA200 = iMA(_Symbol, SwingConfirmTF, 200, 0, MODE_EMA, PRICE_CLOSE);
   h_ConfirmRSI    = iRSI(_Symbol, SwingConfirmTF, 14, PRICE_CLOSE);

   // Vérification handles
   bool ok = true;
   if(h_ScalpEMAFast ==INVALID_HANDLE) { Print("ERR: h_ScalpEMAFast");  ok=false; }
   if(h_ScalpEMASlow ==INVALID_HANDLE) { Print("ERR: h_ScalpEMASlow");  ok=false; }
   if(h_ScalpRSI     ==INVALID_HANDLE) { Print("ERR: h_ScalpRSI");      ok=false; }
   if(h_ScalpATR     ==INVALID_HANDLE) { Print("ERR: h_ScalpATR");      ok=false; }
   if(h_ScalpMACD    ==INVALID_HANDLE) { Print("ERR: h_ScalpMACD");     ok=false; }
   if(h_ScalpBB      ==INVALID_HANDLE) { Print("ERR: h_ScalpBB");       ok=false; }
   if(h_SwingEMAFast ==INVALID_HANDLE) { Print("ERR: h_SwingEMAFast");  ok=false; }
   if(h_SwingEMASlow ==INVALID_HANDLE) { Print("ERR: h_SwingEMASlow");  ok=false; }
   if(h_SwingEMATrend==INVALID_HANDLE) { Print("ERR: h_SwingEMATrend"); ok=false; }
   if(h_SwingRSI     ==INVALID_HANDLE) { Print("ERR: h_SwingRSI");      ok=false; }
   if(h_SwingATR     ==INVALID_HANDLE) { Print("ERR: h_SwingATR");      ok=false; }
   if(h_SwingMACD    ==INVALID_HANDLE) { Print("ERR: h_SwingMACD");     ok=false; }
   if(h_SwingStoch   ==INVALID_HANDLE) { Print("ERR: h_SwingStoch");    ok=false; }
   if(h_SwingADX     ==INVALID_HANDLE) { Print("ERR: h_SwingADX");      ok=false; }
   if(h_ConfirmEMA50 ==INVALID_HANDLE) { Print("ERR: h_ConfirmEMA50");  ok=false; }
   if(h_ConfirmEMA200==INVALID_HANDLE) { Print("ERR: h_ConfirmEMA200"); ok=false; }

   if(!ok)
   {
      Print("❌ INIT FAILED — Handles invalides");
      return INIT_FAILED;
   }

   // Trade config
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   // Fix 07/07 (erreur 10030 sur GOLD#) : on lit le mode de remplissage
   // SUPPORTÉ par le symbole au lieu d'imposer FOK en dur.
   long fill = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((fill & SYMBOL_FILLING_IOC) != 0)      trade.SetTypeFilling(ORDER_FILLING_IOC);
   else if((fill & SYMBOL_FILLING_FOK) != 0) trade.SetTypeFilling(ORDER_FILLING_FOK);
   else                                       trade.SetTypeFilling(ORDER_FILLING_RETURN);
   Print("Filling mode retenu : ", EnumToString(trade.RequestTypeFilling()));
   trade.LogLevel(LOG_LEVEL_ERRORS);

   Print("✅ ACID IA V1 initialisé sur ", _Symbol);
   Print("💓 alive | model=", AcidAIName(), " | init");   // annonce immédiate à L'ŒIL (chat)
   // 👁️ 04/09 : 120 → 15 s. Le patron veut de l'info «…» et se
   // fiche du CPU («…» — ce timer n'en
   // consomme aucun : une ligne de journal, pas un appel d'IA).
   EventSetTimer(15);   // 💓 heartbeat + vue toutes les 15 s (marche marché fermé)
   Print("Asset détecté : ", EnumToString(g_AssetType));
   Print("PipSize : ", g_PipSize);
   Print("MinLot / MaxLot / Step : ", g_MinLot, " / ", g_MaxLot, " / ", g_LotStep);

   if(SendTelegram)
      SendTelegramMsg(StringFormat("🚀 ACID IA démarré sur %s", _Symbol));

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//  OnDeinit
//+------------------------------------------------------------------+
// 💓 Heartbeat temps-réel (marche même marché fermé) → chat de groupe
void OnTimer()
{
   SendHeartbeat();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   // Libérer handles
   int handles[] = {
      h_ScalpEMAFast, h_ScalpEMASlow, h_ScalpRSI, h_ScalpATR,
      h_ScalpMACD,    h_ScalpBB,      h_ScalpADX,
      h_SwingEMAFast, h_SwingEMASlow, h_SwingEMATrend,
      h_SwingRSI,     h_SwingATR,     h_SwingMACD,
      h_SwingStoch,   h_SwingADX,
      h_ConfirmEMA50, h_ConfirmEMA200, h_ConfirmRSI
   };
   for(int i=0; i<ArraySize(handles); i++)
      if(handles[i] != INVALID_HANDLE)
         IndicatorRelease(handles[i]);

   DeleteDashboard();
   Print("ACID IA V1 — DEINIT | Raison: ", reason);
}

void CheckAcidBotCommands()
{
   if(!AcidBotEnabled) return;

   // 🛡️ au 1er passage : restaure l'état pause depuis les GlobalVariables
   // (avant, un restart du terminal effaçait la pause → ACID IA relâchée à l'insu du patron)
   static bool sec_synced = false;
   if(!sec_synced)
   {
      sec_synced = true;
      if(GlobalVariableCheck("ACID_SEC_PAUSED"))
         g_OeilPause = (GlobalVariableGet("ACID_SEC_PAUSED") > 0.5);
      if(g_OeilPause) Print("🛡️ Pause restaurée après redémarrage (ordre durable en vigueur)");
   }

   // 🌉 PONT v2 (09/07) : l'ANCIEN input AcidBotCmdFile (supprimé 13/07) pointait sur un chemin ABSOLU
   // (C:\MT5_Bridge\...) que la sandbox MQL5 REFUSE en silence → le pont n'a
   // JAMAIS fonctionné (pauses/ordres jamais reçus). Chemin relatif en dur
   // (= MQL5\Files du terminal), immunisé contre les inputs fantômes.
   int fh = FileOpen("acidbot_commands.txt", FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(fh == INVALID_HANDLE) return;

   string cmd = "";
   while(!FileIsEnding(fh))
      cmd += FileReadString(fh);
   FileClose(fh);

   if(StringLen(cmd) < 3) return;
   FileDelete("acidbot_commands.txt");
   
   string parts[];
   int n = StringSplit(cmd, '|', parts);
   if(n < 1) return;
   
   string action = parts[0];
   Print("🤖 AcidBot commande reçue : ", cmd);
   
   // BUY|SYMBOL|LOT|SL|TP  — 🛡️ lot soumis aux règles d'acier natives
   if(action == "BUY" && n >= 5)
   {
      string bs = parts[1];
      double bl = StringToDouble(parts[2]), bsl = StringToDouble(parts[3]);
      double bref = SymbolInfoDouble(bs, SYMBOL_ASK);
      bl = SecureLot(bs, bl, (bsl > 0 && bref > 0) ? MathAbs(bref - bsl) : 0);
      if(bl <= 0) Print("🛡️ ordre pont BUY ", bs, " refusé (risque > règle d'acier)");
      else BuyFix(bl, bs, 0, bsl, StringToDouble(parts[4]), "AcidBot");
   }
   // SELL|SYMBOL|LOT|SL|TP  — 🛡️ idem
   else if(action == "SELL" && n >= 5)
   {
      string ss = parts[1];
      double sl2 = StringToDouble(parts[2]), ssl = StringToDouble(parts[3]);
      double sref = SymbolInfoDouble(ss, SYMBOL_BID);
      sl2 = SecureLot(ss, sl2, (ssl > 0 && sref > 0) ? MathAbs(sref - ssl) : 0);
      if(sl2 <= 0) Print("🛡️ ordre pont SELL ", ss, " refusé (risque > règle d'acier)");
      else SellFix(sl2, ss, 0, ssl, StringToDouble(parts[4]), "AcidBot");
   }
   // CLOSE|TICKET
   else if(action == "CLOSE" && n >= 2)
   {
      ClosePos((ulong)StringToInteger(parts[1]));
   }
   // CLOSEALL
   else if(action == "CLOSEALL")
   {
      for(int i=PositionsTotal()-1; i>=0; i--)
         if(posInfo.SelectByIndex(i) && posInfo.Magic()==MagicNumber)
            ClosePos(posInfo.Ticket());
   }
   // MODIFY|TICKET|SL|TP
   else if(action == "MODIFY" && n >= 4)
   {
      trade.PositionModify((ulong)StringToInteger(parts[1]),
                           StringToDouble(parts[2]),
                           StringToDouble(parts[3]));
   }
   // === PILOTAGE PAR L'ŒIL (ia_watchdog.py) ===
   // PAUSE : l'EA cesse d'OUVRIR (il continue de gérer ses positions)
   else if(action == "PAUSE")
   {
      g_OeilPause = true;
      GlobalVariableSet("ACID_SEC_PAUSED", 1);   // 🛡️ persiste au restart du terminal
      Print("👁️ L'ŒIL met l'EA en pause (plus d'ouverture)");
   }
   // RESUME : reprise des ouvertures
   else if(action == "RESUME")
   {
      g_OeilPause = false;
      GlobalVariableSet("ACID_SEC_PAUSED", 0);
      Print("👁️ L'ŒIL relance l'EA");
   }
   // 🔄 RESETLIMITS (04/08 patron, bouton du Centre) : réarme les limites de
   // perte jour + drawdown SANS attendre minuit. Les compteurs repartent de
   // l'équity ACTUELLE (pas de la balance : sinon un flottant rouge re-déclenche
   // l'alarme à la seconde). Entrées de nouveau autorisées immédiatement.
   else if(action == "RESETLIMITS")
   {
      double _bal = AccountInfoDouble(ACCOUNT_BALANCE);
      double _eq  = AccountInfoDouble(ACCOUNT_EQUITY);
      g_DailyLimitHit = false;
      g_DDLimitHit    = false;
      g_DailyStartBal = MathMin(_bal, _eq);   // les pertes se comptent depuis MAINTENANT
      g_DailyLoss     = 0.0;
      g_PeakBalance   = _bal;
      Print("🔄 LIMITES RÉARMÉES (bouton Centre) — pertes recomptées depuis l'équity actuelle (",
            DoubleToString(_eq, 2), " €), entrées de nouveau autorisées");
   }
   // 🛡️ SET|MAXLOT|x  /  SET|RISK|x  /  SET|RECOVERY|0-1 : réglages PROFONDS
   // à distance (le vrai pouvoir de L'ŒIL), persistés en GlobalVariables.
   // 🎛️ «…» : catalogue des curseurs réglables par L'ŒIL,
   // chacun BORNÉ (l'IA règle à sa guise, mais jamais hors règles d'acier).
   else if(action == "SET" && n >= 3)
   {
      SetApply(parts[1], StringToDouble(parts[2]), "", "");
   }
   // 🎯 SETSYM|SYMBOLE|TF|CLÉ|VALEUR : preset PAR CHART (13/07 patron) —
   // TF="*" = tous les timeframes du symbole. Côté lecture, SEC_Ov applique
   // la cascade SYMBOLE+TF > SYMBOLE > globale > input du chart.
   else if(action == "SETSYM" && n >= 5)
   {
      SetApply(parts[3], StringToDouble(parts[4]), parts[1], parts[2]);
   }
   // CLOSESYM|SYMBOL : ferme toutes les positions de l'EA sur ce symbole
   else if(action == "CLOSESYM" && n >= 2)
   {
      for(int i=PositionsTotal()-1; i>=0; i--)
         if(posInfo.SelectByIndex(i) && posInfo.Magic()==MagicNumber
            && posInfo.Symbol()==parts[1])
            ClosePos(posInfo.Ticket());
   }

   // Feedback (pont v2 : sandbox MQL5\Files, comme la lecture)
   int fb = FileOpen("acidbot_feedback.txt", FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(fb != INVALID_HANDLE)
   {
      FileWriteString(fb, StringFormat("OK|%s|%s", action, TimeToString(TimeCurrent())));
      FileClose(fb);
   }
}  // ← UNE SEULE accolade fermante
//+------------------------------------------------------------------+
//  CheckRecovery — Récupération intelligente après perte
//+------------------------------------------------------------------+
void CheckRecovery()
{
   // 🛡️ RÈGLE D'ACIER (09/07) : le recovery était le tueur du compte
   // (X € en un tir le 08/07, 8 tirs en 20 min le soir même).
   // Coupable à distance par L'ŒIL : SET|RECOVERY|0. Rationné : 2/jour/chart.
   if(!SEC_Recovery()) return;
   if(!TradingEnabled) return;   // 🛡️ 05/09 : un chart OBSERVATEUR ne tire jamais (le seul chemin qui échappait au drapeau)
   if(WeekendBlock())  return;                               // 📅 pas de recovery le week-end
   static int rec_day = -1; static int rec_count = 0;
   MqlDateTime _dt; TimeToStruct(TimeCurrent(), _dt);
   if(_dt.day_of_year != rec_day) { rec_day = _dt.day_of_year; rec_count = 0; }
   if(rec_count >= 2) return;

   // 🔧 FIX audit 03/08 : le recovery ignorait spread, news, session et COT — et il
   // se déclenche justement quand le flottant est rouge (= au pire moment, spread
   // et news au plus mauvais). On aligne les mêmes gardes que les entrées normales.
   if(!IsSpreadOK() || !IsNewsOK() || !IsSessionOK()) return;
   if(CotBlocks(g_Bias == BIAS_BUY)) return;

   if(CountPositions() >= (int)SEC_Ov("MAXPOS", MaxPositions)) return;

   // ✅ Cooldown global — 1 tentative par barre M5
   datetime currentBar = iTime(_Symbol, ScalpTF, 0);
   if(g_LastRecoveryBar >= currentBar) return; // ← BLOQUE le spam

   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double floating = equity - balance;

   double threshold = balance * 0.005;
   if(floating > -threshold) return;

   bool isBuy = (g_Bias == BIAS_BUY);
   double score = isBuy ? CalcScalpScore(true) : CalcScalpScore(false);
   if(score < SEC_Ov("SCOREMIN", Scalp_ScoreMin)) return;   // 🎛️ sélectivité pilotable

   // Réutilise le handle ATR scalp déjà alloué en OnInit au lieu d'en
   // recréer un nouveau à chaque appel : l'ancien code faisait
   // iATR(...) sans IndicatorRelease() correspondant, une fuite de handle
   // qui finit par dégrader/bloquer le terminal après des semaines de run.
   double atrBuf[1];
   if(CopyBuffer(h_ScalpATR, 0, 0, 1, atrBuf) < 1) return;
   double atrVal   = atrBuf[0];
   double slPoints = SEC_Ov("SLATR", Scalp_SL_ATR) * atrVal / _Point;
   double tpPoints = SEC_Ov("TPATR", Scalp_TP_ATR) * atrVal / _Point;

   double lossAbs  = MathAbs(floating);
   double lotRecov = NormalizeDouble(lossAbs / (slPoints * _Point * 10), 2);
   lotRecov = MathMax(lotRecov, 0.01);
   // 🛡️ fini le «…» (qui autorisait ~X € de risque
   // sur GOLD) : cap dur SEC_MaxLot + risque réel <= SEC_RiskPct% du solde.
   lotRecov = SecureLot(_Symbol, lotRecov, slPoints * _Point);
   if(lotRecov <= 0)
   {
      Print("🛡️ RECOVERY refusé : risque > ", SEC_RiskPct(), "% du solde (règle d'acier)");
      g_LastRecoveryBar = currentBar;   // pas de re-tentative en boucle sur la même barre
      return;
   }

   MqlTradeRequest req = {};
   MqlTradeResult  res = {};
   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = _Symbol;
   req.volume    = lotRecov;
   req.type      = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.price     = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                         : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.sl        = isBuy ? req.price - slPoints * _Point
                         : req.price + slPoints * _Point;
   req.tp        = isBuy ? req.price + tpPoints * _Point
                         : req.price - tpPoints * _Point;
   req.magic     = MagicNumber;
   req.comment   = "RECOVERY";
   req.deviation = 10;
   // Fix 07/07 v2 : en envoi BRUT (OrderSend), XM rejette FOK (10030) mais
   // accepte IOC — prouvé par les ordres de L'ŒIL. On force IOC ici.
   req.type_filling = ORDER_FILLING_IOC;

   // ✅ Marquer AVANT d'envoyer pour bloquer le spam même en échec
   g_LastRecoveryBar = currentBar;

   if(OrderSend(req, res))
   {
      rec_count++;   // 🛡️ rationnement : 2 recovery/jour/chart maximum
      Print("✅ RECOVERY ouvert | Lot: ", lotRecov, " | Perte: ", floating,
            " | (", rec_count, "/2 aujourd'hui)");
   }
   else
      Print("❌ RECOVERY échoué | Erreur: ", res.retcode);
}


//+------------------------------------------------------------------+
//  OnTick — COEUR DU BOT
//+------------------------------------------------------------------+
void OnTick()
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ||
      !MQLInfoInteger(MQL_TRADE_ALLOWED)) return;

   // Commandes IA EN PREMIER (NON-BLOQUANT)
   CheckAcidBotCommands();  // ← Continue même si IA fail

   UpdateDailyDD();
   if(g_DailyLimitHit) { DrawDashboard(); return; }
   if(g_DDLimitHit)    { DrawDashboard(); return; }

   g_Regime = DetectRegime();
   g_Bias   = DetectBias();
   CheckTradeClosed();
   // 👁️ 05/09 : chart OBSERVATEUR (TradingEnabled=false) = heartbeat + vue (OnTimer) + dashboard,
   // RIEN d'autre : avant, il gérait les positions du chart trader (même symbole, même magic)
   // avec les valeurs PAR DÉFAUT du code (BE temporel 5 min / +40 pips…).
   if(!TradingEnabled) { DrawVision(); DrawDashboard(); return; }   // il VOIT (blocs, FVG, Fibo), il ne trade pas
   CheckManualClose();   // ✋ reprise si le patron a coupe a la main un trade de conviction
   CheckCrashCatcher();      // sync bot Python : pause des entrees si crash

   // Gestion positions ouvertes
   ManagePartialTP();        // sync bot Python : 50% fermes au TP1 (mi-chemin)
   ManageTimeBE();           // BE temporel : 2 min de vie + 1 min en profit => SL au-dessus de l'entree
   ManageBreakEven();
   ManageTrailing();
   ManageLadder();           // 🪜 partial tous les X pips + cloture/reprise a Y pips (par symbole)
   ManageFlowRider();        // 🌊 flux fort + position alignée => SL sur le rail SuperTrend
   ProfitGuard();            // 💎 gain qui s'essouffle => on encaisse sans attendre BE/trail
   NakedGuard();             // 🛡️ position sans SL => SL natif 1.5xATR (autonomie sans L'ŒIL)
   ManageHedge();
   CloseHedgeIfProfit();
   ManageSwingExpiry();
   CheckRecovery();

   // Nouveaux trades seulement si pas trop de positions — on respecte
   // directement l'input MaxPositions (au lieu d'un plafond 4/2 codé en
   // dur qui l'ignorait complètement, en plus du plafond différent utilisé
   // par CheckRecovery() : trois logiques de cap incohérentes entre elles).
   if(CountPositions() < (int)SEC_Ov("MAXPOS", MaxPositions) && TimeCurrent() >= g_CrashPauseUntil && !g_OeilPause)
   {
      if(ScalpEnabled && (BotMode == MODE_SCALP || BotMode == MODE_HYBRID))
      {
         datetime lastScalpBar = iTime(_Symbol, ScalpTF, 0);
         if(g_LastScalpTime < lastScalpBar)
         {
            double scoreBuy  = CalcScalpScore(true);
            double scoreSell = CalcScalpScore(false);
            if(scoreBuy >= SEC_Ov("SCOREMIN", Scalp_ScoreMin) && scoreBuy >= scoreSell)
               OpenScalpTrade(true);
            else if(scoreSell >= SEC_Ov("SCOREMIN", Scalp_ScoreMin) && scoreSell > scoreBuy)
               OpenScalpTrade(false);
         }
      }

      // 🩹 24/09 : clé SWING ajoutée (les six autres modules étaient pilotables,
      // pas celui-ci — impossible de le couper sans toucher aux inputs du chart).
      if(SwingEnabled && SEC_Ov("SWING", 1) >= 0.5 && (BotMode == MODE_SWING || BotMode == MODE_HYBRID))
      {
         datetime lastSwingBar = iTime(_Symbol, SwingTF, 0);
         if(g_LastSwingTime < lastSwingBar)
         {
            double scoreBuy  = CalcSwingScore(true);
            double scoreSell = CalcSwingScore(false);
            if(scoreBuy >= Swing_ScoreMin && scoreBuy >= scoreSell)
               OpenSwingTrade(true);
            else if(scoreSell >= Swing_ScoreMin && scoreSell > scoreBuy)
               OpenSwingTrade(false);
         }
      }

      // 🏀 REBOUND SNIPER : rebond sur niveau reel — module autonome (patron 24/07)
      CheckRebound();
      // 🚀 MOMENTUM CAPTURE : impulsion forte alignée — capte les bougies entières (patron 25/07)
      CheckMomentum();
   }

   if(PendingEnabled && TimeCurrent() >= g_CrashPauseUntil && !g_OeilPause)
   {
      datetime lastPendBar = iTime(_Symbol, ScalpTF, 0);
      if(g_LastPendingTime < lastPendBar)
         ManagePendingOrders();
   }

   if(TimeCurrent() - g_CfgCheck >= 3) { g_CfgCheck = TimeCurrent(); LoadDisplayCfg(); }  // 🎨 config Centre a chaud
   DrawVision();       // 👁️ Order Blocks + FVG + lignes cles (remplace 4 indicateurs Market)
   DrawObjectives();   // 🎯 TP1/TP2/TP3 + SL + entrees des positions & plans en vue
   // 📍 13/09 — UNE FOIS PAR BOUGIE, plus à chaque tick.
   // L'étiquette est désormais posée en TEMPS-GRAPHIQUE (deux bougies à droite,
   // méthode ACID Vision) : elle suit donc le chart toute seule. La recoller à
   // chaque tick ne servait qu'à compenser l'épinglage en pixels — et ça
   // bouclait sur TOUS les objets texte du graphique, à chaque tick.
   static datetime _lastLabelBar = 0;
   datetime _nowBar = iTime(_Symbol, _Period, 0);
   if(_nowBar != _lastLabelBar) { _lastLabelBar = _nowBar; RepositionLabels(); }
   NettoyageOrphelins();
   DrawDashboard();
}
