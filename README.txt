================================================================================
   🧪  ACID BOT — L'ÉCOSYSTÈME DE TRADING
       Version publique · mode d'emploi complet
================================================================================

   Un écosystème de trading automatisé pour MetaTrader 5, écrit en Python et
   en MQL5. Un CERVEAU qui décide, six YEUX qui observent, un ML qui chasse,
   un bot de scalp, un EA sur chaque graphique — et une seule voix, sur
   Telegram.

   Écrit à quatre mains, jour après jour, sur un vrai compte : un trader
   (« le patron », dans le code) et une IA de développement. Tout ce qui
   était personnel — clés, comptes, mots de passe, montants — a été retiré.
   C'est TOI qui colles tes identifiants : section 5.

   Licence : GPL-3.0 (fichier LICENSE).


--------------------------------------------------------------------------------
   SOMMAIRE
--------------------------------------------------------------------------------
    0. Avant tout : à lire
    1. La personnalité de l'écosystème
    2. Les pièces, une par une
    3. Les garde-fous du capital  ← à lire AVANT de passer en réel
    4. Ce qu'il te faut avant d'installer
    5. Où coller TES identifiants  ← le cœur de ce fichier
    6. Installation
    7. Premier démarrage (en SIMULATION)
    8. Passer en réel — seulement quand tout est vert
    9. Entraîner le ML
   10. Les commandes Telegram
   11. Options
   12. Ce qui n'est pas dans ce dépôt, et ce qui a changé
   13. Dépannage
   14. Licence


   CONTENU DU DÉPÔT
   ----------------
   README.txt ................ ce fichier
   LICENSE ................... GPL-3.0
   ACID_INSTALL.py ........... l'installeur (section 6)
   portabilite.py ............ trouve MT5 et ses dossiers sur ta machine
   manifest.json ............. fiche du colis, lue par l'installeur
   secrets\
     secrets_acid.exemple.py . LE modèle où vont tes clés (section 5)
   mt5\
     Experts\ACID IA V1.mq5 .. l'EA (Expert Advisor) MetaTrader 5
     Scripts\ACID_ExportCalendrier.mq5 . export du calendrier économique
   projet\ ................... tout l'écosystème ; l'installeur le pose dans
                               C:\AcidBot\BOT COMPLETO


================================================================================
 0. AVANT TOUT : À LIRE
================================================================================

 ⚠️  Le trading de CFD (indices, or, pétrole, crypto, devises) avec effet de
     levier peut faire perdre TOUT le capital, et vite. Ce projet est partagé
     pour apprendre et pour s'inspirer. Ce n'est NI un conseil en
     investissement, NI un produit fini, NI une promesse de gain.

 ⚠️  Les chiffres cités dans le code (taux de réussite, R gagnés, AUC…) sont
     des mesures faites par l'auteur, sur SES données, à une date donnée. Le
     marché change ; rien ne garantit qu'ils se reproduisent chez toi.

 ⚠️  Plusieurs garde-fous sont nés de pertes réelles. Ils sont là pour une
     raison : ne les desserre pas sans avoir compris ce qu'ils empêchent.

 ✅  Livré prudent :
       · tout l'écosystème démarre en mode SIMULATION : aucun ordre réel ne
         part, y compris ceux que LE CERVEAU confierait à l'EA (détails et
         limites : section 3, couche 0) ;
       · l'EA est livré avec TradingEnabled = false : il observe, il ne
         décide rien lui-même ;
       · risque de base : 1 % par trade, et une enveloppe commune de 5 %
         d'exposition totale (ses exceptions sont listées en section 3) ;
       · les modules qui contournent le budget commun sont coupés (exécuteur
         du conseil, pisteur DAVO, reprises ×2 de la rotation).

 🧭  Conçu et utilisé sous Windows, avec MetaTrader 5 chez le broker Vantage.
     Chez un autre broker, il faudra adapter les noms de symboles (section 13).

 👉  Commence sur un compte DÉMO. Toujours.


================================================================================
 1. LA PERSONNALITÉ DE L'ÉCOSYSTÈME
