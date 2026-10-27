# -*- coding: utf-8 -*-
# =====================================================
# 📡 CANAUX DE SIGNAUX — LE CERVEAU lit les canaux Telegram du patron
# =====================================================
# Demande du patron (06/08) : «…
# …
# …» — puis «…».
#
# Un BOT Telegram ne peut pas lire un canal privé ; on utilise donc Telethon,
# qui se connecte avec le COMPTE du patron (lecture seule, comme s'il lisait
# lui-même). Une seule validation par SMS, puis la session est enregistrée.
#
# Ce module :
#   1. écoute N canaux en continu,
#   2. extrait le signal (sens, symbole, entrée, SL, TP) du texte libre,
#   3. archive tout dans canaux_signaux.json,
#   4. NOTE la fiabilité de chaque canal en comparant ses signaux au marché réel
#      (le prix a-t-il touché son TP ou son SL après coup ?).
#
# LE CERVEAU lit ce fichier : les signaux servent d'AVIS EXTERNE (un juge de plus),
# jamais d'ordre automatique — c'est le patron qui décide de suivre ou pas.
# =====================================================
import io
import re
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).resolve().parent
FICHIER = HERE / "canaux_signaux.json"
SESSION = HERE / "oeil_telethon"          # session Telethon (créée au 1er login)

# 📡 LES CANAUX SUIVIS — ajouter simplement une ligne pour un 2e, 3e…
# (lien d'invitation, @pseudo, ou identifiant numérique)
CANAUX = [
    # Ajoute ici TES canaux Telegram de signaux, un par ligne. Exemples :
    # -1001234567890,                    # identifiant numérique du canal
    # "@nom_du_canal",                   # pseudo public du canal
    # "https://t.me/+lien_invitation",   # lien d'invitation (canal privé)
    # Pour trouver l'identifiant d'un canal : voir README.txt (section Canaux).
    # Liste vide = le module tourne mais n'écoute aucun canal.
    # pisteur_davo.py suit les canaux dont le nom contient DAVO (voir README.txt).
    # (une ligne par canal, sans # devant)
]

MAX_ARCHIVE = 300                          # on garde les N derniers messages

# 🎧 ÉCOUTE DES MÉDIAS (patron 06/08 : «…
# …»). On ne REGARDE jamais
# une image ni une vidéo — on en extrait la BANDE SON et on la transcrit
# (faster-whisper). Un vocal de 30 s contient souvent tout le signal.
ECOUTER_MEDIAS = True
MEDIA_MAX_MO   = 25        # au-delà, on passe (téléchargement trop lourd)
MEDIA_DOSSIER  = HERE / "canaux_medias"
_whisper = {"modele": None}

def _transcrire(fichier: Path) -> str:
    """Bande son -> texte. Renvoie '' si rien d'exploitable."""
    try:
        from faster_whisper import WhisperModel
        import imageio_ffmpeg
        wav = fichier.with_suffix(".wav")
        # extraction audio (marche pour .ogg vocal, .mp3, .mp4, .mov…)
        import subprocess
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                        "-i", str(fichier), "-ac", "1", "-ar", "16000", str(wav)],
                       timeout=180, creationflags=0x08000000)
        if not wav.exists() or wav.stat().st_size < 2000:
            return ""
        if _whisper["modele"] is None:
            _whisper["modele"] = WhisperModel("small", device="cpu", compute_type="int8")
        seg, _info = _whisper["modele"].transcribe(str(wav), vad_filter=True, beam_size=5)
        texte = " ".join(s.text.strip() for s in seg).strip()
        try:
            wav.unlink(); fichier.unlink()      # on ne garde pas les médias
        except Exception:
            pass
        return texte
    except Exception as e:
        print("[canaux] transcription KO:", e)
        return ""


