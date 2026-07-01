"""
SmallCaps Screener — Screener principal (entonnoir 2 passes)

Passe A — prix/volume en batch sur tout l'univers (yf.download groupé) :
           filtres durs prix / perf 1m / liquidité / tendance,
           calcul des signaux vol_ratio / compression / force relative.
Passe B — enrichissement `.info` uniquement sur les survivants :
           filtres durs market cap / exchange, signaux fondamentaux,
           scoring, génération de screener_data.json.

Découpler prix (batch, fiable) et fondamentaux (.info, coûteux) permet de
couvrir l'univers complet au coût d'un ancien scan partiel, et réduit le
nombre d'appels `.info` → moins de throttling Yahoo.
"""

import json
import os
import time
import math
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf
import pandas as pd
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# FILTRES — tous les seuils configurables ici
# ---------------------------------------------------------------------------
FILTERS = {
    # Hard filters — tout ticker qui échoue est éliminé
    "market_cap_min_m": 50,        # millions USD
    "market_cap_max_m": 2000,
    "price_min": 2.0,              # USD
    "price_max": 25.0,             # fourchette resserrée 2-25$ (essai)
    "ipo_year_min": 2015,          # informatif uniquement (plus de points)
    "perf_1m_min": -0.35,
    "perf_1m_max": 0.25,           # garde-fou léger « pas déjà explosé » (le scoring gère le reste)
    "vol_window_short": 10,        # jours pour vol court
    "vol_window_long": 50,         # jours pour vol long (baseline)
    "compression_window": 20,      # jours pour range compressé
    "compression_baseline": 90,    # jours baseline range
    "compression_threshold": 0.70, # range 20j < 70% range 90j
    # --- Tendance (Palier 1) ---
    "ma_trend_window": 50,         # MA de tendance
    "ma_slope_lookback": 10,       # pente = MA(t) vs MA(t-10)
    "trend_require_above_ma": False, # prix > MA50 = SCORING (plus un filtre dur) → capte le début de hausse
    # --- Force relative ---
    "rs_benchmark": "IWM",         # ETF Russell 2000 (small caps US)
    "rs_return_window": 63,        # ~3 mois de bourse
    "rs_line_lookback": 21,        # pente RS-line sur ~1 mois
    "rs_require": False,           # RS = SCORING (plus un filtre dur) → ne pas exiger « déjà fort »
    # --- Liquidité (Palier 1) ---
    "dollar_vol_window": 20,
    "dollar_vol_min": 1_000_000,   # USD, plancher médian (hard) — §9 revue quant, vraie tradabilité
    # --- Signaux affinés (§9) ---
    "use_atr_compression": True,   # compression via True Range (High/Low) au lieu du Close-only
    "obv_lookback": 21,            # OBV en hausse sur ~1 mois → accumulation (vs distribution)
    "high_window": 252,            # fenêtre plus-haut 52 sem. (informatif : pct_52w_high)
    "near_high_pct": 0.75,         # informatif
    "float_max": 50_000_000,       # float < 50M actions → petit float amplifie
    "rs_strong": 0.20,             # surperf RS ≥ 20% (informatif)
    # --- Inflexion précoce : capter le DÉBUT de hausse, pas le sommet ---
    "pivot_window": 50,            # plus-haut de la base RÉCENTE (~10 sem.) — le point de cassure
    "near_pivot_pct": 0.85,        # prix ≥ 85% du plus-haut récent → près du pivot de breakout
    "low_ext_pct": 0.12,           # prix ≤ MA50 × 1.12 → peu étiré (encore tôt)
    # --- Mode de scoring : NON tranché tant que le backtest robuste n'a pas décidé ---
    # "binary"     : ancien score « cases à cocher » (connu/conservateur ; plafonne ~8)
    # "continuous" : facteurs continus → percentile → décile 0-10 (échelle pleine, non validé)
    "scoring_mode": "binary",
    # --- Poids de scoring (utilisés par les deux modes ; configurables pour le backtest) ---
    "score_weights": {
        "accumulation": 4,  # OBV↑ : l'argent rentre (LE meilleur signal pré-explosion)
        "compression": 3,   # base serrée : ressort armé
        "near_pivot": 2,    # proche du point de cassure de la base récente
        "low_ext": 2,       # peu étiré : encore tôt
        "rs_turning": 2,    # la force relative repart à la hausse
        "above_ma": 1,      # au-dessus de la MA50
        "insider": 2, "cash": 1, "revenue": 1, "low_float": 1, "short": 1,
    },
    # --- Filet de sécurité : échantillon NON biaisé des survivants si trop nombreux ---
    "enrich_max": 150,             # borne dure du nb d'appels .info (coût + throttle Yahoo)
    # Soft filters — scoring uniquement
    "vol_ratio_min": 1.2,
    "vol_ratio_max": 3.0,
    "insider_pct_min": 5.0,
    "revenue_growth_min": 0.10,
    "short_interest_high": 15.0,
    # Scoring
    "score_vol_ratio_min": 1.3,
    "score_vol_ratio_max": 2.5,
    "allowed_exchanges": {"NMS", "NYQ", "NGM", "NCM"},
    "rate_limit_s": 0.3,           # entre lots yf.download (Passe A)
    "cache_minutes": 30,
    "max_tickers": 800,            # échantillon univers/scan, rééchantillonné à chaque clic (seed None)
    "download_chunk": 100,         # taille des lots yf.download
    "history_period": "1y",        # 1 an : requis pour plus-haut 52 sem. + ATR90 (Palier 2)
    "enrich_workers": 2,           # threads .info en Passe B — BAS : Yahoo bannit l'IP au-delà
    "enrich_jitter_s": 0.5,        # jitter aléatoire par appel .info (anti-throttle Yahoo)
    "enrich_retries": 4,           # retries sur YFRateLimitError
    "enrich_backoff_s": 3.0,       # base du backoff exponentiel (3, 6, 12, 24s + jitter)
    "shuffle_seed": None,          # int → scan déterministe ; None → aléatoire
}

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_FILE = Path(DATA_DIR) / "screener_data.json"
HISTORY_DIR = Path(DATA_DIR) / "history"   # instantanés datés pour le suivi de performance