================================================================================

 Ce n'est pas « un bot ». C'est une petite équipe, avec une hiérarchie, des
 règles et un caractère. Dans le code, « le patron », c'est toi : le
 propriétaire du compte. Le système te tutoie et te parle comme un trader
 parle à son associé.

 ► UNE SEULE VOIX
   LE CERVEAU (ia_watchdog.py) est à la fois l'œil, la tête et la bouche : il
   voit tout (prix, positions, journal MT5, autres bots, serveurs), il décide,
   et il est le SEUL à te parler sur Telegram. Les autres se taisent et lui
   remontent ce qu'ils savent. Tu n'as qu'une conversation à suivre.

 ► ON MESURE AVANT DE CROIRE
   Aucune idée n'entre en service sur sa bonne mine — même pas celles du
   patron. Chaque détecteur passe le même protocole de backtest :
     · le spread RÉEL est déduit à l'entrée ET à la sortie (sans lui, un
       backtest affichait +101 R ; avec lui, −65 R) ;
     · réglé sur l'historique ancien, validé sur le récent, jamais mélangé ;
     · test du MIROIR : le sens inverse doit perdre, sinon c'est du bruit ;
     · test du DÉCALAGE : entrer une bougie plus tard ne doit pas tout
       effondrer ;
     · test du PLATEAU : les réglages voisins doivent tenir aussi — un pic
       isolé au milieu des pertes, c'est du hasard.
   Ce qui échoue est coupé, même si l'idée était belle. Et quand une idée du
   patron ne passe pas la mesure, le code le lui dit en face (lis l'en-tête de
   bloc_ordres.py ou de chasseur_tendance.py).

 ► LE MARCHÉ EST LE PROFESSEUR
   Le ML n'apprend pas sur les trades passés d'un humain : un modèle entraîné
   sur un historique à 38,8 % de réussite apprend… à reproduire les pertes.
   Il apprend sur les PRIX, avec un protocole anti-illusion : découpage
   temporel strict, fossé de 15 jours entre entraînement et test, « test de
   paranoïa » (on mélange les étiquettes : s'il réussit encore, il triche),
   espérance en R plutôt qu'AUC, et une réserve finale de 30 jours jamais
   touchée. Règle d'or : mieux vaut pas de ML qu'un ML qui ment.

 ► LES YEUX OBSERVENT, LE CERVEAU DÉCIDE
   Six « yeux » spécialisés, courts (deux cents lignes environ), mesurables et
   débranchables un par un. Règle gravée : UN ŒIL NE MODIFIE JAMAIS SES
   PROPRES SEUILS. Il observe, compare sa forme du moment à son backtest, et
   rapporte. Un réglage qu'on tourne cinq fois par jour à l'aveugle dérive ;
   un réglage qui se mesure progresse.

 ► LA MÉMOIRE PLUTÔT QUE LA PRÉDICTION
   Le carnet de bord (carnet_bord.py) pose sous les yeux du CERVEAU ce qui
   s'est passé cette semaine, sans aucun modèle : « un modèle généralise le
   passé et l'impose ; un carnet rappelle et laisse juger ». Les leçons
   chiffrées (lecons_mesurees.py) sont de l'arithmétique sur ses propres
   trades : elles ne peuvent pas halluciner et ne coûtent aucun token. La
   mémoire des réglages (reglages_memoire.py) lui rappelle ce qu'ont donné ses
   réglages précédents avant qu'il en propose un autre. Et tu peux lui
   enseigner toi-même : /lecon <texte>.

 ► LE RISQUE EST COMMUN
   Leçon fondatrice : chaque bot respectait SA limite, personne ne voyait le
   TOTAL. Trois paris de 10 % ouverts en même temps, ce n'est pas 10 % de
   risque, c'est 30 %. D'où une enveloppe UNIQUE (budget_risque.py) que les
   bots consultent avant d'ouvrir : quand elle est pleine, tout le monde
   attend — même celui qui n'a rien perdu.

 ► QUATRE BLOCS, PAS HUIT MARCHÉS
   NAS100/SP500 (corrélation +0,95), BTC/ETH (+0,83), or/argent (+0,77),
   EURUSD/dollar (−0,95) : c'est le même risque sous deux noms. L'Œil 6 ne
   regarde pas le marché ; il regarde les cinq autres yeux, et il a un droit
   de VETO quand ils empilent la même exposition sous des noms différents.

 ► UN GARDE-FOU MUET NE VAUT RIEN
   Quand une protection ne peut pas fonctionner (calendrier illisible,
   serveur éteint, modèle absent), le système le DIT au lieu de faire
   semblant.

 ► L'HUMAIN GARDE LA MAIN
   Passer en réel exige TA confirmation. Revenir en simulation est immédiat
   et sans condition : « revenir en sécurité ne se négocie pas ». Tes ordres
   directs passent : s'ils vont contre une règle, il t'avertit, puis il
   exécute. Seuls le marché, le broker et le plafond de lot s'imposent à toi.

 ► HONNÊTE SUR SES FAIBLESSES
   Chaque module dit ce qu'il ne sait pas faire : la rotation sur niveaux n'a
   pas été mesurée en backtest, le choc de volatilité coûte un ticket cher,
   l'Œil 5 a une faiblesse « dite franchement »… Lis les en-têtes des
   fichiers : c'est le meilleur mode d'emploi.

 ► ET UN PEU DE CARACTÈRE
   Chaque graphique a son IA, « ACID IA » — le trader énervé 🤬 — que LE
   CERVEAU supervise. ia_dialogue.py te laisse les regarder se parler.


================================================================================
 2. LES PIÈCES, UNE PAR UNE
================================================================================

 Ce qui tourne quand tout est lancé (DEMARRER_ECOSYSTEME.bat) :

   MetaTrader 5 ── l'EA « ACID IA V1 » sur chaque graphique
                     └─ demande l'avis du CERVEAU ............. port 8060
   Server.py ───── serveur News ................................ port 5001
   server_ml_v2 ── serveur ML (le seul modèle) ................. port 8001
   ia_watchdog ─── LE CERVEAU + Telegram ................ ports 8060, 8061
   MAMMOUTH ────── le bot Python de scalp
   dashboard ───── le tableau de bord web ...................... port 8050
   sniper_ml ───── le ML chasseur (livré en OBSERVATION)
   yeux\ ───────── les six yeux

 Tout part en arrière-plan (pythonw, aucune fenêtre). Pour tout couper :
 ARRETER_ECOSYSTEME.bat.

 ── LE CERVEAU — ia_watchdog.py ──────────────────────────────────────────
   La seule voix Telegram. L'IA passe par mammouth.ai d'abord, Anthropic en
   secours, Mistral en troisième porte. Il exécute directement dans MT5 avec
   sa propre gestion du risque, valide les idées de l'IA de chaque graphique
   (port 8060), tient le coupe-circuit du jour, pose un stop de survie sur
   tes trades manuels oubliés sans stop, rédige le plan de la journée, et
   gère le mode SIMULATION / RÉEL (fichier mode_trading.txt).
   Dans sa boucle vivent :
     arbitre.py ........... quand deux détecteurs se contredisent, celui qui a
                            le plus rapporté sur CE marché l'emporte
     retour_moyenne.py .... prix à 3 écarts-types de sa moyenne + RSI(3)
                            extrême ; stop large (5 ATR) ; jamais en tendance
                            forte, jamais aux ouvertures de Londres et New York
     chasseur_tendance.py . le biais de fond donne le SENS, on n'entre que sur
                            les rebonds contraires
     signal_dollar.py ..... la divergence du dollar annonce le NASDAQ
     bloc_ordres.py ....... la figure du patron, à risque réduit
     rotation_niveaux.py .. encaisser à +40 pips ; la reprise ×2 au retour
                            sur le niveau (non mesurée) est coupée ici
     chart_patterns.py .... bougies et figures classiques, sans IA
     order_flow.py ........ pression acheteuse/vendeuse tirée du flux de
                            ticks (+ carnet Binance pour la crypto)
     cot_data.py .......... positionnement des grands spéculateurs (CFTC)
     carnet_bord.py, lecons_mesurees.py, reglages_memoire.py : sa mémoire
     tableau.py ........... chaque système y laisse sa fiche d'état
     canaux_signaux.py .... les canaux Telegram que tu suis (option, 5.7)

 ── SERVEUR NEWS — Server.py (port 5001) ─────────────────────────────────
   Flux RSS + API de presse (optionnelles) + calendrier économique publié par
   l'EA. Pour chaque marché : un signal (haussier, baissier, neutre) et un
   « ne touche à rien » autour des annonces majeures. Consulté par l'EA, LE
   CERVEAU, MAMMOUTH et le serveur ML.

 ── SERVEUR ML — server_ml_v2.py (port 8001) ─────────────────────────────
   Le SEUL modèle de l'écosystème (ml_data\modele_v2.pkl, à entraîner chez
   toi : section 9). Sans modèle, il répond HOLD (neutre). Il est
   consultatif : il donne un avis, il ne commande pas.

 ── MAMMOUTH — BOT_MAMMOUTH_COMPLETE_V7.py ───────────────────────────────
   Le bot Python de scalp, avec ses « règles d'acier » (section 3). Allumé au
   démarrage ; /autotrade le coupe ou le rallume. Il lit le même
   mode_trading.txt que LE CERVEAU.

 ── DASHBOARD — dashboard\dashboard_server.py (port 8050) ─────────────────
   http://127.0.0.1:8050 : solde, equity, flottant, résultat du jour, taux de
   réussite, profit factor, drawdown, positions, historique, signaux ML et
   News, avis de l'IA, COT, état de chaque bot, consommation de tokens.
   Libre depuis ton PC ; mot de passe (DASH_PASSWORD) depuis le réseau.

 ── SNIPER ML — sniper_ml.py ─────────────────────────────────────────────
   À chaque clôture H1, il interroge le ML sur dix marchés ; si un sens
   franchit le seuil : entrée au marché, stop 1 ATR, objectif 2R, lot
   minimum, une position par marché, sortie forcée après 40 h. Livré en
   OBSERVATION : il note dans sniper_ml_journal.jsonl ce qu'il aurait pris,
   sans rien ouvrir.

 ── LES SIX YEUX — yeux\ (contrat commun : yeux\base.py) ─────────────────
   Œil 1  crypto → NAS100 ...... un mouvement anormal du BTC/ETH, le NAS100
                                 suit derrière
   Œil 2  métaux → EURUSD+ ..... un GROS mouvement de l'or ou de l'argent,
                                 l'EURUSD suit
   Œil 3  range d'ouverture .... cassure des premières bougies de la séance,
                                 stop de l'autre côté du range
   Œil 4  choc de volatilité ... une bougie qui écrase la normale : on suit
                                 son sens
   Œil 5  bloc devises ......... l'USDJPY+ suit AUDJPY+, CADJPY+, CHFJPY+,
                                 EURGBP+ et le dollar
   Œil 6  le risque ............ ne regarde que les cinq autres ; droit de
                                 veto
   Ils ne tradent pas eux-mêmes : ils rapportent au CERVEAU.

 ── L'EA « ACID IA V1 » — mt5\Experts ────────────────────────────────────
   Le moteur MQL5 de chaque graphique : modes scalp et swing, sa propre IA
   (validée par LE CERVEAU), son filtre d'annonces, ses zones (FVG, niveaux
   clés), ses stops, son break-even, son trailing — et ses propres limites de
   risque (section 3). Il publie aussi le calendrier économique pour Python.
   LE CERVEAU peut ajuster certains de ses réglages à chaud ; /presets montre
   ce qui est effectivement appliqué sur chaque graphique.

 ── LES OUTILS ───────────────────────────────────────────────────────────
   acid_center.py ........... Centre de contrôle : une fenêtre, un onglet de
                              journal par bot, démarrer/arrêter, fermeture
                              propre de MT5 avec sauvegarde des graphiques
                              (CENTRE_DE_CONTROLE.bat)
   ia_dialogue.py ........... les IA qui se parlent, en direct
   controle_avant_vol.py .... vérifie tout, ne modifie rien
                              (CONTROLE AVANT VOL.bat)
   bilan_simulation.py ...... rejoue les ordres simulés sur les vrais prix
   model_arena.py ........... l'arène : cinq IA reçoivent les mêmes données,
                              le marché les note (100 % observation)
   conseil_calculateurs.py .. deux équipes de quatre « mathématiciens » IA
                              délibèrent ; leur exécution automatique est
                              coupée (conseil_executeur.py)
   portabilite.py ........... le seul fichier qui sait où sont MT5 et ses
                              dossiers
   mt5_garde.py ............. empêche les bots de rouvrir MT5 quand tu l'as
                              fermé
   token_meter.py ........... compte les tokens IA, par fonction
   ml_v2_entrainer.py ....... entraîne le modèle ML (section 9)