# ---------- extraction du signal dans du texte libre ----------
SYMBOLES = {
    "XAUUSD": ("XAUUSD", "GOLD", "OR ", "GOLD/USD", "XAU"),
    "BTCUSD": ("BTCUSD", "BITCOIN", "BTC"),
    "ETHUSD": ("ETHUSD", "ETHEREUM", "ETH"),
    "EURUSD": ("EURUSD", "EUR/USD"),
    "USDJPY": ("USDJPY", "USD/JPY"),
    "XAGUSD": ("XAGUSD", "SILVER", "ARGENT", "XAG"),
    "CL-OIL": ("OIL", "PETROLE", "PÉTROLE", "WTI", "USOIL"),
    "SP500":  ("SP500", "S&P", "US500"),
}

def _nombres(txt: str):
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+[.,]?\d*", txt)]

def lire_signal(texte: str) -> dict:
    """Transforme un message en signal structuré. Renvoie {} si ce n'en est pas un."""
    if not texte:
        return {}
    t = texte.upper()
    sym = next((s for s, alias in SYMBOLES.items() if any(a in t for a in alias)), None)
    if not sym:
        return {}
    if re.search(r"\b(BUY|LONG|ACHAT|ACHETER|ACHETE)\b", t):
        sens = "BUY"
    elif re.search(r"\b(SELL|SHORT|VENTE|VENDRE|VEND)\b", t):
        sens = "SELL"
    else:
        return {}                          # parle d'un actif mais ne donne pas de sens
    def _apres(motifs):
        for m in motifs:
            r = re.search(m + r"\D{0,12}(\d+[.,]?\d*)", t)
            if r:
                return float(r.group(1).replace(",", "."))
        return None
    # 🎯 TOUTES les cibles (le patron veut voir TP1/TP2/TP3 séparément)
    tps = []
    # ⚠️ le numéro de cible doit être COLLÉ au mot-clé (TP1, TARGET2) : sans ça,
    # «…» se lisait «…» puis valeur 260 (chiffre avalé).
    # ⚠️ «…» (format d'un canal suivi) : il faut sauter les emojis/flèches entre le
    # libellé et le prix — [^\d\n]{0,8} avale 👉, :, =, espaces… mais pas un
    # retour ligne (sinon on attraperait le nombre de la ligne suivante).
    # Le numéro de cible est COLLÉ au libellé (TP1, TP2) — jamais séparé par un
    # espace. Sans ce détail, «…» (format d'un autre canal) se lisait
    # «…» puis valeur 665 : le premier chiffre du prix était avalé.
    for m in re.finditer(r"(?:TP|TAKE ?PROFIT|TARGET|OBJECTIF)\d?[^\d\n]{0,8}(\d+[.,]?\d*)", t):
        v = float(m.group(1).replace(",", "."))
        if v not in tps:
            tps.append(v)
    return {
        "symbol": sym, "sens": sens,
        # «…» : le prix colle souvent au sens, sans mot-clé
        "entree": _apres([r"ENTR[EÉ]E?", r"ENTRY", r"@", r"PRIX",
                          r"\b(?:BUY|SELL|LONG|SHORT)(?:\s+NOW)?"]),
        "sl":     _apres([r"\bSL\d*\b", r"STOP ?LOSS", r"STOP"]),
        "tp":     tps[0] if tps else None,      # 1re cible (compat + notation)
        "tps":    tps[:3],                      # TP1 / TP2 / TP3
        "texte":  texte[:400],
    }


# ---------- archive ----------
def _charger() -> dict:
    try:
        return json.loads(io.open(FICHIER, encoding="utf-8").read())
    except Exception:
        return {"messages": [], "canaux": {}}

def _sauver(d: dict):
    d["messages"] = d.get("messages", [])[-MAX_ARCHIVE:]
    io.open(FICHIER, "w", encoding="utf-8").write(
        json.dumps(d, ensure_ascii=False, indent=1))

def ajouter_message(canal: str, texte: str, ts: float = None):
    d = _charger()
    sig = lire_signal(texte)
    d["messages"].append({
        "canal": canal, "ts": ts or time.time(),
        "date": datetime.fromtimestamp(ts or time.time()).strftime("%Y-%m-%d %H:%M"),
        "texte": texte[:600], "signal": sig or None, "verdict": None})
    st = d.setdefault("canaux", {}).setdefault(canal, {"messages": 0, "signaux": 0})
    st["messages"] += 1
    if sig:
        st["signaux"] += 1
    _sauver(d)
    return sig


