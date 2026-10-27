# -*- coding: utf-8 -*-
# =====================================================
#  🗨️ DIALOGUE DES IA — la fenêtre où tu regardes tes cerveaux
#  se parler : 🤬 ACID IA (l'IA de chaque chart, le trader énervé)
#  et 🧠 LE CERVEAU (le superviseur). Tail live de ia_dialogue.log.
#  Lancé depuis le Centre de Contrôle (bouton 🗨️ Dialogue IA).
# =====================================================
import io
import sys
from pathlib import Path

import tkinter as tk
from tkinter import scrolledtext

# 🛡️ lancé sous pythonw.exe (Centre) → sys.stdout est None : ne pas planter.
try:
    if sys.stdout is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
FILE = HERE / "ia_dialogue.log"

BG, CARD, TXT, MUTED = "#0d1117", "#161b22", "#c9d1d9", "#8b949e"


class Dialogue:
    def __init__(self, root):
        self.root = root
        root.title("🗨️ Dialogue des IA — ACID IA 🤬 × LE CERVEAU 👁️")
        root.geometry("760x560")
        root.configure(bg=BG)

        tk.Label(root, text="🗨️ CONVERSATION DES CERVEAUX", bg=BG, fg=TXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(root, text="🤬 ACID IA (l'IA de chaque chart) propose · 🧠 LE CERVEAU supervise — en direct",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(0, 6))

        self.t = scrolledtext.ScrolledText(root, bg="#010409", fg=TXT, bd=0,
                                           font=("Consolas", 10), wrap="word",
                                           insertbackground=TXT, spacing3=4)
        self.t.pack(fill="both", expand=True, padx=10, pady=6)
        self.t.tag_config("acid", foreground="#f0883e", lmargin1=10, lmargin2=30)   # orange
        self.t.tag_config("oeil",   foreground="#58a6ff", lmargin1=10, lmargin2=30)   # bleu
        self.t.tag_config("heure",  foreground=MUTED)

        self._pos = 0
        self._seed()
        self.root.after(1000, self._tail)

    def _seed(self):
        try:
            data = FILE.read_text(encoding="utf-8") if FILE.exists() else ""
        except Exception:
            data = ""
        lignes = data.splitlines()[-120:]
        for ln in lignes:
            self._render(ln)
        self._pos = FILE.stat().st_size if FILE.exists() else 0
        if not lignes:
            self.t.insert("end", "  (en attente… les IA parlent quand une ACID IA valide un "
                                 "trade et quand LE CERVEAU analyse)\n", "heure")

    def _render(self, ligne):
        parts = ligne.split(" | ", 2)
        if len(parts) != 3:
            return
        heure, qui, texte = parts
        # «…» = anciennes lignes du log, «…» = nouvelles
        tag = "acid" if ("ACID" in qui or "Sonnet" in qui) else "oeil"
        self.t.insert("end", f"{heure}  ", "heure")
        self.t.insert("end", f"{qui}\n", tag)
        self.t.insert("end", f"   {texte}\n", tag)
        self.t.see("end")

    def _tail(self):
        try:
            if FILE.exists():
                size = FILE.stat().st_size
                if size < self._pos:      # fichier tronqué/roté
                    self._pos = 0
                if size > self._pos:
                    with open(FILE, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._pos)
                        for ln in f.read().splitlines():
                            self._render(ln)
                        self._pos = f.tell()
        except Exception:
            pass
        self.root.after(1000, self._tail)


if __name__ == "__main__":
    r = tk.Tk()
    Dialogue(r)
    r.mainloop()