scan_state = {
    "scanning": False,
    "progress": 0,
    "total": 0,
    "phase": "idle",  # idle | download | price_filter | enrich
}


# ---------------------------------------------------------------------------
# Découverte dynamique des tickers
# ---------------------------------------------------------------------------

def discover_tickers() -> list[str]:
    """
    Récupère les tickers depuis le NASDAQ API (pré-filtré small/micro cap) et Finviz.
    Dédoublonne, mélange (seed optionnel pour reproductibilité), cappe à max_tickers.
    """
    tickers: set[str] = set()
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    # Source 1 : NASDAQ API — pré-filtré sur small + micro caps
    for marketcap in ("Small", "Micro"):
        try:
            resp = requests.get(
                "https://api.nasdaq.com/api/screener/stocks"
                f"?tableonly=true&limit=5000&exchange=nasdaq&marketcap={marketcap}",
                headers=headers,
                timeout=20,
            )
            rows = resp.json().get("data", {}).get("table", {}).get("rows") or []
            before = len(tickers)
            for row in rows:
                symbol = (row.get("symbol") or "").strip().upper()
                if symbol and "." not in symbol and "/" not in symbol:
                    tickers.add(symbol)
            print(f"[discovery] NASDAQ {marketcap}: +{len(tickers) - before} tickers")
        except Exception as e:
            print(f"[discovery] NASDAQ {marketcap} erreur: {e}")

    # Source 2 : Finviz scraping
    try:
        resp = requests.get(
            "https://finviz.com/screener.ashx?v=111&f=cap_small,exch_nasd,geo_usa",
            headers=headers,
            timeout=20,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        before = len(tickers)
        for a in soup.select("a.screener-link-primary"):
            symbol = a.text.strip().upper()
            if symbol:
                tickers.add(symbol)
        print(f"[discovery] Finviz: +{len(tickers) - before} tickers")
    except Exception as e:
        print(f"[discovery] Finviz erreur: {e}")

    result = list(tickers)
    if FILTERS["shuffle_seed"] is not None:
        random.seed(FILTERS["shuffle_seed"])  # scan reproductible (backtest / diff)
    random.shuffle(result)
    cap = FILTERS["max_tickers"]
    print(f"[discovery] Pool total: {len(result)} tickers → cap à {cap}")
    return result[:cap]


# ---------------------------------------------------------------------------
# Helpers (fonctions pures, testables hors ligne)
# ---------------------------------------------------------------------------

def _safe_float(val, default=None):
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if series is None or len(series) < periods + 1:
        return None
    old = series.iloc[-periods - 1]
    new = series.iloc[-1]
    if old == 0:
        return None
    return (new - old) / old


def _range_pct(series: pd.Series, window: int) -> float | None:
    """Range (High-Low) sur `window` jours / dernier prix."""
    if series is None or len(series) < window:
        return None
    sl = series.iloc[-window:]
    rng = sl.max() - sl.min()
    ref = series.iloc[-1]
    if ref == 0:
        return None
    return rng / ref


def _sma(series: pd.Series, window: int) -> float | None:
    if series is None or len(series) < window:
        return None
    return float(series.iloc[-window:].mean())


def _ma_rising(series: pd.Series, window: int, lookback: int) -> bool | None:
    """Pente de la MA >= 0 : MA(aujourd'hui) >= MA(il y a `lookback` jours)."""
    if series is None or len(series) < window + lookback:
        return None
    now = series.iloc[-window:].mean()
    past = series.iloc[-window - lookback:-lookback].mean()
    return bool(now >= past)


def _median_dollar_volume(close: pd.Series, volume: pd.Series, window: int) -> float | None:
    if close is None or volume is None or len(close) < window or len(volume) < window:
        return None
    dv = close.iloc[-window:] * volume.iloc[-window:]
    val = float(dv.median())
    return None if math.isnan(val) else val


def _atr(df: pd.DataFrame, window: int) -> float | None:
    """ATR (moyenne du True Range) sur `window` jours. Nécessite High/Low/Close."""
    if df is None or not {"High", "Low", "Close"}.issubset(df.columns) or len(df) < window + 1:
        return None
    high, low, prev_close = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    val = float(tr.iloc[-window:].mean())
    return None if math.isnan(val) else val


def _obv_rising(close: pd.Series, volume: pd.Series, lookback: int) -> bool | None:
    """
    On-Balance Volume en hausse sur `lookback` jours → accumulation (acheteurs > vendeurs).
    Distingue l'accumulation de la distribution, ce que le ratio de volume brut ne fait pas (§9).
    """
    if close is None or volume is None or len(close) < lookback + 2:
        return None
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * volume).cumsum()
    return bool(obv.iloc[-1] > obv.iloc[-lookback - 1])


