"""
Client d'export Finviz Elite (Epic 13) — source OPTIONNELLE de la Passe B.

Une requête HTTP authentifiée rend l'export CSV du screener (une ligne par titre de
l'univers filtré, ~70 colonnes). `snapshot()` le parse en un dictionnaire par ticker
dont les CLÉS SONT CELLES DU `.info` yfinance lues par `screener_backend.enrich_ticker` :
la Passe B lit donc un instantané au lieu d'appeler Yahoo titre par titre, sans qu'une
seule ligne du corps de l'enrichissement change (branché au Sprint 2 —
`FILTERS["enrich_source"]`, défaut du code : Yahoo).

L'Epic 14 S1 élargit la lecture de la MÊME requête, sans en ajouter aucune :
  - trésorerie et dette absolues RECONSTRUITES depuis les colonnes par action
    (`_balance_sheet`) — l'export ne les sert pas telles quelles, et le critère cash
    valait None ici alors que le chemin Yahoo le rendait : c'est un rattrapage de parité,
    pas un critère neuf ;
  - un bloc `context_flags` de colonnes DESCRIPTIVES (`CONTEXT_MAP`), servi à part du
    contrat d'enrichissement parce qu'aucune n'entre au score, au tri ni à la sélection.

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


def _bool(raw) -> bool | None:
    """« Yes » / « No » de l'export → booléen. Toute autre cellule → None."""
    txt = _text(raw)
    return None if txt is None else {"yes": True, "no": False}.get(txt.lower())


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

def _cell(ligne: dict, colonne: str | tuple[str, ...]) -> str | None:
    """
    Valeur brute d'une colonne. Un tuple énumère des intitulés POSSIBLES : le premier
    présent dans l'en-tête gagne.

    L'export API et l'écran du screener ne nomment pas les mêmes colonnes pareil (l'API
    est plus bavarde : « Sales Growth Quarter Over Quarter » pour « Sales Q/Q »), et seul
    un export réel tranche — c'est exactement ce qui a dû être corrigé après le premier
    appel réel de l'Epic 13. Un intitulé inconnu ne lève pas : la cellule vaut None.
    """
    if isinstance(colonne, str):
        return ligne.get(colonne)
    for nom in colonne:
        if nom in ligne:
            return ligne[nom]
    return None


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
# jamais pénalisants (la date de repli n'est pas essayée).
#   longName          : l'export n'a qu'une colonne de nom, servie en shortName
#   earningsTimestamp : clé de repli du contrat, la principale suffit
UNMAPPED = ("longName", "earningsTimestamp")


# --- Drapeaux de contexte (Epic 14 S1) -------------------------------------
# Colonnes du MÊME export (aucune requête de plus), servies dans un bloc à part du
# contrat d'enrichissement : elles décrivent le titre, elles ne le notent pas. Aucune
# n'entre au score, au tri ni à la sélection — le pattern des marqueurs descriptifs.
#
# ⚠️ Intitulés NON VÉRIFIÉS sur un export réel (aucun appel réseau pendant ce sprint) :
# chaque entrée porte l'intitulé long attendu de l'API puis celui de l'écran en repli.
# Un intitulé faux ne casse rien — la cellule vaut None — mais vide le bloc en silence :
# protocole de vérification dans docs/backend.md.
CONTEXT_MAP = (
    (("Insider Transactions", "Insider Trans"),        "insider_transactions",      _fraction),
    (("Institutional Ownership", "Inst Own"),          "institutional_ownership",   _fraction),
    (("Institutional Transactions", "Inst Trans"),     "institutional_transactions", _fraction),
    ("Short Float",                                    "short_float",               _fraction),
    (("Short Ratio", "Short Interest Ratio"),          "short_ratio",               _number),
    ("EPS Surprise",                                   "eps_surprise",              _fraction),
    (("Revenue Surprise", "Sales Surprise"),           "revenue_surprise",          _fraction),
    ("Optionable",                                     "optionable",                _bool),
    ("Shortable",                                      "shortable",                 _bool),
)
CONTEXT_KEYS = tuple(cle for _, cle, _ in CONTEXT_MAP)


# --- Reconstruction du bilan (Epic 14 S1) ----------------------------------
# L'export ne sert pas les valeurs absolues du bilan, mais ses trois colonnes PAR ACTION
# suffisent à les reconstruire — c'est ce qui rend au chemin Finviz le critère cash que
# le chemin Yahoo servait déjà (parité inter-sources).
_PER_SHARE = {
    "cash_ps": (("Cash Per Share", "Cash/sh"), _number),
    "book_ps": (("Book Value Per Share", "Book/sh"), _number),
    "debt_eq": (("Total Debt/Equity", "Debt/Eq"), _number),
    "shares": (("Shares Outstanding", "Outstanding"), _millions),
}


def _balance_sheet(ligne: dict) -> tuple[float | None, float | None]:
    """
    Trésorerie et dette ABSOLUES (dollars), reconstruites depuis les colonnes par action :

        trésorerie = cash par action × actions en circulation
        dette      = dette/capitaux propres × (valeur comptable par action × actions)

    Tout facteur absent ou illisible → None, le pattern d'absence du module : `cash_positive`
    reste neutre côté enrichissement, jamais pénalisant.

    Capitaux propres NÉGATIFS (valeur comptable par action ≤ 0) : le produit rendrait une
    dette négative, donc un bilan faussement sain — le cas le plus dangereux du lot. La
    dette vaut None (neutre), le verdict cash n'est pas rendu.
    """
    v = {cle: norm(_cell(ligne, col)) for cle, (col, norm) in _PER_SHARE.items()}
    actions = v["shares"]
    if actions is None:
        return None, None
    cash = None if v["cash_ps"] is None else v["cash_ps"] * actions
    capitaux = None if (v["book_ps"] is None or v["book_ps"] <= 0) else v["book_ps"] * actions
    dette = None if (capitaux is None or v["debt_eq"] is None) else v["debt_eq"] * capitaux
    return cash, dette


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
        cash, dette = _balance_sheet(ligne)
        instantane[ticker] = {
            **dict.fromkeys(UNMAPPED),
            **{cle: norm(_cell(ligne, colonne)) for colonne, cle, norm in FIELD_MAP},
            "totalCash": cash,
            "totalDebt": dette,
            "context_flags": {cle: norm(_cell(ligne, colonne))
                              for colonne, cle, norm in CONTEXT_MAP},
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
