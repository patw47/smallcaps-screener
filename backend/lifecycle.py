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

import json
from datetime import date
from pathlib import Path

import pandas as pd

# Mémo daté du balayage des dépôts officiels (Epic 12 S2). Fichier du répertoire de
# données, pas un mémo mémoire : le conteneur redémarre plusieurs fois par jour et un
# mémo mémoire ferait re-balayer tout le suivi à chaque départ.
_FILING_MEMO = "edgar_tracking_daily.json"


def _today() -> str:
    """Jour calendaire courant — seul point d'entrée de l'horloge (simulée en test)."""
    return date.today().isoformat()


def _memo_path() -> Path:
    """Chemin du mémo, résolu à l'appel : le répertoire de données peut être redirigé."""
    import screener_backend
    return Path(screener_backend.DATA_DIR) / _FILING_MEMO


def _price_flags(df: pd.DataFrame | None) -> dict:
    """
    Drapeaux prix ACTUELS d'un titre suivi, depuis sa série DÉJÀ en main (celle du
    scan du jour ou du complément Epic 9 S1) : aucun appel réseau.

    Mêmes capteurs que la Passe A du scan (source unique : `sub_dollar_marker`,
    `_reverse_split_marker`). Série absente ou illisible ⇒ AUCUN drapeau : un dossier
    de risque ne doit jamais faire tomber une ligne de suivi.
    """
    if df is None or "Close" not in df:
        return {}
    from screener_backend import sub_dollar_marker, _reverse_split_marker
    try:
        days, sub_flag = sub_dollar_marker(df["Close"].dropna())
        rs_flag, rs_date = _reverse_split_marker(df)
    except Exception:
        return {}
    return {"sub_dollar_flag": sub_flag, "sub_dollar_days": days,
            "reverse_split_flag": rs_flag, "reverse_split_date": rs_date}


def current_risk_markers(df: pd.DataFrame | None, filings: dict | None = None) -> list[dict]:
    """
    Dossier de risque ACTUEL : drapeaux prix et faits des dépôts officiels composés
    ENSEMBLE par `scoring.risk_markers` — un seul appel, donc un seul ordre de gravité
    décroissante. Codes + niveaux + variables, jamais de texte d'affichage.

    `filings` est le dict de `edgar.survival_signals` (ou None quand EDGAR est muet) :
    ses clés `*_flag` / `*_date` sont exactement celles que lit le composeur, aucune
    traduction intermédiaire. Rien à signaler ⇒ liste VIDE, jamais de clé absente.
    """
    from scoring import risk_markers
    return risk_markers({**_price_flags(df), **(filings or {})})


def scan_filings(tickers) -> dict[str, dict | None]:
    """
    Signaux de dépôt des titres suivis, AU PLUS un balayage par jour calendaire et par
    ticker — les dépôts sont datés au jour, un second appel le même jour ne rapporte
    rien et coûte à la SEC. Le mémo est daté et écrit dans le répertoire de données :
    il survit au redémarrage du conteneur.

    EDGAR muet, désactivé, ticker inconnu ou capteur en erreur ⇒ `None` MÉMORISÉ comme
    un résultat : la cadence tient aussi les jours où EDGAR ne répond pas. Jamais fatal
    — le suivi complet doit être servi même sans un seul dépôt lu.
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
    # Journal de console : le balayage ne se raconte JAMAIS dans le payload servi.
    print(f"[suivi] dépôts officiels : {len(todo)} interrogé(s), "
          f"{len(wanted) - len(todo)} depuis le mémo du jour")
    return memo


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


def track_row(base: dict, entry: dict, df: pd.DataFrame | None, cfg: dict,
              filings: dict | None = None) -> dict:
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
           "checkpoint": None, "phase": "no_data", "status": {"code": "no_data"},
           # Risque ACTUEL, distinct de `risk_markers` (figé à l'entrée, porté par
           # `entry`) : recalculé à chaque construction depuis la série en main et les
           # dépôts du balayage du jour. Posé avant tout retour anticipé — une ligne
           # sans prix porte une liste vide, pas une clé absente ; elle peut même
           # porter un fait de dépôt, seule information restante d'un titre radié.
           "risk_markers_now": current_risk_markers(df, filings)}
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
