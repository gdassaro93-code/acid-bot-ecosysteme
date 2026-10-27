# -*- coding: utf-8 -*-
# =====================================================
#  🧪 ACID — CENTRE DE CONTRÔLE
#  Une seule fenêtre pour piloter tout l'écosystème :
#  News, ML, LE CERVEAU, Mammouth, Dashboard + MT5.
#  Chaque service tourne dans son propre process/port,
#  mais démarrage/arrêt et logs sont ici, en onglets.
# =====================================================
import os
import re
import sys
import socket
import subprocess
import threading
import queue
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, colorchooser

HERE = Path(__file__).resolve().parent
DASH = HERE / "dashboard"
MT5_EXE = r"C:\Program Files\Vantage Markets MT5 Terminal\terminal64.exe"
# 🎨 dossier Files du terminal actif — l'EA y lit acid_display.cfg (onglet Visualisation)
MT5_FILES = Path(__import__("portabilite").mql5_files() or (HERE / "mt5_files_introuvable"))   # version publique : lu par portabilite.py
TUNNEL_LOG = DASH / "tunnel.log"
NO_WIN = 0x08000000            # CREATE_NO_WINDOW (pas de console parasite)
PY = sys.executable

# key, libellé, script, dossier, port de vérification (None = process seulement),
# délai de démarrage (s) pour respecter les dépendances
SERVICES = [
    ("news",     "📰 Serveur News",  "Server.py",                    HERE, 5001, 0),
    ("ml",       "🔬 Serveur ML",    "server_ml_v2.py",              HERE, 8001, 2),
    ("oeil",     "🧠 LE CERVEAU",    "ia_watchdog.py",               HERE, 8060, 4),
    ("mammouth", "🦣 Bot Mammouth",  "BOT_MAMMOUTH_COMPLETE_V7.py",  HERE, None, 6),
    ("dash",     "🖥️ Dashboard",     "dashboard_server.py",          DASH, 8050, 7),
    ("arena",    "🏟️ Arène IA",      "model_arena.py",               HERE, None, 9),
    # 🌍 20/07 : le tunnel devient un service à part entière (ON/OFF + onglet).
    # Non lancé par «…» (reste manuel : on n'expose le PC que si
    # on le veut). cloudflared reste dans dashboard\ (pas besoin de le déplacer).
    ("tunnel",   "🌍 Tunnel public", "cloudflared.exe",              DASH, None, 0,
     [str(DASH / "cloudflared.exe"), "tunnel", "--url", "http://127.0.0.1:8050"]),
    # ── 👁️ LES SIX YEUX (13/09) ────────────────────────────────────────
    # Chacun ne fait QU'UNE chose, mesurée, et rapporte au cerveau. Aucun
    # ne passe d'ordre : ils sont tous en OBSERVATION tant que le patron
    # n'a pas ouvert la main, œil par œil, après une semaine de rapports.
    # L'œil 6 est le seul à agir dès le départ : il ne trade pas, il VETO.
    ("oeil1", "👁️ 1 · crypto→NAS100",  "yeux/oeil1_crypto.py",  HERE, None, 10),
    ("oeil2", "👁️ 2 · métaux→EURUSD",  "yeux/oeil2_metaux.py",  HERE, None, 10),
    ("oeil3", "👁️ 3 · range d'ouv.",   "yeux/oeil3_range.py",   HERE, None, 10),
    ("oeil4", "👁️ 4 · choc volatilité","yeux/oeil4_choc.py",    HERE, None, 10),
    ("oeil5", "👁️ 5 · devises",        "yeux/oeil5_devises.py", HERE, None, 10),
    ("oeil6", "🛡️ 6 · risque (veto)",  "yeux/oeil6_risque.py",  HERE, None, 10),
    # 🎯 16/09 — LE CHASSEUR ML : entre de lui-même quand le ML v2 voit un setup
    # (p ≥ 0,38, validé 6 mois sur 6), stop 1×ATR H1 et objectif 2R fixes.
    ("sniper", "🎯 Sniper ML",          "sniper_ml.py",          HERE, None, 11),
]
KILL_PATTERN = ("ia_watchdog|server_ml_v2|BOT_MAMMOUTH|dashboard_server|"
                "model_arena|Server\\.py|yeux[\\\\/]oeil|sniper_ml")

CHR_N = chr(10)
CHR_D = chr(34)
CHR_S = chr(39)
BG, CARD, TXT, GREEN, RED, MUTED = "#0d1117", "#161b22", "#c9d1d9", "#2ea043", "#cf222e", "#8b949e"


def port_open(p):
    if p is None:
        return None
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=0.4):
            return True
    except OSError:
        return False


class Service:
    def __init__(self, cfg, log_q):
        self.key, self.label, self.script, self.cwd, self.port, self.delay = cfg[:6]
        self.cmd = cfg[6] if len(cfg) > 6 else None   # commande custom (ex: tunnel cloudflared)
        self.log_q = log_q
        self.proc = None

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def up(self):
        # vert si le port répond (peu importe qui l'a lancé) ou si notre process vit
        po = port_open(self.port)
        if po is True:
            return True
        if po is False and self.port is not None:
            return self.running()   # process vivant mais port pas encore prêt
        return self.running()

    def start(self):
        if self.running():
            return
        try:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"   # emojis/accents lisibles dans les onglets
            env["PYTHONUTF8"] = "1"
            if self.cmd:                        # service non-python (ex: tunnel cloudflared)
                # un seul tunnel à la fois : on ferme un cloudflared resté d'un
                # ancien lancement (ex: START_TUNNEL.bat) avant de relancer proprement
                if "cloudflared" in str(self.cmd[0]).lower():
                    subprocess.run(["taskkill", "/IM", "cloudflared.exe", "/F"],
                                   creationflags=NO_WIN, capture_output=True)
                command = list(self.cmd)
            else:
                command = [PY, "-u", self.script]
            self.proc = subprocess.Popen(
                command, cwd=str(self.cwd), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=NO_WIN, encoding="utf-8", errors="replace", bufsize=1)
            threading.Thread(target=self._reader, daemon=True).start()
            self.log_q.put((self.key, f"▶ démarrage de {self.script}…"))
        except Exception as e:
            self.log_q.put((self.key, f"❌ impossible de démarrer : {e}"))

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.log_q.put((self.key, line.rstrip()))
        except Exception:
            pass
        self.log_q.put((self.key, "■ processus terminé."))

    def stop(self):
        if self.proc:
            try:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                               creationflags=NO_WIN, capture_output=True)
            except Exception:
                pass
            self.proc = None


def _list_stack_procs():
    """[(pid, cmdline), …] de TOUT python/pythonw qui exécute un script de la
    stack. 20/07 : l'ancien nettoyage ne visait que python.exe — or le Centre
    lance ses services avec pythonw.exe -> les stacks des lancements
    précédents survivaient et doublonnaient (2 bots sur le même compte)."""
    procs = []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
             "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"],
            creationflags=NO_WIN, capture_output=True, text=True, timeout=15)
        for line in (r.stdout or "").splitlines():
            pid, _, cmd = line.partition("|")
            if pid.strip().isdigit() and re.search(KILL_PATTERN, cmd or ""):
                procs.append((int(pid), (cmd or "").strip()))
    except Exception:
        pass
    return procs


def kill_all_external(exclude=None):
    """Tue toute instance de service déjà lancée (zombie d'un lancement
    précédent, .bat, etc.). `exclude` = PIDs à épargner (nos propres
    services). Retourne le nombre de processus fermés."""
    spare = set(exclude or ())
    spare.add(os.getpid())
    killed = 0
    for pid, _cmd in _list_stack_procs():
        if pid in spare:
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           creationflags=NO_WIN, capture_output=True, timeout=10)
            killed += 1
        except Exception:
            pass
    return killed