def _accum_fraction(close: pd.Series, volume: pd.Series, lookback: int) -> float | None:
    """
    Accumulation CONTINUE : fraction de volume directionnel net sur `lookback` jours,
    dans [-1, 1] (comparable entre tickers). +1 = tout le volume est acheteur, -1 = vendeur.
    Version continue de l'OBV, pour le scoring en percentile.
    """
    if close is None or volume is None or len(close) < lookback + 1:
        return None
    d = close.diff().iloc[-lookback:]
    v = volume.iloc[-lookback:]
    signed = float((v * d.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).sum())
    total = float(v.sum())
    return signed / total if total else None


def _pct_of_high(close: pd.Series, window: int) -> float | None:
    """Dernier prix / plus-haut sur `window` jours (position dans le range 52 sem.)."""
    if close is None or len(close) == 0:
        return None
    w = min(window, len(close))
    hi = float(close.iloc[-w:].max())
    if hi == 0:
        return None
    return float(close.iloc[-1]) / hi


def _rs_metrics(close: pd.Series, bench_close: pd.Series,
                ret_window: int, line_lookback: int) -> tuple[bool | None, bool | None, float | None]:
    """
    Force relative vs benchmark. Aligne les deux séries sur leurs dates communes.
    Retourne (surperforme, RS-line en hausse, magnitude = surperf relative sur ret_window).
    """
    if close is None or bench_close is None:
        return None, None, None
    joined = pd.concat([close, bench_close], axis=1, join="inner").dropna()
    if len(joined) < max(ret_window, line_lookback) + 1:
        return None, None, None
    s, b = joined.iloc[:, 0], joined.iloc[:, 1]
    if s.iloc[-ret_window - 1] == 0 or b.iloc[-ret_window - 1] == 0:
        return None, None, None
    s_ret = s.iloc[-1] / s.iloc[-ret_window - 1] - 1
    b_ret = b.iloc[-1] / b.iloc[-ret_window - 1] - 1
    strength = float(s_ret - b_ret)          # magnitude continue (Palier 2 / #4)
    outperf = bool(s_ret > b_ret)
    rs_line = s / b
    rising = bool(rs_line.iloc[-1] > rs_line.iloc[-line_lookback - 1])
    return outperf, rising, strength


def _build_positives_flags(stock: dict) -> tuple[list[str], list[str]]:
    positives, flags = [], []

    vr = stock.get("vol_ratio")
    if vr and FILTERS["score_vol_ratio_min"] <= vr <= FILTERS["score_vol_ratio_max"]:
        positives.append(f"Volume en hausse x{vr:.1f} (zone idéale)")
    elif vr and vr > FILTERS["score_vol_ratio_max"]:
        flags.append(f"Volume très élevé x{vr:.1f} (possible spike)")

    if stock.get("accumulation"):
        positives.append("OBV en hausse : accumulation (acheteurs > vendeurs)")

    if stock.get("compressed"):
        positives.append("Base serrée (compression ATR) — ressort armé")

    if stock.get("near_pivot"):
        pct = (stock.get("pct_recent_high") or 0) * 100
        positives.append(f"Proche du pivot de sa base récente ({pct:.0f}%) — sur le point de casser")

    if stock.get("low_ext"):
        positives.append("Peu étiré (proche de la MA50) — début de mouvement, pas après")

    if stock.get("rs_turning"):
        positives.append("Force relative qui repart à la hausse (retournement)")

    if stock.get("price_above_ma50"):
        positives.append("Cours au-dessus de la MA50")

    if stock.get("change_1m") is not None and stock["change_1m"] * 100 < -15:
        flags.append(f"Correction forte 1 mois ({stock['change_1m']*100:+.1f}%)")

    if stock.get("insider_buying"):
        positives.append(f"Insiders détiennent {stock.get('insider_pct', 0):.1f}% du capital")

    if stock.get("low_float"):
        positives.append(f"Petit float ({(stock.get('float_shares') or 0)/1e6:.0f}M actions) — mouvements amplifiés")

    # cash_positive : None = donnée absente → ni positif ni flag (ne pas pénaliser)
    if stock.get("cash_positive") is True:
        positives.append("Trésorerie > dette (bilan sain)")
    elif stock.get("cash_positive") is False:
        flags.append("Dette supérieure à la trésorerie")

    if stock.get("revenue_growth") and stock["revenue_growth"] > FILTERS["revenue_growth_min"]:
        positives.append(f"Croissance revenus +{stock['revenue_growth']*100:.0f}%")

    if stock.get("short_interest_pct") and stock["short_interest_pct"] > FILTERS["short_interest_high"]:
        positives.append(f"Short interest élevé {stock['short_interest_pct']:.1f}% → potentiel squeeze")

    if stock.get("ipo_year") and stock["ipo_year"] >= FILTERS["ipo_year_min"]:
        positives.append(f"IPO récente ({stock['ipo_year']})")

    return positives, flags