# ---------- ce que LE CERVEAU lit ----------
def signaux_recents(heures: int = 12, symbole: str = None) -> list:
    """Les signaux exploitables des N dernières heures (pour le contexte du CERVEAU)."""
    d = _charger()
    limite = time.time() - heures * 3600
    out = []
    for m in reversed(d.get("messages", [])):
        if m["ts"] < limite or not m.get("signal"):
            continue
        if symbole and m["signal"].get("symbol") != symbole:
            continue
        out.append(m)
    return out

# 🔤 INITIALES DES CANAUX (patron 07/08 : «…
# …»). Une SEULE lettre : on sait d'où ça
# vient d'un coup d'œil, sans étaler le nom du canal (règle du 06/08).
# Deux canaux d'un même trader peuvent partager leur lettre.
# En cas de collision, choisis une autre lettre (ex. P pour "Price").
INITIALES = {
    # version publique : vide. Ajoute TES canaux, un par ligne, par exemple :
    # "MON CANAL GOLD": "G",
    # Sans entrée, la lettre est la 1re lettre du nom du canal (repli ci-dessous).
}

def initiale(canal: str) -> str:
    """Lettre d'un canal. Table d'abord, sinon 1re lettre alphabétique du nom."""
    n = (canal or "").upper()
    for cle, lettre in INITIALES.items():
        if cle in n:
            return lettre
    for ch in n:                        # repli : on saute emojis et symboles
        if ch.isalpha():
            return ch
    return "?"


def bloc_spt(heures: int = 24, limite: int = 20) -> str:
    """📋 S.P.T — «…» (demande patron 06/08).
    Vue ÉPURÉE : symbole, sens, entrée, SL, TP1/2/3. Rien d'autre — ni blabla,
    ni emoji du canal, ni pub. Utilisée par le Centre de contrôle ET par le
    bouton Telegram «…»."""
    # 🧹 Vue VOULUE PAR LE PATRON (06/08) : «…
    # …».
    # Rien d'autre — ni nom de canal, ni blabla, ni pub.
    sigs = signaux_recents(heures)
    if not sigs:
        return f"📋 S.P.T — aucun signal sur les dernières {heures} h."
    out = [f"📋 S.P.T — SIGNAUX ({heures} h)", ""]
    vus, vus_ligne = set(), {}
    for m in sigs[:limite]:
        s = m["signal"]
        tps = s.get("tps") or ([s["tp"]] if s.get("tp") else [])
        cle = (s["symbol"], s["sens"], s.get("entree"), s.get("sl"), tuple(tps))
        if cle in vus:            # deux canaux qui donnent le même signal = 1 ligne
            # ...mais on garde la trace des DEUX sources : «…» vaut mieux
            # qu'un seul nom quand deux traders disent la même chose.
            lettre = initiale(m.get("canal", ""))
            for i, ligne in enumerate(out):
                if vus_ligne.get(cle) == i and lettre not in ligne.split(":")[0]:
                    tete, reste = ligne.split(":", 1)
                    if lettre not in tete:
                        out[i] = f"{tete.rstrip()}+{lettre} :{reste}"
                    break
            continue
        vus.add(cle)
        vus_ligne[cle] = len(out)
        l = [f"{s['symbol']} {s['sens']}"]
        if s.get("entree"):
            l.append(f"PE {s['entree']:g}")
        if s.get("sl"):
            l.append(f"SL {s['sl']:g}")
        for i, tp in enumerate(tps[:3], 1):
            l.append(f"TP{i} {tp:g}")
        v = m.get("verdict")
        marque = "  ✅" if v == "juste" else ("  ❌" if v == "perdant" else "")
        # 🔤 la lettre du canal en tête de ligne (patron 07/08)
        out.append(f"{initiale(m.get('canal', ''))} : " + "  ·  ".join(l) + marque)
    return "\n".join(out)