================================================================================
 3. LES GARDE-FOUS DU CAPITAL — À LIRE AVANT DE PASSER EN RÉEL
================================================================================

 Ils sont en couches : si une couche lâche, la suivante tient. Les valeurs
 ci-dessous sont celles LIVRÉES dans ce dépôt (« réglages de base »). Chacune
 se change à la ligne indiquée ; le code marque « version publique » partout
 où un réglage a été posé pour ce dépôt.

 ── COUCHE 0 — LE MODE SIMULATION (mode_trading.txt) ─────────────────────
   SIMULATION (défaut) : LE CERVEAU décide pour de vrai mais n'envoie AUCUN
   ordre ; chaque ordre est écrit dans simulation_trades.jsonl. Seul le mot
   REEL dans ce fichier fait partir des ordres : fichier absent, vide ou
   illisible = SIMULATION. L'installeur remet SIMULATION à chaque fois.
   Bascule depuis Telegram : /reel (avec confirmation), /simu (immédiat).

   ⚠️ CE QUE LA SIMULATION COUVRE — ET CE QU'ELLE NE COUVRE PAS
     Couvert :
       · LE CERVEAU et tous les modules de sa boucle, y compris les ordres
         qu'il confierait à l'EA (ils sont simulés eux aussi) ;
       · les ouvertures de MAMMOUTH (il lit le même fichier) ;
       · la route /webhook du serveur News.
     PAS couvert :
       · l'EA dans MT5, pour SES propres décisions : c'est son paramètre
         TradingEnabled qui décide (livré à false) ;
       · sniper_ml.py : il a son propre interrupteur OBSERVATION (livré à
         True). Passé à False, il trade pour de VRAI, même en SIMULATION ;
       · les ordres de PILOTAGE envoyés à l'EA (pause, réglages, fermetures)
         partent vraiment ;
       · MAMMOUTH continue de gérer pour de vrai (fermer, modifier) les
         positions réelles qui portent déjà sa signature ;
       · tes trades manuels, évidemment — et le filet de stop qui les protège
         ne joue qu'en RÉEL.
     En SIMULATION, tout ce que LE CERVEAU envoie lui-même à MT5 est simulé :
     ouvertures, stops… et fermetures. /closeall et /emergency t'annoncent
     donc des fermetures qui n'ont PAS eu lieu sur tes positions réelles
     (l'EA, lui, reçoit directement l'ordre de fermer les siennes).
     Vérifie toujours dans MT5.

 ── COUCHE 1 — LE BUDGET COMMUN (projet\budget_risque.py) ───────────────
   Consulté par LE CERVEAU, MAMMOUTH et le Sniper avant leurs ouvertures au
   marché. Il compte TOUTES les positions ouvertes : bots, EA et trades
   manuels (une position sans stop compte pour sa perte flottante).
   Trois exceptions à connaître :
     · les ordres EN ATTENTE (limite, stop) du CERVEAU sont plafonnés à 1 %
       par trade, mais ne passent pas par l'enveloppe ni par les plafonds de
       positions ;
     · en mode RÉEL, les ordres que LE CERVEAU confie à l'EA (le « pont »)
       ne passent ni par l'enveloppe, ni par le filtre d'annonces, ni par
       les plafonds de positions : seul le plafond SecureLot de l'EA les
       limite (couche 4) ;
     · l'EA ne le consulte pas pour ses propres décisions : il applique ses
       propres limites (couche 4).

   RISQUE_PAR_TRADE_PCT  = 1.0   risque d'un trade (et selon l'origine de
                                 l'idée, voir couche 2)
   ENVELOPPE_TOTALE_PCT  = 5.0   ce que perdraient TOUTES les positions si
                                 tous les stops sautaient en même temps
   PERTE_JOUR_MAX_PCT    = 5.0   au-delà, plus personne n'ouvre jusqu'à
                                 demain (mesuré sur le solde, tes trades
                                 compris)
   PERTE_JOUR_MAX_EUR    = 0.0   plafond optionnel en euros (0 = désactivé)
   OBJECTIF_JOUR_PCT/EUR = 0.0   s'arrêter quand l'objectif du jour est pris
                                 (0 = désactivé)
   Un dépôt n'est pas un gain, un retrait n'est pas une perte : la référence
   du jour se recale toute seule.

 ── COUCHE 2 — LES PALIERS DE CAPITAL (projet\paliers.py) ───────────────
   Plus le compte est petit, plus l'univers est étroit. « On ne bannit aucun
   marché par opinion — seulement par arithmétique. »

   Risque permis selon l'origine de l'idée :
     RISQUE_VALIDE_PCT     = 1.0   stratégie validée hors échantillon
                                   (retour à la moyenne)
     RISQUE_PENDING_PCT    = 1.0   pièges posés d'avance, plan du jour
     RISQUE_BLOC_PCT       = 0.5   la figure du bloc d'ordres
     RISQUE_NON_VALIDE_PCT = 0.5   tout le reste (scalp IA, idées du
                                   cerveau, reprises)
   Marchés ouverts selon le capital :
     moins de 100 € ....... BTCUSD, NAS100, SP500
     de 100 à 200 € ....... + EURUSD+, USDJPY+
     200 € et plus ........ les dix marchés de l'univers
   Positions sur un même marché : 2 sous 200 €, 3 sous 400 €, 5 au-delà
   (plafonnées à 3 par le CERVEAU). Jambes par idée (TP1/TP2/TP3) : 1 sous
   200 €, 2 sous 400 €, 3 au-delà. Lot plafonné à 0,02 sous 200 €.
   Un marché trop cher pour le budget (lot minimum × stop le plus serré que le
   broker accepte) est écarté tant que le capital ne le permet pas.

 ── COUCHE 3 — LE CERVEAU (projet\ia_watchdog.py) ───────────────────────
   RISK_PCT              = 1.0   risque visé par ouverture
   RISQUE_TRADE_MAX_PCT  = 1.0   plafond dur par trade
   MAX_LOT               = 0.02  lot maximum par ordre (jusqu'à 0,20 sur un
                                 setup de forte conviction — toujours dans
                                 la limite de 1 % de risque par trade)
   MAX_POS_PAR_SYMBOLE   = 3     positions sur un même marché
   MAX_POSITIONS_COMPTE  = 30    plafond global du compte
   DAILY_DD_LIMIT_PCT    = 10.0  coupe-circuit : si les pertes RÉALISÉES par
                                 les bots dans la journée atteignent 10 % du
                                 solde du matin, plus aucune ouverture (tes
                                 trades manuels ne comptent pas ; 0 = coupé)
   CONF_PLANCHER         = 80    confiance minimale pour TOUTE ouverture des
                                 bots, quel que soit le mode
   Les modes (/modes) — démarrage en INTELLIGENT :
       Calme (Sniper) ...... seuil 78 %,  50 ouvertures/jour,  8 positions
       Intelligent ......... seuil 70 %, 150 ouvertures/jour, 12 positions
       Agressif (Rafale) ... seuil 60 %, 300 ouvertures/jour, 16 positions
     Sur le forex, le seuil du mode est relevé de 8 points. Le plancher de
     80 % s'applique de toute façon : il faut donc 80 % partout, et 86 % sur
     le forex en mode Calme. Les modes jouent surtout sur le nombre
     d'ouvertures et de positions.
     (le mode choisi survit aux redémarrages)
   NEWS_BLACKOUT_MIN     = 15    aucune entrée ±15 min autour d'une annonce
                                 majeure
   SPREAD_MAX_PART       = 0.25  le spread ne dépasse jamais le quart de la
                                 distance du stop
   CALL_SYMBOL_COOLDOWN  = 4 h   avant un nouvel « appel » sur le même marché
   CLUSTER_ENABLED       = False grappes d'entrées (jusqu'à 15 jambes, panier
                                 jusqu'à 15 % du solde) : COUPÉES
   Week-end ............. analyse seulement, aucune entrée — sauf le retour à
                          la moyenne sur BTCUSD et ETHUSD (la crypto ne dort
                          pas)
   FILET_SL_MANUEL       = True  un trade MANUEL laissé sans stop reçoit,
                                 après 90 s, un stop de survie (2 × ATR H1,
                                 jamais plus de 10 % du solde en jeu) — en
                                 RÉEL seulement
   Veto COT ............. pas contre les grands spéculateurs quand ils pèsent
                          au moins 20 % de l'intérêt ouvert dans l'autre sens
                          — sauf un « dump tactique » : momentum violent
                          confirmé, lot minimum imposé, stop de 12 pips au plus
   Œil 6 ................ veto sur l'exposition empilée (corrélations)
   Réglages proposés par l'IA (risque, lot maximum, seuils de l'EA…) : ils te
   sont SOUMIS sur Telegram, rien ne change sans ton accord — sauf si tu
   appuies sur « Oui à tout (2 h) », qui lui laisse carte blanche deux heures.

 ── COUCHE 4 — L'EA « ACID IA V1 » (paramètres, dans MT5) ────────────────
   Ils se règlent en attachant l'EA (onglet Paramètres), graphique par
   graphique. Pour ses propres décisions, l'EA applique SES limites ; il ne
   passe pas par le budget Python (mais ses positions comptent dedans). Les
   ordres que LE CERVEAU lui transmet par le pont, eux, ne rencontrent que
   le plafond SecureLot : ni ses limites journalières, ni son filtre
   d'annonces ne les arrêtent.
   TradingEnabled    = false  ← l'EA ne prend AUCUNE décision lui-même : il
                                observe et dessine. Attention : en mode RÉEL,
                                les ordres que LE CERVEAU lui confie passent
                                quand même (par le « pont »).
   AcidBotEnabled    = true     le pont avec LE CERVEAU. À false, plus rien ne
                                passe : ni ordres, ni fermetures, ni pauses,
                                ni réglages (/stop_ea ne marche plus).
   RiskLevel         = Normal → RiskPctNormal = 1 %
                                (Safe 0,5 % · Aggressive 2 %)
   Plafond de tout ordre (SecureLot) : 1 % du solde. Si seul le lot minimum
   est possible, il est accepté jusqu'à 2 % du solde, sinon REFUSÉ à voix
   haute. (Valeurs de base réglables à chaud : /presets montre l'état réel.)
   MaxDailyLossPct   = 5      perte maximale du jour, en % (0 = désactivé)
   MaxDailyLossEur   = 0      plafond en euros (0 = désactivé)
   KillSwitchOwnPct  = 15     dernier rempart, sur ses PROPRES positions
   MaxDrawdownPct    = 15     drawdown maximal
   MaxPositions      = 6      positions simultanées
   MaxTradesPerDay   = 100    entrées par jour et par graphique
   MaxSpreadPips     = 20     au-delà, pas d'entrée
   MinMarginPct      = 200    marge libre minimale, en %
   NoWeekendTrading  = true   NewsFilterEnabled = true (±15 min)
   ⚠️ RepriseEnabled = true : si tu coupes à la main un trade auquel l'EA
      croyait fort, il le REPREND. Mets false si tu veux garder la main.
   ⚠️ AICanTrade = true : l'IA du graphique peut poser des ordres en attente
      et fermer, toujours sous ces mêmes limites.

 ── COUCHE 5 — MAMMOUTH (projet\BOT_MAMMOUTH_COMPLETE_V7.py) ────────────
   RISK_PCT_DEFAULT          = 2.0   plafond propre par trade… que le budget
                                     commun ramène à 0,5 % (scalp IA)
   DAILY_DRAWDOWN_LIMIT_PCT  = 10.0  −10 % dans la journée : il ferme tout
   MAX_LOT_HARD              = 0.02  lot maximum
   MAX_POSITIONS             = 6     positions simultanées
   TILT_LOSSES / TILT_PAUSE_MIN = 3 / 60   3 pertes de suite → 60 min de
                                           pause (anti-tilt)
   SYMBOL_COOLDOWN_MIN       = 15    avant de retoucher un même marché
   CYCLE_COOLDOWN_S          = 60    entre deux re-entrées sur un niveau
   MIN_HOLD_MIN              = 5     un gain ne s'encaisse qu'après 5 min
   En SIMULATION, ses ouvertures sont simulées ; ses fermetures et
   modifications, elles, restent réelles (voir couche 0).

 ── LES MODULES COUPÉS EXPRÈS — lis leur en-tête avant de les rallumer ───
   conseil_executeur.py  ACTIF = False   exécuterait les ordres du conseil
                                         des calculateurs SANS filtre ni
                                         budget commun
   pisteur_davo.py       ACTIF = False   suit un canal de signaux précis, à
                                         lot fixe 0,05, hors budget commun
   rotation_niveaux.py   MAX_REPRISES = 0   reprises ×2 sur un niveau
                                         (non mesurées, sans contrôle de
                                         l'enveloppe ni du coupe-circuit)
   ia_watchdog.py        CLUSTER_ENABLED = False   les grappes d'entrées
   sniper_ml.py          OBSERVATION = True        voir couche 0

 ── DEUX CONSEILS ────────────────────────────────────────────────────────
   · Pour durcir : baisse d'abord ENVELOPPE_TOTALE_PCT et PERTE_JOUR_MAX_PCT
     (budget_risque.py) : ce sont eux qui protègent le TOTAL.
   · N'augmente jamais un plafond pour « rattraper » une journée. C'est
     exactement ce que ces garde-fous empêchent.


================================================================================
 4. CE QU'IL TE FAUT AVANT D'INSTALLER
================================================================================

   · Windows 10 ou 11, 64 bits, et environ 3 Go libres.
   · Python 3.12.10, 64 bits — la série 3.12 exactement (python.org).
     Pendant l'installation :
       ☑ « Add python.exe to PATH »      (première page)
       ☑ « tcl/tk and IDLE »             (« Customize installation » ; coché
                                          par défaut — ne le décoche pas)
     Pourquoi 3.12 : le paquet MetaTrader5 ne publie de roue que pour cp312,
     et les versions des bibliothèques ML sont épinglées.
   · MetaTrader 5, installé depuis le site de ton broker (Vantage
     recommandé), lancé UNE fois, connecté à ton compte, puis refermé : c'est
     ce premier lancement qui crée le dossier où l'installeur posera l'EA.
   · Un compte Telegram (pour créer ton bot) et au moins UNE clé d'IA.


================================================================================
 5. OÙ COLLER TES IDENTIFIANTS
================================================================================

 Tout tient en UN fichier : le coffre, secrets_acid.py. Aucune clé n'est
 écrite ailleurs dans le code. Ce fichier n'est jamais publié (.gitignore).

 ── 5.1  CRÉER TON COFFRE ────────────────────────────────────────────────
   1. Dans le dossier secrets\, copie secrets_acid.exemple.py et renomme la
      copie : secrets_acid.py
      (si Windows masque les extensions, vérifie que le fichier ne s'appelle
       pas « secrets_acid.py.txt »)
   2. Ouvre-le avec le Bloc-notes (clic droit ▸ Ouvrir avec ▸ Bloc-notes).
   3. Remplace chaque A_REMPLIR_… et chaque 0 par TA valeur :
        · garde les guillemets là où il y en a :  TELEGRAM_TOKEN = "123:ABC…"
        · n'en mets PAS autour des nombres :     ADMIN_ID = 123456789
   4. Enregistre (encodage UTF-8, celui par défaut du Bloc-notes).

   L'installeur copie ce fichier dans C:\AcidBot\BOT COMPLETO\. Une fois
   installé, c'est CE fichier-là qu'il faut modifier, puis redémarrer
   l'écosystème (ARRETER puis DEMARRER).

 ── 5.2  CE QUE CONTIENT LE COFFRE ───────────────────────────────────────
   VARIABLE                   OBLIGATOIRE   OÙ L'OBTENIR / QUOI METTRE
   ─────────────────────────  ────────────  ────────────────────────────────
   TELEGRAM_TOKEN             OUI           @BotFather (5.3)
   TELEGRAM_CHAT              OUI           ton identifiant Telegram, ENTRE
                                            guillemets (5.3)
   ADMIN_ID                   OUI           le MÊME identifiant, SANS
                                            guillemets (5.3)
   MT5_LOGIN                  OUI           ton numéro de compte MT5, sans
                                            guillemets (5.4)
   MT5_PASSWORD               OUI           le mot de passe de TRADING (5.4)
   MT5_SERVER                 OUI           le nom exact du serveur (5.4)
   ANTHROPIC_API_KEY          au moins      console.anthropic.com (5.5)
   MAMMOUTH_API_KEY           UNE des       mammouth.ai (5.5)
   MISTRAL_API_KEY            trois         console.mistral.ai (5.5)
   ANTHROPIC_API_KEY_BACKUP   non           2e clé Anthropic ; sinon ""
   MAMMOUTH_API_KEY_2         non           pas utilisée pour l'instant :
                                            laisse-la telle quelle
   TG_API_ID, TG_API_HASH,    non           seulement pour lire des canaux
   TG_PHONE                                 de signaux (5.7)
   API_KEYS (7 clés presse)   non           sites gratuits (5.6)
   ADMIN_PASSWORD             conseillé     un mot de passe que TU inventes :
                                            il protège la commande admin du
                                            serveur News
   DASH_PASSWORD              conseillé     un mot de passe que TU inventes :
                                            il ouvre le dashboard depuis le
                                            réseau ou le lien public. Tant
                                            qu'il commence par A_REMPLIR, le
                                            dashboard ne s'ouvre QUE depuis
                                            ton PC.

 ── 5.3  TELEGRAM, PAS À PAS ─────────────────────────────────────────────
   Ton bot :
     1. Dans Telegram, ouvre @BotFather, envoie /newbot, choisis un nom puis
        un identifiant qui finit par « bot ».
     2. BotFather te donne un jeton du genre 123456789:AAH…  →  TELEGRAM_TOKEN
     3. Ouvre la conversation avec TON bot et appuie sur « Démarrer » : un bot
        ne peut pas écrire à quelqu'un qui ne lui a jamais parlé.
   Ton identifiant (un nombre) :
     · le plus simple : écris à @userinfobot, il te répond « Id: 123456789 » ;
     · ou : envoie un message à ton bot, puis ouvre dans un navigateur
       https://api.telegram.org/bot<TON_JETON>/getUpdates
       et lis le nombre après "from":{"id":
   Mets-le deux fois :
       TELEGRAM_CHAT = "123456789"      ← avec guillemets
       ADMIN_ID      = 123456789        ← sans guillemets
   Le bot n'obéit QU'À ADMIN_ID : personne d'autre ne peut le piloter.
   (L'EA a aussi des champs Telegram dans ses paramètres : laisse-les, ils
    ne servent plus — c'est LE CERVEAU qui parle.)

 ── 5.4  TON COMPTE METATRADER 5 ─────────────────────────────────────────
     MT5_LOGIN    = 12345678                 ← sans guillemets
     MT5_PASSWORD = "ton mot de passe"       ← le mot de passe de TRADING,
                                                pas le mot de passe
                                                investisseur (lecture seule)
     MT5_SERVER   = "NomExactDuServeur"      ← tel que MT5 l'affiche dans
                                                Fichier ▸ Se connecter à un
                                                compte de trading
   Connecte-toi AUSSI à ce compte dans le terminal MT5 lui-même : les bots
   travaillent à travers le terminal ouvert. Commence par un compte DÉMO.

 ── 5.5  LES CLÉS D'IA (au moins une) ────────────────────────────────────
   · mammouth.ai — un forfait qui donne accès à plusieurs modèles (Claude,
     GPT, Gemini, Mistral, Grok…). C'est la porte PRINCIPALE du CERVEAU, de
     l'IA de chaque graphique, de l'arène et du conseil des calculateurs.
     Recommandé.
   · console.anthropic.com ▸ API Keys — Claude. Le secours du CERVEAU et le
     moteur de MAMMOUTH. Crée la clé DANS un espace de travail (workspace) :
     c'est ce qui marche partout. ANTHROPIC_WORKSPACE_ID (ligne prévue,
     commentée, dans le coffre) ne dépanne qu'une clé d'organisation, et
     seulement pour LE CERVEAU.
   · console.mistral.ai — la troisième porte, quand les deux autres sont
     fermées (il existe une offre gratuite).
   Avec une seule clé, l'essentiel fonctionne ; les fonctions qui ne
   trouvent pas leur IA le disent dans les journaux.
   💸 Ces API sont payantes à l'usage (sauf offres gratuites) : /tokens te
   montre chaque jour qui consomme quoi.

 ── 5.6  LES CLÉS DE PRESSE (toutes facultatives) ────────────────────────
   Dans le dictionnaire API_KEYS du coffre. Sans elles, le serveur News vit
   sur ses flux RSS ; chaque clé ajoute une source. Une source que tu
   n'utilises pas : laisse son A_REMPLIR_… tel quel, elle est ignorée sans
   bruit. Une clé renseignée mais refusée (périmée, quota) déclenche une
   alerte Telegram par jour, jusqu'à ce que tu la changes ou la retires.
     GNEWS_API_KEY ........ gnews.io
     MEDIASTACK_API_KEY ... mediastack.com
     GUARDIAN_API_KEY ..... open-platform.theguardian.com
     FINNHUB_API_KEY ...... finnhub.io
     THENEWSAPI_KEY ....... thenewsapi.com
     CURRENTS_API_KEY ..... currentsapi.services
     NEWSAPI_KEY .......... newsapi.org

 ── 5.7  LES CANAUX DE SIGNAUX TELEGRAM (facultatif) ─────────────────────
   LE CERVEAU peut lire les canaux de signaux que tu suis, en lecture seule,
   avec TON compte Telegram (un bot ne peut pas lire un canal privé). Les
   signaux y servent d'avis externe ; il ne les exécute jamais tout seul.
     1. https://my.telegram.org ▸ API development tools → api_id et
        api_hash  →  TG_API_ID (nombre, sans guillemets), TG_API_HASH
        (texte, avec), TG_PHONE (ton numéro au format +33…, avec).
     2. Dans projet\canaux_signaux.py (une fois installé :
        C:\AcidBot\BOT COMPLETO\canaux_signaux.py), ajoute tes canaux dans
        la liste CANAUX, un par ligne :
            CANAUX = [
                -1001234567890,                 # identifiant numérique
                "@nom_du_canal",                # canal public
                "https://t.me/+lien_invitation",  # canal privé
            ]
        Liste vide = le module tourne mais n'écoute rien.
     3. Première connexion, une seule fois, dans une console :
            cd /d "C:\AcidBot\BOT COMPLETO"
            python canaux_signaux.py
        Telegram t'envoie un code : tape-le (et ton mot de passe de
        vérification en deux étapes si tu en as un). Ctrl+C quand c'est fait.
     ⚠️ Cela crée oeil_telethon.session : ce fichier donne un accès COMPLET à
        ton compte Telegram. Ne le partage jamais (il est dans .gitignore).
     Les vocaux sont transcrits par faster-whisper (lourd, environ 1,5 Go).
     Si tu ne l'installes pas, mets ECOUTER_MEDIAS = False dans le même
     fichier.

 ── 5.8  ET C'EST TOUT ───────────────────────────────────────────────────
   Il n'y a rien d'autre à coller nulle part. Pour vérifier la syntaxe de ton
   coffre une fois installé :
       cd /d "C:\AcidBot\BOT COMPLETO"
       python -c "import secrets_acid; print('coffre lisible')"


================================================================================
 6. INSTALLATION
================================================================================

   1. Télécharge ce dépôt (bouton « Code ▸ Download ZIP » sur GitHub, ou
      git clone) et décompresse-le, par exemple dans
      C:\ACID_colis.
   2. Remplis ton coffre (section 5) : secrets\secrets_acid.py.
   3. MetaTrader 5 FERMÉ, ouvre une console dans le dossier du dépôt
      (dans l'Explorateur : tape « cmd » dans la barre d'adresse, Entrée).
   4. Essai à blanc (rien n'est écrit) :
          python ACID_INSTALL.py --blanc
   5. Installation pour de vrai :
          python ACID_INSTALL.py
      Autre dossier que C:\AcidBot\BOT COMPLETO :
          python ACID_INSTALL.py --vers "D:\MonDossier\ACID"

   Ce que fait l'installeur, dans l'ordre :
     0. vérifie le colis (et te prévient si secrets_acid.py manque) ;
     1. vérifie Python 3.12 et tkinter ;
     2. trouve TON terminal MT5 (via portabilite.py) ;
     3. choisit la destination ;
     4. installe les paquets Python épinglés (projet\requirements.txt) ;
     5. pose le projet et ton coffre ;
     6. répare les chemins gravés en dur (une copie « .avant_migration » de
        chaque fichier touché est gardée) ;
     7. pose l'EA dans ton terminal ;
     8. compile l'EA (metaeditor64) ;
     9. force le mode SIMULATION ;
    10. vérifie que les ports 5001, 8001, 8050, 8060 et 8061 sont libres.
   Il ne lance AUCUN bot, n'ouvre pas MT5 et ne passe jamais en réel.
   Trois avertissements « absent du colis » (presets, pont, graphiques) sont
   normaux dans cette version publique.

   Sans faster-whisper (≈1,5 Go) : avant de lancer l'installation, mets un #
   devant les lignes faster-whisper et imageio-ffmpeg de
   projet\requirements.txt, puis ECOUTER_MEDIAS = False (section 5.7).

   Les deux lanceurs (DEMARRER_ECOSYSTEME.bat et DEMARRAGE_AUTO.bat)
   trouvent MT5 tout seuls, via portabilite.py : aucun chemin à modifier.

   ── ENSUITE, DANS METATRADER 5 (ce que l'installeur ne peut pas faire) ──
   a. Outils ▸ Options ▸ Expert Advisors ▸ ☑ Autoriser WebRequest pour les
      URL listées, et ajoute :
          http://127.0.0.1:5001     (serveur News)
          http://127.0.0.1:8001     (serveur ML)
          http://127.0.0.1:8060     (LE CERVEAU)
      Sans ça, l'EA reçoit l'erreur 4014 à chaque appel et reste muet.
   b. Le bouton « Algo Trading » de la barre d'outils doit être VERT.
   c. Observation du marché (Ctrl+M) : affiche ces symboles, noms EXACTS
      (chez Vantage, le « + » fait partie du nom) :
          NAS100  BTCUSD  XAUUSD+  USDX  SP500  CL-OIL  EURUSD+
          XAGUSD  USDJPY+  GBPUSD+  ETHUSD
      (+ AUDJPY+, CADJPY+, CHFJPY+, EURGBP+ pour que l'Œil 5 voie tout.)
      Ouvre un graphique H1 de chacun et fais défiler vers la gauche pour
      que MT5 télécharge l'historique.
   d. Pare-feu Windows : autorise python.exe et pythonw.exe (réseau privé).
   e. Attache l'EA « ACID IA V1 » (Navigateur ▸ Expert Advisors) sur les
      graphiques des marchés que tu veux lui confier — l'auteur
      l'utilisait surtout en M5. Laisse TradingEnabled = false tant que tu
      observes.


================================================================================
 7. PREMIER DÉMARRAGE (EN SIMULATION)
================================================================================

   Tout se passe dans C:\AcidBot\BOT COMPLETO.

   1. Ouvre MT5 et connecte-toi (démo).
   2. Dans une console :
          cd /d "C:\AcidBot\BOT COMPLETO"
          python portabilite.py
      → il doit trouver ton terminal et ses dossiers.
   3. Double-clic sur « CONTROLE AVANT VOL.bat » : il passe tout en revue
      (code, broker, symboles, sécurité, services, EA) et ne modifie rien.
      Avant le démarrage, « services éteints » et « modèle ML introuvable »
      sont normaux.
   4. (Conseillé) entraîne le ML : section 9.
   5. Double-clic sur DEMARRER_ECOSYSTEME.bat : MT5, News, ML, LE CERVEAU,
      MAMMOUTH, dashboard, Sniper et les six yeux démarrent, sans aucune
      fenêtre.
   6. Sur Telegram, écris à ton bot :
          /start   puis   /help
          /mode        → doit répondre SIMULATION
          /gardefous   → l'état de tous les garde-fous
          /vois        → ce qu'il voit (bots, experts, graphiques, serveurs)
   7. Le dashboard : http://127.0.0.1:8050
      Les journaux de chaque bot : CENTRE_DE_CONTROLE.bat
   8. Laisse tourner. Après quelques jours :
          python bilan_simulation.py 1000
      (1000 = ton capital de départ) rejoue tous les ordres simulés sur les
      vrais prix : combien vaudrait le compte, quelle a été la pire perte,
      est-ce qu'il saigne lentement ou est-ce qu'il gagne.


================================================================================
 8. PASSER EN RÉEL — SEULEMENT QUAND TOUT EST VERT
================================================================================

   ☐ Plusieurs jours de SIMULATION, sur un compte DÉMO, et un bilan
     (bilan_simulation.py) que tu comprends.
   ☐ CONTROLE AVANT VOL vert de bout en bout.
   ☐ La section 3 relue ; les plafonds réglés sur ce que tu acceptes de
     perdre en une journée — pas sur ce que tu espères gagner.
   ☐ Puis, sur Telegram : /reel → confirme. /mode pour vérifier.
     Retour instantané en sécurité : /simu.
   ☐ L'EA : seulement si tu veux qu'il trade lui aussi, passe TradingEnabled
     à true dans ses paramètres (F7 sur le graphique ▸ Paramètres).
   ☐ Le Sniper ML : seulement après avoir lu sniper_ml_journal.jsonl,
     OBSERVATION = False dans sniper_ml.py.
   ☐ Les modules coupés exprès (section 3) : lis leur en-tête d'abord.


================================================================================
 9. ENTRAÎNER LE ML
================================================================================

   MT5 ouvert et connecté, historique des symboles téléchargé (6.c) :
       cd /d "C:\AcidBot\BOT COMPLETO"
       python ml_v2_entrainer.py            tout : données, fidélité, modèle
       python ml_v2_entrainer.py 5000       plus rapide, pour tester
       python ml_v2_entrainer.py --sans-donnees   réentraîne sur le jeu déjà
                                                  généré
   Il génère le jeu de données depuis les bougies H1/H4 de ton broker (spread
   réel déduit), vérifie que ses formules sont identiques à celles du
   serveur, puis entraîne. Le modèle n'est ENREGISTRÉ (ml_data\modele_v2.pkl)
   que s'il passe chaque étape du protocole (section 1) ; sinon rien n'est
   gardé. Redémarre ensuite l'écosystème : le serveur 8001 le charge.
   Compte du temps (et de la mémoire) pour un entraînement complet.


================================================================================
 10. LES COMMANDES TELEGRAM
================================================================================

   /start, /help .... ouvrir la conversation, la liste des commandes
   /vois ............ ce que voit LE CERVEAU (bots, experts, graphiques,
                      serveurs)
   /status .......... compte + positions par système
   /positions ....... positions ouvertes (avec boutons de fermeture)
   /mode ............ SIMULATION ou RÉEL, et bascule
   /reel ............ passage en réel — TOUJOURS avec confirmation
   /simu ............ retour en simulation, immédiat
   /modes ........... stratégie : Calme (Sniper) / Intelligent / Agressif
   /gardefous ....... l'état LIVE de tous les garde-fous
   /presets ......... les réglages effectifs de l'EA sur chaque graphique
   /signals ......... signaux ML en direct
   /news ............ l'actualité des marchés
   /briefing ........ briefing marché rédigé par l'IA
   /plan ............ plan de la journée (TP1/TP2/TP3, stop, break-even) ;
                      « /plan force » pour le refaire
   /figures ......... figures chartistes et bougies détectées (M15)
   /cot ............. positionnement des grands spéculateurs (CFTC)
   /spt ............. tous les signaux des canaux suivis, en un bloc
   /conseil [question]  l'avis du conseiller IA, sur les données live
   /lecon <texte> ... enseigne une leçon au trader IA ; /lecon seul = les
                      relire
   /youtu <lien> .... il écoute une vidéo YouTube et en tire des leçons
                      (« /youtu <lien> images » : il regarde aussi l'écran)
   /tokens .......... consommation de tokens du jour, par fonction
   /dashboard ....... liens vers le dashboard (local et public)
   /autotrade [on|off]  allumer / couper MAMMOUTH
   /stop_ea ......... demande à l'EA de fermer toutes SES positions
   /closeall ........ fermer toutes les positions du compte, prévenir l'EA
                      et mettre MAMMOUTH en pause (*)
   /emergency ....... arrêt d'urgence : exactement le même geste (*)
   /errors .......... dernières alertes et erreurs
   /resetai ......... forcer la reconnexion des IA après un quota
   /clear ........... effacer le contexte de la conversation
   Et surtout : écris-lui librement. Il répond en trader, avec le contexte du
   marché.
   (*) en SIMULATION, voir l'avertissement de la section 3, couche 0.


================================================================================
 11. OPTIONS
================================================================================

 ── LIEN PUBLIC DU DASHBOARD (Cloudflare, sans compte) ───────────────────
   1. Choisis d'abord un vrai DASH_PASSWORD dans le coffre (section 5.2).
   2. Télécharge cloudflared pour Windows (dépôt GitHub cloudflare/
      cloudflared, fichier cloudflared-windows-amd64.exe), renomme-le
      cloudflared.exe et pose-le dans C:\AcidBot\BOT COMPLETO\dashboard\.
   3. Lance dashboard\START_TUNNEL.bat : il affiche un lien
      https://….trycloudflare.com. Les visiteurs doivent entrer
      DASH_PASSWORD ; le chat des bots leur reste fermé. Une fois ton mot de
      passe choisi, une seule route s'ouvre sans lui : la question au trader
      IA, bridée par LE CERVEAU (5 questions par heure et par adresse, 150
      par jour) — elle consomme tes tokens.

 ── REPRISE APRÈS CRASH (redémarrage automatique) ────────────────────────
   DEMARRER_ECOSYSTEME.bat pose un témoin (ecosysteme_actif.flag) que LE
   CERVEAU rafraîchit en continu ; ARRETER_ECOSYSTEME.bat l'efface. Au
   démarrage de Windows, demarrage_auto.vbs ne relance tout QUE si le témoin
   a moins de 15 minutes — donc seulement si la machine est tombée pendant
   que l'écosystème tournait. Pour l'activer, crée une tâche planifiée :
       schtasks /Create /TN "ACID reprise apres crash" /SC ONLOGON
                /TR "wscript.exe \"C:\AcidBot\BOT COMPLETO\demarrage_auto.vbs\""
   (une seule ligne ; ou Planificateur de tâches ▸ Créer une tâche ▸
    déclencheur « À l'ouverture de session » ▸ action wscript.exe avec le
    chemin du .vbs en argument.)

 ── LE CALENDRIER ÉCONOMIQUE HISTORIQUE ──────────────────────────────────
   Le conseil des calculateurs (et le pisteur DAVO) lisent
   acid_calendrier_histo.csv. Pour le produire :
     1. MT5 ▸ Fichier ▸ Ouvrir le dossier des données ▸ MQL5\Scripts :
        copie-y mt5\Scripts\ACID_ExportCalendrier.mq5.
     2. Compile-le (MetaEditor, F7), puis dans MT5 : Navigateur ▸ Scripts ▸
        double-clic sur ACID_ExportCalendrier.
     Il lit le calendrier, écrit le CSV dans MQL5\Files, et s'arrête. Il ne
     trade pas. Relance-le de temps en temps : il exporte aussi les 30 jours
     à venir.

 ── L'ARÈNE DES MODÈLES ──────────────────────────────────────────────────
   START_ARENA.bat (ou python model_arena.py) : cinq IA reçoivent les mêmes
   données de marché, décident, et le marché les note. 100 % observation.
       python model_arena.py once     un seul tour
       python model_arena.py stats    le classement
   Demande une clé mammouth.ai.

 ── LE CONSEIL DES CALCULATEURS ──────────────────────────────────────────
   Deux équipes de quatre spécialistes IA (via mammouth.ai) délibèrent sur
   les prix, les positions, le calendrier, et peuvent chercher sur Internet.
       python conseil_calculateurs.py duel "on achète quoi ?"
   Leur exécution automatique (conseil_executeur.py) est coupée.


================================================================================
 12. CE QUI N'EST PAS DANS CE DÉPÔT, ET CE QUI A CHANGÉ
================================================================================

 ── PAS DANS LE DÉPÔT ────────────────────────────────────────────────────
   · Tes secrets : le coffre et la session Telegram (jamais publiés).
   · Les modèles ML entraînés et les jeux de données : ils se fabriquent chez
     toi (section 9).
   · Les journaux, états, mémoires et historiques (json, jsonl, log) : ils
     naissent au premier démarrage. Chaque lecture d'état tolère un fichier
     absent.
   · Les profils de graphiques, presets et fichiers du pont MT5 de l'auteur.
   · cloudflared.exe (à télécharger, section 11).
   · L'ancien code mort et la documentation PDF.
   · Les commentaires du code ont été « neutralisés » : montants et soldes
     remplacés par « X € », citations personnelles par « «…» », numéros de
     positions retirés. Le code lui-même est resté identique — vérifié
     automatiquement — à l'exception des réglages et correctifs ci-dessous et
     de quelques textes (montants retirés de deux consignes données à l'IA,
     noms des canaux de signaux suivis par l'auteur).

 ── CHANGÉ PAR RAPPORT À LA VERSION D'ORIGINE ────────────────────────────
   (repérable dans le code par la mention « version publique »)
   · Risque de base : 1 %/trade, enveloppe 5 %, perte du jour 5 % (budget
     commun), paliers 1 % / 0,5 %, coupe-circuit du CERVEAU réactivé à 10 %.
   · Les « vannes » ouvertes par l'auteur sont refermées : paliers de capital
     rétablis, pause de 4 h par marché, grappes coupées, et dans MAMMOUTH
     15 min par marché et 60 s entre deux re-entrées.
   · Démarrage en mode Intelligent (au lieu d'Agressif).
   · EA livré avec TradingEnabled = false, risque Normal à 1 %, perte du jour
     5 %, dernier rempart à 15 %, plafond SecureLot à 1 % (2 % pour un lot
     minimum ; 2 % et 8 % chez l'auteur).
   · Coupés : l'exécuteur automatique du conseil, le pisteur DAVO et les
     reprises ×2 de la rotation (ils contournent le budget commun).
   · SIMULATION étendue : les ordres que LE CERVEAU confie à l'EA sont
     désormais simulés eux aussi, et la route /webhook du serveur News
     refuse tout ordre tant que le mode n'est pas RÉEL.
   · Canaux de signaux : liste vide, et une liste vide n'écoute RIEN (au
     lieu de toutes tes conversations).
   · Serveur News : écoute locale seulement (127.0.0.1) — sa route /webhook
     passe des ordres sans mot de passe. Une clé de presse non renseignée est
     ignorée au lieu de déclencher des alertes.
   · Dashboard : aucun accès réseau tant que DASH_PASSWORD n'est pas choisi.
   · Les lanceurs et les dossiers du terminal MT5 sont trouvés par
     portabilite.py : plus aucun dossier utilisateur gravé dans le code. Le
     chemin d'installation par défaut de Vantage, encore écrit dans quelques
     fichiers, est réécrit par l'installeur (étape 6).
   · /reel affiche les vrais plafonds au moment de passer en réel.
   · Correctif : _client_anthropic() s'appelait lui-même (récursion infinie
     quand ANTHROPIC_WORKSPACE_ID n'est pas défini).


================================================================================
 13. DÉPANNAGE
================================================================================

   « python n'est pas reconnu », ou le Microsoft Store s'ouvre
       → Réinstalle Python 3.12.10 en cochant « Add python.exe to PATH ».
         Désactive aussi Paramètres ▸ Applications ▸ Alias d'exécution
         d'application ▸ python.exe / python3.exe.

   pip échoue sur MetaTrader5
       → Mauvaise version de Python : il faut la 3.12, en 64 bits.

   « tkinter ABSENT »
       → Relance l'installeur Python ▸ Modify ▸ coche « tcl/tk and IDLE ».

   « aucun dossier terminal »
       → Lance MT5 une fois, connecte-toi, ferme-le, relance l'installeur.

   Plusieurs MT5 installés, ou un autre broker que Vantage
       → portabilite.py : modifie BROKER = "Vantage", ou force le chemin :
             setx ACID_MT5_TERMINAL "C:\Users\<toi>\AppData\Roaming\
                  MetaQuotes\Terminal\<GUID>"     (une seule ligne)
             setx ACID_MT5_EXE "C:\…\terminal64.exe"
         puis ouvre une NOUVELLE console.

   « symbole INTROUVABLE »
       → Affiche-le dans l'Observation du marché (6.c). Chez un autre broker
         les noms diffèrent (XAUUSD au lieu de XAUUSD+, US100 au lieu de
         NAS100…) : il faut alors les adapter dans le code (paliers.py,
         yeux\, l'EA…). C'est le vrai chantier d'un changement de broker.

   L'EA affiche l'erreur 4014
       → URL WebRequest non autorisées (6.a).

   « port occupé »
       → netstat -ano | findstr "5001 8001 8050 8060 8061"
         8061 est le verrou d'instance unique du CERVEAU : s'il est pris, un
         CERVEAU tourne déjà, et le nouveau se ferme tout seul.

   Le bot ne répond pas sur Telegram
       → TELEGRAM_TOKEN et ADMIN_ID corrects ? As-tu appuyé sur « Démarrer »
         dans la conversation avec ton bot ? Il n'obéit qu'à ADMIN_ID.
         Regarde ia_watchdog.log.

   Les IA se taisent (« quota », « 429 », « 401 »)
       → /resetai ; vérifie tes clés ; /tokens pour la consommation. Clé
         Anthropic d'organisation refusée : crée plutôt la clé dans un espace
         de travail (ANTHROPIC_WORKSPACE_ID ne dépanne que LE CERVEAU).

   MT5 se rouvre tout seul
       → Un bot tourne encore : ARRETER_ECOSYSTEME.bat, ou le bouton de
         fermeture propre de MT5 dans le Centre de contrôle.

   Tout arrêter, vraiment
       → ARRETER_ECOSYSTEME.bat : arrête les bots (python ET pythonw), le
         Centre, le tunnel, et efface le témoin de reprise.

   Les journaux
       → Dans C:\AcidBot\BOT COMPLETO : ia_watchdog.log, mammouth_v7.log,
         ml_server.log… ou en onglets dans le Centre de contrôle.


================================================================================
 14. LICENCE
================================================================================

   GPL-3.0 — voir LICENSE. Tu peux utiliser, étudier, modifier et
   redistribuer ce code. Si tu distribues une version modifiée, elle reste
   sous GPL-3.0, avec son code source. Le logiciel est fourni SANS AUCUNE
   GARANTIE (articles 15 et 16 de la licence) : tu restes seul responsable de
   ce que tu fais de ton argent.

   Bon trading — et commence en démo. 🧪