class App:
    def __init__(self, root):
        self.root = root
        self.log_q = queue.Queue()
        self.services = {c[0]: Service(c, self.log_q) for c in SERVICES}
        self.texts = {}
        self.dots = {}
        root.title("🧪 ACID — Centre de Contrôle")
        root.geometry("1180x740")
        root.configure(bg=BG)

        # --- barre du haut ---
        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(top, text="🧪 ACID — CENTRE DE CONTRÔLE", bg=BG, fg=TXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        for txt, cmd, col in [("▶ TOUT DÉMARRER", self.start_all, GREEN),
                              ("■ TOUT ARRÊTER", self.stop_all, RED),
                              ("🔄 RESET LIMITES EA", self.reset_limites_ea, "#bc4c00"),
                              ("🧟 TUER LES DOUBLONS", self.kill_zombies, "#9e6a03"),
                              ("🗨️ Dialogue IA", self.open_dialogue, CARD),
                              ("🖥️ Dashboard", lambda: webbrowser.open("http://127.0.0.1:8050"), CARD),
                              ("🌍 Lien tunnel", self.show_tunnel, CARD),
                              ("🧠 Réentraîner ML", self.retrain_ml, CARD)]:
            tk.Button(top, text=txt, command=cmd, bg=col, fg="white", bd=0,
                      font=("Segoe UI", 9, "bold"), padx=10, pady=6,
                      activebackground=col).pack(side="right", padx=4)

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=6)

        # --- panneau gauche : services ---
        left = tk.Frame(body, bg=BG, width=250)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        for key, label, *_ in SERVICES:
            self._service_row(left, key, label)
        # MT5
        self._mt5_row(left)

        # --- panneau droit : onglets logs ---
        style = ttk.Style()
        try:
            style.theme_use("default")
        except Exception:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=TXT, padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", "#1f6feb")])
        nb = ttk.Notebook(body)
        nb.pack(side="right", fill="both", expand=True)
        for key, label, *_ in SERVICES:
            # 🏟️ l'onglet Arène a une barre avec le bouton «…»
            if key == "arena":
                cont = tk.Frame(nb, bg=BG)
                bar = tk.Frame(cont, bg=BG)
                bar.pack(fill="x")
                tk.Button(bar, text="📊 Rapport (classement)", command=self.arena_report,
                          bg="#1f6feb", fg="white", bd=0, font=("Segoe UI", 9, "bold"),
                          padx=12, pady=5, activebackground="#1f6feb").pack(side="left", padx=4, pady=4)
                # 🗨️ barre de chat de groupe (parler à tous les bots actifs)
                chatf = tk.Frame(cont, bg=BG)
                chatf.pack(side="bottom", fill="x", pady=(2, 4))
                tk.Label(chatf, text="🗨️", bg=BG, fg=TXT, font=("Segoe UI", 12)).pack(side="left", padx=(6, 2))
                self.council_entry = tk.Entry(chatf, bg="#010409", fg=TXT, insertbackground=TXT,
                                              bd=0, font=("Segoe UI", 10))
                self.council_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
                self.council_entry.bind("<Return>", lambda e: self.council_send())
                tk.Button(chatf, text="Parler aux bots", command=self.council_send, bg="#2ea043",
                          fg="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10,
                          activebackground="#2ea043").pack(side="right", padx=4)
                # 🧮 10/10 — LE CONSEIL DES CALCULATEURS (demande patron).
                # Deux équipes de quatre super calculateurs : ASTRA (GPT) et
                # GROK (grok-4.7). Le patron pose sa question ici ; l'équipe A
                # répond pour ses 4 Astra, l'équipe B pour ses 4 Grok. Jamais
                # huit réponses : une par équipe.
                for lib, eq, coul in (("🅰️ ASTRA", "A", "#8957e5"),
                                      ("🅱️ GROK", "B", "#db6d28"),
                                      ("⚖️ les deux", "AB", "#1f6feb")):
                    tk.Button(chatf, text=lib, bg=coul, fg="white", bd=0,
                              font=("Segoe UI", 9, "bold"), padx=10,
                              activebackground=coul,
                              command=lambda e=eq: self.conseil_send(e)).pack(side="right", padx=2)
                parent = cont
            else:
                parent = nb
            t = scrolledtext.ScrolledText(parent, bg="#010409", fg="#9ece9e", bd=0,
                                          font=("Consolas", 9), insertbackground=TXT, wrap="none")
            t.tag_config("err", foreground="#f85149")
            t.tag_config("warn", foreground="#d29922")
            t.tag_config("ok", foreground="#3fb950")
            t.pack(fill="both", expand=True)
            nb.add(parent if key == "arena" else t, text=label)
            self.texts[key] = t

        # 🎯 S.P.T — SIGNAUX PSEUDO TRADERS (06/08, demande patron) : un terminal
        # dédié qui n'affiche QUE l'essentiel des signaux des canaux suivis —
        # symbole, action, PE, SL, TP1/2/3. Ni pub, ni blabla, ni nom de canal.
        sptf = tk.Frame(nb, bg=BG)
        sptbar = tk.Frame(sptf, bg=BG)
        sptbar.pack(fill="x")
        tk.Button(sptbar, text="↻ Rafraîchir", command=self.spt_reload, bg=CARD, fg=TXT,
                  bd=0, padx=10, pady=4).pack(side="left", padx=4, pady=4)
        for lib, h in (("24 h", 24), ("48 h", 48), ("7 jours", 168)):
            tk.Button(sptbar, text=lib, command=lambda x=h: self.spt_reload(x), bg=CARD,
                      fg=TXT, bd=0, padx=10, pady=4).pack(side="left", padx=2, pady=4)
        self.spt_txt = scrolledtext.ScrolledText(sptf, bg="#010409", fg="#9ece9e", bd=0,
                                                 font=("Consolas", 10), wrap="none")
        self.spt_txt.pack(fill="both", expand=True)
        nb.add(sptf, text="🎯 S.P.T")

        # 🎓 L'ÉCOLE DU BOT (15/07, demande patron : «…
        # …») — la mentalité du trader, visible et pilotable : voir les
        # leçons apprises, en enseigner, en retirer, et lui faire regarder une
        # vidéo YouTube sans passer par Telegram. Ajout/retrait = fichier direct
        # (effet immédiat, LE CERVEAU relit acid_lecons.txt à chaque verdict) ;
        # YouTube = via LE CERVEAU (il faut son cerveau IA).
        ecole = tk.Frame(nb, bg=BG)
        ebar = tk.Frame(ecole, bg=BG)
        ebar.pack(fill="x")
        tk.Button(ebar, text="↻ Recharger", command=self.ecole_reload, bg=CARD, fg=TXT,
                  bd=0, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=4, pady=4)
        tk.Button(ebar, text="🗑 Oublier la sélection", command=self.ecole_delete, bg=CARD,
                  fg="#f85149", bd=0, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(ebar, text="💾 Enregistrer", command=self.ecole_save, bg=CARD, fg=TXT,
                  bd=0, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(ebar, text="📂 Charger", command=self.ecole_load, bg=CARD, fg=TXT,
                  bd=0, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(ebar, text="✅ Demander la validation", command=self.ecole_validate, bg="#1f6feb",
                  fg="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(ebar, text="🧠 Corriger", command=self.ecole_corriger, bg="#8250df",
                  fg="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(ebar, text="💉 Inject", command=self.ecole_inject, bg="#1a7f37",
                  fg="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(ebar, text="💡 Idée → code (Mistral)", command=self.ecole_strategie, bg="#bc4c00",
                  fg="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10, pady=4).pack(side="left", padx=4)
        tk.Label(ebar, text="la mentalité du trader — injectée dans CHAQUE verdict", bg=BG,
                 fg=MUTED, font=("Segoe UI", 8, "italic")).pack(side="right", padx=8)
        lf = tk.Frame(ecole, bg=BG)
        lf.pack(fill="both", expand=True, padx=4)
        esb = tk.Scrollbar(lf)
        esb.pack(side="right", fill="y")
        self.ecole_list = tk.Listbox(lf, bg="#010409", fg="#9ece9e", bd=0, selectmode="extended",
                                     font=("Segoe UI", 10), yscrollcommand=esb.set,
                                     selectbackground="#1f6feb", highlightthickness=0)
        self.ecole_list.pack(side="left", fill="both", expand=True)
        esb.config(command=self.ecole_list.yview)
        self.ecole_out = scrolledtext.ScrolledText(ecole, bg="#010409", fg="#d29922", bd=0,
                                                   font=("Segoe UI", 9), height=6, wrap="word")
        self.ecole_out.pack(fill="x", padx=4, pady=(4, 0))
        addf = tk.Frame(ecole, bg=BG)
        addf.pack(fill="x", pady=(4, 0))
        tk.Label(addf, text="📚", bg=BG, fg=TXT, font=("Segoe UI", 11)).pack(side="left", padx=(6, 2))
        self.ecole_entry = tk.Entry(addf, bg="#010409", fg=TXT, insertbackground=TXT, bd=0,
                                    font=("Segoe UI", 10))
        self.ecole_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
        self.ecole_entry.bind("<Return>", lambda e: self.ecole_add())
        tk.Button(addf, text="➕ Enseigner", command=self.ecole_add, bg="#2ea043", fg="white",
                  bd=0, font=("Segoe UI", 9, "bold"), padx=10).pack(side="right", padx=4)
        ytf = tk.Frame(ecole, bg=BG)
        ytf.pack(fill="x", pady=(4, 6))
        tk.Label(ytf, text="🎓", bg=BG, fg=TXT, font=("Segoe UI", 11)).pack(side="left", padx=(6, 2))
        self.ecole_yt = tk.Entry(ytf, bg="#010409", fg=TXT, insertbackground=TXT, bd=0,
                                 font=("Segoe UI", 10))
        self.ecole_yt.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
        self.ecole_yt.bind("<Return>", lambda e: self.ecole_youtu())
        self.ecole_yeux = tk.BooleanVar(value=False)
        tk.Checkbutton(ytf, text="🎬 voir les images", variable=self.ecole_yeux, bg=BG, fg=TXT,
                       selectcolor=CARD, activebackground=BG, activeforeground=TXT, bd=0,
                       font=("Segoe UI", 8), highlightthickness=0).pack(side="left", padx=(0, 4))
        tk.Button(ytf, text="🎓 Apprendre de cette vidéo", command=self.ecole_youtu, bg="#8250df",
                  fg="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10).pack(side="right", padx=4)
        tk.Button(ytf, text="➕ Doc", command=self.ecole_doc, bg="#9e6a03", fg="white",
                  bd=0, font=("Segoe UI", 9, "bold"), padx=10).pack(side="right", padx=(0, 4))
        nb.add(ecole, text="🎓 École")

        # 🧮 CONSO TOKENS (23/07, demande patron) : camembert + tableau de la
        # conso IA du jour VENTILÉE PAR FONCTION (qui mange quoi). Lit
        # token_stats.json (rempli en temps réel par LE CERVEAU + MAMMOUTH via
        # token_meter). Auto-rafraîchi toutes les 30 s.
        tok = tk.Frame(nb, bg=BG)
        tkbar = tk.Frame(tok, bg=BG)
        tkbar.pack(fill="x")
        tk.Button(tkbar, text="↻ Rafraîchir", command=self.tokens_refresh, bg=CARD, fg=TXT,
                  bd=0, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=4, pady=4)
        self.tokens_head = tk.Label(tkbar, text="conso IA du jour, par fonction — chiffres réels",
                                    bg=BG, fg=MUTED, font=("Segoe UI", 8, "italic"))
        self.tokens_head.pack(side="right", padx=8)
        tkbody = tk.Frame(tok, bg=BG)
        tkbody.pack(fill="both", expand=True)
        self.tokens_canvas = tk.Canvas(tkbody, bg="#010409", bd=0, highlightthickness=0, width=300)
        self.tokens_canvas.pack(side="left", fill="y", padx=8, pady=8)
        self.tokens_text = scrolledtext.ScrolledText(tkbody, bg="#010409", fg=TXT, bd=0,
                                                     font=("Consolas", 10), wrap="none")
        self.tokens_text.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=8)
        nb.add(tok, text="🧮 Tokens")

        # ⚙️ RÉGLAGES (29/07, demande patron) : le tableau de reference des 3
        # bots, EDITABLE depuis le Centre. Les cles EA partent en direct dans la
        # sandbox MQL5\Files (effet immediat, persiste dans le terminal) ; les
        # constantes Python sont reecrites dans le .py (redemarrage requis).
        reg = tk.Frame(nb, bg=BG)
        rbar = tk.Frame(reg, bg=BG)
        rbar.pack(fill="x")
        tk.Button(rbar, text="↻ Relire les valeurs", command=self.reglages_reload, bg=CARD, fg=TXT,
                  bd=0, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=4, pady=4)
        tk.Button(rbar, text="💾 Appliquer la sélection", command=self.reglages_appliquer,
                  bg="#2ea043", fg="white", bd=0, font=("Segoe UI", 9, "bold"),
                  padx=12, pady=4).pack(side="left", padx=4)
        self.reg_info = tk.Label(rbar, text="double-clic sur une ligne pour changer sa valeur",
                                 bg=BG, fg=MUTED, font=("Segoe UI", 8, "italic"))
        self.reg_info.pack(side="right", padx=8)
        cols = ("systeme", "cle", "valeur", "role")
        style.configure("Reg.Treeview", background="#010409", fieldbackground="#010409",
                        foreground=TXT, rowheight=22, borderwidth=0)
        style.configure("Reg.Treeview.Heading", background=CARD, foreground=TXT)
        self.reg_tree = ttk.Treeview(reg, columns=cols, show="headings", style="Reg.Treeview")
        for c, w in zip(cols, (110, 210, 90, 620)):
            self.reg_tree.heading(c, text=c.upper())
            self.reg_tree.column(c, width=w, anchor="w")
        rsb = tk.Scrollbar(reg, command=self.reg_tree.yview)
        rsb.pack(side="right", fill="y")
        self.reg_tree.configure(yscrollcommand=rsb.set)
        self.reg_tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.reg_tree.bind("<Double-1>", self.reglages_editer)
        self.reg_out = scrolledtext.ScrolledText(reg, bg="#010409", fg="#d29922", bd=0,
                                                 font=("Consolas", 9), height=5, wrap="word")
        self.reg_out.pack(fill="x", padx=4, pady=(0, 4))
        nb.add(reg, text="⚙️ Réglages")

        # 🎨 VISUALISATION (24/07, demande patron) : personnaliser les couleurs
        # du panneau/Vision et choisir quelles infos l'IA affiche sur le chart.
        # Ecrit acid_display.cfg dans le dossier Files du terminal ; l'EA le
        # relit a chaud (toutes les 3 s) et applique — aucun rechargement.
        self._build_visu_tab(nb)

        self.status = tk.Label(root, text="Prêt.", bg=BG, fg=MUTED, anchor="w",
                               font=("Segoe UI", 9))
        # (après la barre de statut : ecole_reload() l'utilise — l'appeler avant
        # crashait le Centre au démarrage, attrapé le 15/07)
        self.ecole_reload()
        self.status.pack(fill="x", padx=12, pady=(0, 8))

        self.reglages_reload()   # tableau des reglages des 3 bots
        self.tokens_refresh()   # 🧮 1er rendu + auto-refresh (se reprogramme seul)
        self.root.after(150, self._drain_logs)
        self.root.after(300, self._poll_status)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(1200, self._tray_start)   # 🔔 icone systray prete des le depart
        self.root.after(1500, self.spt_reload)    # 🎯 signaux pseudo traders au demarrage

    def _service_row(self, parent, key, label):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=3)
        dot = tk.Label(f, text="●", bg=CARD, fg=MUTED, font=("Segoe UI", 13))
        dot.pack(side="left", padx=(8, 4))
        self.dots[key] = dot
        tk.Label(f, text=label, bg=CARD, fg=TXT, font=("Segoe UI", 10),
                 anchor="w", width=15).pack(side="left")
        tk.Button(f, text="↻", width=2, bd=0, bg=CARD, fg=TXT,
                  command=lambda k=key: self.restart(k)).pack(side="right", padx=(0, 6))
        tk.Button(f, text="■", width=2, bd=0, bg=CARD, fg="#f85149",
                  command=lambda k=key: self.services[k].stop()).pack(side="right")
        tk.Button(f, text="▶", width=2, bd=0, bg=CARD, fg="#3fb950",
                  command=lambda k=key: self.services[k].start()).pack(side="right")

    def _mt5_row(self, parent):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=(14, 3))
        self.mt5_dot = tk.Label(f, text="●", bg=CARD, fg=MUTED, font=("Segoe UI", 13))
        self.mt5_dot.pack(side="left", padx=(8, 4))
        tk.Label(f, text="📈 MetaTrader 5", bg=CARD, fg=TXT, font=("Segoe UI", 10),
                 anchor="w", width=15).pack(side="left")
        tk.Button(f, text="Lancer", bd=0, bg=CARD, fg="#3fb950",
                  command=self.launch_mt5).pack(side="right", padx=(0, 6))
        tk.Button(f, text="Fermer ✔", bd=0, bg=CARD, fg="#d29922",
                  command=self.close_mt5_propre).pack(side="right", padx=(0, 6))
        tk.Button(f, text="⟲ Charts", bd=0, bg=CARD, fg=TXT,
                  command=self.restore_charts).pack(side="right", padx=(0, 6))

    def launch_mt5(self):
        try:
            if Path(MT5_EXE).exists():
                subprocess.Popen([MT5_EXE])
        except Exception:
            pass

    # 💾 (patron 05/08 : «…»)
    MT5_CHARTS = Path(__import__("portabilite").profils_charts() or (HERE / "mt5_profils_introuvables"))
    # (version publique : dossier des profils lu par portabilite.py, plus de chemin gravé en dur)
    CHARTS_BACKUP = HERE / "mt5_charts_backup"

    def _mt5_tourne(self) -> bool:
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                               creationflags=NO_WIN, capture_output=True, timeout=5)
            return b"terminal64" in (r.stdout or b"")
        except Exception:
            return False

    def close_mt5_propre(self):
        """Fermeture PROPRE : demande à MT5 de quitter (il sauvegarde ses charts),
        attend la fin, puis BACKUP du plan de travail (Profiles\\Charts)."""
        self.status.config(text="📈 Fermeture propre de MT5 en cours…")

        def worker():
            import shutil
            try:
                # WM_CLOSE (SANS /F) : MT5 écrit ses .chr et sort proprement
                subprocess.run(["taskkill", "/IM", "terminal64.exe"],
                               creationflags=NO_WIN, capture_output=True, timeout=10)
                for _ in range(30):
                    if not self._mt5_tourne():
                        break
                    threading.Event().wait(1)
                if self._mt5_tourne():
                    self.root.after(0, lambda: self.status.config(
                        text="⚠️ MT5 ne se ferme pas (popup ouvert ?) — ferme-le à la main, PAS de kill."))
                    return
                if self.MT5_CHARTS.exists():
                    if self.CHARTS_BACKUP.exists():
                        shutil.rmtree(self.CHARTS_BACKUP, ignore_errors=True)
                    shutil.copytree(self.MT5_CHARTS, self.CHARTS_BACKUP)
                    n = len(list(self.CHARTS_BACKUP.rglob("*.chr")))
                    self.root.after(0, lambda: self.status.config(
                        text=f"✔ MT5 fermé proprement — plan de travail sauvegardé ({n} charts)."))
            except Exception as e:
                self.root.after(0, lambda: self.status.config(text=f"❌ fermeture MT5 : {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def restore_charts(self):
        """⟲ Restaure le dernier plan de travail sauvegardé (MT5 doit être FERMÉ)."""
        import shutil
        if self._mt5_tourne():
            self.status.config(text="⚠️ Ferme MT5 d'abord (Fermer ✔) — on ne restaure pas à chaud.")
            return
        if not self.CHARTS_BACKUP.exists():
            self.status.config(text="⚠️ Aucun backup de charts encore fait (utilise « Fermer ✔ » une fois).")
            return
        try:
            shutil.rmtree(self.MT5_CHARTS, ignore_errors=True)
            shutil.copytree(self.CHARTS_BACKUP, self.MT5_CHARTS)
            n = len(list(self.MT5_CHARTS.rglob("*.chr")))
            self.status.config(text=f"⟲ Plan de travail restauré ({n} charts) — lance MT5, tout revient.")
        except Exception as e:
            self.status.config(text=f"❌ restauration : {e}")

    def council_send(self):
        """🗨️ Envoie un message à TOUS les bots actifs (via /api/council de
        LE CERVEAU) et affiche leurs réponses dans le terminal Arène."""
        msg = self.council_entry.get().strip()
        if not msg:
            return
        self.council_entry.delete(0, "end")
        self.log_q.put(("arena", f"\n🧑 Toi : {msg}"))

        def worker():
            try:
                import json as _json, urllib.parse, urllib.request
                url = "http://127.0.0.1:8060/api/council?msg=" + urllib.parse.quote(msg)
                with urllib.request.urlopen(url, timeout=90) as r:
                    data = _json.loads(r.read().decode("utf-8"))
                reps = data.get("replies", [])
                if not reps:
                    self.log_q.put(("arena", "  (aucun bot branché ne répond — LE CERVEAU démarré ?)"))
                for rep in reps:
                    self.log_q.put(("arena", f"  {rep['name']} : {rep['text']}"))
            except Exception as e:
                self.log_q.put(("arena", f"  ❌ chat indisponible : {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def conseil_send(self, equipes="AB"):
        """🧮 LE CONSEIL DES CALCULATEURS — demande du patron (10/10) :
        «…
        …».
        Les quatre membres d'une équipe calculent SÉPARÉMENT le même dossier
        (prix réels du compte, calendrier, recherche internet en direct), puis
        un porte-parole rend UN avis. S'ils convergent, c'est solide ; s'ils
        divergent, il le dit. Chaque avis peut porter un signal exécutable."""
        msg = self.conseil_entry_texte()
        if not msg:
            msg = ("Où faut-il investir maintenant sur l'or, le NAS100, le pétrole "
                   "ou le BTC, et comment capturer ce mouvement de façon logique ?")
        qui = {"A": "🅰️ ASTRA", "B": "🅱️ GROK", "AB": "les deux équipes"}[equipes]
        self.log_q.put(("arena", f"\n🧑 Toi → {qui} : {msg}"))
        self.log_q.put(("arena", "   (les calculateurs travaillent — compte environ une minute…)"))

        def worker():
            try:
                import conseil_calculateurs as cc
                liste = ("A", "B") if equipes == "AB" else (equipes,)
                for r in cc.consulter(msg, equipes=liste):
                    for ligne in cc.texte(r).splitlines():
                        self.log_q.put(("arena", "  " + ligne))
                    self.log_q.put(("arena", ""))
            except Exception as e:
                self.log_q.put(("arena", f"  ❌ conseil indisponible : {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def conseil_entry_texte(self):
        """Récupère la question tapée et vide le champ (partagé avec le chat)."""
        try:
            m = self.council_entry.get().strip()
            if m:
                self.council_entry.delete(0, "end")
            return m
        except Exception:
            return ""

    # ---------- 🎓 L'École du bot ----------
    LECONS = HERE / "acid_lecons.txt"

    def ecole_reload(self):
        """Recharge la liste des leçons depuis acid_lecons.txt."""
        self.ecole_list.delete(0, "end")
        try:
            lignes = [l.lstrip("-•").strip() for l in
                      self.LECONS.read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception:
            lignes = []
        for i, l in enumerate(lignes, 1):
            self.ecole_list.insert("end", f" {i}. {l}")
        self.status.config(text=f"🎓 {len(lignes)} leçon(s) dans la tête du trader.")

    def ecole_add(self):
        """Enseigne une leçon à la main — effet immédiat (fichier relu à chaque verdict)."""
        texte = self.ecole_entry.get().strip()
        if not texte:
            return
        self.ecole_entry.delete(0, "end")
        with open(self.LECONS, "a", encoding="utf-8") as f:
            f.write("- [👑 patron] " + texte + "\n")
        self.ecole_reload()
        self.status.config(text=f"📚 Leçon enseignée : « {texte[:60]} »")

    def ecole_delete(self):
        """Fait oublier les leçons sélectionnées (réécrit le fichier sans elles)."""
        sel = set(self.ecole_list.curselection())
        if not sel:
            self.status.config(text="🎓 Sélectionne d'abord la ou les leçons à oublier.")
            return
        try:
            lignes = [l for l in self.LECONS.read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception:
            return
        restantes = [l for i, l in enumerate(lignes) if i not in sel]
        self.LECONS.write_text("\n".join(restantes) + ("\n" if restantes else ""), encoding="utf-8")
        self.ecole_reload()
        self.status.config(text=f"🗑 {len(sel)} leçon(s) oubliée(s).")

    def ecole_youtu(self):
        """Fait regarder une vidéo YouTube au cerveau (via LE CERVEAU — long).
        Case «…» cochée = il regarde aussi les captures."""
        url = self.ecole_yt.get().strip()
        if not url:
            return
        yeux = self.ecole_yeux.get()
        self.ecole_yt.delete(0, "end")
        self.ecole_out.delete("1.0", "end")
        self.ecole_out.insert("end",
            ("🎬 J'écoute ET je regarde les images de la vidéo…\n" if yeux
             else "🎓 Je regarde la vidéo (transcription intégrale + analyse IA)…\n")
            + "🎬 Une vidéo de plusieurs heures peut prendre 5-15 min — la "
              "progression défile dans l'onglet LE CERVEAU.\n")

        def worker():
            try:
                import json as _json, urllib.parse, urllib.request
                u = ("http://127.0.0.1:8060/api/ecole?youtu=" + urllib.parse.quote(url)
                     + ("&yeux=1" if yeux else ""))
                with urllib.request.urlopen(u, timeout=1800) as r:
                    res = _json.loads(r.read().decode("utf-8")).get("resultat", "(pas de réponse)")
            except Exception as e:
                res = f"❌ École indisponible : {e} — LE CERVEAU est-il démarré ?"
            def maj():
                self.ecole_out.delete("1.0", "end")
                self.ecole_out.insert("end", res.replace("*", "").replace("_", ""))
                self.ecole_reload()
            self.root.after(0, maj)

        threading.Thread(target=worker, daemon=True).start()

    def ecole_save(self):
        """💾 Sauvegarde les leçons actuelles dans un petit .txt (snapshot datable)."""
        from tkinter import filedialog
        from datetime import datetime
        if not self.LECONS.exists():
            self.status.config(text="🎓 Aucune leçon à enregistrer.")
            return
        chemin = filedialog.asksaveasfilename(
            title="Enregistrer les leçons", defaultextension=".txt",
            initialfile=f"lecons_acid_{datetime.now().strftime('%Y-%m-%d')}.txt",
            filetypes=[("Texte", "*.txt")])
        if not chemin:
            return
        Path(chemin).write_text(self.LECONS.read_text(encoding="utf-8"), encoding="utf-8")
        self.status.config(text=f"💾 Leçons enregistrées : {Path(chemin).name}")

    def ecole_load(self):
        """📂 Charge un fichier de leçons — remplace ou ajoute, au choix."""
        from tkinter import filedialog, messagebox
        chemin = filedialog.askopenfilename(
            title="Charger un fichier de leçons", filetypes=[("Texte", "*.txt")])
        if not chemin:
            return
        contenu = Path(chemin).read_text(encoding="utf-8", errors="replace").strip()
        if not contenu:
            self.status.config(text="📂 Fichier vide — rien chargé.")
            return
        remplacer = messagebox.askyesno(
            "Charger les leçons",
            "Remplacer les leçons actuelles ?\n\nOui = remplacer tout\nNon = ajouter à la suite")
        if remplacer:
            self.LECONS.write_text(contenu + "\n", encoding="utf-8")
        else:
            with open(self.LECONS, "a", encoding="utf-8") as f:
                f.write(contenu + "\n")
        self.ecole_reload()
        self.status.config(text=f"📂 Leçons chargées depuis {Path(chemin).name}"
                                + (" (remplacement)" if remplacer else " (ajout)"))

    def ecole_validate(self):
        """✅ Demande à ACID IA de valider sa mentalité — verdict affiché ici
        ET annoncé sur Telegram (via LE CERVEAU)."""
        self.ecole_out.delete("1.0", "end")
        self.ecole_out.insert("end", "✅ ACID IA relit toute sa mentalité et rend son verdict…\n")

        def worker():
            try:
                import json as _json, urllib.request
                with urllib.request.urlopen(
                        "http://127.0.0.1:8060/api/ecole?valider=1", timeout=180) as r:
                    res = _json.loads(r.read().decode("utf-8")).get("resultat", "(pas de réponse)")
            except Exception as e:
                res = f"❌ École indisponible : {e} — LE CERVEAU est-il démarré ?"
            self.root.after(0, lambda: (self.ecole_out.delete("1.0", "end"),
                                        self.ecole_out.insert("end", res)))

        threading.Thread(target=worker, daemon=True).start()

    def _ecole_call(self, param, entete):
        """Appel générique d'une action École du CERVEAU, résultat dans la zone texte."""
        self.ecole_out.delete("1.0", "end")
        self.ecole_out.insert("end", entete + "\n")

        def worker():
            try:
                import json as _json, urllib.request
                # param simple («…») -> ?corriger=1 ; param déjà formé
                # («…») -> tel quel
                qs = param if "=" in param else f"{param}=1"
                with urllib.request.urlopen(
                        f"http://127.0.0.1:8060/api/ecole?{qs}", timeout=180) as r:
                    res = _json.loads(r.read().decode("utf-8")).get("resultat", "(pas de réponse)")
            except Exception as e:
                res = f"❌ École indisponible : {e} — LE CERVEAU est-il démarré ?"
            self.root.after(0, lambda: (self.ecole_out.delete("1.0", "end"),
                                        self.ecole_out.insert("end", res), self.ecole_reload()))

        threading.Thread(target=worker, daemon=True).start()

    def ecole_strategie(self):
        """💡 Mistral réfléchit : comment CODER la mentalité apprise (réglage
        existant ou vraie stratégie de code à transférer au patron pour Claude).
        Sur la/les leçon(s) sélectionnée(s), sinon toutes."""
        import urllib.parse
        sel = [self.ecole_list.get(i).split(". ", 1)[-1] for i in self.ecole_list.curselection()]
        param = "strategie"
        if sel:
            param += "=1&lecon=" + urllib.parse.quote("\n".join(sel))
        self._ecole_call(param if sel else "strategie",
                         "💡 Mistral réfléchit à comment coder cette mentalité "
                         "(réglage existant ou stratégie de code à me transférer)…")

    def ecole_corriger(self):
        """🧠 ACID IA réécrit sa mentalité à sa sauce (dédoublonne, jette le
        dangereux) — PROPOSITION seulement, rien n'est encore remplacé."""
        self._ecole_call("corriger", "🧠 ACID IA relit tout et réécrit une mentalité propre à sa "
                                     "sauce (dédoublonnage, tri)… puis clique « 💉 Inject » si ça te va.")

    def ecole_inject(self):
        """💉 Remplace l'ancienne liste par la proposition d'ACID (après ta
        validation) — l'ancienne est sauvegardée en .bak."""
        from tkinter import messagebox
        if not messagebox.askyesno(
                "Injecter la mentalité réécrite",
                "Remplacer TOUTE la liste actuelle par la version réécrite par ACID IA ?\n\n"
                "(l'ancienne sera sauvegardée en .bak — tu dois avoir cliqué « 🧠 Corriger » d'abord)"):
            return
        self._ecole_call("inject", "💉 Injection de la mentalité réécrite…")

    def ecole_doc(self):
        """📄 «…» (15/07) : choisir un .pdf/.docx/.txt — LE CERVEAU le lit en
        entier et en grave les leçons (même pipeline que YouTube)."""
        from tkinter import filedialog
        chemin = filedialog.askopenfilename(
            title="Choisis le document à faire lire au trader",
            filetypes=[("Documents", "*.pdf *.docx *.txt *.md")])
        if not chemin:
            return
        self.ecole_out.delete("1.0", "end")
        self.ecole_out.insert("end", f"📄 Je lis « {Path(chemin).name} » en entier (analyse IA)…\n"
                                     "📚 Un LIVRE complet peut prendre plusieurs minutes — la "
                                     "progression défile dans l'onglet LE CERVEAU.\n")

        def worker():
            try:
                import json as _json, urllib.request
                req = urllib.request.Request(
                    "http://127.0.0.1:8060/api/ecole",
                    data=_json.dumps({"chemin": chemin}).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=900) as r:
                    res = _json.loads(r.read().decode("utf-8")).get("resultat", "(pas de réponse)")
            except Exception as e:
                res = f"❌ École indisponible : {e} — LE CERVEAU est-il démarré ?"
            def maj():
                self.ecole_out.delete("1.0", "end")
                self.ecole_out.insert("end", res.replace("*", "").replace("_", ""))
                self.ecole_reload()
            self.root.after(0, maj)

        threading.Thread(target=worker, daemon=True).start()

    def open_dialogue(self):
        """🗨️ Ouvre la fenêtre du dialogue des IA (ACID IA × LE CERVEAU)."""
        try:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            subprocess.Popen([PY, "ia_dialogue.py"], cwd=str(HERE), env=env, creationflags=NO_WIN)
            self.status.config(text="🗨️ Fenêtre du dialogue des IA ouverte.")
        except Exception as e:
            self.status.config(text=f"❌ dialogue : {e}")

    def arena_report(self):
        """🏟️ Lance `model_arena.py stats` et affiche le classement dans
        l'onglet Arène (thread séparé : ne fige pas la fenêtre)."""
        self.log_q.put(("arena", "\n📊 Génération du classement…"))

        def worker():
            try:
                env = dict(os.environ)
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                r = subprocess.run([PY, "model_arena.py", "stats"], cwd=str(HERE), env=env,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", creationflags=NO_WIN, timeout=60)
                out = (r.stdout or "").strip() or (r.stderr or "").strip() or "(aucune donnée d'arène)"
            except Exception as e:
                out = f"❌ rapport impossible : {e}"
            self.log_q.put(("arena", "──────── CLASSEMENT ────────"))
            for line in out.splitlines():
                self.log_q.put(("arena", line))
            self.log_q.put(("arena", "────────────────────────────"))

        threading.Thread(target=worker, daemon=True).start()

    def restart(self, key):
        self.services[key].stop()
        self.root.after(1500, self.services[key].start)

    def start_all(self):
        self.status.config(text="Nettoyage des anciennes instances puis démarrage échelonné…")
        threading.Thread(target=self._start_all_worker, daemon=True).start()

    def _start_all_worker(self):
        # on épargne les services que CETTE fenêtre gère déjà — on ne tue que
        # les doublons d'un lancement précédent
        mine = {s.proc.pid for s in self.services.values() if s.running()}
        kill_all_external(exclude=mine)
        for cfg in SERVICES:
            key, delay = cfg[0], cfg[5]
            if key == "tunnel":       # le tunnel reste manuel (ON/OFF) — pas exposé sans le vouloir
                continue
            self.root.after(int(delay * 1000), self.services[key].start)

    def kill_zombies(self):
        """🧟 Force la fermeture des ANCIENNES stacks (doublons survivants d'un
        lancement précédent : 2 bots sur le même compte = ordres en double).
        Épargne les services gérés par cette fenêtre — on peut donc cliquer
        sans risque avant un «…» propre."""
        self.status.config(text="🧟 Chasse aux doublons en cours…")

        def worker():
            mine = {s.proc.pid for s in self.services.values() if s.running()}
            n = kill_all_external(exclude=mine)
            msg = (f"🧟 {n} ancien(s) processus fermé(s) — voie libre pour un démarrage propre."
                   if n else "🧟 Aucun doublon trouvé : tout est propre.")
            self.root.after(0, lambda: self.status.config(text=msg))

        threading.Thread(target=worker, daemon=True).start()

    # ⚙️ ---------- ONGLET RÉGLAGES (29/07) ----------
    # (systeme, cle, defaut, role) — EA = envoye en direct via SET|CLE|valeur ;
    # OEIL / MAMMOUTH = constante reecrite dans le .py (redemarrage requis).
    REGLAGES = [
        ("EA", "RISK", "2.0", "% du capital risque par trade"),
        ("EA", "MAXLOT", "0.02", "lot maximum absolu par ordre"),
        ("EA", "MAXPOS", "6", "positions simultanees par chart"),
        ("EA", "MAXDAY", "100", "entrees par jour et par chart"),
        ("EA", "SCOREMIN", "7", "selectivite des entrees (0-12)"),
        ("EA", "SCALP", "0", "moteur scalp M5 (0=off, condamne au backtest)"),
        ("EA", "SCALPMAX", "10", "scalps max par jour"),
        ("EA", "REBOUND", "1", "moteur rebond sur niveau (0/1)"),
        ("EA", "MOM", "1", "moteur momentum / impulsion (0/1)"),
        ("EA", "PENDING", "1", "pose de pendings (0/1)"),
        ("EA", "PGUARD", "1", "ProfitGuard : encaisse un gain qui s essouffle"),
        ("EA", "COTVETO", "1", "veto COT natif de l EA (0/1)"),
        ("EA", "AIVAL", "1", "validation IA de chaque entree (0/1)"),
        ("EA", "CANTRADE", "1", "liberte d action de l IA du chart (0/1)"),
        ("EA", "MAXCLUSTER", "6", "paris correles meme sens max"),
        ("EA", "BEPIPS", "50", "pips de profit avant break-even"),
        ("EA", "TRAILSTART", "120", "pips avant demarrage du trailing"),
        ("EA", "TRAILSTEP", "30", "pas du trailing (pips)"),
        ("EA", "SLATR", "2.0", "SL = X x ATR"),
        ("EA", "TPATR", "3.0", "TP = X x ATR"),
        ("EA", "NEWSMIN", "15", "minutes de blackout autour des news"),
        ("EA", "RECOVERY", "1", "module de recuperation (0/1)"),
        ("OEIL", "MAX_LOT", "0.02", "lot max absolu de L OEIL"),
        ("OEIL", "MAX_POSITIONS_OEIL", "10", "positions max de L OEIL"),
        ("OEIL", "MAX_POSITIONS_COMPTE", "30", "plafond GLOBAL du compte (tous bots)"),
        ("OEIL", "MAX_ACTIONS_PER_DAY", "100", "ouvertures par jour"),
        ("OEIL", "MIN_ACTION_CONF", "70", "confiance mini pour agir (%)"),
        ("OEIL", "COT_VETO_PCT", "20", "seuil du veto COT (% de l OI)"),
        ("OEIL", "RISK_PCT", "10.0", "% du capital par ouverture"),
        ("OEIL", "DAILY_DD_LIMIT_PCT", "10.0", "perte journaliere avant blocage"),
        ("OEIL", "EXIT_BE_AT", "10", "pips avant break-even"),
        ("OEIL", "EXIT_BE_LOCK", "5", "pips verrouilles au BE"),
        ("OEIL", "EXIT_TRAIL_AT", "25", "pips avant trailing"),
        ("OEIL", "EXIT_TRAIL_STEP", "8", "pas du trailing"),
        ("OEIL", "PANIER_MIN_GAIN", "1.0", "gain net du panier avant action (EUR)"),
        ("OEIL", "PANIER_MODE", "verrouiller", "verrouiller | couper"),
        ("OEIL", "RETOUR_POINTS", "250", "points plus loin pour la reprise apres BE"),
        ("OEIL", "REPRISES_MAX", "2", "reprises max du plan avant abandon"),
        ("OEIL", "DISCIPLINE_MAX_SENS", "2", "positions max meme sens (crypto)"),
        ("OEIL", "MEMO_JOURS", "7", "memoire glissante du chat (jours)"),
        ("OEIL", "GERER_MANUEL", "False", "L OEIL gere les trades manuels (False = il n y touche pas)"),
        ("OEIL", "COUNCIL_ACTIF", "False", "chat de groupe (13 appels IA/message) — False = coupe"),
        ("OEIL", "CALLS_CHARTS_ACTIF", "False", "calls des charts 15h/19h — False = coupe"),
        ("MAMMOUTH", "MAX_POSITIONS", "6", "positions simultanees"),
        ("MAMMOUTH", "MIN_CONFIDENCE", "55.0", "seuil ML avant appel IA"),
        ("MAMMOUTH", "RISK_PCT_DEFAULT", "2.0", "% risque par trade"),
        ("MAMMOUTH", "ATR_SL_MULT", "1.5", "SL = X x ATR"),
        ("MAMMOUTH", "ATR_TP_MULT", "2.5", "TP = X x ATR"),
        ("MAMMOUTH", "BE_TRIGGER_PIPS", "18", "pips avant break-even"),
        ("MAMMOUTH", "TRAIL_START_PIPS", "30", "pips avant trailing"),
        ("MAMMOUTH", "TRAIL_STEP_PIPS", "16", "pas du trailing"),
        ("MAMMOUTH", "QUICK_SL_EUR", "3.0", "coupe la perte a -X EUR"),
        ("MAMMOUTH", "QUICK_TP_EUR", "1.0", "encaisse des +X EUR"),
        ("MAMMOUTH", "SYMBOL_COOLDOWN_MIN", "15", "minutes entre 2 entrees / symbole"),
        ("MAMMOUTH", "DAILY_DRAWDOWN_LIMIT_PCT", "10.0", "kill switch journalier (%)"),
        ("MAMMOUTH", "MAMMOUTH_PAUSE_S", "600", "pause apres 3 refus 429 (secondes)"),
    ]

    def _py_fichier(self, systeme):
        return HERE / ("ia_watchdog.py" if systeme == "OEIL" else "BOT_MAMMOUTH_COMPLETE_V7.py")

    def _py_valeur(self, systeme, cle):
        """Lit la valeur ACTUELLE de la constante dans le .py."""
        try:
            motif = re.compile(r"^" + re.escape(cle) + r"\s*=\s*([^#\n]+)")
            for l in self._py_fichier(systeme).read_text(encoding="utf-8").splitlines():
                m = motif.match(l)
                if m:
                    return m.group(1).strip().strip(CHR_D).strip(CHR_S)
        except Exception:
            pass
        return "?"

    def reglages_reload(self):
        """Remplit le tableau avec les valeurs REELLES lues dans le code."""
        for i in self.reg_tree.get_children():
            self.reg_tree.delete(i)
        for sysx, cle, defaut, role in self.REGLAGES:
            val = defaut if sysx == "EA" else self._py_valeur(sysx, cle)
            self.reg_tree.insert("", "end", values=(sysx, cle, val, role))
        self.reg_info.config(text="double-clic sur une ligne pour changer sa valeur")

    def reglages_editer(self, event=None):
        """Double-clic : petite fenetre pour saisir la nouvelle valeur."""
        sel = self.reg_tree.selection()
        if not sel:
            return
        sysx, cle, val, role = self.reg_tree.item(sel[0], "values")
        win = tk.Toplevel(self.root)
        win.title(sysx + " - " + cle)
        win.configure(bg=BG)
        win.geometry("420x170")
        tk.Label(win, text=cle, bg=BG, fg=TXT, font=("Segoe UI", 12, "bold")).pack(pady=(12, 2))
        tk.Label(win, text=role, bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=380).pack()
        e = tk.Entry(win, bg="#010409", fg=TXT, insertbackground=TXT, bd=0,
                     font=("Consolas", 12), justify="center")
        e.insert(0, val)
        e.pack(fill="x", padx=40, pady=10, ipady=6)
        e.focus_set()

        def ok():
            self.reg_tree.item(sel[0], values=(sysx, cle, e.get().strip(), role))
            win.destroy()
            self.reg_info.config(text="valeur modifiee — clique Appliquer la selection")
        tk.Button(win, text="Valider", command=ok, bg="#2ea043", fg="white", bd=0,
                  font=("Segoe UI", 10, "bold"), padx=16, pady=5).pack()
        e.bind("<Return>", lambda ev: ok())

    def spt_reload(self, heures: int = 24):
        """🎯 Recharge le terminal des signaux (lecture du fichier alimenté en
        direct par LE CERVEAU via Telethon — aucun appel réseau ici)."""
        def worker():
            try:
                import importlib, canaux_signaux
                importlib.reload(canaux_signaux)
                txt = canaux_signaux.bloc_spt(heures, limite=40)
            except Exception as e:
                txt = f"🎯 S.P.T indisponible : {e}"
            def maj():
                self.spt_txt.delete("1.0", "end")
                self.spt_txt.insert("end", txt)
            self.root.after(0, maj)
        threading.Thread(target=worker, daemon=True).start()

    def reset_limites_ea(self):
        """🔄 (04/08 patron) Réarme les limites perte-jour + drawdown de l'EA sur
        TOUS les charts, sans attendre minuit. Envoie RESETLIMITS via le pont :
        l'EA recompte les pertes depuis l'équity ACTUELLE et rouvre les entrées.
        (C'est l'alarme «…» en orange du panneau.)"""
        try:
            MT5_FILES.mkdir(parents=True, exist_ok=True)
            (MT5_FILES / "acidbot_commands.txt").write_text(
                "RESETLIMITS", encoding="ansi", errors="replace")
            tk.messagebox.showinfo(
                "Reset limites EA",
                "RESETLIMITS envoyé.\nAu prochain tick, l'EA réarme perte-jour + "
                "drawdown (compteurs repris à l'équity actuelle) et rouvre les entrées.")
        except Exception as e:
            tk.messagebox.showerror("Reset limites EA", "Échec : " + str(e))

    def reglages_appliquer(self):
        """EA -> commande live ; OEIL/MAMMOUTH -> reecriture de la constante."""
        sel = self.reg_tree.selection()
        if not sel:
            self.reg_out.insert("end", "Selectionne d abord une ligne." + CHR_N)
            return
        sysx, cle, val, _role = self.reg_tree.item(sel[0], "values")
        try:
            if sysx == "EA":
                MT5_FILES.mkdir(parents=True, exist_ok=True)
                (MT5_FILES / "acidbot_commands.txt").write_text(
                    "SET|" + cle + "|" + val, encoding="ansi", errors="replace")
                self.reg_out.insert("end", "EA : SET|" + cle + "|" + val +
                                    " envoye — effet immediat sur les charts." + CHR_N)
            else:
                f = self._py_fichier(sysx)
                src = f.read_text(encoding="utf-8")
                brut = val if re.fullmatch(r"-?[0-9.]+", val) else CHR_D + val + CHR_D
                motif = re.compile(r"(?m)^(" + re.escape(cle) + r"\s*=\s*)([^#\n]+)")
                neuf, n = motif.subn(lambda m: m.group(1) + brut + "   ", src, count=1)
                if not n:
                    self.reg_out.insert("end", cle + " introuvable dans " + f.name + CHR_N)
                    return
                f.write_text(neuf, encoding="utf-8")
                self.reg_out.insert("end", sysx + " : " + cle + " = " + val + " ecrit dans " +
                                    f.name + " — REDEMARRE " + sysx + " pour l activer." + CHR_N)
        except Exception as e:
            self.reg_out.insert("end", str(e) + CHR_N)
        self.reg_out.see("end")

    # ---------- 🔔 SYSTRAY (31/07, demande patron) ----------
    # La croix NE FERME PLUS : elle range le Centre dans la zone de
    # notification (et le retire de la barre des taches). Seul le menu
    # clic-droit de l'icone permet de quitter pour de bon.
    def _tray_image(self):
        """Icone generee a la volee (fiole ACID verte) — aucun fichier requis."""
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (13, 17, 23, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((8, 8, 56, 56), fill=(22, 27, 34, 255), outline=(46, 160, 67, 255), width=3)
        d.polygon([(28, 16), (36, 16), (40, 44), (24, 44)], fill=(46, 160, 67, 255))
        d.rectangle((26, 12, 38, 18), fill=(201, 209, 217, 255))
        return img

    def _tray_start(self):
        """Lance l'icone systray dans son propre thread (une seule fois)."""
        if getattr(self, "_tray", None):
            return
        try:
            import pystray
            menu = pystray.Menu(
                pystray.MenuItem("Ouvrir le Centre", self._tray_show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Tout demarrer", lambda i, x: self.root.after(0, self.start_all)),
                pystray.MenuItem("Tout arreter", lambda i, x: self.root.after(0, self.stop_all)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quitter le Centre", self._tray_quit),
            )
            self._tray = pystray.Icon("acid", self._tray_image(), "ACID - Centre de Controle", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception as e:
            self._tray = None
            print("systray indisponible :", e)

    def _tray_show(self, icon=None, item=None):
        """Reaffiche la fenetre (double-clic ou 'Ouvrir')."""
        self.root.after(0, self._restaurer)

    def _restaurer(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _tray_quit(self, icon=None, item=None):
        """Seule vraie sortie : propose d'arreter les services puis ferme."""
        self.root.after(0, self._quitter_pour_de_bon)

    def _quitter_pour_de_bon(self):
        self._restaurer()
        if tk.messagebox.askyesno("Quitter", "Arreter aussi tous les services ?"):
            self.stop_all()
        try:
            if getattr(self, "_tray", None):
                self._tray.stop()
        except Exception:
            pass
        self.root.after(300, self.root.destroy)

    def _on_close(self):
        """La croix range dans le systray au lieu de fermer."""
        self._tray_start()
        if getattr(self, "_tray", None):
            self.root.withdraw()          # disparait de la barre des taches
            if not getattr(self, "_tray_dit", False):
                self._tray_dit = True
                try:
                    self._tray.notify("Le Centre tourne en arriere-plan.\n"
                                      "Clic droit sur l'icone pour le rouvrir ou quitter.",
                                      "ACID - Centre de Controle")
                except Exception:
                    pass
        else:
            self._quitter_pour_de_bon()   # systray KO : on garde l'ancien comportement

    def stop_all(self):
        for s in self.services.values():
            s.stop()
        threading.Thread(target=kill_all_external, daemon=True).start()
        self.status.config(text="Tous les services arrêtés.")

    # 🎨 palette du camembert (assez de teintes distinctes pour ~10 fonctions)
    # 🎨 --- onglet VISUALISATION (personnalisation panneau + Vision) ---
    VISU_COLORS = [   # (cle cfg, libelle, defaut RGB — = defauts de l'EA)
        ("title",  "Titre du panneau",  (255, 215, 0)),
        ("ia",     "Ligne IA",          (0, 191, 255)),
        ("text",   "Texte / chiffres",  (192, 192, 192)),
        ("tp",     "TP1/TP2/TP3",       (255, 215, 0)),
        ("sig",    "Action du bot",     (144, 238, 144)),
        ("obbull", "Order Block +",     (0, 128, 128)),
        ("obbear", "Order Block −",     (128, 0, 0)),
        ("fvg",    "Fair Value Gap",    (47, 79, 79)),
        ("lines",  "Lignes clés",       (218, 165, 32)),
        ("fibo",   "Fibonacci",         (147, 112, 219)),
        ("arrbuy", "Flèche BUY",        (0, 255, 0)),
        ("arrsell","Flèche SELL",       (255, 0, 0)),
        ("objentry","Ligne d'entrée",   (255, 215, 0)),
        ("objsl",  "Ligne SL",          (255, 99, 71)),
        ("objtp",  "Lignes TP (objectifs)", (50, 205, 50)),
        ("objpend","Ligne pending",     (30, 144, 255)),
    ]
    VISU_TOGGLES = [  # (cle cfg, libelle, defaut)
        ("rsi", "RSI", True), ("adx", "ADX", True), ("atr", "ATR", True),
        ("spread", "Spread", True), ("regime", "Régime / biais", True),
        ("pos", "Positions", True), ("lastsig", "Dernière action", True),
    ]

    def _build_visu_tab(self, nb):
        visu = tk.Frame(nb, bg=BG)
        top = tk.Frame(visu, bg=BG); top.pack(fill="x", pady=(6, 2))
        tk.Button(top, text="✅ Appliquer (l'EA lit en 3 s)", command=self.visu_apply,
                  bg="#2ea043", fg="white", bd=0, font=("Segoe UI", 9, "bold"),
                  padx=12, pady=5).pack(side="left", padx=6)
        tk.Button(top, text="↺ Défauts", command=self.visu_reset, bg=CARD, fg=TXT,
                  bd=0, font=("Segoe UI", 9), padx=10, pady=5).pack(side="left")
        tk.Label(top, text="couleurs & infos affichées par l'IA sur le chart", bg=BG,
                 fg=MUTED, font=("Segoe UI", 8, "italic")).pack(side="right", padx=8)

        body = tk.Frame(visu, bg=BG); body.pack(fill="both", expand=True, padx=6)
        # colonne gauche : couleurs
        left = tk.LabelFrame(body, text=" Couleurs ", bg=BG, fg=TXT, bd=1,
                             font=("Segoe UI", 9, "bold"), labelanchor="n")
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.visu_colors = {}       # cle -> [r,g,b]
        self.visu_swatch = {}       # cle -> bouton (pastille)
        for key, label, rgb in self.VISU_COLORS:
            row = tk.Frame(left, bg=BG); row.pack(fill="x", pady=2, padx=6)
            tk.Label(row, text=label, bg=BG, fg=TXT, font=("Segoe UI", 9),
                     width=16, anchor="w").pack(side="left")
            self.visu_colors[key] = list(rgb)
            sw = tk.Button(row, text="        ", bg=self._rgb_hex(rgb), bd=1,
                           command=lambda k=key: self.visu_pick(k))
            sw.pack(side="left", padx=4)
            self.visu_swatch[key] = sw
        # colonne droite : infos + police
        right = tk.LabelFrame(body, text=" Infos affichées ", bg=BG, fg=TXT, bd=1,
                              font=("Segoe UI", 9, "bold"), labelanchor="n")
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.visu_toggles = {}
        for key, label, dflt in self.VISU_TOGGLES:
            v = tk.BooleanVar(value=dflt)
            self.visu_toggles[key] = v
            tk.Checkbutton(right, text=label, variable=v, bg=BG, fg=TXT, selectcolor=CARD,
                           activebackground=BG, activeforeground=TXT, bd=0, anchor="w",
                           font=("Segoe UI", 9), highlightthickness=0).pack(fill="x", padx=8, pady=1)
        fr = tk.Frame(right, bg=BG); fr.pack(fill="x", padx=8, pady=(10, 2))
        tk.Label(fr, text="Taille police :", bg=BG, fg=TXT, font=("Segoe UI", 9)).pack(side="left")
        self.visu_font = tk.IntVar(value=11)
        tk.Spinbox(fr, from_=7, to=20, width=4, textvariable=self.visu_font,
                   font=("Segoe UI", 9)).pack(side="left", padx=6)
        nb.add(visu, text="🎨 Visualisation")

    def _rgb_hex(self, rgb):
        return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def visu_pick(self, key):
        cur = self._rgb_hex(self.visu_colors[key])
        res = colorchooser.askcolor(color=cur, title="Couleur")
        if res and res[0]:
            self.visu_colors[key] = [int(c) for c in res[0]]
            self.visu_swatch[key].config(bg=self._rgb_hex(self.visu_colors[key]))

    def visu_reset(self):
        for key, _, rgb in self.VISU_COLORS:
            self.visu_colors[key] = list(rgb)
            self.visu_swatch[key].config(bg=self._rgb_hex(rgb))
        for key, _, dflt in self.VISU_TOGGLES:
            self.visu_toggles[key].set(dflt)
        self.visu_font.set(11)

    def visu_apply(self):
        try:
            lines = [f"font={self.visu_font.get()}"]
            for key, _, _ in self.VISU_COLORS:
                r, g, b = self.visu_colors[key]
                lines.append(f"{key}={r},{g},{b}")
            for key, _, _ in self.VISU_TOGGLES:
                lines.append(f"{key}={1 if self.visu_toggles[key].get() else 0}")
            MT5_FILES.mkdir(parents=True, exist_ok=True)
            (MT5_FILES / "acid_display.cfg").write_text("\n".join(lines) + "\n", encoding="ascii")
            self.status.config(text="🎨 Config d'affichage envoyée — l'EA l'applique dans ~3 s sur tous les charts.")
        except Exception as e:
            self.status.config(text=f"🎨 échec écriture config : {e}")

    TOKENS_PALETTE = ["#1f6feb", "#2ea043", "#d29922", "#8250df", "#e5534b",
                      "#3fb950", "#db61a2", "#0aa2c0", "#bc8cff", "#f0883e"]

    def tokens_refresh(self):
        """🧮 Redessine le camembert + le tableau de conso du jour PAR FONCTION.
        Best-effort : ne casse jamais le Centre ; se reprogramme toutes les 30 s."""
        try:
            import token_meter
            d = token_meter.jour_courant()   # relit token_stats.json à chaque appel
            fonctions = d.get("fonctions", {}) or {}
            cnv = self.tokens_canvas
            cnv.delete("all")
            self.tokens_text.delete("1.0", "end")
            items = sorted(fonctions.items(),
                           key=lambda kv: kv[1]["entree"] + kv[1]["sortie"], reverse=True)
            total = sum(v["entree"] + v["sortie"] for _, v in items)
            if not items or total <= 0:
                cnv.create_text(150, 150, text="pas encore\nde données\n(redémarre LE CERVEAU)",
                                fill=MUTED, font=("Segoe UI", 11), justify="center")
                self.tokens_text.insert("end", "Aucune conso enregistrée aujourd'hui.\n\n"
                                        "Le camembert se remplira dès que LE CERVEAU et MAMMOUTH\n"
                                        "tourneront avec la nouvelle version (redémarrage requis).")
                self.tokens_head.config(text="conso IA du jour, par fonction — chiffres réels")
                self.root.after(30000, self.tokens_refresh)
                return
            # --- camembert ---
            x0, y0, x1, y1 = 20, 30, 280, 290
            start = 90.0   # on démarre en haut
            for i, (nom, v) in enumerate(items):
                tt = v["entree"] + v["sortie"]
                extent = -360.0 * tt / total   # sens horaire
                col = self.TOKENS_PALETTE[i % len(self.TOKENS_PALETTE)]
                cnv.create_arc(x0, y0, x1, y1, start=start, extent=extent,
                               fill=col, outline="#010409", width=2)
                start += extent
            # --- tableau / légende ---
            jour_tot_e = d.get("entree", 0); jour_tot_s = d.get("sortie", 0)
            attr = 100 * total / ((jour_tot_e + jour_tot_s) or 1)
            self.tokens_head.config(
                text=f"jour : {jour_tot_e + jour_tot_s:,} tok · {d.get('appels', 0)} appels "
                     f"· {attr:.0f}% attribué".replace(",", " "))
            self.tokens_text.tag_config("hdr", foreground=TXT)
            self.tokens_text.insert("end", f"{'FONCTION':<26}{'TOKENS':>11}{'  %':>6}{'  APPELS':>9}"
                                           f"{'  MOY/APPEL':>12}\n", "hdr")
            self.tokens_text.insert("end", "─" * 72 + "\n", "hdr")
            for i, (nom, v) in enumerate(items):
                tt = v["entree"] + v["sortie"]
                col = self.TOKENS_PALETTE[i % len(self.TOKENS_PALETTE)]
                moy = tt // v["appels"] if v["appels"] else 0
                tag = f"c{i}"
                self.tokens_text.tag_config(tag, foreground=col)
                ligne = (f"{'█ ' + nom[:24]:<26}{tt:>11,}{100 * tt / total:>5.0f}%"
                         f"{v['appels']:>9,}{moy:>12,}\n").replace(",", " ")
                self.tokens_text.insert("end", ligne, tag)
        except Exception as e:
            try:
                self.tokens_text.insert("end", f"\n(compteur indisponible : {str(e)[:80]})")
            except Exception:
                pass
        self.root.after(30000, self.tokens_refresh)

    def retrain_ml(self):
        """🧠 Réentraîne le ML (ml_v2_entrainer.py, sur les bougies Vantage)
        puis demande au serveur ML de recharger (/force_retrain).
        🩹 16/09 : ce bouton lançait train_model.py, qui recréait l'ancien
        modèle VTMarkets (AUC 0,507 = pile ou face). Le nouvel entraîneur ne
        remplace le modèle en service QUE s'il passe tout le protocole (fossé,
        paranoïa, 6 mois glissants, réserve de 30 jours) ; sinon il ne touche à
        rien. Il lui faut MT5 ouvert, et plusieurs minutes."""
        self.status.config(text="🧠 Réentraînement ML en cours…")

        def worker():
            try:
                env = dict(os.environ)
                env["PYTHONIOENCODING"] = "utf-8"; env["PYTHONUTF8"] = "1"
                r = subprocess.run([PY, "-u", "ml_v2_entrainer.py"], cwd=str(HERE), env=env,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=1800, creationflags=NO_WIN)
                for ligne in (r.stdout or "").splitlines():
                    self.log_q.put(("ml", ligne))
                auc = ""
                for ligne in (r.stdout or "").splitlines():
                    if "VALIDÉ ET ENREGISTRÉ" in ligne or "REFUSÉ" in ligne or "avec filtre" in ligne:
                        auc = ligne.strip()
                # recharger le modèle dans le serveur ML s'il tourne
                rechargé = ""
                try:
                    import urllib.request
                    urllib.request.urlopen("http://127.0.0.1:8001/force_retrain", timeout=8)
                    rechargé = " · modèle rechargé dans le serveur ✅"
                except Exception:
                    rechargé = " · (redémarre le serveur ML pour charger)"
                msg = ("🧠 Réentraînement terminé — " + (auc or "voir l'onglet ML") + rechargé)
                self.root.after(0, lambda: self.status.config(text=msg))
            except Exception as e:
                self.root.after(0, lambda: self.status.config(text=f"❌ réentraînement ML : {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def show_tunnel(self):
        """🌍 Démarre le tunnel (service intégré) s'il est éteint, sinon copie le
        lien depuis son onglet. Plus de console à part : le lien s'affiche dans
        l'onglet «…» comme n'importe quel autre service."""
        svc = self.services["tunnel"]
        if not svc.up():
            svc.start()
            self.status.config(text="🌍 Tunnel en démarrage… le lien apparaît dans l'onglet « 🌍 Tunnel public » (~8 s), puis reclique ici pour le copier.")
            return
        url = None
        try:
            txt = self.texts["tunnel"].get("1.0", "end")
            m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", txt)
            url = m[-1] if m else None
        except Exception:
            pass
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.status.config(text=f"🌍 {url}  (copié · mot de passe : DASH_PASSWORD de secrets_acid.py)")
            # 20/07 patron : le lien doit AUSSI s'afficher en clair dans
            # l'onglet Tunnel, pas seulement dans la barre du bas.
            for ligne in ("", "═══════════════════════════════════════════════",
                          f"🌍  LIEN PUBLIC : {url}",
                          "🔑  mot de passe dashboard : DASH_PASSWORD de secrets_acid.py",
                          "📋  (lien copié dans le presse-papiers)",
                          "═══════════════════════════════════════════════", ""):
                self.log_q.put(("tunnel", ligne))
        else:
            self.status.config(text="🌍 Tunnel actif — lien pas encore prêt, reclique dans quelques secondes.")

    def _drain_logs(self):
        try:
            for _ in range(400):
                key, line = self.log_q.get_nowait()
                t = self.texts.get(key)
                if not t:
                    continue
                tag = ("err" if any(k in line for k in ("ERROR", "❌", "Traceback", "Erreur"))
                       else "warn" if any(k in line for k in ("WARNING", "⚠️"))
                       else "ok" if any(k in line for k in ("✅", "démarr", "OK")) else None)
                t.insert("end", line + "\n", tag)
                # limite à ~600 lignes par onglet
                if int(t.index("end-1c").split(".")[0]) > 600:
                    t.delete("1.0", "100.0")
                t.see("end")
        except queue.Empty:
            pass
        self.root.after(200, self._drain_logs)

    def _poll_status(self):
        up = 0
        for key, s in self.services.items():
            ok = s.up()
            self.dots[key].config(fg=GREEN if ok else RED if s.proc else MUTED)
            up += 1 if ok else 0
        # MT5
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                               creationflags=NO_WIN, capture_output=True, text=True)
            self.mt5_dot.config(fg=GREEN if "terminal64" in r.stdout else MUTED)
        except Exception:
            pass
        self.status.config(text=f"{up}/{len(self.services)} services en ligne.")
        self.root.after(2000, self._poll_status)



if __name__ == "__main__":
    from tkinter import messagebox
    tk.messagebox = messagebox
    root = tk.Tk()
    App(root)
    root.mainloop()
