"""
Client d'export Finviz Elite (Epic 13) — source OPTIONNELLE de la Passe B.

Une requête HTTP authentifiée rend l'export CSV du screener (une ligne par titre de
l'univers filtré, ~70 colonnes). `snapshot()` le parse en un dictionnaire par ticker
dont les CLÉS SONT CELLES DU `.info` yfinance lues par `screener_backend.enrich_ticker` :
la Passe B lit donc un instantané au lieu d'appeler Yahoo titre par titre, sans qu'une
seule ligne du corps de l'enrichissement change (branché au Sprint 2 —
`FILTERS["enrich_source"]`, défaut du code : Yahoo).

Deux invariants tiennent tout le module :

  - **Jamais fatal.** Jeton absent, réseau muet, CSV illisible, cellule vide : `None`
    (ou un champ à `None`), jamais une exception. Le clapet de la Passe B s'appuie
    là-dessus pour retomber sur le chemin Yahoo dans le même scan.
  - **Le jeton ne sort jamais.** Il vit dans `config/local.yml` (gitignoré), le code
    n'a pas de défaut, et aucun journal n'imprime l'URL ni le message d'une exception
    réseau — `requests` recopie l'URL complète dans le sien.

Défauts du code NEUTRES : sans section `finviz:` en config locale, pas de jeton, donc
module INACTIF (`snapshot()` rend `None` sans tenter la moindre requête).
"""
from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

# Défauts NEUTRES — sans jeton, le module est inactif.
CFG = {
    "export_url": "",   # lien d'export du compte Elite, SANS son paramètre d'authentification
    "token": "",        # jeton d'authentification — config locale seulement, jamais versionné
}

CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "/app/config/local.yml"))

_TIMEOUT_S = 20
_RETRIES = 2        # sobre : 3 tentatives au total
_BACKOFF_S = 2.0

# Cellules « pas de valeur » de l'export.
_EMPTY = {"", "-", "N/A"}

_SUFFIXES = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

# Formats de date rencontrés dans l'export. L'API d'export horodate les dates de
# résultats (« 3/25/2026 4:30:00 PM ») ; « Feb 25 » (sans année) est traité à part.
_DATE_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%Y-%m-%d", "%b %d %Y", "%b %d, %Y")


# ---------------------------------------------------------------------------
# Normalisation des cellules — toute valeur illisible vaut None, jamais une exception
# ---------------------------------------------------------------------------

def _text(raw) -> str | None:
    """Cellule texte. Vide, « - » ou « N/A » → None."""
    txt = (raw or "").strip()
    return None if txt in _EMPTY else txt


def _number(raw) -> float | None:
    """« 412.50M » → 412500000.0. Sans suffixe, la valeur telle quelle."""
    txt = _text(raw)
    if txt is None:
        return None
    txt = txt.replace(",", "").replace("$", "")
    mult = _SUFFIXES.get(txt[-1:].upper(), 1.0)
    if mult != 1.0:
        txt = txt[:-1]
    try:
        return float(txt) * mult
    except ValueError:
        return None


def _millions(raw) -> float | None:
    """
    Capitalisation ou nombre d'actions de l'export API : servi EN MILLIONS, SANS
    suffixe (vérifié sur l'export réel le 2026-09-05 — une capitalisation small cap
    arrive comme « 233.06 »). Un suffixe explicite, s'il apparaît, garde le pas.
    """
    txt = _text(raw)
    if txt is None:
        return None
    if txt[-1:].upper() in _SUFFIXES:
        return _number(txt)
    valeur = _number(txt)
    return None if valeur is None else valeur * 1e6


def _fraction(raw) -> float | None:
    """« 3.45% » → 0.0345 — les champs de pourcentage du contrat sont des FRACTIONS."""
    txt = _text(raw)
    if txt is None:
        return None
    try:
        return float(txt.rstrip("%").replace(",", "")) / 100.0
    except ValueError:
        return None


