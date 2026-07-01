"""
Suivi de performance des sélections RÉELLES dans le temps.

Contrairement au backtest (rétrospectif, biaisé par la survie), ce suivi mesure
ce qui a VRAIMENT été sélectionné, en temps réel : pour chaque ticker, on retient
la première date où il est apparu dans un scan (prix + score d'alors), puis on
calcule son rendement jusqu'à aujourd'hui et son écart vs l'indice IWM.

Au fil des scans quotidiens, l'historique (data/history/) s'enrichit et ce suivi
donne la mesure honnête et NON biaisée de la performance du screener.

Usage : DATA_DIR=/app/data PYTHONPATH=backend python track.py
        (ou via l'endpoint API  GET /api/performance)
"""

import argparse
import glob
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from screener_backend import FILTERS, HISTORY_DIR, _download_prices


def load_first_flagged(history_dir: Path = HISTORY_DIR) -> dict[str, dict]:
    """Pour chaque ticker, la PREMIÈRE fois qu'il a été sélectionné (date, prix, score)."""
    picks: dict[str, dict] = {}
    files = sorted(glob.glob(str(Path(history_dir) / "*.json")))   # tri chronologique par nom
    for f in files:
        try:
            snap = json.loads(Path(f).read_text())
        except Exception:
            continue
        date = snap.get("scanned_at")
        for p in snap.get("picks", []):
            tk = p.get("ticker")
            if tk and tk not in picks:
                picks[tk] = {"date": date, "price": p.get("price"), "score": p.get("score")}
    return picks


def _value_on_or_after(close: pd.Series, target_date) -> float | None:
    """Premier cours dont la date est >= target_date (jour d'entrée), sinon None."""
    if close is None or len(close) == 0:
        return None
    for ts, val in close.items():
        if ts.date() >= target_date:
            return float(val)
    return None


def _period_for(days: int) -> str:
    """Profondeur de téléchargement yfinance couvrant l'ancienneté de la plus vieille sélection."""
    if days <= 55:
        return "3mo"
    if days <= 120:
        return "6mo"
    if days <= 250:
        return "1y"
    return "2y"


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "mean": None, "median": None, "hit": None}
    return {
        "n": len(xs), "mean": statistics.mean(xs),
        "median": statistics.median(xs), "hit": sum(1 for x in xs if x > 0) / len(xs),
    }


def run_tracker(history_dir: Path = HISTORY_DIR, high_score: int = 7,
                quiet: bool = False) -> dict:
    """Calcule la performance depuis sélection, agrège par score, compare à IWM."""
    picks = load_first_flagged(history_dir)
    if not picks:
        result = {"n_picks": 0, "message": "Aucun historique de sélections pour l'instant."}
        if not quiet:
            print("\n[track] Aucun historique. Lance quelques scans d'abord (data/history/ vide).\n")
        return result

    now = datetime.now(tz=timezone.utc)
    earliest = min(datetime.fromisoformat(p["date"]) for p in picks.values() if p.get("date"))
    period = _period_for((now - earliest).days)

    tickers = list(picks)
    prices = _download_prices(tickers, FILTERS["rs_benchmark"], period=period)
    bench_df = prices.pop(FILTERS["rs_benchmark"], None)
    bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None
    bench_cur = float(bench_close.iloc[-1]) if bench_close is not None and len(bench_close) else None

    rows = []
    for tk, info in picks.items():
        df = prices.get(tk)
        entry_price = info.get("price")
        if df is None or "Close" not in df or not entry_price:
            continue
        close = df["Close"].dropna()
        if len(close) == 0:
            continue
        cur = float(close.iloc[-1])
        ret = cur / entry_price - 1

        excess = None
        if bench_close is not None and bench_cur:
            entry_date = datetime.fromisoformat(info["date"]).date()
            bench_entry = _value_on_or_after(bench_close, entry_date)
            if bench_entry:
                excess = ret - (bench_cur / bench_entry - 1)

        held = (now - datetime.fromisoformat(info["date"])).days
        rows.append({"ticker": tk, "score": info.get("score"), "ret": ret,
                     "excess": excess, "held_days": held})

    all_ret = [r["ret"] for r in rows]
    all_excess = [r["excess"] for r in rows if r["excess"] is not None]
    high = [r["ret"] for r in rows if (r["score"] or 0) >= high_score]
    low = [r["ret"] for r in rows if (r["score"] or 0) < high_score]

    result = {
        "n_picks": len(picks), "n_tracked": len(rows),
        "overall": _stats(all_ret),
        "excess_mean": (statistics.mean(all_excess) if all_excess else None),
        "high_score": _stats(high), "low_score": _stats(low), "high_score_threshold": high_score,
        "rows": sorted(rows, key=lambda r: r["ret"], reverse=True),
        "as_of": now.isoformat(),
    }
    if not quiet:
        _print_report(result)
    return result


def _pct(x):
    return "    n/a" if x is None else f"{x*100:+7.2f}%"


def _hit(x):
    return "n/a" if x is None else f"{x*100:.0f}%"


def _print_report(r: dict) -> None:
    o = r["overall"]
    print(f"\n{'='*60}\n  SUIVI DE PERFORMANCE DES SÉLECTIONS\n{'='*60}")
    print(f"  Tickers sélectionnés (uniques) : {r['n_picks']}   suivis : {r['n_tracked']}")
    print(f"\n  Rendement moyen depuis sélection : {_pct(o['mean'])}   "
          f"médian : {_pct(o['median'])}   gagnants : {_hit(o['hit'])}")
    print(f"  Écart moyen vs IWM               : {_pct(r['excess_mean'])}")
    h, l = r["high_score"], r["low_score"]
    print(f"\n  Par score (seuil {r['high_score_threshold']}) :")
    print(f"    Score haut (>= {r['high_score_threshold']}) : {_pct(h['mean'])}   (n={h['n']})")
    print(f"    Score bas  (<  {r['high_score_threshold']}) : {_pct(l['mean'])}   (n={l['n']})")
    top = r["rows"][:8]
    if top:
        print("\n  Top rendements :")
        for x in top:
            print(f"    {x['ticker']:<6} score={x['score']} {_pct(x['ret'])}  (depuis {x['held_days']}j)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Suivi de performance des sélections du screener")
    ap.add_argument("--high", type=int, default=7, help="seuil de score « haut »")
    args = ap.parse_args()
    run_tracker(high_score=args.high)
