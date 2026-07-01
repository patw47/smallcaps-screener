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
    "price_max": 50.0,
    "ipo_year_min": 2015,          # informatif uniquement (plus de points)
    "perf_1m_min": -0.35,
    "perf_1m_max": 0.40,           # assoupli 0.25→0.40 : ne pas amputer les leaders RS (§9)
    "vol_window_short": 10,        # jours pour vol court
    "vol_window_long": 50,         # jours pour vol long (baseline)
    "compression_window": 20,      # jours pour range compressé
    "compression_baseline": 90,    # jours baseline range
    "compression_threshold": 0.70, # range 20j < 70% range 90j
    # --- Tendance (Palier 1) ---
    "ma_trend_window": 50,         # MA de tendance
    "ma_slope_lookback": 10,       # pente = MA(t) vs MA(t-10)
    "trend_require_above_ma": True, # prix > MA50 exigé en plus de pente ≥ 0 (§9 revue quant)
    # --- Force relative (Palier 1) ---
    "rs_benchmark": "IWM",         # ETF Russell 2000 (small caps US)
    "rs_return_window": 63,        # ~3 mois de bourse
    "rs_line_lookback": 21,        # pente RS-line sur ~1 mois
    "rs_require": True,            # RS en filtre DUR (ultra-qualité) — sauf si benchmark indispo
    # --- Liquidité (Palier 1) ---
    "dollar_vol_window": 20,
    "dollar_vol_min": 1_000_000,   # USD, plancher médian (hard) — §9 revue quant, vraie tradabilité
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
    "history_period": "6mo",       # suffit pour MA50/RS63/compression90/vol50, ~2× plus léger que 1y
    "enrich_workers": 2,           # threads .info en Passe B — BAS : Yahoo bannit l'IP au-delà
    "enrich_jitter_s": 0.5,        # jitter aléatoire par appel .info (anti-throttle Yahoo)
    "enrich_retries": 4,           # retries sur YFRateLimitError
    "enrich_backoff_s": 3.0,       # base du backoff exponentiel (3, 6, 12, 24s + jitter)
    "shuffle_seed": None,          # int → scan déterministe ; None → aléatoire
}

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_FILE = Path(DATA_DIR) / "screener_data.json"

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


def _rs_metrics(close: pd.Series, bench_close: pd.Series,
                ret_window: int, line_lookback: int) -> tuple[bool | None, bool | None]:
    """
    Force relative vs benchmark. Aligne les deux séries sur leurs dates communes
    (halts / gaps). Retourne (surperforme sur ret_window, RS-line en hausse).
    """
    if close is None or bench_close is None:
        return None, None
    joined = pd.concat([close, bench_close], axis=1, join="inner").dropna()
    if len(joined) < max(ret_window, line_lookback) + 1:
        return None, None
    s, b = joined.iloc[:, 0], joined.iloc[:, 1]
    if s.iloc[-ret_window - 1] == 0 or b.iloc[-ret_window - 1] == 0:
        return None, None
    s_ret = s.iloc[-1] / s.iloc[-ret_window - 1] - 1
    b_ret = b.iloc[-1] / b.iloc[-ret_window - 1] - 1
    outperf = bool(s_ret > b_ret)
    rs_line = s / b
    rising = bool(rs_line.iloc[-1] > rs_line.iloc[-line_lookback - 1])
    return outperf, rising


def _build_positives_flags(stock: dict) -> tuple[list[str], list[str]]:
    positives, flags = [], []

    vr = stock.get("vol_ratio")
    if vr and FILTERS["score_vol_ratio_min"] <= vr <= FILTERS["score_vol_ratio_max"]:
        positives.append(f"Volume en hausse x{vr:.1f} (zone idéale)")
    elif vr and vr > FILTERS["score_vol_ratio_max"]:
        flags.append(f"Volume très élevé x{vr:.1f} (possible spike)")

    if stock.get("compressed"):
        positives.append("Compression de range détectée (potentiel breakout)")

    if stock.get("rs_signal"):
        positives.append("Force relative > IWM et RS-line en hausse (leader)")

    if stock.get("price_above_ma50"):
        positives.append("Cours au-dessus de la MA50, pente haussière (tendance saine)")

    if stock.get("change_1m") is not None and stock["change_1m"] * 100 < -15:
        flags.append(f"Correction forte 1 mois ({stock['change_1m']*100:+.1f}%)")

    if stock.get("insider_buying"):
        positives.append(f"Insiders détiennent {stock.get('insider_pct', 0):.1f}% du capital")

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