def _tech_rules(sig: dict) -> list[tuple[bool, int]]:
    """Règles TECHNIQUES (prix/volume, sans .info) — dispo dès la Passe A."""
    W = FILTERS["score_weights"]
    return [
        (bool(sig.get("accumulation")), W["accumulation"]),   # OBV↑ : l'argent rentre (pilier)
        (bool(sig.get("compressed")), W["compression"]),      # base serrée (pilier)
        (bool(sig.get("near_pivot")), W["near_pivot"]),       # près du pivot de breakout
        (bool(sig.get("low_ext")), W["low_ext"]),             # peu étiré : encore tôt
        (bool(sig.get("rs_turning")), W["rs_turning"]),       # force relative qui repart
        (bool(sig.get("price_above_ma50")), W["above_ma"]),   # au-dessus MA50
    ]


def _fundamental_rules(stock: dict) -> list[tuple[bool, int]]:
    """Règles FONDAMENTALES (via .info) — ajoutées en Passe B."""
    W = FILTERS["score_weights"]
    return [
        (bool(stock.get("insider_buying")), W["insider"]),
        (stock.get("cash_positive") is True, W["cash"]),      # None ne compte pas
        (bool(stock.get("revenue_growth") and
              stock["revenue_growth"] > FILTERS["revenue_growth_min"]), W["revenue"]),
        (bool(stock.get("low_float")), W["low_float"]),
        (bool(stock.get("short_interest_pct") and
              stock["short_interest_pct"] > FILTERS["short_interest_high"]), W["short"]),
    ]


def _binary_price_score(sig: dict) -> int:
    """[Ancienne version binaire — conservée pour comparaison au backtest.]"""
    return sum(w for cond, w in _tech_rules(sig) if cond)


def _binary_score(stock: dict) -> int:
    """[Ancienne version binaire — conservée pour comparaison au backtest.]"""
    rules = _tech_rules(stock) + _fundamental_rules(stock)
    raw = sum(w for cond, w in rules if cond)
    raw_max = sum(w for _, w in rules)
    return round(10 * raw / raw_max) if raw_max else 0


# ---------------------------------------------------------------------------
# Scoring PERCENTILE de facteurs continus (recommandation quant)
# Chaque facteur → valeur continue → percentile parmi les candidats → moyenne pondérée.
# (key_de_la_valeur, nom_du_poids, higher_is_better)
# ---------------------------------------------------------------------------
TECH_FACTORS = [
    ("f_accum",      "accumulation", True),   # fraction volume directionnel net
    ("f_atr_ratio",  "compression",  False),  # ATR20/ATR90 : plus bas = plus comprimé
    ("f_pct_recent", "near_pivot",   True),   # proximité du plus-haut récent
    ("f_ext",        "low_ext",      False),  # écart à la MA50 : plus bas = plus tôt
    ("f_rs",         "rs_turning",   True),   # magnitude de force relative
]
FUND_FACTORS = [
    ("insider_pct",        "insider",   True),
    ("cash_bin",           "cash",      True),   # 1 / 0 / None(neutre)
    ("revenue_growth",     "revenue",   True),
    ("float_shares",       "low_float", False),  # plus petit float = mieux
    ("short_interest_pct", "short",     True),
]