def _epoch(raw) -> float | None:
    """Date de l'export → secondes epoch UTC (minuit), l'unité des dates du contrat."""
    txt = _text(raw)
    if txt is None:
        return None
    # « Feb 25/a », « 2/25/2026 AMC » : le moment de la séance ne fait pas partie de la date.
    for marker in ("/a", "/b", "AMC", "BMO"):
        txt = txt.replace(marker, "")
    txt = txt.strip()
    for fmt in _DATE_FORMATS:
        try:
            quand = datetime.strptime(txt, fmt)
            # L'heure de séance éventuelle ne fait pas partie de la date : minuit UTC.
            return quand.replace(hour=0, minute=0, second=0,
                                 tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    # ponytail: l'export affiche parfois la date de résultats sans année (« Feb 25 ») —
    # on prend la prochaine occurrence, une date de résultats regardant vers l'avant.
    try:
        jour = datetime.strptime(txt, "%b %d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    maintenant = datetime.now(tz=timezone.utc)
    an = maintenant.year + (1 if (jour.replace(year=maintenant.year) - maintenant).days < -182 else 0)
    return jour.replace(year=an).timestamp()


def _exchange(raw) -> str | None:
    """Nom de place Finviz → code de place yfinance, via EXCHANGES. Inconnue → None."""
    txt = _text(raw)
    return None if txt is None else EXCHANGES.get(txt.upper())


# ---------------------------------------------------------------------------
# Table de correspondance — SOURCE UNIQUE (documentée dans docs/backend.md)
# ---------------------------------------------------------------------------

# Finviz nomme les places de cotation, yfinance les code (`FILTERS["allowed_exchanges"]`
# compare des codes). L'export ne distingue pas les trois compartiments NASDAQ : tous
# rendent le code du compartiment principal, qui est celui des places autorisées.
EXCHANGES = {
    "NASDAQ": "NMS",
    "NASD": "NMS",
    "NYSE": "NYQ",
    "AMEX": "ASE",            # NYSE American — hors places autorisées, comme aujourd'hui
    "NYSE AMERICAN": "ASE",
}

# (colonne de l'export, clé du contrat d'enrichissement, normalisation)
FIELD_MAP = (
    ("Company",           "shortName",              _text),
    ("Sector",            "sector",                 _text),
    ("Industry",          "industry",               _text),
    ("Exchange",          "exchange",               _exchange),
    # Intitulés VÉRIFIÉS sur l'export réel (2026-09-05) — l'API d'export nomme les
    # colonnes plus longuement que l'écran du screener.
    ("Market Cap",        "marketCap",              _millions),
    ("Shares Float",      "floatShares",            _millions),
    ("Short Float",       "shortPercentOfFloat",    _fraction),
    ("Insider Ownership", "heldPercentInsiders",    _fraction),
    ("Sales Growth Quarter Over Quarter", "revenueGrowth", _fraction),
    ("Earnings Date",     "earningsTimestampStart", _epoch),
    ("IPO Date",          "firstTradeDateEpochUtc", _epoch),
)

# Champs du contrat SANS équivalent dans l'export : présents et à None — neutres, donc
# jamais pénalisants (`cash_positive` reste None, la date de repli n'est pas essayée).
#   longName          : l'export n'a qu'une colonne de nom, servie en shortName
#   earningsTimestamp : clé de repli du contrat, la principale suffit
#   totalCash/Debt    : l'export donne des ratios, pas les valeurs absolues du bilan
UNMAPPED = ("longName", "earningsTimestamp", "totalCash", "totalDebt")


# ---------------------------------------------------------------------------
# Config locale — section `finviz:` de config/local.yml (gitignoré)
# ---------------------------------------------------------------------------

def load_config(path: Path | None = None) -> None:
    """
    Surcharge CFG avec la section `finviz:` de la config locale, si elle existe.

    Fichier absent, illisible, section absente : CFG reste NEUTRE (module inactif).
    Les clés inconnues sont ignorées — cette lecture ne doit jamais empêcher un
    démarrage, le module n'étant qu'une source optionnelle.
    """
    path = CONFIG_FILE if path is None else path
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return
    section = raw.get("finviz") if isinstance(raw, dict) else None
    if isinstance(section, dict):
        CFG.update({k: v for k, v in section.items() if k in CFG})


load_config()


# ---------------------------------------------------------------------------
# Récupération et parsing
# ---------------------------------------------------------------------------

def _get(url: str) -> str | None:
    """Seule sortie réseau du module — doublée en test."""
    reponse = requests.get(url, timeout=_TIMEOUT_S)
    return reponse.text if reponse.status_code == 200 else None


def _export_url() -> str:
    """Lien d'export + jeton d'authentification."""
    separateur = "&" if "?" in CFG["export_url"] else "?"
    return f"{CFG['export_url']}{separateur}auth={CFG['token']}"


def _fetch(url: str) -> str | None:
    """Le CSV, ou None après retries. N'imprime JAMAIS l'URL ni le message d'erreur."""
    for tentative in range(_RETRIES + 1):
        try:
            texte = _get(url)
            if texte:
                return texte
            print("[finviz] export sans contenu")
        except Exception as e:
            # Type seul : le message de `requests` recopie l'URL, donc le jeton.
            print(f"[finviz] export indisponible : {type(e).__name__}")
        if tentative < _RETRIES:
            time.sleep(_BACKOFF_S * (tentative + 1))
    return None


def _parse(texte: str) -> dict[str, dict]:
    """CSV → un dict par ticker, portant TOUTES les clés du contrat (valeur ou None)."""
    lignes = csv.DictReader(io.StringIO(texte.lstrip("\ufeff")))   # l'export peut porter un BOM
    instantane: dict[str, dict] = {}
    for ligne in lignes:
        ticker = (ligne.get("Ticker") or "").strip().upper()
        if not ticker:
            continue
        instantane[ticker] = {
            **dict.fromkeys(UNMAPPED),
            **{cle: norm(ligne.get(colonne)) for colonne, cle, norm in FIELD_MAP},
        }
    return instantane


def snapshot() -> dict[str, dict] | None:
    """
    Instantané fondamental de l'univers, par ticker — ou None (module inactif, export
    indisponible, CSV illisible). Jamais d'exception : le repli est l'affaire de l'appelant.
    """
    if not CFG["token"] or not CFG["export_url"]:
        return None
    texte = _fetch(_export_url())
    if texte is None:
        return None
    try:
        return _parse(texte)
    except Exception as e:
        print(f"[finviz] export illisible : {type(e).__name__}")
        return None