def resume_pour_cerveau(heures: int = 12) -> str:
    """Bloc texte injecté dans le contexte de décision du CERVEAU."""
    sigs = signaux_recents(heures)
    if not sigs:
        return ""
    lignes = ["📡 SIGNAUX DES CANAUX SUIVIS (avis EXTERNES — tu les prends en "
              "compte pour t'orienter, tu ne les exécutes pas aveuglément) :"]
    for m in sigs[:8]:
        s = m["signal"]
        det = " ".join(filter(None, [
            f"entrée {s['entree']}" if s.get("entree") else "",
            f"SL {s['sl']}" if s.get("sl") else "",
            f"TP {s['tp']}" if s.get("tp") else ""]))
        lignes.append(f"  • [{m['date']}] {s['symbol']} {s['sens']} {det}".rstrip())
    # fiabilité mesurée
    d = _charger()
    for canal, st in (d.get("canaux") or {}).items():
        j, p = st.get("justes", 0), st.get("perdants", 0)
        if j + p >= 3:
            lignes.append(f"  📊 fiabilité « {canal} » : {j}/{j+p} signaux gagnants "
                          f"({j/(j+p)*100:.0f}%) — pondère leur avis en conséquence.")
    return "\n".join(lignes)


# ---------- notation : le marché juge les signaux ----------
def noter_signaux(mt5, resolveur=None, horizon_h: int = 8):
    """Vérifie a posteriori si le prix a touché le TP (juste) ou le SL (perdant).
    resolveur : fonction symbole_interne -> symbole broker (ex : _sym_reel)."""
    d = _charger()
    change = False
    for m in d.get("messages", []):
        s = m.get("signal")
        if not s or m.get("verdict") or not s.get("entree"):
            continue
        if time.time() - m["ts"] > horizon_h * 3600:
            m["verdict"] = "expiré"
            change = True
            continue
        sym = resolveur(s["symbol"]) if resolveur else s["symbol"]
        try:
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 200)
            if r is None or not len(r):
                continue
            depuis = [x for x in r if float(x["time"]) >= m["ts"]]
            if not depuis:
                continue
            haut = max(float(x["high"]) for x in depuis)
            bas = min(float(x["low"]) for x in depuis)
            tp, sl = s.get("tp"), s.get("sl")
            v = None
            if s["sens"] == "BUY":
                if tp and haut >= tp: v = "juste"
                elif sl and bas <= sl: v = "perdant"
            else:
                if tp and bas <= tp: v = "juste"
                elif sl and haut >= sl: v = "perdant"
            if v:
                m["verdict"] = v
                st = d.setdefault("canaux", {}).setdefault(m["canal"], {})
                st["justes" if v == "juste" else "perdants"] = \
                    st.get("justes" if v == "juste" else "perdants", 0) + 1
                change = True
        except Exception:
            pass
    if change:
        _sauver(d)


