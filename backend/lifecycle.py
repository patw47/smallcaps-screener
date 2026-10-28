"""
Dossier de risque ACTUEL d'un titre : drapeaux prix et faits des dépôts officiels.

Gardé par la refonte de l'Epic 15 (Sprint 2) pour l'alerte post-résultats : les drapeaux
sont affichés à côté de l'alerte, ils ne filtrent rien. Codes + niveaux + variables,
jamais de texte d'affichage — le frontend traduit.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from screener_backend import FILTERS

# Mémo daté du balayage des dépôts officiels (Epic 12 S2). Fichier du répertoire de
# données, pas un mémo mémoire : un redémarrage ne doit pas faire re-balayer.
_FILING_MEMO = "edgar_tracking_daily.json"

# Niveau de gravité de chaque marqueur, émis comme DONNÉE. L'ordre de ce dictionnaire
# est celui de la liste servie : gravité décroissante.
MARKER_LEVELS = {
    "going_concern": "high",
    "reverse_split": "high",
    "dilution": "medium",
    "late_filing": "low",
    "sub_dollar": "low",
}


def _today() -> str:
    """Jour calendaire courant — seul point d'entrée de l'horloge (simulée en test)."""
    return date.today().isoformat()


def _memo_path() -> Path:
    """Chemin du mémo, résolu à l'appel : le répertoire de données peut être redirigé."""
    import screener_backend
    return Path(screener_backend.DATA_DIR) / _FILING_MEMO


def sub_dollar_marker(close: pd.Series) -> tuple[int, bool]:
    """
    Marqueur « cours sous le plancher de cotation » : (longueur de la série, drapeau).

    La règle de conformité ne mord qu'après une série CONSÉCUTIVE sous le plancher. La
    longueur est renvoyée à côté du booléen : c'est elle qui porte la gravité.
    """
    if close is None or len(close) == 0:
        return 0, False
    under = close.tail(FILTERS["sub_dollar_window"]) < FILTERS["sub_dollar_price"]
    run = best = 0
    for u in under:
        run = run + 1 if u else 0
        best = max(best, run)
    return best, bool(best >= FILTERS["sub_dollar_min_days"])


def reverse_split_marker(df: pd.DataFrame) -> tuple[bool | None, str | None]:
    """
    Regroupement d'actions (ratio ∈ ]0,1[) dans la fenêtre : (drapeau, date de l'opération).
    Drapeau None si la colonne manque (capteur muet, neutre).
    """
    if df is None or "Stock Splits" not in df.columns:
        return None, None
    sp = df["Stock Splits"].tail(FILTERS["reverse_split_window"])
    hits = sp[(sp > 0) & (sp < 1)]
    if hits.empty:
        return False, None
    return True, str(pd.Timestamp(hits.index[-1]).date())


def risk_markers(s: dict) -> list[dict]:
    """
    Marqueurs levés, en CODES + variables. Aucun marqueur → liste VIDE.

    Variables portées quand elles existent : `date` (date du fait) et `days` (longueur de
    la série sous le plancher de cotation, qui porte la gravité).
    """
    out = []
    for code, level in MARKER_LEVELS.items():
        if not s.get(f"{code}_flag"):
            continue
        marker = {"code": code, "level": level}
        if s.get(f"{code}_date"):
            marker["date"] = s[f"{code}_date"]
        if code == "sub_dollar" and s.get("sub_dollar_days") is not None:
            marker["days"] = s["sub_dollar_days"]
        out.append(marker)
    return out


def _price_flags(df: pd.DataFrame | None) -> dict:
    """
    Drapeaux prix depuis une série DÉJÀ en main : aucun appel réseau. Série absente ou
    illisible ⇒ AUCUN drapeau.
    """
    if df is None or "Close" not in df:
        return {}
    try:
        days, sub_flag = sub_dollar_marker(df["Close"].dropna())
        rs_flag, rs_date = reverse_split_marker(df)
    except Exception:
        return {}
    return {"sub_dollar_flag": sub_flag, "sub_dollar_days": days,
            "reverse_split_flag": rs_flag, "reverse_split_date": rs_date}


def current_risk_markers(df: pd.DataFrame | None, filings: dict | None = None) -> list[dict]:
    """
    Dossier de risque ACTUEL : drapeaux prix et faits des dépôts officiels composés
    ENSEMBLE, donc un seul ordre de gravité décroissante.

    `filings` est le dict de `edgar.survival_signals` (ou None quand EDGAR est muet).
    Rien à signaler ⇒ liste VIDE, jamais de clé absente.
    """
    return risk_markers({**_price_flags(df), **(filings or {})})


def scan_filings(tickers) -> dict[str, dict | None]:
    """
    Signaux de dépôt des titres, AU PLUS un balayage par jour calendaire et par ticker —
    les dépôts sont datés au jour, un second appel le même jour ne rapporte rien et coûte
    à la SEC. Le mémo est daté et écrit dans le répertoire de données.

    EDGAR muet, désactivé, ticker inconnu ou capteur en erreur ⇒ `None` MÉMORISÉ comme
    un résultat. Jamais fatal.
    """
    day, path = _today(), _memo_path()
    memo: dict[str, dict | None] = {}
    try:
        saved = json.loads(path.read_text())
        if saved.get("day") == day:          # mémo d'hier ⇒ balayage complet
            memo = saved.get("tickers") or {}
    except Exception:
        pass                                 # mémo absent ou illisible ⇒ balayage complet

    wanted = sorted({tk for tk in tickers if tk})
    todo = [tk for tk in wanted if tk not in memo]
    for tk in todo:
        try:
            import edgar
            memo[tk] = edgar.survival_signals(tk)
        except Exception:
            memo[tk] = None
    if todo:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"day": day, "tickers": memo}))
        except Exception:
            pass                             # mémo non écrit ⇒ on re-balaiera, jamais fatal
    print(f"[dépôts] {len(todo)} interrogé(s), {len(wanted) - len(todo)} depuis le mémo du jour")
    return memo
