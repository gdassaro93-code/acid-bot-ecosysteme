# -*- coding: utf-8 -*-
# =====================================================
#  📋 LE TABLEAU — chaque système laisse sa fiche, tout le monde peut la lire
#
#  IDÉE DU PATRON (16/09) :
#    «…
#      …
#      …
#      …»
#    «…
#      …
#      …»
#    «…
#      …»
#
#  POURQUOI ÇA MARCHE ICI : c'est déjà prouvé dans cet écosystème. Le CERVEAU
#  ne peut pas lire le calendrier économique (le paquet Python de MT5 a 46
#  fonctions, aucune pour ça) — il lit le fichier que l'EA lui laisse. Même
#  machine, même disque, zéro réseau, zéro clé d'API. Ce module généralise ça.
#
#  ── TROIS RÈGLES, ET ELLES COMPTENT ────────────────────────────────────
#
#  1. UNE FICHE EST UN ÉTAT, PAS UN JOURNAL.
#     Chaque écriture REMPLACE la précédente. Une fiche fait 300 à 800 octets
#     et ne grossit jamais. Le patron demandait «…
#     …» — avec un état, il n'y a rien à
#     effacer : le fichier d'aujourd'hui EST le fichier de toujours.
#     (Ce qui doit s'accumuler — leçons, journaux — a déjà ses propres
#     fichiers ; ce n'est pas le rôle du tableau.)
#
#  2. TOUTE FICHE DIT QUAND ELLE A ÉTÉ ÉCRITE.
#     Un bot arrêté laisse sa fiche derrière lui. Sans horodatage, le lecteur
#     croirait une information morte. `lire()` renvoie toujours `_age_s`, et
#     `frais()` refuse ce qui est trop vieux. Une fiche périmée ne ment pas :
#     elle se tait.
#
#  3. FAITS SEULEMENT.
#     Des nombres, des oui/non, des noms de marché. Pas de phrases, pas
#     d'émojis, pas de commentaires. Si une valeur ne change JAMAIS une
#     décision chez celui qui la lit, elle n'a rien à faire là.
#
#  ── LE FORMAT ──────────────────────────────────────────────────────────
#      # cerveau | 2026-09-16 03:45:12 | pid 21184
#      positions=12
#      risque_pct=7.0
#      gele=0
#  Lisible par le patron dans le Bloc-notes, parsable en trois lignes.
#
#  ── L'ÉCRITURE EST ATOMIQUE ────────────────────────────────────────────
#  On écrit dans un .tmp puis on remplace. Sans ça, un lecteur qui tombe
#  pendant l'écriture lit une demi-fiche et croit que le risque est à 0.
# =====================================================
import os
import time
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent / "tableau"
FRAIS_DEFAUT_S = 120.0        # au-delà, une fiche n'est plus une nouvelle

# Les systèmes du Centre de contrôle. Le nom de la fiche = le nom du service.
FICHES = {
    "cerveau":   "décide et exécute — positions, risque, gel, solde",
    "mammouth":  "le bot Telegram — pause, tilt, pertes consécutives",
    "ea":        "ACID IA dans MT5 — écrit depuis MQL5 (acid_*.txt)",
    "ml":        "le modèle — dernier entraînement, qualité, avis du jour",
    "serveur":   "les API externes — news, COT, disponibilité",
    "oeil1":     "crypto → NAS100",
    "oeil2":     "métaux → EURUSD+",
    "oeil3":     "cassure du range d'ouverture",
    "oeil4":     "choc de volatilité",
    "oeil5":     "devises → USDJPY+",
    "oeil6":     "le veto de risque — blocs ouverts, refus",
}


def _chemin(nom: str) -> Path:
    nom = "".join(c for c in str(nom).lower() if c.isalnum() or c in "_-")
    if not nom:
        raise ValueError("nom de fiche vide")
    return DOSSIER / f"{nom}.txt"