def _rank_pct(values: list) -> list[float]:
    """Percentile [0,1] de chaque valeur (plus grand = plus proche de 1). None → 0.5 (neutre)."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out = [0.5] * len(values)
    n = len(present)
    if n <= 1:
        return out
    for rank, (i, _) in enumerate(sorted(present, key=lambda x: x[1])):
        out[i] = rank / (n - 1)
    return out


def _factor_composite(items: list[dict], factors: list[tuple]) -> list[float]:
    """Composite ∈ [0,1] par item = moyenne pondérée des percentiles de chaque facteur."""
    W = FILTERS["score_weights"]
    pct = {}
    for key, wname, higher in factors:
        vals = [it.get(key) for it in items]
        if not higher:
            vals = [(-v if v is not None else None) for v in vals]
        pct[wname] = _rank_pct(vals)
    total_w = sum(W[wname] for _, wname, _ in factors) or 1
    return [sum(W[wname] * pct[wname][i] for _, wname, _ in factors) / total_w
            for i in range(len(items))]


def _select_scores(signals_list: list[dict]) -> list[float]:
    """
    Score technique des survivants pour choisir qui enrichir (ordre seul).
    Suit FILTERS['scoring_mode'] pour rester cohérent avec le score final.
    """
    if FILTERS["scoring_mode"] == "continuous":
        return _factor_composite(signals_list, TECH_FACTORS)
    return [float(_binary_price_score(s)) for s in signals_list]


def _score_candidates(candidates: list[dict]) -> None:
    """
    Écrit `score` (0-10) dans chaque candidat, en place, selon FILTERS['scoring_mode'] :
      - "binary"     : ancien score « cases à cocher » (par ticker ; plafonne ~8).
      - "continuous" : moyenne pondérée de percentiles de facteurs continus, étalée en RANG
        DÉCILE (le meilleur du vivier du jour = 10). Le rang évite le tassement au milieu.
    """
    if FILTERS["scoring_mode"] == "continuous":
        comp = _factor_composite(candidates, TECH_FACTORS + FUND_FACTORS)
        ranks = _rank_pct(comp)
        for stock, r in zip(candidates, ranks):
            stock["score"] = round(10 * r)
    else:
        for stock in candidates:
            stock["score"] = _binary_score(stock)


# ---------------------------------------------------------------------------
# Téléchargement prix en batch
# ---------------------------------------------------------------------------

def _extract_symbol(data: pd.DataFrame, sym: str) -> pd.DataFrame | None:
    """Extrait le sous-DataFrame OHLCV d'un ticker depuis le résultat yf.download."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if sym not in data.columns.get_level_values(0):
                return None
            sub = data[sym].dropna(how="all")
        else:
            sub = data.dropna(how="all")  # chunk d'un seul symbole
        return sub if not sub.empty else None
    except Exception:
        return None


def _download_prices(tickers: list[str], bench_symbol: str,
                     period: str | None = None) -> dict[str, pd.DataFrame]:
    """Télécharge l'OHLCV de tous les tickers (+ benchmark) en lots groupés.
    `period` par défaut = FILTERS["history_period"] ; surchargé par le backtest (ex. 2y)."""
    prices: dict[str, pd.DataFrame] = {}
    all_syms = tickers + [bench_symbol]
    chunk = FILTERS["download_chunk"]
    n_chunks = (len(all_syms) + chunk - 1) // chunk
    period = period or FILTERS["history_period"]

    for idx in range(0, len(all_syms), chunk):
        part = all_syms[idx:idx + chunk]
        try:
            data = yf.download(
                part, period=period, interval="1d",
                group_by="ticker", auto_adjust=True,
                threads=True, progress=False,
            )
        except Exception as e:
            print(f"[download] lot {idx // chunk + 1}/{n_chunks} erreur: {e}")
            continue
        for sym in part:
            df = _extract_symbol(data, sym)
            if df is not None:
                prices[sym] = df
        print(f"[download] lot {idx // chunk + 1}/{n_chunks} → {len(prices)} séries")
        time.sleep(FILTERS["rate_limit_s"])
    return prices


# ---------------------------------------------------------------------------
# Passe A — filtres prix/volume (aucun réseau, pur calcul sur le DataFrame)
# ---------------------------------------------------------------------------