def _compute_score(stock: dict) -> int:
    """
    Score pondéré normalisé sur 10 (corrige l'ancien plafond dur qui écrasait
    l'information au sommet du classement). Chaque règle : (condition, poids).
    """
    rules = [
        (bool(stock.get("vol_ratio") and
              FILTERS["score_vol_ratio_min"] <= stock["vol_ratio"] <= FILTERS["score_vol_ratio_max"]), 2),
        (bool(stock.get("compressed")), 2),
        (bool(stock.get("rs_signal")), 2),                 # force relative (Palier 1)
        (bool(stock.get("insider_buying")), 2),
        (bool(stock.get("price_above_ma50")), 1),          # tendance (Palier 1)
        (stock.get("cash_positive") is True, 1),           # None ne compte pas
        (bool(stock.get("revenue_growth") and
              stock["revenue_growth"] > FILTERS["revenue_growth_min"]), 1),
        (bool(stock.get("short_interest_pct") and
              stock["short_interest_pct"] > FILTERS["short_interest_high"]), 1),
    ]
    raw = sum(w for cond, w in rules if cond)
    raw_max = sum(w for _, w in rules)
    return round(10 * raw / raw_max) if raw_max else 0


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


def _download_prices(tickers: list[str], bench_symbol: str) -> dict[str, pd.DataFrame]:
    """Télécharge l'OHLCV 1 an de tous les tickers (+ benchmark) en lots groupés."""
    prices: dict[str, pd.DataFrame] = {}
    all_syms = tickers + [bench_symbol]
    chunk = FILTERS["download_chunk"]
    n_chunks = (len(all_syms) + chunk - 1) // chunk

    for idx in range(0, len(all_syms), chunk):
        part = all_syms[idx:idx + chunk]
        try:
            data = yf.download(
                part, period=FILTERS["history_period"], interval="1d",
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

    range_20 = _range_pct(close, FILTERS["compression_window"])
    range_90 = _range_pct(close, FILTERS["compression_baseline"])
    compressed = bool(
        range_20 is not None and range_90 is not None and range_90 > 0
        and (range_20 / range_90) < FILTERS["compression_threshold"]
    )

    rs_outperf, rs_line_rising = _rs_metrics(
        close, bench_close, FILTERS["rs_return_window"], FILTERS["rs_line_lookback"]
    )
    rs_signal = bool(rs_outperf and rs_line_rising)
    # Force relative en filtre DUR (ultra-qualité). Si benchmark indispo → rs_outperf None
    # → on ne rejette pas (fallback gracieux, RS redevient scoring only).
    if FILTERS["rs_require"] and rs_outperf is not None and not rs_signal:
        return None, "rs:weak"

    signals = {
        "price": round(price, 2),
        "change_1d": round(change_1d, 4) if change_1d is not None else None,
        "change_1m": round(change_1m, 4),
        "dollar_volume": round(dollar_vol),
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "compressed": compressed,
        "ma50": round(ma50, 2),
        "price_above_ma50": bool(price > ma50),
        "rs_outperf": bool(rs_outperf) if rs_outperf is not None else None,
        "rs_line_rising": bool(rs_line_rising) if rs_line_rising is not None else None,
        "rs_signal": rs_signal,
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

    # --- Insiders / short / revenus ---
    insider_pct = (_safe_float(info.get("heldPercentInsiders"), 0) or 0) * 100
    insider_buying = bool(insider_pct > FILTERS["insider_pct_min"])
    short_interest_pct = (_safe_float(info.get("shortPercentOfFloat"), 0) or 0) * 100
    revenue_growth = _safe_float(info.get("revenueGrowth"))

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
        "cash_positive": cash_positive,
        "ipo_year": ipo_year,
        "catalyst_type": None,
        "catalyst_date": None,
        **signals,  # price, change_1d, change_1m, dollar_volume, vol_ratio, compressed,
                    # ma50, price_above_ma50, rs_outperf, rs_line_rising, rs_signal
    }
    stock["score"] = _compute_score(stock)
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

    # Échantillonnage NON biaisé des survivants pour borner les appels .info.
    # random.sample (seed None) → rééchantillonné à chaque scan : les clics successifs
    # couvrent tout le pool qualifié, sans biais de sélection (pas de ranking).
    n_all = len(survivors)
    if n_all > FILTERS["enrich_max"]:
        capped = random.sample(survivors, FILTERS["enrich_max"])
        rejection_counts["sampled_out"] = n_all - FILTERS["enrich_max"]
    else:
        capped = survivors
    print(f"\n[Passe A] {n_all} survivants ultra-qualité / {total} tickers → {len(capped)} enrichis")

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

    candidates.sort(key=lambda x: x["score"], reverse=True)

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
    scan_state.update({"scanning": False, "phase": "idle"})
    return output


if __name__ == "__main__":
    run_scan()
