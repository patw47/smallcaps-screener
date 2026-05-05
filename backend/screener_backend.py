"""
SmallCaps Screener — Screener principal
Découverte dynamique des tickers, fetch yfinance, calcule les métriques, génère screener_data.json
"""

import json
import os
import time
import math
import random
import requests
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
    "ipo_year_min": 2015,          # élargi de 2018 → 2015
    "perf_1m_min": -0.35,          # élargi de -30% → -35%
    "perf_1m_max": 0.25,           # élargi de +20% → +25%
    "vol_window_short": 10,        # jours pour vol court
    "vol_window_long": 50,         # jours pour vol long
    "compression_window": 20,      # jours pour range compressé
    "compression_baseline": 90,    # jours baseline range
    "compression_threshold": 0.70, # range 20j < 70% range 90j
    # Soft filters — utilisés uniquement pour le scoring, pas d'élimination
    "vol_ratio_min": 1.2,          # scoring seulement
    "vol_ratio_max": 3.0,          # scoring seulement
    "insider_pct_min": 5.0,
    "revenue_growth_min": 0.10,
    "short_interest_high": 15.0,
    # Scoring
    "score_vol_ratio_min": 1.3,
    "score_vol_ratio_max": 2.5,
    "score_change_1m_max": 0.15,
    "allowed_exchanges": {"NMS", "NYQ", "NGM", "NCM"},
    "rate_limit_s": 0.3,
    "cache_minutes": 30,
    "max_tickers": 300,
}

os.makedirs("/app/data", exist_ok=True)
OUTPUT_FILE = Path("/app/data/screener_data.json")

scan_state = {
    "scanning": False,
    "progress": 0,
    "total": 0,
}


# ---------------------------------------------------------------------------
# Découverte dynamique des tickers
# ---------------------------------------------------------------------------