def analyze_prices(ticker: str, df: pd.DataFrame,
                   bench_close: pd.Series | None) -> tuple[dict | None, str]:
    """Filtres durs prix/volume + signaux techniques. Retourne (signaux, 'ok') ou (None, raison)."""
    if df is None or "Close" not in df or "Volume" not in df:
        return None, "history:cols"
    close = df["Close"].dropna()
    volume = df["Volume"].dropna()
    if len(close) < FILTERS["vol_window_long"] + FILTERS["ma_slope_lookback"]:
        return None, f"history:{len(close)}j"

    # --- Prix ---
    price = _safe_float(close.iloc[-1])
    if price is None:
        return None, "price:None"
    if not (FILTERS["price_min"] <= price <= FILTERS["price_max"]):
        return None, f"price:{price:.2f}"

    # --- Perf 1 mois (~21 jours de bourse) ---
    change_1m = _pct_change(close, 21)
    if change_1m is None:
        return None, "change_1m:None"
    if not (FILTERS["perf_1m_min"] <= change_1m <= FILTERS["perf_1m_max"]):
        return None, f"change_1m:{change_1m*100:.1f}%"

    # --- Liquidité (hard) ---
    dollar_vol = _median_dollar_volume(close, volume, FILTERS["dollar_vol_window"])
    if dollar_vol is None or dollar_vol < FILTERS["dollar_vol_min"]:
        return None, f"liquidity:{int(dollar_vol) if dollar_vol else 0}"

    # --- Tendance : pente MA50 >= 0, et prix > MA50 si exigé (hard) ---
    ma50 = _sma(close, FILTERS["ma_trend_window"])
    ma50_rising = _ma_rising(close, FILTERS["ma_trend_window"], FILTERS["ma_slope_lookback"])
    if ma50 is None or not ma50_rising:
        return None, "trend:down"
    if FILTERS["trend_require_above_ma"] and price <= ma50:
        return None, "trend:below_ma"

    # --- Signaux de scoring (prix/volume) ---
    change_1d = _pct_change(close, 1)

    vol_recent = float(volume.iloc[-FILTERS["vol_window_short"]:].mean())
    baseline = volume.iloc[-FILTERS["vol_window_long"]:-FILTERS["vol_window_short"]]  # sans recouvrement
    vol_base = float(baseline.median()) if len(baseline) else None
    vol_ratio = vol_recent / vol_base if vol_base and vol_base > 0 else None

    # Compression : ratio ATR court / ATR long (True Range High/Low) — fallback Close-only.
    # atr_ratio = valeur CONTINUE (plus bas = plus comprimé) ; compressed = seuil booléen (affichage).
    compressed = False
    atr_ratio = None
    if FILTERS["use_atr_compression"]:
        atr_s = _atr(df, FILTERS["compression_window"])
        atr_l = _atr(df, FILTERS["compression_baseline"])
        if atr_s is not None and atr_l is not None and atr_l > 0:
            atr_ratio = atr_s / atr_l
    else:
        range_20 = _range_pct(close, FILTERS["compression_window"])
        range_90 = _range_pct(close, FILTERS["compression_baseline"])
        if range_20 is not None and range_90 is not None and range_90 > 0:
            atr_ratio = range_20 / range_90
    if atr_ratio is not None:
        compressed = bool(atr_ratio < FILTERS["compression_threshold"])

    # Accumulation : OBV en hausse (§9 — remplace le ratio de volume brut au scoring)
    accumulation = bool(_obv_rising(close, volume, FILTERS["obv_lookback"]))

    # Position dans le range 52 sem. (informatif) + proche du pivot de la base RÉCENTE (scoring)
    pct_52w = _pct_of_high(close, FILTERS["high_window"])
    near_high = bool(pct_52w is not None and pct_52w >= FILTERS["near_high_pct"])
    pct_recent = _pct_of_high(close, FILTERS["pivot_window"])
    near_pivot = bool(pct_recent is not None and pct_recent >= FILTERS["near_pivot_pct"])

    # Peu étiré : prix proche de la MA50 (encore tôt dans le mouvement, pas après)
    low_ext = bool(ma50 and price <= ma50 * (1 + FILTERS["low_ext_pct"]))

    rs_outperf, rs_line_rising, rs_strength = _rs_metrics(
        close, bench_close, FILTERS["rs_return_window"], FILTERS["rs_line_lookback"]
    )
    rs_signal = bool(rs_outperf and rs_line_rising)
    rs_turning = bool(rs_line_rising)  # la RS repart (retournement) — scoring
    # Filtre RS dur seulement si rs_require=True (par défaut False → RS = scoring).
    if FILTERS["rs_require"] and rs_outperf is not None and not rs_signal:
        return None, "rs:weak"

    # --- Facteurs CONTINUS pour le scoring percentile ---
    f_accum = _accum_fraction(close, volume, FILTERS["obv_lookback"])
    f_ext = (price / ma50 - 1) if ma50 else None

    signals = {
        "price": round(price, 2),
        "change_1d": round(change_1d, 4) if change_1d is not None else None,
        "change_1m": round(change_1m, 4),
        "dollar_volume": round(dollar_vol),
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "compressed": compressed,
        "accumulation": accumulation,
        "pct_52w_high": round(pct_52w, 3) if pct_52w is not None else None,
        "near_high": near_high,
        "pct_recent_high": round(pct_recent, 3) if pct_recent is not None else None,
        "near_pivot": near_pivot,
        "low_ext": low_ext,
        "ma50": round(ma50, 2),
        "price_above_ma50": bool(price > ma50),
        "rs_outperf": bool(rs_outperf) if rs_outperf is not None else None,
        "rs_line_rising": bool(rs_line_rising) if rs_line_rising is not None else None,
        "rs_turning": rs_turning,
        "rs_strength": round(rs_strength, 4) if rs_strength is not None else None,
        "rs_signal": rs_signal,
        # Facteurs continus (scoring percentile) :
        "f_accum": f_accum,
        "f_atr_ratio": atr_ratio,
        "f_pct_recent": pct_recent,
        "f_ext": f_ext,
        "f_rs": rs_strength,
    }
    return signals, "ok"