# ---------- écoute en continu ----------
async def _ecouter(api_id: int, api_hash: str, telephone: str, on_signal=None):
    from telethon import TelegramClient, events
    client = TelegramClient(str(SESSION), api_id, api_hash)
    await client.start(phone=telephone)
    cibles = []
    for c in CANAUX:
        try:
            # 🐛 FIX 07/08 : `"t.me/+" in c` explosait sur les identifiants
            # NUMÉRIQUES («…») — 7 canaux
            # sur 8 tombaient au démarrage et seul le lien d'invitation
            # survivait. D'où «…». On teste le type d'abord.
            if isinstance(c, str) and ("t.me/+" in c or "joinchat" in c):   # lien d'invitation privé
                from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
                hash_inv = c.rstrip("/").split("+")[-1].split("/")[-1]
                try:
                    await client(ImportChatInviteRequest(hash_inv))   # rejoint si pas déjà membre
                except Exception:
                    pass                                              # déjà membre : très bien
                inv = await client(CheckChatInviteRequest(hash_inv))
                cibles.append(getattr(inv, "chat", None) or inv)
            else:
                cibles.append(await client.get_entity(c))
        except Exception as e:
            # 🔁 REPLI (07/08) : get_entity sur un identifiant BRUT échoue tant
            # que Telethon n'a pas l'entité dans le cache de sa session
            # («…»). On la retrouve alors dans
            # les conversations du compte — le patron est déjà membre.
            trouve = None
            try:
                async for d in client.iter_dialogs():
                    if d.id == c or getattr(d.entity, "id", None) == abs(int(c)) % 10**10:
                        trouve = d.entity
                        break
            except Exception:
                pass
            if trouve is not None:
                cibles.append(trouve)
                print(f"canal {c} : récupéré via les conversations "
                      f"({getattr(trouve, 'title', '?')})")
            else:
                print(f"canal {c} : {e}")
    # 🧹 DÉDUP (07/08) : le même canal peut être listé deux fois — une fois par
    # son identifiant numérique, une fois par son lien d'invitation (cas de
    # un canal vu au démarrage). Sans ça ses signaux sont comptés DOUBLE
    # et pèsent deux fois plus lourd dans les statistiques que les autres.
    vus, uniques, doublons = set(), [], []
    for x in cibles:
        ident = getattr(x, "id", None) or getattr(x, "title", None) or id(x)
        if ident in vus:
            doublons.append(getattr(x, "title", "?"))
            continue
        vus.add(ident)
        uniques.append(x)
    if doublons:
        print(f"[canaux] doublon ignoré : {', '.join(doublons)} "
              f"(listé 2× — identifiant ET lien d'invitation)")
    cibles = uniques
    noms = [getattr(x, "title", "?") for x in cibles]
    print(f"[canaux] écoute de {len(cibles)} canal/canaux : " + ", ".join(noms[:10]))

    @client.on(events.NewMessage(chats=cibles or None, func=lambda _e: bool(cibles)))   # version publique : liste vide = n'écoute RIEN (jamais toutes tes conversations)
    async def _(ev):
        try:
            nom = getattr(ev.chat, "title", None) or str(ev.chat_id)
            txt = (ev.raw_text or "").strip()

            # 🎧 AUDIO / VOCAL / VIDÉO : on ÉCOUTE (jamais on ne regarde).
            # Images, gifs, stickers, photos -> ignorés d'office (ordre patron).
            if ECOUTER_MEDIAS and len(txt) < 10 and ev.message.media:
                m = ev.message
                a_du_son = bool(getattr(m, "voice", None) or getattr(m, "audio", None)
                                or getattr(m, "video", None) or getattr(m, "video_note", None))
                if not a_du_son:
                    doc = getattr(m, "document", None)
                    mime = getattr(doc, "mime_type", "") if doc else ""
                    a_du_son = mime.startswith(("audio/", "video/"))
                if a_du_son:
                    taille = getattr(getattr(m, "document", None), "size", 0) or 0
                    if taille and taille > MEDIA_MAX_MO * 1024 * 1024:
                        return
                    MEDIA_DOSSIER.mkdir(exist_ok=True)
                    chemin = await m.download_media(file=str(MEDIA_DOSSIER))
                    if chemin:
                        dit = _transcrire(Path(chemin))
                        if dit:
                            print(f"[canaux] 🎧 transcrit ({len(dit)} car.) : {dit[:90]}…")
                            txt = (txt + " " + dit).strip() if txt else dit

            # 🚫 tout ce qui n'a pas de texte exploitable (image/gif/sticker seuls)
            if len(txt) < 10:
                return
            sig = ajouter_message(nom, txt, ev.message.date.timestamp())
            if sig and on_signal:
                on_signal(nom, sig)
        except Exception as e:
            print("[canaux] erreur:", e)

    await client.run_until_disconnected()


def demarrer_ecoute(api_id, api_hash, telephone, on_signal=None):
    """À appeler dans un thread : lance l'écoute Telethon en continu."""
    asyncio.set_event_loop(asyncio.new_event_loop())
    asyncio.get_event_loop().run_until_complete(
        _ecouter(int(api_id), api_hash, telephone, on_signal))


if __name__ == "__main__":
    # Première connexion (validation SMS) puis écoute :
    #   python canaux_signaux.py
    from secrets_acid import TG_API_ID, TG_API_HASH, TG_PHONE
    demarrer_ecoute(TG_API_ID, TG_API_HASH, TG_PHONE,
                    lambda c, s: print(f"📡 {c} → {s['symbol']} {s['sens']}"))