def discover_tickers() -> list[str]:
    """
    Récupère les tickers depuis le NASDAQ API (pré-filtré small/micro cap) et Finviz.
    Dédoublonne, mélange, retourne max 300.
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
    random.shuffle(result)
    cap = FILTERS["max_tickers"]
    print(f"[discovery] Pool total: {len(result)} tickers → cap à {cap}")
    return result[:cap]


# ---------------------------------------------------------------------------
# Helpers
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


def _build_positives_flags(stock: dict) -> tuple[list[str], list[str]]:
    positives, flags = [], []

    vr = stock.get("vol_ratio")
    if vr and FILTERS["score_vol_ratio_min"] <= vr <= FILTERS["score_vol_ratio_max"]:
        positives.append(f"Volume en hausse x{vr:.1f} (zone idéale)")
    elif vr and vr > FILTERS["score_vol_ratio_max"]:
        flags.append(f"Volume très élevé x{vr:.1f} (possible spike)")

    if stock.get("compressed"):
        positives.append("Compression de range détectée (potentiel breakout)")

    if stock.get("change_1m") is not None:
        pct = stock["change_1m"] * 100
        if abs(pct) < FILTERS["score_change_1m_max"] * 100:
            positives.append(f"Consolidation calme 1 mois ({pct:+.1f}%)")
        elif pct < -15:
            flags.append(f"Correction forte 1 mois ({pct:+.1f}%)")

    if stock.get("insider_buying"):
        positives.append(f"Insiders détiennent {stock.get('insider_pct', 0):.1f}% du capital")

    if stock.get("cash_positive"):
        positives.append("Trésorerie > dette (bilan sain)")
    else:
        flags.append("Dette supérieure à la trésorerie")

    if stock.get("revenue_growth") and stock["revenue_growth"] > FILTERS["revenue_growth_min"]:
        positives.append(f"Croissance revenus +{stock['revenue_growth']*100:.0f}%")

    if stock.get("short_interest_pct") and stock["short_interest_pct"] > FILTERS["short_interest_high"]:
        positives.append(f"Short interest élevé {stock['short_interest_pct']:.1f}% → potentiel squeeze")

    if stock.get("ipo_year") and stock["ipo_year"] >= FILTERS["ipo_year_min"]:
        positives.append(f"IPO récente ({stock['ipo_year']})")

    return positives, flags


def _compute_score(stock: dict) -> int:
    score = 0

    vr = stock.get("vol_ratio")
    if vr and FILTERS["score_vol_ratio_min"] <= vr <= FILTERS["score_vol_ratio_max"]:
        score += 2

    if stock.get("compressed"):
        score += 2

    ch1m = stock.get("change_1m")
    if ch1m is not None and abs(ch1m) < FILTERS["score_change_1m_max"]:
        score += 2

    if stock.get("insider_buying"):
        score += 2

    if stock.get("cash_positive"):
        score += 1

    if stock.get("revenue_growth") and stock["revenue_growth"] > FILTERS["revenue_growth_min"]:
        score += 1

    if stock.get("ipo_year") and stock["ipo_year"] >= FILTERS["ipo_year_min"]:
        score += 1

    if stock.get("short_interest_pct") and stock["short_interest_pct"] > FILTERS["short_interest_high"]:
        score += 1

    return min(score, 10)


# ---------------------------------------------------------------------------
# Fetch + analyse d'un ticker
# ---------------------------------------------------------------------------

def analyze_ticker(ticker: str) -> tuple[dict | None, str]:
    """
    Retourne (stock_dict, "ok") si le ticker passe tous les filtres.
    Retourne (None, raison) sinon.
    """
    try:
        tkr = yf.Ticker(ticker)
        info = tkr.info or {}

        # --- Bourse autorisée ---
        exchange = info.get("exchange", "")
        if exchange not in FILTERS["allowed_exchanges"]:
            return None, f"exchange:{exchange or 'N/A'}"

        # --- Prix ---
        price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price is None:
            return None, "price:None"
        if not (FILTERS["price_min"] <= price <= FILTERS["price_max"]):
            return None, f"price:{price:.2f}"

        # --- Market cap ---
        mc_raw = _safe_float(info.get("marketCap"))
        if mc_raw is None:
            return None, "market_cap:None"
        mc_m = mc_raw / 1e6
        if not (FILTERS["market_cap_min_m"] <= mc_m <= FILTERS["market_cap_max_m"]):
            return None, f"market_cap:{mc_m:.0f}M"

        # --- IPO year — scoring uniquement, pas d'élimination ---
        ipo_epoch = info.get("firstTradeDateEpochUtc")
        ipo_year = None
        if ipo_epoch:
            ipo_year = datetime.fromtimestamp(ipo_epoch, tz=timezone.utc).year

        # --- Historique (1y pour avoir les 90j de compression baseline) ---
        hist = tkr.history(period="1y", interval="1d")
        if hist.empty or len(hist) < FILTERS["vol_window_long"]:
            return None, f"history:{len(hist) if not hist.empty else 0}j"

        close = hist["Close"]
        volume = hist["Volume"]

        # --- Perf 1 jour ---
        change_1d = _pct_change(close, 1)

        # --- Perf 1 mois (~21 jours de bourse) ---
        change_1m = _pct_change(close, 21)
        if change_1m is None:
            return None, "change_1m:None"
        if not (FILTERS["perf_1m_min"] <= change_1m <= FILTERS["perf_1m_max"]):
            return None, f"change_1m:{change_1m*100:.1f}%"

        # --- Ratio de volume (court / long) — scoring uniquement, pas de hard filter ---
        vol_short = float(volume.iloc[-FILTERS["vol_window_short"]:].mean())
        vol_long = float(volume.iloc[-FILTERS["vol_window_long"]:].mean())
        vol_ratio = None
        if vol_long > 0 and not math.isnan(vol_long):
            vol_ratio = vol_short / vol_long

        # --- Compression de range (nécessite ~90j, disponible avec period="1y") ---
        range_20 = _range_pct(close, FILTERS["compression_window"])
        range_90 = _range_pct(close, FILTERS["compression_baseline"])
        compressed = False
        if range_20 is not None and range_90 is not None and range_90 > 0:
            compressed = bool((range_20 / range_90) < FILTERS["compression_threshold"])

        # --- Bilan ---
        total_cash = _safe_float(info.get("totalCash"), 0)
        total_debt = _safe_float(info.get("totalDebt"), 0)
        cash_positive = bool(total_cash > total_debt)

        # --- Insiders ---
        insider_pct = (_safe_float(info.get("heldPercentInsiders"), 0) or 0) * 100
        insider_buying = bool(insider_pct > FILTERS["insider_pct_min"])

        # --- Short interest ---
        short_interest_pct = (_safe_float(info.get("shortPercentOfFloat"), 0) or 0) * 100

        # --- Croissance revenus ---
        revenue_growth = _safe_float(info.get("revenueGrowth"))

        stock = {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": exchange,
            "price": round(price, 2),
            "change_1d": round(change_1d, 4) if change_1d is not None else None,
            "change_1m": round(change_1m, 4),
            "market_cap_m": round(mc_m, 1),
            "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "compressed": compressed,
            "cash_positive": cash_positive,
            "insider_buying": insider_buying,
            "insider_pct": round(insider_pct, 2),
            "short_interest_pct": round(short_interest_pct, 2),
            "revenue_growth": round(revenue_growth, 4) if revenue_growth is not None else None,
            "ipo_year": ipo_year,
            "catalyst_type": None,
            "catalyst_date": None,
        }

        stock["score"] = _compute_score(stock)
        stock["positives"], stock["flags"] = _build_positives_flags(stock)

        return stock, "ok"

    except Exception as e:
        return None, f"exception:{type(e).__name__}:{e}"


# ---------------------------------------------------------------------------
# Scan complet
# ---------------------------------------------------------------------------

def run_scan(tickers: list[str] | None = None) -> dict:
    """
    Lance le scan. Si tickers est None, découverte dynamique via discover_tickers().
    """
    watchlist = tickers if tickers is not None else discover_tickers()
    total = len(watchlist)

    scan_state["scanning"] = True
    scan_state["progress"] = 0
    scan_state["total"] = total

    candidates = []
    scanned = 0
    rejection_counts: dict[str, int] = {}

    print(f"\n{'='*55}")
    print(f"  SmallCaps Screener — scan de {total} tickers")
    print(f"{'='*55}")

    for ticker in watchlist:
        scanned += 1
        scan_state["progress"] = scanned

        bar_len = 40
        filled = int(bar_len * scanned / total)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r[{bar}] {scanned}/{total}  {ticker:<8}", end="", flush=True)

        result, reason = analyze_ticker(ticker)
        if result:
            candidates.append(result)
        else:
            # Regroupe les rejections par catégorie (ex: "price:14.50" → "price")
            category = reason.split(":")[0]
            rejection_counts[category] = rejection_counts.get(category, 0) + 1

        time.sleep(FILTERS["rate_limit_s"])

    print(f"\n{'='*55}")
    print(f"  {len(candidates)} candidats trouvés sur {total} scannés")
    print(f"{'='*55}")
    print(f"\n  Rejections par filtre :")
    for cat, count in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<20} {count:>4} tickers")
    print()

    candidates.sort(key=lambda x: x["score"], reverse=True)

    output = {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "total_scanned": total,
        "candidates": len(candidates),
        "stocks": candidates,
        "rejection_stats": rejection_counts,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    scan_state["scanning"] = False
    return output


if __name__ == "__main__":
    run_scan()