# ---------------------------------------------------------------------------
# Passe B — enrichissement fondamental (.info, un appel réseau par survivant)
# ---------------------------------------------------------------------------

def _fetch_info(ticker: str) -> dict:
    """
    Fetch .info avec retries + backoff exponentiel sur rate-limit Yahoo.
    Yahoo throttle agressivement l'endpoint .info : sans backoff, un scan complet
    fait bannir l'IP (YFRateLimitError sur tous les appels suivants).
    """
    last_exc = None
    for attempt in range(FILTERS["enrich_retries"] + 1):
        try:
            return yf.Ticker(ticker).info or {}
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "rate" in msg or "too many" in msg or "429" in msg:
                # backoff exponentiel + jitter : laisse Yahoo respirer
                time.sleep(FILTERS["enrich_backoff_s"] * (2 ** attempt) + random.uniform(0, 1.0))
                continue
            raise
    raise last_exc


def enrich_ticker(ticker: str, signals: dict) -> tuple[dict | None, str]:
    """Fetch .info, filtres market cap / exchange, signaux fondamentaux, scoring."""
    # Jitter aléatoire : désynchronise les threads pour éviter les rafales → throttle Yahoo
    if FILTERS["enrich_jitter_s"]:
        time.sleep(random.uniform(0, FILTERS["enrich_jitter_s"]))
    try:
        info = _fetch_info(ticker)
    except Exception as e:
        return None, f"exception:{type(e).__name__}"

    # --- Bourse autorisée ---
    exchange = info.get("exchange", "")
    if exchange not in FILTERS["allowed_exchanges"]:
        return None, f"exchange:{exchange or 'N/A'}"

    # --- Market cap ---
    mc_raw = _safe_float(info.get("marketCap"))
    if mc_raw is None:
        return None, "market_cap:None"
    mc_m = mc_raw / 1e6
    if not (FILTERS["market_cap_min_m"] <= mc_m <= FILTERS["market_cap_max_m"]):
        return None, f"market_cap:{mc_m:.0f}M"

    # --- IPO year — informatif ---
    ipo_epoch = info.get("firstTradeDateEpochUtc")
    ipo_year = datetime.fromtimestamp(ipo_epoch, tz=timezone.utc).year if ipo_epoch else None

    # --- Bilan : None si donnée absente (ne pas pénaliser l'absence) ---
    total_cash = _safe_float(info.get("totalCash"), None)
    total_debt = _safe_float(info.get("totalDebt"), None)
    cash_positive = None if (total_cash is None or total_debt is None) else bool(total_cash > total_debt)

    # --- Insiders / short / revenus / float ---
    insider_pct = (_safe_float(info.get("heldPercentInsiders"), 0) or 0) * 100
    insider_buying = bool(insider_pct > FILTERS["insider_pct_min"])
    short_interest_pct = (_safe_float(info.get("shortPercentOfFloat"), 0) or 0) * 100
    revenue_growth = _safe_float(info.get("revenueGrowth"))
    float_shares = _safe_float(info.get("floatShares"), None)
    low_float = bool(float_shares is not None and float_shares < FILTERS["float_max"])

    stock = {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": exchange,
        "market_cap_m": round(mc_m, 1),
        "insider_pct": round(insider_pct, 2),
        "insider_buying": insider_buying,
        "short_interest_pct": round(short_interest_pct, 2),
        "revenue_growth": round(revenue_growth, 4) if revenue_growth is not None else None,
        "float_shares": int(float_shares) if float_shares is not None else None,
        "low_float": low_float,
        "cash_positive": cash_positive,
        "cash_bin": (1.0 if cash_positive is True else (0.0 if cash_positive is False else None)),
        "ipo_year": ipo_year,
        "catalyst_type": None,
        "catalyst_date": None,
        **signals,  # inclut les facteurs continus f_accum / f_atr_ratio / f_pct_recent / f_ext / f_rs
    }
    # Le score (percentile) est calculé sur l'ENSEMBLE des candidats dans run_scan,
    # pas ici (un percentile n'a de sens que par rapport au vivier). On pose positives/flags.
    stock["positives"], stock["flags"] = _build_positives_flags(stock)
    return stock, "ok"


# ---------------------------------------------------------------------------
# Scan complet (orchestration 2 passes)
# ---------------------------------------------------------------------------