def ecrire(nom: str, **faits) -> bool:
    """Pose (ou remplace) la fiche de ce système.

    Les valeurs sont converties en texte simple : les booléens deviennent 0/1
    — un lecteur écrit en MQL5 ou lu à l'œil n'a pas à connaître «…».
    Une valeur None est simplement omise plutôt qu'écrite «…» : une
    information absente et une information nulle ne sont pas la même chose."""
    try:
        DOSSIER.mkdir(exist_ok=True)
        lignes = [f"# {nom} | {time.strftime('%Y-%m-%d %H:%M:%S')} | "
                  f"pid {os.getpid()}"]
        for cle, val in faits.items():
            if val is None:
                continue
            if isinstance(val, bool):
                val = 1 if val else 0
            elif isinstance(val, float):
                val = f"{val:.4g}"
            txt = str(val).replace("\n", " ").replace("|", "/").strip()
            lignes.append(f"{cle}={txt}")
        cible = _chemin(nom)
        tmp = cible.with_suffix(".tmp")
        tmp.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        os.replace(tmp, cible)      # atomique : jamais de demi-fiche lue
        return True
    except Exception:
        return False


def lire(nom: str) -> dict:
    """La fiche d'un système, plus son âge en secondes sous `_age_s`.

    Renvoie {} si elle n'existe pas. Les valeurs restent du TEXTE : c'est au
    lecteur de convertir ce dont il a besoin, avec sa propre tolérance aux
    saletés. Convertir ici obligerait à deviner, et deviner finit toujours par
    transformer une panne en chiffre plausible."""
    try:
        f = _chemin(nom)
        brut = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    d = {}
    for ligne in brut.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if "=" in ligne:
            k, _, v = ligne.partition("=")
            d[k.strip()] = v.strip()
    if d:
        try:
            d["_age_s"] = round(time.time() - f.stat().st_mtime, 1)
        except Exception:
            d["_age_s"] = 1e9
    return d


def frais(nom: str, max_age_s: float = FRAIS_DEFAUT_S) -> dict:
    """La fiche, mais seulement si elle est encore d'actualité.

    Un système arrêté laisse sa dernière fiche sur le disque ; la lire sans
    regarder son âge revient à décider sur l'état d'hier."""
    d = lire(nom)
    if not d or d.get("_age_s", 1e9) > max_age_s:
        return {}
    return d


def tous(max_age_s: float = None) -> dict:
    """Toutes les fiches présentes -> {nom: fiche}."""
    out = {}
    if not DOSSIER.exists():
        return out
    for f in sorted(DOSSIER.glob("*.txt")):
        d = lire(f.stem)
        if d and (max_age_s is None or d.get("_age_s", 1e9) <= max_age_s):
            out[f.stem] = d
    return out


def bloc(max_age_s: float = 300.0, sauf: str = None) -> str:
    """Le tableau en quelques lignes, pour le contexte du CERVEAU.

    `sauf` évite de se relire soi-même : le cerveau n'apprend rien de sa
    propre fiche, et chaque ligne inutile dans un prompt coûte de l'argent au
    patron."""
    lignes = []
    for nom, d in tous(max_age_s).items():
        if sauf and nom == sauf:
            continue
        faits = " ".join(f"{k}={v}" for k, v in d.items()
                         if not k.startswith("_"))
        if faits:
            lignes.append(f"  {nom} ({d['_age_s']:.0f}s) : {faits}")
    return ("\n📋 TABLEAU DES SYSTÈMES (ce que les autres ont laissé) :\n"
            + "\n".join(lignes)) if lignes else ""


def etat() -> str:
    """Pour le patron : qui écrit, qui s'est tu."""
    out = ["📋 LE TABLEAU — " + str(DOSSIER)]
    vues = tous()
    for nom, role in FICHES.items():
        d = vues.get(nom)
        if not d:
            out.append(f"   ○ {nom:<10} aucune fiche          — {role}")
        else:
            age = d["_age_s"]
            marque = "●" if age <= FRAIS_DEFAUT_S else "◐"
            quand = f"{age:.0f}s" if age < 3600 else f"{age/3600:.1f}h"
            n = len([k for k in d if not k.startswith("_")])
            out.append(f"   {marque} {nom:<10} {n:>2} faits, il y a {quand:<8}— {role}")
    for nom in vues:
        if nom not in FICHES:
            out.append(f"   ? {nom:<10} fiche inconnue au catalogue")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(etat())
