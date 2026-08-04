"""
Cycle de vie d'un titre suivi (Epic 8 S4) — calendrier d'observation commun aux
deux familles.

Le calendrier (`checkpoint_day`, `horizon`) est un protocole de MESURE, pas un
critère de sélection : il ne dit pas quels titres entrent, seulement quand on les
regarde. Chaque famille passe SON propre cfg — aucune valeur de règle ne vit ici,
et faire diverger un calendrier de l'autre ne demande qu'un cfg différent.

Trois phases, exclusives :
  - "open"    — en observation, la fenêtre court encore
  - "closed"  — l'ancienneté a atteint l'horizon (>= horizon séances) : pile à
                l'horizon la fenêtre est échue, une séance avant elle court encore
  - "no_data" — aucune séance exploitable depuis l'entrée (retrait de la cote ?) ;
                ni ouverte ni close — la ligne reste affichée, c'est l'absence de
                données qui est l'information

Le point de contrôle n'est PAS une sortie : un titre passé sous le seuil reste
"open" jusqu'à l'horizon. Couper les retardataires en cours de route détruit le
rendement mesuré du panier.
"""
from __future__ import annotations

import pandas as pd


def _after_entry(close: pd.Series, entry_date: str) -> pd.Series:
    """
    Séances postérieures à l'entrée. Comparaison robuste : Timestamp explicite aligné
    sur le fuseau de l'index (yfinance renvoie parfois un index tz-aware — comparer à
    un naïf lèverait).
    """
    try:
        entry_ts = pd.Timestamp(entry_date)
        tz = getattr(close.index, "tz", None)
        if tz is not None and entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize(tz)
        return close[close.index > entry_ts]
    except Exception:
        return close.iloc[0:0]


def track_row(base: dict, entry: dict, df: pd.DataFrame | None, cfg: dict) -> dict:
    """
    Une ligne de suivi : `base` (identité — ticker, et la fenêtre pour la Purge
    silencieuse) + `entry` (entry_date, entry_price…), enrichis de la trajectoire
    depuis l'entrée et de sa `phase`.

    Jours de bourse comptés sur l'index du titre lui-même (robuste aux jours fériés).
    `status` et `checkpoint` sont des CODES + variables (Epic 8 S1) traduits par le
    frontend ; les seuils ne voyagent pas ici, le frontend les tient du bloc `display`.
    """
    cp_day, cp_thr, horizon = cfg["checkpoint_day"], cfg["checkpoint_thr"], cfg["horizon"]
    row = {**base, **entry, "days_held": None, "days_left": None, "ret": None,
           "checkpoint": None, "phase": "no_data", "status": {"code": "no_data"}}
    if df is None or "Close" not in df:
        return row
    after = _after_entry(df["Close"].dropna(), entry["entry_date"])
    if not len(after):
        return row

    days = len(after)
    row["days_held"] = days
    row["days_left"] = max(0, horizon - days)
    row["ret"] = round(float(after.iloc[-1]) / entry["entry_price"] - 1, 4)

    if days >= horizon:  # pile à l'horizon ⇒ fenêtre échue
        r_end = float(after.iloc[horizon - 1]) / entry["entry_price"] - 1
        row["phase"] = "closed"
        row["checkpoint"] = {"code": "window_closed", "h": horizon}
        row["status"] = {"code": "explosion" if r_end >= 1.0
                         else "crash" if r_end <= -0.5 else "closed"}
        row["ret_63"] = round(r_end, 4)
        return row

    row["phase"] = "open"  # y compris sous le seuil : le checkpoint n'est pas une sortie
    if days >= cp_day:
        r_cp = float(after.iloc[cp_day - 1]) / entry["entry_price"] - 1
        row["checkpoint"] = {"code": "week_one"}
        row["ret_5"] = round(r_cp, 4)
        row["status"] = {"code": "above" if r_cp >= cp_thr else "below"}
    else:
        row["checkpoint"] = {"code": "too_early"}
        row["status"] = {"code": "too_early", "d": days, "cp": cp_day}
    return row