def run_scan(tickers: list[str] | None = None) -> dict:
    """
    Lance le scan. Si tickers est None, découverte dynamique via discover_tickers().
    Passe A (batch prix) → survivants → Passe B (.info) → JSON trié par score.
    """
    watchlist = tickers if tickers is not None else discover_tickers()
    total = len(watchlist)

    scan_state.update({"scanning": True, "progress": 0, "total": total, "phase": "download"})
    rejection_counts: dict[str, int] = {}

    print(f"\n{'='*55}")
    print(f"  SmallCaps Screener — univers de {total} tickers")
    print(f"{'='*55}")

    # --- Téléchargement prix en batch (+ benchmark) ---
    prices = _download_prices(watchlist, FILTERS["rs_benchmark"])
    bench_df = prices.pop(FILTERS["rs_benchmark"], None)
    bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None
    if bench_close is None:
        print(f"[benchmark] {FILTERS['rs_benchmark']} indisponible → force relative ignorée ce scan")

    # --- Passe A : filtres prix/volume sur tout l'univers ---
    scan_state["phase"] = "price_filter"
    survivors: list[tuple[str, dict]] = []
    for ticker in watchlist:
        df = prices.get(ticker)
        if df is None:
            rejection_counts["no_data"] = rejection_counts.get("no_data", 0) + 1
            continue
        signals, reason = analyze_prices(ticker, df, bench_close)
        if signals:
            survivors.append((ticker, signals))
        else:
            cat = reason.split(":")[0]
            rejection_counts[cat] = rejection_counts.get(cat, 0) + 1

    # Classement par SCORE TECHNIQUE PERCENTILE (accumulation en tête) pour choisir qui
    # mérite l'appel .info coûteux. Le percentile est cross-sectionnel : « les meilleures
    # parmi le vivier du jour ». L'accumulation EST la thèse → classer par elle est légitime.
    tech_scores = _select_scores([sig for _, sig in survivors])
    ranked = sorted(zip(survivors, tech_scores),
                    key=lambda x: (x[1], x[0][1].get("dollar_volume") or 0), reverse=True)
    survivors = [s for s, _ in ranked]
    n_all = len(survivors)
    capped = survivors[:FILTERS["enrich_max"]]
    if n_all > len(capped):
        rejection_counts["below_cutoff"] = n_all - len(capped)
    print(f"\n[Passe A] {n_all} survivants / {total} tickers → {len(capped)} enrichis (top score technique)")

    # --- Passe B : enrichissement .info sur les survivants retenus (parallèle, borné) ---
    scan_state.update({"phase": "enrich", "progress": 0, "total": len(capped)})
    candidates = []
    n_surv = len(capped)
    with ThreadPoolExecutor(max_workers=FILTERS["enrich_workers"]) as pool:
        futures = {pool.submit(enrich_ticker, tk, sig): tk for tk, sig in capped}
        for i, fut in enumerate(as_completed(futures), 1):
            scan_state["progress"] = i
            bar_len = 40
            filled = int(bar_len * i / max(n_surv, 1))
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r[{bar}] {i}/{n_surv}  {futures[fut]:<8}", end="", flush=True)

            stock, reason = fut.result()
            if stock:
                candidates.append(stock)
            else:
                cat = reason.split(":")[0]
                rejection_counts[cat] = rejection_counts.get(cat, 0) + 1

    print(f"\n{'='*55}")
    print(f"  {len(candidates)} candidats trouvés sur {total} tickers de l'univers")
    print(f"{'='*55}")
    print(f"\n  Rejections par filtre :")
    for cat, count in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<20} {count:>4} tickers")
    print()

    # Score PERCENTILE final (technique + fondamental) calculé sur l'ENSEMBLE des candidats,
    # puis tri décroissant (magnitude RS en départage).
    _score_candidates(candidates)
    candidates.sort(key=lambda x: (x["score"], x.get("rs_strength") or 0), reverse=True)

    output = {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "universe_size": total,
        "total_scanned": total,
        "survivors_price_filter": n_all,
        "enriched": n_surv,
        "candidates": len(candidates),
        "stocks": candidates,
        "rejection_stats": rejection_counts,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    _write_snapshot(output)   # historique daté pour le suivi de performance
    scan_state.update({"scanning": False, "phase": "idle"})
    return output


def _write_snapshot(output: dict) -> None:
    """
    Enregistre un instantané daté des candidats dans data/history/ pour le suivi de
    performance dans le temps. Chaque scan = un fichier. Ne fait jamais échouer le scan.
    """
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        picks = [
            {
                "ticker": s["ticker"], "score": s["score"], "price": s["price"],
                "sector": s.get("sector"),
                "accumulation": s.get("accumulation"), "compressed": s.get("compressed"),
                "near_pivot": s.get("near_pivot"), "rs_strength": s.get("rs_strength"),
            }
            for s in output.get("stocks", [])
        ]
        snap = {
            "scanned_at": output["scanned_at"],
            "candidates": len(picks),
            "picks": picks,
        }
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        (HISTORY_DIR / f"{ts}.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False))
        print(f"[snapshot] {len(picks)} sélections → history/{ts}.json")
    except Exception as e:
        print(f"[snapshot] erreur (ignorée): {e}")


if __name__ == "__main__":
    run_scan()
