# -*- coding: utf-8 -*-
# =====================================================
#  🔐 SECRETS ACID — LE COFFRE-FORT (modèle à remplir)
#
#  1. Copie ce fichier, DANS CE MÊME DOSSIER secrets\, et renomme la copie
#     secrets_acid.py  (ACID_INSTALL.py la posera tout seul à côté des
#     programmes). Déjà installé ? Modifie directement
#     C:\AcidBot\BOT COMPLETO\secrets_acid.py  puis redémarre l'écosystème.
#  2. Remplace chaque A_REMPLIR_... (et chaque 0) par TA valeur. Garde les
#     guillemets là où il y en a ; n'en ajoute pas autour des nombres.
#  3. Ne publie JAMAIS secrets_acid.py : il est ignoré par git (.gitignore).
#
#  Tout l'écosystème lit ses clés ICI et nulle part ailleurs :
#   - bot Python & serveur News : import direct
#   - LE CERVEAU & dashboard : lecture du texte de ce fichier
#  Garde le format  NOM = valeur  (une valeur par ligne).
#  Le détail de chaque valeur (où l'obtenir, obligatoire ou non) : README.txt, section 5.
# =====================================================

# --- Telegram COMPTE PERSO (lecture des canaux de signaux — OPTIONNEL) ---
# À créer sur https://my.telegram.org -> API development tools (2 min, gratuit).
# Sert UNIQUEMENT à lire les canaux de signaux que tu suis (Telethon, lecture seule).
# Laisse tel quel si tu n'utilises pas les canaux de signaux.
# TG_API_ID = un nombre · TG_API_HASH = un texte · TG_PHONE = ton numéro, ex. +33612345678
TG_API_ID   = 0
TG_API_HASH = "A_REMPLIR_TG_API_HASH"
TG_PHONE    = "A_REMPLIR_TG_PHONE"

# --- Telegram : le bot qui te parle (OBLIGATOIRE) ---
# TELEGRAM_TOKEN : donné par @BotFather quand tu crées ton bot.
# TELEGRAM_CHAT  : ton identifiant de chat, ENTRE GUILLEMETS (voir README.txt).
# ADMIN_ID       : le MÊME identifiant, en nombre, SANS guillemets.
TELEGRAM_TOKEN = "A_REMPLIR_TELEGRAM_TOKEN"
TELEGRAM_CHAT  = "0"
ADMIN_ID       = 0

# --- IA (au moins UNE clé ; mammouth.ai + Anthropic recommandés) ---
# Clé Anthropic refusée parce que créée au niveau de l'ORGANISATION ? Crée-la
# plutôt dans un espace de travail (c'est la seule solution pour MAMMOUTH), ou,
# pour LE CERVEAU seulement, retire le # de la ligne suivante :
# ANTHROPIC_WORKSPACE_ID = "wrkspc_A_REMPLIR"
ANTHROPIC_API_KEY        = "A_REMPLIR_ANTHROPIC_API_KEY"   # console.anthropic.com : secours du CERVEAU, moteur de MAMMOUTH
ANTHROPIC_API_KEY_BACKUP = ""   # optionnel : clé de secours (laisse vide sinon)
MAMMOUTH_API_KEY         = "A_REMPLIR_MAMMOUTH_API_KEY"    # mammouth.ai : porte principale du CERVEAU, arène, conseil
MAMMOUTH_API_KEY_2       = "A_REMPLIR_MAMMOUTH_API_KEY_2"  # non utilisée pour l'instant : laisse tel quel
MISTRAL_API_KEY          = "A_REMPLIR_MISTRAL_API_KEY"     # console.mistral.ai : 3e porte, quand les deux autres sont fermées

# --- MT5 : TON compte chez TON broker (OBLIGATOIRE) ---
# MT5_LOGIN    : ton numéro de compte, en nombre, SANS guillemets.
# MT5_PASSWORD : le mot de passe de TRADING du compte (pas le mot de passe investisseur).
# MT5_SERVER   : le nom EXACT du serveur, tel que MT5 l'affiche à la connexion.
# Conseil : commence avec un compte DÉMO.
MT5_LOGIN    = 0
MT5_PASSWORD = "A_REMPLIR_MT5_PASSWORD"
MT5_SERVER   = "A_REMPLIR_MT5_SERVER"

# --- Serveur News : clés des APIs presse (gratuites, chacune OPTIONNELLE) ---
# Une source que tu n'utilises pas : laisse son A_REMPLIR_... tel quel, elle est
# ignorée sans alerte. Une clé renseignée mais refusée déclenche une alerte Telegram.
API_KEYS = {
    "GNEWS_API_KEY":      "A_REMPLIR_GNEWS_API_KEY",        # gnews.io
    "MEDIASTACK_API_KEY": "A_REMPLIR_MEDIASTACK_API_KEY",   # mediastack.com
    "GUARDIAN_API_KEY":   "A_REMPLIR_GUARDIAN_API_KEY",     # open-platform.theguardian.com
    "FINNHUB_API_KEY":    "A_REMPLIR_FINNHUB_API_KEY",      # finnhub.io
    "THENEWSAPI_KEY":     "A_REMPLIR_THENEWSAPI_KEY",       # thenewsapi.com
    "CURRENTS_API_KEY":   "A_REMPLIR_CURRENTS_API_KEY",     # currentsapi.services
    "NEWSAPI_KEY":        "A_REMPLIR_NEWSAPI_KEY",          # newsapi.org
}

# --- Accès divers : des mots de passe que TU inventes ---
# Tant que DASH_PASSWORD commence par A_REMPLIR, le dashboard ne s'ouvre QUE
# depuis ce PC (aucun accès réseau ni lien public). Ne le laisse pas vide.
ADMIN_PASSWORD = "A_REMPLIR_ADMIN_PASSWORD"       # admin du serveur News
DASH_PASSWORD  = "A_REMPLIR_DASH_PASSWORD"   # invités du dashboard / du lien public
